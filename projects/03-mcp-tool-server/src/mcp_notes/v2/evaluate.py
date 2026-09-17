"""Actual stdio evaluation and demo, isolated temporary runtime only."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from jsonschema import Draft202012Validator
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from .catalog import digest
from .client import call_bounded
from .contracts import Result

ROOT = Path(__file__).resolve().parents[3]


def safe_env():
    # Do not inherit model keys, tracing, provider endpoints or project runtime configuration.
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH") if k in os.environ}
    env.update(PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1",
               NETWORK_ACCESS_BLOCKED_IN_TESTS="1")
    return env


async def evaluate():
    cases_path = ROOT / "evals/cases/p3-v2.json"
    frozen = json.loads(cases_path.read_text(encoding="utf-8"))
    results = []
    with tempfile.TemporaryDirectory(prefix="p3-v2-eval-") as temporary:
        audit = Path(temporary) / "audit"
        audit.mkdir()
        params = StdioServerParameters(command=sys.executable,
            args=["-m", "mcp_notes.v2.server", "--notes-root", str(ROOT / "evals/fixtures/notes-v1"),
                  "--audit-root", str(audit)], env=safe_env(), cwd=str(ROOT))
        async with Client(stdio_client(params)) as client:
            tools = (await client.list_tools()).tools
            assert {t.name for t in tools} == {"search_notes", "read_note"}
            for tool in tools:
                assert tool.input_schema["additionalProperties"] is False
                assert tool.output_schema["additionalProperties"] is False
                assert tool.annotations.read_only_hint
            resource = await client.read_resource("notes://service-info")
            info = json.loads(resource.contents[0].text)
            assert info["read_only"] is True
            for case in frozen["cases"]:
                result = await call_bounded(client, case["tool"], case["args"])
                Draft202012Validator(Result.model_json_schema()).validate(result.model_dump(mode="json"))
                passed = result.status == case["status"] and result.error_code == case.get("error")
                if "minimum_hits" in case:
                    passed &= len(result.hits) >= case["minimum_hits"]
                if "maximum_hits" in case:
                    passed &= len(result.hits) <= case["maximum_hits"]
                assert result.snapshot_hash == info["snapshot_hash"]
                results.append({"id": case["id"], "passed": passed, "status": result.status,
                                "error_code": result.error_code, "hits": len(result.hits)})
            first = await call_bounded(client, "search_notes", {"keyword": "检索"})
            read = await call_bounded(client, "read_note", {"note_id": first.hits[0].note_id})
            replay = await call_bounded(client, "read_note", {"note_id": first.hits[0].note_id})
            assert read.document == replay.document
            assert hashlib.sha256(read.document.text.encode()).hexdigest() == first.hits[0].content_sha256
        receipts = [json.loads(p.read_text(encoding="utf-8")) for p in audit.glob("*.json")]
        assert len(receipts) == 2 * (len(results) + 3)
        pairs = {}
        for receipt in receipts:
            expected = receipt.pop("content_hash")
            assert digest(receipt) == expected
            pairs.setdefault(receipt["call_id"], set()).add(receipt["phase"])
        assert all(phases == {"begin", "end"} for phases in pairs.values())
        assert not list(Path(temporary).glob("*.db"))
        return {"schema_version": "p3-v2-evaluation-1", "cases_sha256": digest(frozen),
                "snapshot_hash": info["snapshot_hash"], "passed": sum(r["passed"] for r in results),
                "total": len(results), "cases": results, "audit_receipts": len(receipts),
                "protocol": "actual MCP stdio", "read_replay_identical": True,
                "content_quality_evaluated": False, "real_model_calls": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(evaluate())
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    print(text)
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
