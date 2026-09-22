"""Bounded local text library. No network, model, filesystem input or HTML execution."""
from collections import Counter
import hashlib
import json
import math
import re
import unicodedata

from domain import digest, fields, identifier, require, text
from store import now

MAX_BYTES = 48000
LIMITS = {"documents": 50, "versions": 200, "requests": 1000, "content_bytes": MAX_BYTES}


def version_id(value, empty=False):
    require(type(value) is str and (empty and value == "" or re.fullmatch(r"ver-[a-f0-9]{64}", value)))
    return value


def tokens(value):
    value = unicodedata.normalize("NFKC", value).lower()
    result = []
    for item in re.findall(r"[a-z0-9][a-z0-9_+.#-]*|[\u4e00-\u9fff]+", value):
        if "\u4e00" <= item[0] <= "\u9fff":
            result.extend(item[i:i + 2] for i in range(len(item) - 1)) if len(item) > 1 else result.append(item)
        else:
            result.append(item)
    return result


def chunks(content, version):
    result, pending, start, end = [], [], 0, 0

    def emit():
        nonlocal pending
        if pending:
            result.append({"text": "\n".join(pending), "line_start": start, "line_end": end,
                           "column_start": 1, "column_end": len(pending[-1])})
            pending = []

    for number, line in enumerate(content.split("\n"), 1):
        if not line.strip():
            emit()
            continue
        if len(line) > 800:
            emit()
            for offset in range(0, len(line), 800):
                result.append({"text": line[offset:offset + 800], "line_start": number, "line_end": number,
                               "column_start": offset + 1, "column_end": min(offset + 800, len(line))})
            continue
        if pending and sum(len(s) + 1 for s in pending) + len(line) > 800:
            emit()
        if not pending:
            start = number
        pending.append(line)
        end = number
    emit()
    require(0 < len(result) <= 128, "LIBRARY_LIMIT")
    for index, chunk in enumerate(result, 1):
        chunk.update(chunk_id=f"{version}:chunk-{index}",
                     content_hash=hashlib.sha256(chunk["text"].encode()).hexdigest(),
                     locator=f"L{chunk['line_start']}:C{chunk['column_start']}-L{chunk['line_end']}:C{chunk['column_end']}")
    return result


def rank(records, query, top_k):
    terms = set(tokens(query))
    if not terms or not records:
        return []
    bags = [Counter(tokens(record["text"])) for record in records]
    lengths = [sum(bag.values()) for bag in bags]
    average = max(sum(lengths) / len(lengths), 1)
    frequencies = {term: sum(term in bag for bag in bags) for term in terms}
    ranked = []
    for record, bag, length in zip(records, bags, lengths):
        score = 0.0
        for term in terms:
            count = bag[term]
            if count:
                inverse = math.log(1 + (len(records) - frequencies[term] + .5) / (frequencies[term] + .5))
                score += inverse * count * 2.2 / (count + 1.2 * (.25 + .75 * length / average))
        if score:
            if query.casefold() in record["text"].casefold():
                score += 1
            ranked.append({**record, "score": round(score, 6)})
    return sorted(ranked, key=lambda item: (-item["score"], item["chunk_id"]))[:top_k]


class Library:
    def __init__(self, store):
        self.store = store
        with store.transaction() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS library_versions (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL,
                    version_id TEXT UNIQUE NOT NULL, parent_version TEXT NOT NULL,
                    metadata_json TEXT NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL,
                    chunks_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS library_requests (
                    request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
                    version_id TEXT NOT NULL REFERENCES library_versions(version_id));
                CREATE TABLE IF NOT EXISTS library_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL,
                    document_id TEXT NOT NULL, version_id TEXT NOT NULL,
                    kind TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL);
            """)

    @staticmethod
    def _view(row, detail=False):
        require(row is not None, "NOT_FOUND")
        value = {**json.loads(row["metadata_json"]), "document_id": row["document_id"],
                 "version_id": row["version_id"], "parent_version": row["parent_version"],
                 "content_hash": row["content_hash"], "created_at": row["created_at"]}
        parts = json.loads(row["chunks_json"])
        value["chunk_count"] = len(parts)
        if detail:
            value.update(content=row["content"], chunks=parts)
        return value

    def catalog(self):
        with self.store.transaction() as connection:
            rows = connection.execute("SELECT * FROM library_versions ORDER BY sequence DESC").fetchall()
            grouped = {}
            for row in rows:
                item = self._view(row)
                if item["document_id"] not in grouped:
                    grouped[item["document_id"]] = {**item, "versions": []}
                grouped[item["document_id"]]["versions"].append({key: item[key] for key in
                    ("version_id", "created_at", "content_hash", "title")})
            events = [{**dict(row), "details": json.loads(row["details_json"])} for row in
                      connection.execute("SELECT * FROM library_events ORDER BY id DESC LIMIT 20")]
            for event in events:
                event.pop("details_json")
        return {"schema_version": "local-library-v1", "mode": "local-lexical", "documents": list(grouped.values()),
                "events": events, "limits": LIMITS, "version_count": len(rows),
                "used_by_scripted_workflow": False}

    def get(self, version):
        version_id(version)
        with self.store.transaction() as connection:
            return self._view(connection.execute("SELECT * FROM library_versions WHERE version_id=?", (version,)).fetchone(), True)

    def import_text(self, payload, actor='local-browser', bind_owner=False):
        fields(payload, "request_id title filename source_ref rights_note content confirmed expected_version")
        request = identifier(payload["request_id"])
        require(payload["confirmed"] is True, "LIBRARY_CONFIRMATION")
        expected = version_id(payload["expected_version"], empty=True)
        metadata = {name: text(payload[name], low, high) for name, low, high in
                    (("title", 2, 120), ("filename", 1, 120), ("source_ref", 3, 300), ("rights_note", 4, 500))}
        require(all(not any(ord(c) < 32 for c in value) for value in metadata.values()))
        try:
            for value in metadata.values():
                value.encode("utf-8")
        except UnicodeError:
            require(False)
        filename = metadata["filename"]
        require(not filename.startswith(".") and re.fullmatch(r"[^/\\:<>\"|?*\x00-\x1f]+\.(txt|md)", filename, re.I), "LIBRARY_FILE")
        require(type(payload["content"]) is str)
        content = payload["content"].replace("\r\n", "\n").replace("\r", "\n")
        require(content.strip() and not any(ord(c) < 32 and c not in "\n\t" for c in content))
        try:
            encoded = content.encode("utf-8")
        except UnicodeError:
            require(False)
        require(len(encoded) <= MAX_BYTES, "LIBRARY_LIMIT")
        # Hash the entire request: reusing a key never changes a prior decision or version.
        signature = digest(payload)
        content_hash = hashlib.sha256(encoded).hexdigest()
        document = "doc-" + hashlib.sha256(metadata["source_ref"].encode()).hexdigest()[:32]
        version = "ver-" + digest({"metadata": metadata, "content_hash": content_hash})
        parts = chunks(content, version)
        with self.store.transaction() as connection:
            if bind_owner:
                owner = connection.execute('SELECT user_id FROM document_owners WHERE document_id=?',
                                           (document,)).fetchone()
                require(owner is None or owner['user_id'] == actor, 'NOT_FOUND')
                if owner is None:
                    connection.execute('INSERT INTO document_owners VALUES(?,?)', (document, actor))
            prior = connection.execute("SELECT * FROM library_requests WHERE request_id=?", (request,)).fetchone()
            if prior:
                require(prior["payload_hash"] == signature, "IDEMPOTENCY_CONFLICT")
                row = connection.execute("SELECT * FROM library_versions WHERE version_id=?", (prior["version_id"],)).fetchone()
                return self._view(row, True)
            require(connection.execute("SELECT count(*) FROM library_requests").fetchone()[0] < LIMITS["requests"], "LIBRARY_LIMIT")
            latest = connection.execute("SELECT * FROM library_versions WHERE document_id=? ORDER BY sequence DESC LIMIT 1", (document,)).fetchone()
            require(expected == (latest["version_id"] if latest else ""), "LIBRARY_STALE")
            if not latest or latest["version_id"] != version:
                # Reverting to older identical content would need a new revision identity; reject clearly for now.
                require(not connection.execute("SELECT 1 FROM library_versions WHERE version_id=?", (version,)).fetchone(), "LIBRARY_OLD_VERSION")
                require(connection.execute("SELECT count(*) FROM library_versions").fetchone()[0] < LIMITS["versions"], "LIBRARY_LIMIT")
                if not latest:
                    require(connection.execute("SELECT count(DISTINCT document_id) FROM library_versions").fetchone()[0] < LIMITS["documents"], "LIBRARY_LIMIT")
                created = now()
                connection.execute("INSERT INTO library_versions(document_id,version_id,parent_version,metadata_json,content,content_hash,chunks_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                                   (document, version, expected, json.dumps(metadata, ensure_ascii=False), content, content_hash, json.dumps(parts, ensure_ascii=False), created))
                connection.execute("INSERT INTO library_events(request_id,document_id,version_id,kind,details_json,created_at) VALUES(?,?,?,?,?,?)",
                                   (request, document, version, "version_imported", json.dumps({"actor": actor, "content_hash": content_hash, "chunk_count": len(parts), "bytes": len(encoded), "authorization_confirmed": True}), created))
            connection.execute("INSERT INTO library_requests VALUES(?,?,?)", (request, signature, version))
            return self._view(connection.execute("SELECT * FROM library_versions WHERE version_id=?", (version,)).fetchone(), True)

    def search(self, payload):
        fields(payload, "query document_ids top_k")
        query = text(payload["query"], 0, 200)
        ids = payload["document_ids"]
        require(type(ids) is list and len(ids) <= LIMITS["documents"])
        ids = [identifier(value, "doc-") for value in ids]
        require(len(ids) == len(set(ids)))
        require(type(payload["top_k"]) is int and 1 <= payload["top_k"] <= 20)
        with self.store.transaction() as connection:
            rows = connection.execute("SELECT * FROM library_versions WHERE sequence IN (SELECT max(sequence) FROM library_versions GROUP BY document_id)").fetchall()
            require(set(ids) <= {row["document_id"] for row in rows}, "NOT_FOUND")
            records = []
            for row in rows:
                if ids and row["document_id"] not in ids:
                    continue
                item = self._view(row, True)
                records.extend({**part, **{key: item[key] for key in ("title", "filename", "source_ref", "document_id", "version_id")},
                                "source_hash": item["content_hash"]} for part in item["chunks"])
        return {"mode": "local-lexical", "query": query, "results": rank(records, query, payload["top_k"]),
                "searched_chunks": len(records), "generated_answer": False}
