"""Frozen research-project contracts. Creation stores no report and starts no engine."""
import json
import hashlib
import uuid

from domain import digest, fields, identifier, require, text
from library import Library, rank
from store import now

MAX_PROJECTS = 200


def project_text(value, minimum, maximum):
    value = text(value, minimum, maximum)
    require(not any(ord(c) < 32 and c not in '\n\t' for c in value), 'PROJECT_CONTRACT')
    try:
        value.encode('utf-8')
    except UnicodeError:
        require(False, 'PROJECT_CONTRACT')
    return value


class ResearchProjects:
    def __init__(self, store):
        self.store = store
        with store.transaction() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS research_projects (
                    project_id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    payload_hash TEXT NOT NULL, title TEXT NOT NULL, question TEXT NOT NULL,
                    constraints_json TEXT NOT NULL, version_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS research_project_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
                    request_id TEXT NOT NULL, kind TEXT NOT NULL, details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS research_project_scopes (
                    project_id TEXT PRIMARY KEY REFERENCES research_projects(project_id),
                    manifest_json TEXT NOT NULL, contract_hash TEXT NOT NULL);
            """)

    @staticmethod
    def _view(row):
        require(row is not None, "NOT_FOUND")
        return {
            "project_id": row["project_id"], "request_id": row["request_id"],
            "title": row["title"], "question": row["question"],
            "constraints": json.loads(row["constraints_json"]),
            "version_ids": json.loads(row["version_ids_json"]),
            "status": "DRAFT_FROZEN", "created_at": row["created_at"],
            "report_bound": False, "engine_started": False,
        }

    @staticmethod
    def _validate(payload):
        fields(payload, "request_id title question constraints version_ids confirmed")
        request = identifier(payload["request_id"])
        require(payload["confirmed"] is True, "PROJECT_CONFIRMATION")
        title = project_text(payload["title"], 2, 80)
        question = project_text(payload["question"], 10, 500)
        constraints = payload["constraints"]
        require(type(constraints) is list and len(constraints) <= 8, "PROJECT_CONTRACT")
        constraints = [project_text(item, 2, 160) for item in constraints]
        require(len(constraints) == len(set(constraints)), "PROJECT_CONTRACT")
        versions = payload["version_ids"]
        require(type(versions) is list and 1 <= len(versions) <= 50, "PROJECT_CONTRACT")
        require(all(isinstance(item, str) and len(item) == 68 and item.startswith("ver-") and
                    all(char in "0123456789abcdef" for char in item[4:]) for item in versions), "PROJECT_CONTRACT")
        require(len(versions) == len(set(versions)), "PROJECT_CONTRACT")
        return request, {"title": title, "question": question, "constraints": constraints,
                         "version_ids": sorted(versions), "confirmed": True}

    @staticmethod
    def _contract(project, manifest):
        return digest({"schema_version": "research-scope-v1", "title": project['title'],
                       "question": project['question'], "constraints": project['constraints'],
                       "version_ids": project['version_ids'], "manifest": manifest})

    def _detail(self, connection, row):
        result = self._view(row)
        scope = connection.execute('SELECT * FROM research_project_scopes WHERE project_id=?',
                                   (result['project_id'],)).fetchone()
        require(scope is not None, 'PROJECT_INTEGRITY')
        manifest = json.loads(scope['manifest_json'])
        require([m['version_id'] for m in manifest] == result['version_ids'] and
                self._contract(result, manifest) == scope['contract_hash'], 'PROJECT_INTEGRITY')
        result.update(manifest=manifest, contract_hash=scope['contract_hash'])
        return result

    def create(self, payload, actor='local-browser', *, auth=None, owner=None, reviewer_id=None):
        require((auth is None and owner is None and reviewer_id is None) or
                (auth is not None and owner is not None and reviewer_id is not None), 'INPUT_INVALID')
        request, value = self._validate(payload)
        signature = digest(value)
        with self.store.transaction() as connection:
            previous = connection.execute("SELECT * FROM research_projects WHERE request_id=?", (request,)).fetchone()
            if previous:
                require(previous["payload_hash"] == signature, "PROJECT_CONFLICT")
                if auth is not None:
                    auth.bind_project_in_transaction(connection, previous['project_id'], owner, reviewer_id,
                                                     existing=True)
                return self._detail(connection, previous)
            require(connection.execute('SELECT count(*) FROM research_projects').fetchone()[0] < MAX_PROJECTS,
                    'PROJECT_LIMIT')
            markers = ",".join("?" * len(value["version_ids"]))
            rows = connection.execute("SELECT * FROM library_versions WHERE version_id IN (" + markers + ") ORDER BY version_id",
                                      tuple(value["version_ids"])).fetchall()
            require(len(rows) == len(value["version_ids"]), "NOT_FOUND")
            require(len({row["document_id"] for row in rows}) == len(rows), "PROJECT_CONTRACT")
            if auth is not None:
                owned = {row[0] for row in connection.execute(
                    'SELECT document_id FROM document_owners WHERE user_id=?', (owner['user_id'],))}
                require(all(row['document_id'] in owned for row in rows), 'NOT_FOUND')
            manifest = [Library._view(row) for row in rows]
            contract_hash = self._contract(value, manifest)
            project = "project-" + uuid.uuid4().hex
            created = now()
            connection.execute("INSERT INTO research_projects VALUES(?,?,?,?,?,?,?,?)", (
                project, request, signature, value["title"], value["question"],
                json.dumps(value["constraints"], ensure_ascii=False),
                json.dumps(value["version_ids"], ensure_ascii=False), created))
            connection.execute('INSERT INTO research_project_scopes VALUES(?,?,?)',
                               (project, json.dumps(manifest, ensure_ascii=False), contract_hash))
            connection.execute("INSERT INTO research_project_events VALUES(NULL,?,?,?,?,?)", (
                project, request, "project_frozen",
                json.dumps({"actor": actor, "version_count": len(rows), "contract_hash": contract_hash,
                            "engine_started": False, "content_quality_approval": False}, ensure_ascii=False), created))
            if auth is not None:
                auth.bind_project_in_transaction(connection, project, owner, reviewer_id)
            return self._detail(connection, connection.execute("SELECT * FROM research_projects WHERE project_id=?", (project,)).fetchone())

    def list(self):
        with self.store.transaction() as connection:
            return [self._view(row) for row in connection.execute("SELECT * FROM research_projects ORDER BY created_at DESC, project_id DESC")]

    def get(self, project_id):
        identifier(project_id, 'project-')
        with self.store.transaction() as connection:
            row = connection.execute("SELECT * FROM research_projects WHERE project_id=?", (project_id,)).fetchone()
            result = self._detail(connection, row)
            result["events"] = [{**dict(item), "details": json.loads(item["details_json"])} for item in
                                connection.execute("SELECT * FROM research_project_events WHERE project_id=? ORDER BY id", (project_id,))]
            for event in result["events"]:
                event.pop("details_json")
            return result

    def _records(self, project):
        records = []
        with self.store.transaction() as connection:
            for frozen in project['manifest']:
                row = connection.execute('SELECT * FROM library_versions WHERE version_id=?',
                                         (frozen['version_id'],)).fetchone()
                require(row is not None, 'PROJECT_INTEGRITY')
                require(Library._view(row) == frozen, 'PROJECT_INTEGRITY')
                require(hashlib.sha256(row['content'].encode()).hexdigest() == frozen['content_hash'], 'PROJECT_INTEGRITY')
                from library import chunks
                parts = json.loads(row['chunks_json'])
                require(parts == chunks(row['content'], frozen['version_id']), 'PROJECT_INTEGRITY')
                records.extend({**part, **{key: frozen[key] for key in
                    ('version_id', 'document_id', 'title', 'source_ref', 'filename')},
                    'source_hash': frozen['content_hash']} for part in parts)
        return records

    def search(self, project_id, payload):
        fields(payload, 'query top_k')
        query = project_text(payload['query'], 0, 200)
        require(type(payload['top_k']) is int and 1 <= payload['top_k'] <= 20)
        project = self.get(project_id)
        records = self._records(project)
        return {'project_id': project_id, 'contract_hash': project['contract_hash'],
                'mode': 'frozen-lexical', 'generated_answer': False, 'searched_chunks': len(records),
                'results': rank(records, query, payload['top_k'])}

    def evidence(self, project_id, payload):
        fields(payload, 'version_id chunk_id content_hash')
        require(all(type(v) is str and len(v) <= 100 for v in payload.values()))
        project = self.get(project_id)
        require(payload['version_id'] in project['version_ids'], 'PROJECT_EVIDENCE')
        record = next((r for r in self._records(project) if r['version_id'] == payload['version_id'] and
                       r['chunk_id'] == payload['chunk_id']), None)
        require(record is not None and record['content_hash'] == payload['content_hash'], 'PROJECT_EVIDENCE')
        return {'project_id': project_id, 'contract_hash': project['contract_hash'],
                'binding_verified': True, 'content_quality_accepted': False, 'evidence': record}
