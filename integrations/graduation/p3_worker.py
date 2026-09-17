"""Host-owned MCP bridge, creates only its own stdio subprocess."""
import argparse
import asyncio
import json
import sys

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp_notes._network_block import install_network_block
from mcp_notes.v2.client import call_bounded
from mcp_notes.v2.contracts import ReadArgs
from common import P3, clean_env


async def run(notes, audit, request):
    if set(request) != {"note_ids"} or not isinstance(request["note_ids"], list) or len(request["note_ids"]) > 8:
        raise ValueError("invalid-arguments")
    ids = [ReadArgs(note_id=value).note_id for value in request["note_ids"]]
    params = StdioServerParameters(command=sys.executable,
        args=["-m", "mcp_notes.v2.server", "--notes-root", notes, "--audit-root", audit],
        env=clean_env(P3), cwd=str(P3))
    async with Client(stdio_client(params)) as client:
        tools = (await client.list_tools()).tools
        if {t.name for t in tools} != {"read_note", "search_notes"}:
            raise ValueError("MCP_PERMISSION_DRIFT")
        info = json.loads((await client.read_resource("notes://service-info")).contents[0].text)
        values = [(await call_bounded(client, "read_note", {"note_id": value})).model_dump(mode="json") for value in ids]
        return {"schema_version": "p3-bridge-v1", "snapshot_hash": info["snapshot_hash"], "results": values}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--notes-root", required=True)
    parser.add_argument("--audit-root", required=True)
    args = parser.parse_args()
    install_network_block()
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError("INPUT_TOO_LARGE")
        result = asyncio.run(asyncio.wait_for(run(args.notes_root, args.audit_root, json.loads(raw)), 20))
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        print('{"error":"P3_ADAPTER_FAILED"}')
        raise SystemExit(2)
