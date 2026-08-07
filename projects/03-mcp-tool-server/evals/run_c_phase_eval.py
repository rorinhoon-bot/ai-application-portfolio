r"""P3 C 阶段离线固定评估运行器（确定性、离线、虚构数据、无模型、不联网）。

读取 `evals/gold/c-phase-v1.json` 的固定期望，经真实 MCP 适配层（in-process v2
Client(Server)）跑固定场景，逐项比对稳定结果，输出评估报表与计数。覆盖：

- Tool 清单：仅 search_notes / create_task；approve/reject/cancel 不暴露。
- search_notes 成功（虚构夹具命中）与失败（非法关键词 → invalid-arguments）。
- create_task 成功返回 PENDING（task_id / confirmation_id 格式稳定）与失败
  （空标题 → invalid-arguments）。
- 本地可信 Host（Tool 外）批准 / 拒绝 / 取消 / 未知确认 / 身份错绑，命中固定
  稳定错误码；负向终态不发布任务文件。

全部使用 `evals/fixtures/notes-v1` 虚构笔记与临时受控目录；不读写真实私人笔记、
不调用模型、不联网。运行：`.venv/Scripts/python.exe evals/run_c_phase_eval.py`。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import tempfile

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from mcp.client import Client  # noqa: E402

from mcp_notes.host import TrustedHostController  # noqa: E402
from mcp_notes.server import ServerConfig, build_server  # noqa: E402
from mcp_notes.tasks import (  # noqa: E402
    CONFIRMATION_IDENTITY_MISMATCH,
    CONFIRMATION_REQUIRED,
    TasksStore,
    TrustedContext,
)

_FIXTURES = os.path.join(_ROOT, "evals", "fixtures", "notes-v1")
_GOLD = os.path.join(_ROOT, "evals", "gold", "c-phase-v1.json")
_SUBJECT = "p3-local-service"


def _load_gold() -> dict:
    with open(_GOLD, encoding="utf-8") as f:
        return json.load(f)


def _check(name: str, cond: bool, detail: str, results: list) -> None:
    results.append((name, cond, detail))
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}: {detail}")


async def _run(tmp: str, gold: dict, results: list) -> None:
    notes_root = os.path.join(tmp, "notes")
    task_root = os.path.join(tmp, "tasks")
    db_path = os.path.join(tmp, "control.db")
    os.makedirs(notes_root, exist_ok=True)
    os.makedirs(task_root, exist_ok=True)
    if os.path.isdir(_FIXTURES):
        for n in os.listdir(_FIXTURES):
            if n.endswith(".md"):
                shutil.copyfile(os.path.join(_FIXTURES, n), os.path.join(notes_root, n))

    config = ServerConfig(
        db_path=db_path,
        task_root=task_root,
        notes_root=notes_root,
        subject=_SUBJECT,
    )
    server = build_server(config)
    exp = gold["expectations"]

    async with Client(server) as c:
        # Tool 清单
        tools = sorted(t.name for t in (await c.list_tools()).tools)
        _check(
            "tools_exposed",
            set(tools) == set(exp["tools"]),
            f"{tools} == {exp['tools']}",
            results,
        )
        exposed = set(tools)
        _check(
            "confirmation_actions_not_exposed",
            (not exp["confirmation_actions_exposed"])
            and not any(n in exposed for n in ("approve", "reject", "cancel")),
            f"approve/reject/cancel in {exposed}: {any(n in exposed for n in ('approve','reject','cancel'))}",
            results,
        )

        # search 成功
        se = exp["search_success"]
        r = await c.call_tool("search_notes", {"keyword": se["keyword"]})
        d = json.loads(r.content[0].text)
        _check(
            "search_success",
            d["status"] == se["status"] and d["total_matched"] == se["total_matched"],
            f"status={d['status']} total_matched={d['total_matched']}",
            results,
        )

        # search 失败
        si = exp["search_invalid"]
        r = await c.call_tool("search_notes", {"keyword": si["keyword"]})
        d = json.loads(r.content[0].text)
        _check(
            "search_invalid",
            d["status"] == si["status"] and d["error_code"] == si["error_code"],
            f"status={d['status']} code={d.get('error_code')}",
            results,
        )

        # create PENDING
        cp = exp["create_pending"]
        r = await c.call_tool("create_task", {"title": "复习任务", "description": "每天复习一小时"})
        d = json.loads(r.content[0].text)
        ok_pending = (
            d["status"] == cp["status"]
            and re.match(cp["task_id_pattern"], d["task_id"] or "")
            and re.match(cp["confirmation_id_pattern"], d["confirmation_id"] or "")
        )
        _check(
            "create_pending",
            ok_pending,
            f"status={d['status']} task_id={d['task_id']} cid={d['confirmation_id']}",
            results,
        )
        cid = d["confirmation_id"]
        tid = d["task_id"]

        # create 失败（空标题）
        ci = exp["create_invalid"]
        r = await c.call_tool("create_task", {"title": ci["title"], "description": "x"})
        d = json.loads(r.content[0].text)
        _check(
            "create_invalid",
            d["status"] == ci["status"] and d["error_code"] == ci["error_code"],
            f"status={d['status']} code={d.get('error_code')}",
            results,
        )

    # Host 批准（Tool 外）→ 发布文件
    ha = exp["host_approve"]
    host = TrustedHostController(db_path, task_root, _SUBJECT)
    ap = host.approve(cid)
    published = os.path.exists(os.path.join(task_root, f"{tid}.json"))
    _check(
        "host_approve",
        ap.outcome == ha["outcome"] and published == ha["publishes_file"],
        f"outcome={ap.outcome} published={published}",
        results,
    )
    host.close()

    # Host 拒绝
    store2 = TasksStore(db_path, task_root)
    ctx2 = TrustedContext(_SUBJECT, "b" * 64)
    res2 = store2.create_task("拒绝任务", "描述", ctx2)
    host2 = TrustedHostController(db_path, task_root, _SUBJECT)
    rj = host2.reject(res2.confirmation_id)
    _check(
        "host_reject",
        rj.outcome == exp["host_reject"]["outcome"]
        and not os.path.exists(os.path.join(task_root, res2.task_id + ".json")),
        f"outcome={rj.outcome}",
        results,
    )
    host2.close()
    store2.close()

    # Host 取消
    store3 = TasksStore(db_path, task_root)
    ctx3 = TrustedContext(_SUBJECT, "d" * 64)
    res3 = store3.create_task("取消任务", "描述", ctx3)
    host3 = TrustedHostController(db_path, task_root, _SUBJECT)
    cx = host3.cancel(res3.confirmation_id)
    _check(
        "host_cancel",
        cx.outcome == exp["host_cancel"]["outcome"]
        and not os.path.exists(os.path.join(task_root, res3.task_id + ".json")),
        f"outcome={cx.outcome}",
        results,
    )
    host3.close()
    store3.close()

    # Host 未知确认
    host4 = TrustedHostController(db_path, task_root, _SUBJECT)
    un = host4.approve("conf-0000000000000000")
    _check(
        "host_unknown",
        un.outcome == "error" and un.error_code == exp["host_unknown"]["error_code"],
        f"outcome={un.outcome} code={un.error_code}",
        results,
    )
    host4.close()

    # Host 身份错绑：记录属于 _SUBJECT，另一部署主体的 Host 不得批准（P0-4）
    store5 = TasksStore(db_path, task_root)
    ctx5 = TrustedContext(_SUBJECT, "e" * 64)
    res5 = store5.create_task("错绑任务", "描述", ctx5)
    host5 = TrustedHostController(db_path, task_root, "service-B-subject")
    mm = host5.approve(res5.confirmation_id)
    _check(
        "host_identity_mismatch",
        mm.error_code == exp["host_identity_mismatch"]["error_code"]
        and not os.path.exists(os.path.join(task_root, res5.task_id + ".json")),
        f"code={mm.error_code}",
        results,
    )
    host5.close()
    store5.close()


def main() -> int:
    gold = _load_gold()
    tmp = tempfile.mkdtemp(prefix="p3-eval-")
    results: list = []
    try:
        asyncio.run(_run(tmp, gold, results))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n========== C-PHASE OFFLINE EVAL REPORT ==========")
    print(f"scenarios: {total}  passed: {passed}  failed: {total - passed}")
    print(
        "all stable (no model call / stdio-only runtime, external network blocked in tests / "
        f"fictional fixtures): {passed == total}"
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
