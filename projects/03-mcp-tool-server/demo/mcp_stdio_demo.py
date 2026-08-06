r"""P3 C 阶段 stdio 演示：真实本地 stdio MCP Server/Client 成功 + 失败路径。

演示内容（全部使用虚构夹具，运行时只用 stdio；测试中的父进程与 Server 子进程均
默认阻断外部网络（生产不受影响）/ 不调模型 / 不暴露路径或正文）：

成功路径
  1. list_tools：仅暴露 search_notes 与 create_task；approve/reject/cancel 不暴露。
  2. search_notes("检索")：返回命中（稳定 note_id / 标题 / 脱敏摘录 / 匹配计数）。
  3. create_task(title, description)：经 stdio 调用，返回 PENDING（task_id +
     confirmation_id）；不写任务文件。
  4. 本地可信 Host 在 Tool 外批准该 confirmation_id（TrustedContext 由服务自有
     记录派生），验证受控任务文件被 no-replace 原子发布。

失败路径（均返回稳定错误码，不泄露异常 / 路径 / 正文）
  5. search_notes("..")：非法关键词 → invalid-arguments。
  6. create_task("", description)：空标题 → invalid-arguments。
  7. Host 批准未知 / 非法 confirmation_id → confirmation-required。
  8. Host 以错绑 subject 批准已知 confirmation_id → confirmation-identity-mismatch
     （证明身份绑定由 TasksStore 强制，错绑被拒）。

运行：`.venv/Scripts/python.exe demo/mcp_stdio_demo.py`（须在项目根目录，src 自动加入路径）。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from mcp.client import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

from mcp_notes.host import TrustedHostController  # noqa: E402

_SUBJECT = "p3-local-service"
_FIXTURES = os.path.join(_ROOT, "evals", "fixtures", "notes-v1")


def _redact(text: str) -> str:
    """把工具/Host 返回的脱敏 JSON 文本原样展示（其本身已不含路径/正文/密钥）。"""
    return text


def _echo(step: str, payload) -> None:
    print(f"\n=== {step} ===")
    if isinstance(payload, str):
        print(_redact(payload))
    else:
        print(payload)


async def _run(tmp: str) -> dict:
    notes_root = os.path.join(tmp, "notes")
    task_root = os.path.join(tmp, "tasks")
    db_path = os.path.join(tmp, "control.db")
    os.makedirs(notes_root, exist_ok=True)
    os.makedirs(task_root, exist_ok=True)
    # 复制虚构夹具到临时笔记根（演示自包含，不污染仓库）
    if os.path.isdir(_FIXTURES):
        for name in os.listdir(_FIXTURES):
            if name.endswith(".md"):
                shutil.copyfile(
                    os.path.join(_FIXTURES, name), os.path.join(notes_root, name)
                )

    env = dict(os.environ)
    env["PYTHONPATH"] = _SRC
    env["MCP_NOTES_DB_PATH"] = db_path
    env["MCP_NOTES_TASK_ROOT"] = task_root
    env["MCP_NOTES_NOTES_ROOT"] = notes_root
    env["MCP_NOTES_SUBJECT"] = _SUBJECT

    results: dict = {}

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_notes.server"],
        env=env,
        cwd=_ROOT,
    )

    async with Client(stdio_client(params)) as client:
        # 1. list_tools
        tools = await client.list_tools()
        tool_names = sorted(t.name for t in tools.tools)
        _echo("1. list_tools", tool_names)
        exposed = set(tool_names)
        results["tools_exposed"] = tool_names
        results["approve_not_exposed"] = not any(
            n in exposed for n in ("approve", "reject", "cancel")
        )

        # 2. search_notes success
        r = await client.call_tool("search_notes", {"keyword": "检索"})
        _echo("2. search_notes('检索')", r.content[0].text)
        results["search_success"] = json.loads(r.content[0].text)

        # 5. search_notes failure (invalid keyword)
        r = await client.call_tool("search_notes", {"keyword": ".."})
        _echo("5. search_notes('..') [失败预期]", r.content[0].text)
        results["search_invalid"] = json.loads(r.content[0].text)

        # 3. create_task success
        r = await client.call_tool(
            "create_task",
            {"title": "复习任务", "description": "每天复习一小时"},
        )
        _echo("3. create_task [PENDING]", r.content[0].text)
        created = json.loads(r.content[0].text)
        results["create_pending"] = created

        # 6. create_task invalid (empty title)
        r = await client.call_tool("create_task", {"title": "", "description": "x"})
        _echo("6. create_task('') [失败预期]", r.content[0].text)
        results["create_invalid"] = json.loads(r.content[0].text)

    # 4. Host approve (outside tool surface) -> verify published file
    host = TrustedHostController(db_path, task_root, _SUBJECT)
    cid = created.get("confirmation_id")
    tid = created.get("task_id")
    ap = host.approve(cid)
    _echo("4. Host.approve(confirmation_id) [本地可信确认]", ap)
    published = os.path.join(task_root, f"{tid}.json")
    results["published_exists"] = os.path.exists(published)
    _echo("4b. 受控任务文件已发布", f"exists={results['published_exists']}")
    host.close()

    # 7. Host approve unknown confirmation
    host2 = TrustedHostController(db_path, task_root, _SUBJECT)
    ap_unknown = host2.approve("conf-0000000000000000")
    _echo("7. Host.approve(未知 confirmation_id) [失败预期]", ap_unknown)
    results["approve_unknown"] = ap_unknown.outcome
    host2.close()

    # 8. Host 以错绑 subject 批准已知 confirmation_id（演示身份绑定由 Host 配置强制）
    # 复用同一个 cid；用错误 subject 配置的 Host 批准应被身份绑定拒绝
    host3 = TrustedHostController(db_path, task_root, "attacker-subject")
    ap_mismatch = host3.approve(cid)
    _echo("8. Host.approve(错绑 subject) [失败预期]", ap_mismatch)
    results["approve_mismatch"] = ap_mismatch.error_code
    host3.close()

    return results


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="p3-stdio-demo-")
    try:
        results = asyncio.run(_run(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n========== DEMO SUMMARY ==========")
    print("tools exposed        :", results.get("tools_exposed"))
    print("approve/reject/cancel not exposed:", results.get("approve_not_exposed"))
    print("search success hits  :", results.get("search_success", {}).get("total_matched"))
    print("search invalid code  :", results.get("search_invalid", {}).get("error_code"))
    print("create pending status:", results.get("create_pending", {}).get("status"))
    print("create invalid code  :", results.get("create_invalid", {}).get("error_code"))
    print("published file exists:", results.get("published_exists"))
    print("approve unknown      :", results.get("approve_unknown"))
    print("approve mismatch code:", results.get("approve_mismatch"))
    ok = (
        results.get("approve_not_exposed")
        and results.get("search_success", {}).get("status") == "ok"
        and results.get("search_invalid", {}).get("error_code") == "invalid-arguments"
        and results.get("create_pending", {}).get("status") == "pending"
        and results.get("create_invalid", {}).get("error_code") == "invalid-arguments"
        and results.get("published_exists")
        and results.get("approve_unknown") == "error"
        and results.get("approve_mismatch") == "confirmation-identity-mismatch"
    )
    print("ALL CHECKS PASSED    :", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
