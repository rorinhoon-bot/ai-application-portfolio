"""Verify the approved P2 runtime without network or model calls."""

from __future__ import annotations

import json
import os
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph


EXPECTED_VERSIONS = {
    "langgraph": "1.2.9",
    "langgraph-checkpoint-sqlite": "3.1.0",
    "pydantic": "2.13.4",
    "pydantic-settings": "2.14.2",
    "pytest": "9.1.1",
}


class SmokeState(TypedDict):
    value: int


def increment(state: SmokeState) -> SmokeState:
    return {"value": state["value"] + 1}


def build_graph(checkpointer: SqliteSaver):
    builder = StateGraph(SmokeState)
    builder.add_node("increment", increment)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    return builder.compile(checkpointer=checkpointer)


def verify_versions() -> dict[str, str]:
    actual = {package: version(package) for package in EXPECTED_VERSIONS}
    if actual != EXPECTED_VERSIONS:
        raise RuntimeError(
            f"Installed direct dependency versions differ: {actual!r}"
        )
    return actual


def verify_sqlite_recovery() -> dict[str, object]:
    config = {"configurable": {"thread_id": "environment-smoke"}}

    with TemporaryDirectory(prefix="p2-langgraph-smoke-") as temp_dir:
        checkpoint_path = Path(temp_dir) / "checkpoints.sqlite3"

        with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            graph = build_graph(saver)
            result = graph.invoke({"value": 1}, config)
            if result != {"value": 2}:
                raise RuntimeError(f"Unexpected graph result: {result!r}")

        with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            graph = build_graph(saver)
            snapshot = graph.get_state(config)
            if snapshot.values != {"value": 2}:
                raise RuntimeError(
                    f"Checkpoint recovery mismatch: {snapshot.values!r}"
                )

        return {
            "graph_result": result,
            "recovered_state": snapshot.values,
            "checkpoint_created": checkpoint_path.is_file(),
        }


def main() -> None:
    if os.environ.get("LANGGRAPH_STRICT_MSGPACK") != "true":
        raise RuntimeError("LANGGRAPH_STRICT_MSGPACK must equal 'true'")

    output = {
        "status": "passed",
        "versions": verify_versions(),
        "sqlite_recovery": verify_sqlite_recovery(),
        "network_used": False,
        "model_api_used": False,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
