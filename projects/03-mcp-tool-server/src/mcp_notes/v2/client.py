"""Bounded read-only retry. Write intentions are never automatically retried."""
import asyncio
import json
from mcp.shared.exceptions import MCPError
from mcp_types import REQUEST_TIMEOUT

from .contracts import Result, ToolFailure


async def call_bounded(client, name, arguments, *, timeout_seconds=3.0):
    if not 0 < timeout_seconds <= 30:
        raise ValueError("invalid-arguments")
    attempts = 2 if name in ("search_notes", "read_note") else 1
    for attempt in range(attempts):
        try:
            wire = await asyncio.wait_for(client.call_tool(name, arguments,
                                         read_timeout_seconds=timeout_seconds), timeout_seconds)
            payload = Result.model_validate(wire.structured_content)
            if (bool(wire.is_error) != (payload.status == "error") or len(wire.content) != 1
                    or json.loads(wire.content[0].text) != payload.model_dump(mode="json")):
                raise ToolFailure("output-invalid")
        except asyncio.TimeoutError:
            if attempt + 1 < attempts:
                continue
            raise ToolFailure("tool-timeout") from None
        except MCPError as exc:
            if exc.code == REQUEST_TIMEOUT:
                if attempt + 1 < attempts:
                    continue
                raise ToolFailure("tool-timeout") from None
            raise ToolFailure("io-error") from None
        except ToolFailure:
            raise
        except Exception:
            raise ToolFailure("output-invalid") from None
        if payload.error_code in ("tool-timeout", "io-error") and attempt + 1 < attempts:
            continue
        return payload
