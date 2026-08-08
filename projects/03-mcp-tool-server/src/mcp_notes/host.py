r"""P3 C 阶段：本地可信 Host 控制器（在 MCP Tool 之外批准 / 拒绝 / 取消）。

本模块是“受控人工确认”的落点，刻意**不**作为 MCP Tool 暴露，而是由本地可信
进程在 Tool 调用之外直接驱动既有 `tasks.py` 核心：

- `TrustedHostController.approve / reject / cancel(confirmation_id)`：
  先通过 `TasksStore.lookup_correlation_id` 从服务**自有持久化记录**取回该
  confirmation 的 correlation_id，再**用 Host 自身配置的 `self._subject`** 重建
  `TrustedContext`，最后调用 `TasksStore` 对应方法。身份绑定的 subject **来自 Host
  受控配置**，绝不直接信任记录中的 subject 作为授权主体（见 P0-4 / D-018）。
- `TrustedContext` 的 correlation_id 来自服务自身存储，subject 来自 Host 配置；
  绝不取自 Tool 参数、模型文本、MCP 请求字段或客户端自报值；身份绑定
  （subject + correlation_id 同时相等）由 `TasksStore` 强制校验。
- 仅本地、离线；不联网、不调用模型、不暴露绝对路径或正文。

该控制器用于 C/D 阶段演示与集成测试中的“批准 / 拒绝 / 取消”步骤，证明受控写
的确认动作完全在 MCP Tool 表面之外、由本地可信边界完成。

网络说明（P1-5）：运行时只用 stdio；测试中的父进程与 Server 子进程均默认阻断
外部网络。
"""

from __future__ import annotations

from typing import Optional

from .identity import RuntimeIdentity
from .tasks import (
    CONFIRMATION_REQUIRED,
    INVALID_ARGUMENTS,
    TaskPublishError,
    TaskResult,
    TasksStore,
    TrustedContext,
    _valid_correlation_id,
    _valid_subject,
)


class TrustedHostController:
    """本地可信 Host 控制器：在 Tool 外完成一次确认消费。

    身份绑定的 subject 来自 Host 受控配置（`self._subject`），由 D-3 唯一可信来源
    `identity.json`（经 `load_runtime_identity()` 加载的 `RuntimeIdentity`）注入；
    须符合 D-1 精确字符白名单 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`（缺失/非法在
    构造时失败关闭）；correlation_id 来自服务自有持久化记录（64 位小写十六进制派生）；
    不接收任何客户端可控身份。**生产构造器不再接受裸 `subject: str`**——传入非
    `RuntimeIdentity` → `TaskPublishError(INVALID_ARGUMENTS)` 失败关闭（见 D-3 §5.1）。
    """

    def __init__(self, db_path: str, task_root: str, identity: RuntimeIdentity, clock=None):
        # D-3 §5.1：生产构造器仅接受 RuntimeIdentity；裸 str 或任何非 RuntimeIdentity
        # → 失败关闭（绝不接受绕过加载器的裸 subject 入口）。
        if not isinstance(identity, RuntimeIdentity):
            raise TaskPublishError(INVALID_ARGUMENTS)
        subject = identity.subject
        # D-1 纵深防御：subject 仍须符合精确字符白名单，缺失/非法不构建控制器
        if not _valid_subject(subject):
            raise TaskPublishError(INVALID_ARGUMENTS)
        self._store = TasksStore(db_path, task_root, clock)
        self._subject = subject

    def _rebuild_context(self, confirmation_id) -> Optional[TrustedContext]:
        """用 Host 自身 subject + 记录 correlation_id 重建受控上下文。

        记录不存在 / 非法 / 损坏 → 返回 None（稳定 CONFIRMATION_REQUIRED）。
        绝不使用记录中的 subject 作为授权主体。
        """
        corr = self._store.lookup_correlation_id(confirmation_id)
        if corr is None:
            return None
        # P0-1：取回的 correlation_id 必须经核心格式校验；损坏/旧格式（非 64 位小写
        # 十六进制）→ 失败关闭，绝不写文件、不泄露原始值。
        if not _valid_correlation_id(corr):
            return None
        try:
            return TrustedContext(self._subject, corr)
        except Exception:  # noqa: BLE001 - 非法受控上下文：失败关闭
            return None

    def approve(self, confirmation_id) -> TaskResult:
        ctx = self._rebuild_context(confirmation_id)
        if ctx is None:
            # 未知 / 非法 / 损坏确认：稳定错误码，不回显输入、不泄露路径
            return TaskResult.error(CONFIRMATION_REQUIRED, confirmation_id)
        return self._store.approve(confirmation_id, ctx)

    def reject(self, confirmation_id) -> TaskResult:
        ctx = self._rebuild_context(confirmation_id)
        if ctx is None:
            return TaskResult.error(CONFIRMATION_REQUIRED, confirmation_id)
        return self._store.reject(confirmation_id, ctx)

    def cancel(self, confirmation_id) -> TaskResult:
        ctx = self._rebuild_context(confirmation_id)
        if ctx is None:
            return TaskResult.error(CONFIRMATION_REQUIRED, confirmation_id)
        return self._store.cancel(confirmation_id, ctx)

    def close(self) -> None:
        self._store.close()
