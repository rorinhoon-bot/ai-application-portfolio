"""Uses P1's real HTML parser on original integration fixtures, no P1 database."""
import hashlib
import json
import re
import sys

from common import HERE, P1Request, P1Response, Record, digest
from cited_rag.adapters.html_parser import PythonDocsHtmlParser


def catalog():
    records = []
    sources = {}
    manifest = json.loads((HERE / "fixtures/manifest.json").read_text(encoding="utf-8-sig"))
    for candidate in ("graph-plan", "chain-plan"):
        path = HERE / "fixtures" / f"{candidate}.html"
        raw = path.read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        if manifest["files"][path.name] != source_hash:
            raise ValueError("FIXTURE_HASH_MISMATCH")
        sources[path.name] = source_hash
        parsed = PythonDocsHtmlParser().parse(raw.decode("utf-8"))
        for section in ("tool-calling", "human-approval", "recovery"):
            blocks = [block for block in parsed.blocks if block.section_anchor == section]
            text = "\n\n".join(block.clean_text for block in blocks)
            record_id = candidate + "-" + section
            records.append(Record(record_id=record_id, candidate_id=candidate, section_id=section,
                title=parsed.page_title + ": " + section, text=text,
                source_file=path.name, source_sha256=source_hash,
                content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                block_orders=[b.block_order for b in blocks],
                note_id=hashlib.sha256((record_id + ".md").encode()).hexdigest()[:16]))
    return sources, records


def handle(request):
    request = P1Request.model_validate(request)
    sources, records = catalog()
    if request.operation == "search":
        if not request.query.strip() or not request.candidate_ids:
            raise ValueError("QUERY_INVALID")
        terms = set(re.findall(r"[\w-]{2,}", request.query.casefold()))
        ranked = []
        for record in records:
            if record.candidate_id not in request.candidate_ids:
                continue
            score = sum(3 * (term in record.section_id) + (term in record.text.casefold()) for term in terms)
            if score:
                ranked.append((score, record.record_id, record))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        records = [r for _, _, r in ranked[:request.top_k]]
    return P1Response(schema_version="p1-integration-v1", mode="fixture-keyword",
                      corpus_hash=digest(sources), records=records).model_dump(mode="json")


if __name__ == "__main__":
    def offline(event, args):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.bind"):
            raise RuntimeError("OFFLINE_NETWORK_BLOCKED")
    sys.addaudithook(offline)
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError("INPUT_TOO_LARGE")
        print(json.dumps(handle(json.loads(raw)), ensure_ascii=False))
    except Exception:
        print('{"error":"P1_ADAPTER_FAILED"}')
        raise SystemExit(2)
