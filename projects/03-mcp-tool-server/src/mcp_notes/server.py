r"""P3 C 阶段：本地 MCP Server 适配层（stdio only，复用 B2a 安全核心）。

本模块是 P3 C 阶段唯一新增的 MCP 集成代码，刻意只做“适配”，不改变底层安全语义：

- Server：`mcp.server.MCPServer`（v2 高层 API，非 FastMCP）。
- Tool `search_notes(keyword)`：只读检索，复用 `search.py` + `index.py` 对**虚构**
  笔记夹具建立索引；结果仅含稳定 note_id / 标题 / 脱敏截断摘录 / 匹配计数，绝不
  泄露绝对路径、正文或用户名。
- Tool `create_task(title, description)`：仅创建 **PENDING** 待确认意图。
  `TrustedContext` 由本 Server 的受控本地配置派生——`subject` 来自服务配置（固定），
  `correlation_id` 由 Server **按规范化请求内容本地派生**（内容哈希）；客户端不能直接提供或覆盖 correlation_id，它不是凭证、不授予批准权限，批准仍要求 Tool 外本地 Host、自身受控 subject 与记录匹配；相同规范化请求重放得到相同
  task_id / confirmation_id，MCP 重试保持幂等（见 D-018）。批准 / 拒绝 / 取消**不**
  作为 Tool 暴露，由本地可信 Host 控制器在 Tool 外调用既有 `tasks.py` 核心完成。
- Resource `notes://service-info`：静态只读服务描述（服务名 / 版本 / transport /
  工具清单 / 身份派生说明），不含任何绝对路径或密钥。
- 不使用 `ctx.elicit()` / `Resolve()` 或任何 MCP 客户端输入作为可信人工确认或身份来源。
- 所有结果以脱敏 JSON 文本返回；业务失败（非法参数 / 幂等冲突 / 未知确认等）携带
  稳定错误码，绝不回显异常文本、路径或正文。

仅本地 stdio。不引入 mcp[cli] / Inspector / HTTP / SSE / WebSocket / uv / 网络 Transport，
不联网、不调用真实模型 API、不读写真实私人笔记、不创建真实 symlink/junction。

网络说明（P1-5）：运行时只用 stdio；测试中的父进程与 Server 子进程均默认阻断外部
网络（仅测试环境开关 `NETWORK_ACCESS_BLOCKED_IN_TESTS=1` 启用），生产不受影响。
"""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.shared.exceptions import MCPError
from mcp_types import CallToolResult, TextContent

from . import contracts
from .contracts import (
    INVALID_ARGUMENTS,
    Keyword,
    NoteIndexEntry,
    SearchHit,
    validate_keyword,
)
from ._network_block import maybe_install_network_block
from .search import search_notes
from .index import build_index, read_note_content
from .safe_open import IndexBuildFailed, UnsafeOpenUnavailable
from .tasks import (
    CONFIRMATION_REQUIRED,
    TASK_ROOT_UNSAFE,
    TASK_WRITE_FAILED,
    TaskPublishError,
    TasksStore,
    TrustedContext,
    _valid_correlation_id,
    _valid_subject,
)

_SERVICE_NAME = "p3-local-notes"
_SERVICE_VERSION = "1.0.0"

# 规范化请求内容 → 稳定关联 ID 的分隔符（与 tasks.py 的 _CONTENT_SEP 同义）
_CONTENT_SEP = "\x1f"

# 每个 Tool 允许的字段与必填字段（用于协议层形状守卫：拒绝非对象 / 未知字段 /
# 缺失必填；未知字段绝不静默忽略）。
_TOOL_ARG_SPEC: dict[str, tuple[set[str], set[str]]] = {
    "search_notes": ({"keyword"}, {"keyword"}),
    "create_task": ({"title", "description"}, {"title", "description"}),
}


def _derive_correlation_id(title: str, description: str) -> str:
    """服务端按规范化请求内容派生的稳定关联 ID（P0-3 幂等）。

    相同规范化 title/description → 相同 correlation_id → 相同 task_id /
    confirmation_id；不同内容 → 不同 correlation_id → 独立意图。客户端不能直接提供或覆盖 correlation_id，它不是凭证、不授予批准权限，批准仍要求 Tool 外本地 Host、自身受控 subject 与记录匹配。subject 仍来自服务配置，不在此派生。
    """
    norm = (
        unicodedata.normalize("NFKC", title).strip()
        + _CONTENT_SEP
        + unicodedata.normalize("NFKC", description).strip()
    )
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ServerConfig:
    """Server 受控本地配置（绝不含客户端可控字段）。

    subject 固定为服务身份，须符合 D-1 精确字符白名单
    `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`（缺失/非法在 `from_env` 失败关闭）；
    correlation_id 由 Server 运行时本地派生，不在此配置。
    task_root 必须由部署配置预存在（见 D-015）；本模块**绝不**创建任务根或任何祖先目录。`server.main()` 仅创建部署配置指定的 SQLite 状态库父目录（`os.path.dirname(db_path)`），绝不创建 `task_root`。
    """

    db_path: str
    task_root: str
    notes_root: str
    subject: str
    service_name: str = _SERVICE_NAME
    version: str = _SERVICE_VERSION

    @classmethod
    def from_env(cls, environ: Optional[dict] = None) -> "ServerConfig":
        """从环境变量读取配置，缺省使用虚构相对路径（指向仓库内虚构夹具）。

        不读写真实私人笔记；notes_root 默认真实指向本仓库 `evals/fixtures/notes-v1`
        （原创虚构数据），task_root / db_path 默认在 `.mcp-notes/` 下，须由部署配置
        预存在（入口不创建任务根）。
        """
        env = environ if environ is not None else dict(os.environ)
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        # src/mcp_notes -> 上两级到仓库根 -> evals/fixtures/notes-v1（真实虚构夹具）
        default_notes = os.path.abspath(
            os.path.join(pkg_dir, "..", "..", "evals", "fixtures", "notes-v1")
        )
        config = cls(
            db_path=env.get("MCP_NOTES_DB_PATH", os.path.join(".mcp-notes", "control.db")),
            task_root=env.get("MCP_NOTES_TASK_ROOT", os.path.join(".mcp-notes", "tasks")),
            notes_root=env.get("MCP_NOTES_NOTES_ROOT", default_notes),
            subject=env.get("MCP_NOTES_SUBJECT", "p3-local-service"),
        )
        # D-1 配置启动失败关闭：subject 必须符合精确字符白名单，缺失/非法不启动 Server
        if not _valid_subject(config.subject):
            raise TaskPublishError(INVALID_ARGUMENTS)
        return config


def _hit_to_dict(hit: SearchHit) -> dict:
    return {
        "note_id": hit.note_id,
        "title": hit.title,
        "excerpt": hit.excerpt,
        "match_count": hit.match_count,
    }


def _build_entries(notes_root: str) -> Sequence[NoteIndexEntry]:
    """建立笔记索引；任何失败（原生不可用 / reparse / IO）整体失败、返回空索引，
    不让 Server 崩溃、不泄露底层错误。检索层对空索引安全返回 0 命中。
    """
    try:
        return tuple(build_index(notes_root))
    except (UnsafeOpenUnavailable, IndexBuildFailed):
        return ()


def _ok(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _err(code: str, extra: Optional[dict] = None) -> str:
    payload = {"status": "error", "error_code": code}
    if extra:
        payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


class SafeMCPServer(MCPServer):
    """MCPServer 子类：在协议层拦截 Tool 调用异常与非法参数形状。

    关键修复（P0-2）：框架对 Tool 参数的 Pydantic 校验若失败，会把原始异常文本
    （含类型细节与 URL）回显给客户端。本子类在 `_handle_call_tool` 统一：

    - 形状守卫：参数非对象 / 含未知字段 / 缺失必填 → 直接返回脱敏
      `invalid-arguments`，且不静默忽略未知字段；
    - 任何残留异常（含框架参数校验）→ 脱敏为 `invalid-arguments`，绝不回显 `str(e)`、
      类型细节或 Pydantic 文档 URL；
    - `MCPError`（协议级错误）仍按原样上抛。
    """

    _allowed_args: dict[str, tuple[set[str], set[str]]] = {}

    async def _handle_call_tool(self, ctx, params):
        context = Context(
            request_context=ctx,
            mcp_server=self,
            input_params=params,
            subscriptions=self._subscriptions,
        )
        name = params.name
        arguments = params.arguments or {}
        # 形状守卫：非对象 / 未知字段 / 缺失必填 → 稳定 invalid-arguments（不泄露）
        if not isinstance(arguments, dict):
            return CallToolResult(
                content=[TextContent(type="text", text=_err(INVALID_ARGUMENTS))],
                is_error=True,
            )
        allowed = self._allowed_args.get(name)
        if allowed is not None:
            allowed_keys, required_keys = allowed
            keys = set(arguments.keys())
            if not keys <= allowed_keys or not required_keys <= keys:
                return CallToolResult(
                    content=[TextContent(type="text", text=_err(INVALID_ARGUMENTS))],
                    is_error=True,
                )
        try:
            return await self.call_tool(name, arguments, context)
        except MCPError:
            raise
        except Exception:  # noqa: BLE001 - 失败关闭，绝不回显异常文本 / 类型 / URL
            return CallToolResult(
                content=[TextContent(type="text", text=_err(INVALID_ARGUMENTS))],
                is_error=True,
            )


def build_server(config: ServerConfig) -> SafeMCPServer:
    """构造并注册 Tools / Resource 的 `SafeMCPServer`（v2）。

    复用既有安全核心：`search_notes` / `build_index` / `read_note_content` /
    `TasksStore`。`create_task` 仅创建 PENDING；`TrustedContext` 由 Server 本地配置
    派生（subject 固定，correlation_id 按规范化请求内容派生）。`approve` / `reject` /
    `cancel` 不注册为 Tool。
    """
    entries: Sequence[NoteIndexEntry] = _build_entries(config.notes_root)
    notes_root = config.notes_root
    content_provider: Callable[[NoteIndexEntry], str] = (
        lambda entry: read_note_content(entry, notes_root)
    )
    subject = config.subject

    server = SafeMCPServer(name=config.service_name)
    server._allowed_args = dict(_TOOL_ARG_SPEC)

    @server.tool(
        name="search_notes",
        description=(
            "在受控笔记集中做只读关键词检索，返回稳定 note_id、标题、脱敏截断摘录与"
            "匹配计数。不暴露绝对路径、正文或用户名。参数 keyword 为单一关键词字符串，"
            "长度 1..80，拒绝路径/URL/命令语义。"
        ),
    )
    def search_notes_tool(keyword: str) -> str:
        kw = validate_keyword(keyword)
        if not isinstance(kw, Keyword):
            return _err(INVALID_ARGUMENTS)
        result = search_notes(kw, entries, content_provider)
        return _ok(
            {
                "status": result.status,
                "hits": [_hit_to_dict(h) for h in result.hits],
                "total_matched": result.total_matched,
            }
        )

    @server.tool(
        name="create_task",
        description=(
            "创建一条受控任务意图（PENDING，待本地可信人工确认）。仅登记意图并等待"
            "确认；不写任务文件、不发布。TrustedContext 由 Server 本地配置派生"
            "(subject 固定，correlation_id 按规范化请求内容派生，相同请求重放幂等)，"
            "不取用任何客户端输入。批准/拒绝/取消由本地可信 Host 在 Tool 外完成，"
            "不作为 Tool 暴露。参数仅接受 title 与 description（字符串）。"
        ),
    )
    def create_task_tool(title: str, description: str) -> str:
        # correlation_id 由 Server 按规范化请求内容本地派生（P0-3 幂等），绝不来自
        # Tool 参数 / 客户端 / 模型文本 / MCP 请求字段
        correlation_id = _derive_correlation_id(title, description)
        # D-1 契约守卫：派生 correlation_id 必为 64 位小写十六进制（sha256.hexdigest）；
        # 客户端永远不能直接提供或覆盖 correlation_id
        if not _valid_correlation_id(correlation_id):
            return _err(INVALID_ARGUMENTS)
        try:
            ctx = TrustedContext(subject, correlation_id)
        except TaskPublishError:
            # 配置 subject 非法（不应发生）：失败关闭，不泄露
            return _err(INVALID_ARGUMENTS)
        # TasksStore 连接在此 worker 线程内创建并使用，避免跨线程共享 sqlite 连接
        # （MCP v2 在独立线程运行 Tool 处理器）。
        store = TasksStore(config.db_path, config.task_root)
        try:
            res = store.create_task(title, description, ctx)
        except TaskPublishError as exc:
            return _err(exc.code)
        except Exception:  # noqa: BLE001 - 失败关闭，绝不回显异常文本
            return _err(TASK_WRITE_FAILED)
        finally:
            store.close()
        if res.outcome == "pending":
            return _ok(
                {
                    "status": "pending",
                    "task_id": res.task_id,
                    "confirmation_id": res.confirmation_id,
                    "expires_at": res.expires_at,
                    "note": (
                        "Intent created. Must be approved by the local trusted host "
                        "outside the MCP tool surface before any file is written."
                    ),
                }
            )
        # unchanged / error：直接透传稳定 outcome 与 error_code（不含路径 / 正文）
        return _ok(
            {
                "status": res.outcome,
                "task_id": res.task_id,
                "confirmation_id": res.confirmation_id,
                "error_code": res.error_code,
            }
        )

    @server.resource(
        "notes://service-info",
        mime_type="application/json",
        description="静态只读服务描述：服务名、版本、transport、工具清单与身份派生说明。",
    )
    def service_info() -> str:
        return _ok(
            {
                "service": config.service_name,
                "version": config.version,
                "transport": "stdio",
                "tools": ["search_notes", "create_task"],
                "tools_note": (
                    "create_task returns PENDING only. approve/reject/cancel are handled "
                    "by the local trusted host outside the MCP tool surface and are NOT "
                    "exposed as tools."
                ),
                "resources": ["notes://service-info"],
                "allowed_dirs": {
                    "notes_root": "<controlled fictional notes dir, configured at start>",
                    "task_root": "<controlled task dir, pre-existing per deployment config>",
                },
                "identity": (
                    "TrustedContext.subject is server-configured and fixed. correlation_id is "
                    "deterministically derived by the server from the verified, NFKC-normalized "
                    "title/description (idempotent on replay). The client cannot directly supply "
                    "or override correlation_id. It is not a credential and grants no approval "
                    "authority; approval still requires the Tool-external local Host, its own "
                    "controlled subject, and a matching persisted record."
                ),
                "network": (
                    "Runtime uses stdio only. In tests, both the parent process and the Server "
                    "subprocess default to blocking external network access (test-only switch); "
                    "production network capability is unchanged."
                ),
            }
        )

    return server


def main() -> None:
    """`python -m mcp_notes.server` 入口：本地 stdio 运行。

    任务根（task_root）必须由部署配置预存在（D-015）；入口**绝不**创建任务根，缺失
    时由底层句柄级安全层以 `task-root-unsafe` 失败关闭；`server.main()` 仅创建部署配置指定的 SQLite 状态库父目录（`os.makedirs(os.path.dirname(db_path), exist_ok=True)`），绝不创建 `task_root` 或其祖先目录。task_root 必须预存在，缺失 / 越界 / reparse / 原生不可用时仍以 `task-root-unsafe` 失败关闭。
    仅测试环境（NETWORK_ACCESS_BLOCKED_IN_TESTS=1）为 Server 子进程启用网络阻断。
    """
    config = ServerConfig.from_env()
    # 仅测试环境：为 Server 子进程启用外部网络阻断；生产不受影响
    maybe_install_network_block()
    # 注意：此处不创建 task_root；其预存在性由 safe_task_write 句柄层在发布时校验。
    # 创建部署配置指定的 SQLite 状态库父目录（仅此目录；绝不创建 task_root 或其祖先目录）。
    db_dir = os.path.dirname(os.path.abspath(config.db_path)) or "."
    os.makedirs(db_dir, exist_ok=True)
    server = build_server(config)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
