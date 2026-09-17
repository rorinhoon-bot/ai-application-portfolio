"""Local offline CLI. Runtime IDs only; no arbitrary model, path or provider options."""
import argparse
import json
import re
import sys

from common import HERE, BoundaryError, safe_directory
from workflow_runtime import Runtime, initialize, QUESTION


def summary(state):
    return {key: state.get(key) for key in ("run_id", "status", "current_node", "request_hash",
        "report_revision", "report_hash", "model_call_count", "tool_call_count", "artifact_id", "errors",
        "request", "evidence", "review_findings", "report")}


def main():
    parser = argparse.ArgumentParser(description="可信AI应用方案研究与交付平台：离线演示")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--question", default=QUESTION)
    for action in ("status", "recover", "approve", "reject", "cancel"):
        child = sub.add_parser(action)
        child.add_argument("run_id")
        if action not in ("status", "recover"):
            child.add_argument("--expected-hash", required=True)
    args = parser.parse_args()
    def offline(event, values):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.bind"):
            raise RuntimeError("OFFLINE_NETWORK_BLOCKED")
    sys.addaudithook(offline)
    try:
        parent = HERE / ".runs"
        if not parent.exists():
            parent.mkdir()
        safe_directory(parent)
        if args.command == "start":
            _, state = initialize(parent, args.question)
        else:
            if not re.fullmatch(r"run-[a-f0-9]{32}", args.run_id):
                raise BoundaryError("RUN_ID_INVALID")
            with Runtime(parent / args.run_id) as runtime:
                if args.command == "status":
                    state = runtime.state()
                elif args.command == "recover":
                    state = runtime.recover()
                else:
                    state = runtime.decide(args.command, args.expected_hash)
        print(json.dumps(summary(state), ensure_ascii=False, indent=2))
        return 0
    except BoundaryError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    except Exception:
        print('{"error":"INTEGRATION_FAILED"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
