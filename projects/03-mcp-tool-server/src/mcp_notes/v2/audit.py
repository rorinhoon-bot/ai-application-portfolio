"""No-replace receipts in a deployment-owned directory, no raw arguments."""
from datetime import datetime, timezone

from mcp_notes.safe_task_write import publish_task_file
from .catalog import digest
from .contracts import ToolFailure


class Audit:
    def __init__(self, root):
        self.root = str(root)

    def record(self, *, call_id, phase, tool, snapshot_hash, arguments_hash, result=None):
        event = {
            "schema_version": "p3-audit-v2", "call_id": call_id, "phase": phase,
            "tool": tool, "snapshot_hash": snapshot_hash, "arguments_hash": arguments_hash,
            "time": datetime.now(timezone.utc).isoformat(),
            "result_hash": digest(result) if result is not None else None,
            "error_code": result.get("error_code") if result is not None else None,
        }
        event["content_hash"] = digest(event)
        try:
            outcome = publish_task_file(self.root, f"audit-{call_id}-{phase}", event)
            if outcome != "created":
                raise ToolFailure("audit-unavailable")
        except Exception:
            raise ToolFailure("audit-unavailable") from None
        return event
