"""D-3 测试 28 用「受测启动包装器」（受控 Host 启动入口，仅测试使用）。

严格复刻生产 demo / evals 的 bootstrap 路径（D-3 §7.2 E-28）：先经 `MCP_NOTES_IDENTITY_FILE`
加载 `RuntimeIdentity`，再构造 `TrustedHostController(... identity=identity)`——**不保留
`subject=` 入口**，否则会制造 D-3 §5.1 禁止的「绕开加载器直接传裸 str」路径。

bootstrap 失败（身份文件缺失 / schema 非法 / 相等性断言失败）→ 仅向 stderr 输出稳定码
`invalid-arguments`、非零退出；不泄露路径 / 用户名 / Traceback / 原始异常。生产不使用本文件。
"""

import os
import sys
import tempfile

_SRC = os.environ.get("P3_SRC")
if _SRC and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from mcp_notes.host import TrustedHostController  # noqa: E402
from mcp_notes.identity import load_runtime_identity  # noqa: E402
from mcp_notes.tasks import TaskPublishError  # noqa: E402


def main() -> int:
    try:
        identity = load_runtime_identity(os.environ)
        tmp = tempfile.mkdtemp(prefix="p3-launcher-")
        db_path = os.path.join(tmp, "control.db")
        task_root = os.path.join(tmp, "tasks")
        os.makedirs(task_root, exist_ok=True)
        # 构造受控 Host（仅验证 bootstrap 注入；不执行任何确认动作）
        TrustedHostController(db_path, task_root, identity)
    except TaskPublishError:
        # bootstrap 身份失败：仅输出稳定码，不回显路径/正文/异常
        sys.stderr.write("invalid-arguments\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
