r"""P3 Slice B2a：create_task 受控写入离线核心（纯标准库，离线，无 MCP SDK）。

本切片实现“受控写”的离线核心，刻意不含任何 MCP Server / Resource / stdio /
Host / Client 代码（那些属于后续 B2b，需单独批准）：

- `create_task(title, description, trusted_context)` 严格数据合同与参数校验：
  仅在缺失可信本地主体 / 关联 ID 或参数非法时返回稳定 `invalid-arguments`，
  不写任何文件、不联网。
- Human-in-the-loop 状态机：首次创建 `PENDING` 待确认意图；可信本地人工通过
  `approve` / `reject` / `cancel` 一次性消费；过期（创建后十分钟）懒求值转为
  `EXPIRED`。
- 确认绑定：可信主体、关联 ID、内容哈希与 `PENDING` 状态；身份错绑、未确认、过期、
  取消、重复批准、内容变化全部拒绝，且均不写任务文件。
- 持久化：标准库 `sqlite3` 保存确认记录、幂等映射与最小审计事件（审计不存正文）。
- 发布：受控任务目录内程序派生 `<task_id>.json`，no-replace 原子发布由
  `safe_task_write`（Windows 原生 `NtCreateFile(FILE_CREATE, OBJ_DONT_REPARSE)`
  原子无覆盖 + 句柄式任务根 / 祖先目录 reparse 与 TOCTOU 防护）完成；冲突绝不覆盖；
  最终路径仅由服务生成的 `task_id` 派生，外部无法指定。
- 不引入 MCP SDK、网络、模型、真实笔记或系统设置；不创建 / 运行真实链接。
- 所有失败映射为稳定错误码，不泄露路径、正文、用户名、密钥或原始异常栈。

设计依据：D-004（只建待确认意图）、D-005（十分钟有效期 + 一次性消费）、
D-006（稳定 task_id + no-replace 发布）、D-007（标准库 sqlite3 持久化）。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional

from .contracts import (
    INVALID_ARGUMENTS,
    TASK_TITLE_MIN,
    TASK_TITLE_MAX,
    TASK_DESC_MIN,
    TASK_DESC_MAX,
    validate_task_field,
)
from .safe_task_write import (
    SafeWriteError,
    publish_task_file as _safe_publish,
)

# --------------------------------------------------------------------------- #
# 稳定错误码（对外不含路径 / 正文 / 用户名 / 原始异常）
# --------------------------------------------------------------------------- #
CONFIRMATION_REQUIRED = "confirmation-required"
CONFIRMATION_IDENTITY_MISMATCH = "confirmation-identity-mismatch"
CONFIRMATION_MISMATCH = "confirmation-mismatch"
CONFIRMATION_EXPIRED = "confirmation-expired"
CONFIRMATION_ALREADY_CONSUMED = "confirmation-already-consumed"
CONFIRMATION_INVALID_ID = "confirmation-invalid-id"
IDEMPOTENCY_CONFLICT = "idempotency-conflict"
TASK_CONFLICT = "task-conflict"
TASK_WRITE_FAILED = "task-write-failed"
TASK_INVALID_ID = "task-invalid-id"
TASK_ROOT_UNSAFE = "task-root-unsafe"

# --------------------------------------------------------------------------- #
# 合同常量
# --------------------------------------------------------------------------- #
CONFIRM_VALIDITY_SECONDS = 600  # 确认有效期固定十分钟（D-005）
TASK_ID_RE = re.compile(r"^[A-Za-z0-9-]{4,64}$")
_CONTENT_SEP = "\x1f"  # 标题 / 描述之间的单位分隔符，避免归一后拼接歧义

# 终态集合（除 PENDING 外不可再被批准消费）
_TERMINAL_STATUSES = frozenset({"APPROVED", "REJECTED", "CANCELLED", "EXPIRED"})

# 可信上下文字段边界（P1-5）：非空 str，长度 1.._TRUSTED_MAX，无控制字符。
_TRUSTED_MAX = 256

# 服务生成的 confirmation_id 严格格式（P1-6）：conf- + 16 位十六进制。
_CONFIRMATION_ID_RE = re.compile(r"^conf-[0-9a-f]{16}$")

# D-1 精确身份格式：
#   subject      —— 受控配置身份，首字符须为字母/数字，其后 0..127 个
#                  字母/数字/`.`/`_`/`-`，总长 1..128。
#   correlation_id —— 由服务端按 NFKC 规范化的 title/description 派生的 64 位小写
#                  十六进制（hashlib.sha256(...).hexdigest()），无前缀；客户端永远
#                  不能直接提供或覆盖它。
_SUBJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CORRELATION_ID_RE = re.compile(r"^[0-9a-f]{64}$")


def _valid_trusted_value(value) -> bool:
    """TrustedContext.subject / correlation_id 的严格边界校验。"""
    if not isinstance(value, str):
        return False
    if len(value) < 1 or len(value) > _TRUSTED_MAX:
        return False
    for ch in value:
        # 拒绝所有 C0 / DEL 控制字符（ord < 0x20 或 == 0x7f）
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            return False
    return True


def _valid_subject(value) -> bool:
    """D-1: subject 精确字符白名单。

    首字符须为字母/数字，其后 0..127 个字母/数字/`.`/`_`/`-`，总长 1..128。
    """
    if not isinstance(value, str):
        return False
    return bool(_SUBJECT_RE.match(value))


def _valid_correlation_id(value) -> bool:
    """D-1: correlation_id 须为服务端按 NFKC 派生的 64 位小写十六进制（无前缀）。"""
    if not isinstance(value, str):
        return False
    return bool(_CORRELATION_ID_RE.match(value))


def _check_context(trusted_context) -> Optional[str]:
    """校验可信上下文是否合法；非法返回稳定 INVALID_ARGUMENTS（不抛异常）。"""
    if not isinstance(trusted_context, TrustedContext):
        return INVALID_ARGUMENTS
    if not _valid_subject(trusted_context.subject):
        return INVALID_ARGUMENTS
    if not _valid_correlation_id(trusted_context.correlation_id):
        return INVALID_ARGUMENTS
    return None


def _validate_confirmation_id(confirmation_id) -> bool:
    """校验服务生成的 confirmation_id 严格格式；非法或未知输入一律 False。"""
    if not isinstance(confirmation_id, str):
        return False
    return bool(_CONFIRMATION_ID_RE.match(confirmation_id))


@dataclass(frozen=True)
class TrustedContext:
    """可信本地边界注入的主体与调用关联 ID（非 Tool 参数，不由模型 / 客户端控制）。

    D-1 构造即校验：subject 必须符合精确字符白名单
    `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`（首字符字母/数字，总长 1..128）；
    correlation_id 必须匹配服务端按 NFKC 派生的 64 位小写十六进制
    `^[0-9a-f]{64}$`（无前缀），构造即强制校验；correlation_id 由服务端 `TasksStore`
    / `server` 派生落库，客户端永远不能直接提供或覆盖。subject 或 correlation_id
    不合法抛受控的 `TaskPublishError(INVALID_ARGUMENTS)`，绝不抛原始 TypeError 或泄露异常。
    """

    subject: str
    correlation_id: str

    def __init__(self, subject, correlation_id):
        if not _valid_subject(subject) or not _valid_correlation_id(correlation_id):
            raise TaskPublishError(INVALID_ARGUMENTS)
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "correlation_id", correlation_id)


@dataclass(frozen=True)
class TaskIntent:
    """确认意图（PENDING 待消费对象）。"""

    confirmation_id: str
    task_id: str
    subject: str
    correlation_id: str
    content_hash: str
    title: str
    description: str
    status: str
    created_at: float
    expires_at: float


@dataclass(frozen=True)
class TaskResult:
    """受控写对外结果。outcome 为 pending / created / unchanged / rejected /
    cancelled / error；error 分支携带稳定 error_code。"""

    outcome: str
    task_id: Optional[str]
    confirmation_id: Optional[str]
    error_code: Optional[str]
    expires_at: Optional[float] = None

    @classmethod
    def error(
        cls,
        code: str,
        confirmation_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> "TaskResult":
        return cls("error", task_id, confirmation_id, code)


class TaskPublishError(Exception):
    """内部发布异常，携带稳定错误码（不包裹原始 OSError 文本）。"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# D-4 的私有连接 seam：测试可以替换这些普通 Python 函数，不能也不应直接替换
# sqlite3.Connection（C 类型）。BEGIN IMMEDIATE 才是跨进程唯一消费的正确性闸门；
# busy_timeout 只降低暂时 SQLITE_BUSY 的概率。
def _make_connection(db_path: str):
    return sqlite3.connect(db_path)


def _commit(conn) -> None:
    conn.commit()


def _close(conn) -> None:
    conn.close()


def _content_hash(title: str, description: str) -> str:
    """内容哈希：规范化标题 + 描述（不含 title/desc 之外的任何绑定）。"""
    return hashlib.sha256(
        (title + _CONTENT_SEP + description).encode("utf-8")
    ).hexdigest()


def _derive_task_id(subject: str, correlation_id: str, content_hash: str) -> str:
    """稳定 task_id：绑定可信主体、关联 ID 与内容哈希；受限字符集（D-006）。"""
    seed = hashlib.sha256(
        (subject + _CONTENT_SEP + correlation_id + _CONTENT_SEP + content_hash).encode(
            "utf-8"
        )
    ).hexdigest()
    return "task-" + seed[:16]


def _derive_confirmation_id(task_id: str, content_hash: str) -> str:
    """稳定 confirmation_id：绑定 task_id 与内容哈希；同一意图可幂等重放。"""
    seed = hashlib.sha256(
        (task_id + _CONTENT_SEP + content_hash).encode("utf-8")
    ).hexdigest()
    return "conf-" + seed[:16]


class TasksStore:
    """受控写核心存储：sqlite3 持久化确认 / 幂等 / 审计 + 受控任务目录 no-replace 发布。

    所有公开方法都返回 `TaskResult`；任何非预期异常（sqlite3 错误）向上传播前回滚
    事务。写操作的高层失败（发布失败、冲突）走稳定错误码，不泄露底层细节。
    """

    def __init__(self, db_path: str, task_root: str, clock=None):
        self._db_path = db_path
        self._task_root = task_root
        self._clock = clock if clock is not None else time.time
        self._conn = _make_connection(db_path)
        self._configure_connection(self._conn)
        self._init_schema()

    def close(self) -> None:
        try:
            _close(self._conn)
        except sqlite3.Error:
            pass

    def _now(self) -> float:
        return self._clock()

    @staticmethod
    def _configure_connection(conn) -> None:
        """只缓解 SQLite 忙等待；绝不是并发正确性机制。"""
        conn.execute("PRAGMA busy_timeout = 5000")

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS confirmations (
                confirmation_id TEXT PRIMARY KEY,
                task_id         TEXT NOT NULL,
                subject         TEXT NOT NULL,
                correlation_id  TEXT NOT NULL,
                content_hash    TEXT NOT NULL,
                title           TEXT NOT NULL,
                description     TEXT NOT NULL,
                status          TEXT NOT NULL,
                created_at      REAL NOT NULL,
                expires_at      REAL NOT NULL,
                consumed_at     REAL
            );
            CREATE TABLE IF NOT EXISTS idempotency (
                subject         TEXT NOT NULL,
                correlation_id  TEXT NOT NULL,
                confirmation_id TEXT NOT NULL,
                task_id         TEXT NOT NULL,
                content_hash    TEXT NOT NULL,
                status          TEXT NOT NULL,
                PRIMARY KEY (subject, correlation_id)
            );
            CREATE TABLE IF NOT EXISTS audit (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at     REAL NOT NULL,
                event           TEXT NOT NULL,
                error_code      TEXT,
                task_id         TEXT,
                confirmation_id TEXT
            );
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # 公开 API
    # ------------------------------------------------------------------ #
    def create_task(
        self, title, description, trusted_context
    ) -> TaskResult:
        """建立冻结写意图并返回 PENDING_CONFIRMATION；不直接写任务文件。"""
        bad = _check_context(trusted_context)
        if bad is not None:
            # 缺失 / 非法可信主体或关联 ID → 拒绝建意图（PRD：缺失时拒绝写意图）
            return TaskResult.error(bad)
        norm_title = validate_task_field(title, TASK_TITLE_MIN, TASK_TITLE_MAX)
        norm_desc = validate_task_field(description, TASK_DESC_MIN, TASK_DESC_MAX)
        if norm_title is None or norm_desc is None:
            return TaskResult.error(INVALID_ARGUMENTS)

        content_hash = _content_hash(norm_title, norm_desc)
        subject = trusted_context.subject
        correlation_id = trusted_context.correlation_id
        now = self._now()
        expires_at = now + CONFIRM_VALIDITY_SECONDS
        cur = self._conn.cursor()
        try:
            row = cur.execute(
                "SELECT confirmation_id, task_id, subject, correlation_id, content_hash, "
                "title, description, status, created_at, expires_at FROM confirmations "
                "WHERE subject=? AND correlation_id=?",
                (subject, correlation_id),
            ).fetchone()
            if row is not None:
                intent = self._row_to_intent(row)
                if intent.content_hash == content_hash:
                    # 同主体 + 同关联 ID + 同内容 → 安全幂等重放
                    if intent.status == "PENDING":
                        self._audit(
                            cur, "create_replay_pending", None,
                            intent.task_id, intent.confirmation_id,
                        )
                        self._conn.commit()
                        return TaskResult(
                            "pending", intent.task_id, intent.confirmation_id,
                            None, expires_at=intent.expires_at,
                        )
                    if intent.status == "APPROVED":
                        self._audit(
                            cur, "create_replay_approved", None,
                            intent.task_id, intent.confirmation_id,
                        )
                        self._conn.commit()
                        return TaskResult(
                            "unchanged", intent.task_id, intent.confirmation_id, None
                        )
                    if intent.status == "EXPIRED":
                        self._audit(
                            cur, "create_replay_expired", CONFIRMATION_EXPIRED,
                            intent.task_id, intent.confirmation_id,
                        )
                        self._conn.commit()
                        return TaskResult.error(
                            CONFIRMATION_EXPIRED, intent.confirmation_id, intent.task_id
                        )
                    # REJECTED / CANCELLED：终态负向，安全返回不匹配，不写文件
                    self._audit(
                        cur, "create_replay_terminal", CONFIRMATION_MISMATCH,
                        intent.task_id, intent.confirmation_id,
                    )
                    self._conn.commit()
                    return TaskResult.error(
                        CONFIRMATION_MISMATCH, intent.confirmation_id, intent.task_id
                    )
                # 同一关联 ID 配不同内容 → 幂等冲突，不新建意图（D-005）
                self._audit(cur, "create_idempotency_conflict", IDEMPOTENCY_CONFLICT, None, None)
                self._conn.commit()
                return TaskResult.error(IDEMPOTENCY_CONFLICT)

            task_id = _derive_task_id(subject, correlation_id, content_hash)
            confirmation_id = _derive_confirmation_id(task_id, content_hash)
            cur.execute(
                "INSERT INTO confirmations "
                "(confirmation_id, task_id, subject, correlation_id, content_hash, "
                "title, description, status, created_at, expires_at, consumed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    confirmation_id, task_id, subject, correlation_id, content_hash,
                    norm_title, norm_desc, "PENDING", now, expires_at, None,
                ),
            )
            cur.execute(
                "INSERT OR REPLACE INTO idempotency "
                "(subject, correlation_id, confirmation_id, task_id, content_hash, status) "
                "VALUES (?,?,?,?,?,?)",
                (subject, correlation_id, confirmation_id, task_id, content_hash, "PENDING"),
            )
            self._audit(cur, "create_pending", None, task_id, confirmation_id)
            self._conn.commit()
            return TaskResult(
                "pending", task_id, confirmation_id, None, expires_at=expires_at
            )
        except sqlite3.Error:
            self._conn.rollback()
            raise

    def approve(self, confirmation_id, trusted_context) -> TaskResult:
        """两阶段批准：PENDING→PUBLISHING 提交后才发布，再写 APPROVED。

        每个终态动作先 `BEGIN IMMEDIATE`。它取得 SQLite RESERVED 写预约，故不能
        出现“一个进程已发布，另一个进程把同一记录写成负向终态”的交错；条件 UPDATE
        和 D-2 no-replace 是纵深防御。发布失败未知是否留有文件，一律保留 PUBLISHING。
        """
        bad = _check_context(trusted_context)
        if bad is not None:
            return TaskResult.error(bad)
        if not _validate_confirmation_id(confirmation_id):
            return TaskResult.error(CONFIRMATION_INVALID_ID)
        intent = self._begin_for_terminal(confirmation_id, trusted_context)
        if isinstance(intent, TaskResult):
            return intent
        if intent.status == "PUBLISHING":
            return self._recover_publishing(intent, trusted_context, approve_result=True)
        if intent.status != "PENDING":
            self._rollback_quietly()
            return self._terminal_result(intent, "approve")

        now = self._now()
        cur = self._conn.cursor()
        try:
            if now >= intent.expires_at:
                self._write_terminal(cur, intent, "EXPIRED", now)
                recovered = self._commit_or_recover(intent, trusted_context, approve_result=False)
                if recovered is not None:
                    return recovered
                self._audit_best_effort("approve_expired", CONFIRMATION_EXPIRED, intent)
                return TaskResult.error(CONFIRMATION_EXPIRED)
            # phase 1: PUBLISHING 必须先持久化；不写 consumed_at。
            cur.execute(
                "UPDATE confirmations SET status='PUBLISHING' WHERE confirmation_id=? "
                "AND status='PENDING' AND subject=? AND correlation_id=?",
                (confirmation_id, intent.subject, intent.correlation_id),
            )
            if cur.rowcount != 1:
                self._rollback_quietly()
                return TaskResult.error(TASK_WRITE_FAILED, task_id=intent.task_id)
            recovered = self._commit_or_recover(intent, trusted_context, approve_result=False)
            if recovered is not None:
                return recovered
        except sqlite3.Error:
            self._rollback_quietly()
            return TaskResult.error(TASK_WRITE_FAILED, task_id=intent.task_id)

        # phase 2: 再次拿写预约，保留到发布、最终 UPDATE、提交全部结束。
        try:
            self._begin_immediate()
            intent = self._read_intent(confirmation_id)
            if intent is None:
                self._rollback_quietly()
                return TaskResult.error(TASK_WRITE_FAILED)
            if intent.status == "APPROVED":
                self._rollback_quietly()
                return TaskResult(
                    "unchanged", intent.task_id, intent.confirmation_id,
                    CONFIRMATION_ALREADY_CONSUMED,
                )
            if intent.status != "PUBLISHING":
                self._rollback_quietly()
                return TaskResult.error(CONFIRMATION_MISMATCH, task_id=intent.task_id)
            return self._finish_publishing(intent, trusted_context, approve_result=True)
        except sqlite3.Error:
            self._rollback_quietly()
            return self._recover_commit_state(confirmation_id, trusted_context, True)

    def reject(self, confirmation_id, trusted_context) -> TaskResult:
        return self._terminalize(
            confirmation_id, trusted_context, "REJECTED", "reject", "rejected"
        )

    def cancel(self, confirmation_id, trusted_context) -> TaskResult:
        return self._terminalize(
            confirmation_id, trusted_context, "CANCELLED", "cancel", "cancelled"
        )

    def lookup_context(self, confirmation_id) -> Optional["TrustedContext"]:
        """受控本地只读：按已知 confirmation_id 取回存储的 subject / correlation_id，
        重建 `TrustedContext` 供本地可信 Host 控制器在 Tool 外批准 / 拒绝 / 取消。

        仅从服务自有持久化记录派生——correlation_id 由本服务生成并落库，绝不使用
        Tool 参数、模型文本、MCP 请求字段或客户端自报值。未知 / 非法 / 损坏输入
        一律返回 None（不回显任意输入、不泄露路径 / 正文）。

        注意：本方法返回**记录中的 subject**，仅供内部/测试参考；生产 Host 必须
        使用 `lookup_correlation_id` + 自身 `self._subject` 重建上下文，绝不直接信任
        记录中的 subject 作为授权主体（见 P0-4 / D-018）。
        """
        if not _validate_confirmation_id(confirmation_id):
            return None
        try:
            row = self._conn.execute(
                "SELECT subject, correlation_id FROM confirmations "
                "WHERE confirmation_id=?",
                (confirmation_id,),
            ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        subject, corr = row
        try:
            return TrustedContext(subject, corr)
        except TaskPublishError:
            # 存储数据异常（不应发生）：失败关闭，不泄露
            return None

    def lookup_correlation_id(self, confirmation_id) -> Optional[str]:
        """受控本地只读：按已知 confirmation_id 仅取回存储的 correlation_id。

        供本地可信 Host 控制器在 Tool 外批准 / 拒绝 / 取消时，与**自身配置的**
        `self._subject` 重建 `TrustedContext`（P0-4）：身份绑定的 subject 来自 Host
        受控配置，绝不取用记录中的 subject 作为授权主体。未知 / 非法 / 损坏输入
        一律返回 None（不回显任意输入、不泄露路径 / 正文）。
        """
        if not _validate_confirmation_id(confirmation_id):
            return None
        try:
            row = self._conn.execute(
                "SELECT correlation_id FROM confirmations "
                "WHERE confirmation_id=?",
                (confirmation_id,),
            ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        return row[0]

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _begin_immediate(self) -> None:
        self._conn.execute("BEGIN IMMEDIATE")

    def _rollback_quietly(self) -> None:
        try:
            self._conn.rollback()
        except sqlite3.Error:
            pass

    def _read_intent(self, confirmation_id) -> Optional[TaskIntent]:
        row = self._conn.execute(
            "SELECT confirmation_id, task_id, subject, correlation_id, content_hash, "
            "title, description, status, created_at, expires_at FROM confirmations "
            "WHERE confirmation_id=?",
            (confirmation_id,),
        ).fetchone()
        return None if row is None else self._row_to_intent(row)

    def _begin_for_terminal(self, confirmation_id, trusted_context):
        """拿到写预约后再读权威状态；返回 intent 或稳定失败结果。"""
        try:
            self._begin_immediate()
            intent = self._read_intent(confirmation_id)
        except sqlite3.Error:
            self._rollback_quietly()
            return TaskResult.error(TASK_WRITE_FAILED)
        if intent is None:
            self._rollback_quietly()
            return TaskResult.error(CONFIRMATION_REQUIRED)
        if (
            trusted_context.subject != intent.subject
            or trusted_context.correlation_id != intent.correlation_id
        ):
            self._rollback_quietly()
            return TaskResult.error(CONFIRMATION_IDENTITY_MISMATCH)
        return intent

    @staticmethod
    def _terminal_result(intent: TaskIntent, action: str) -> TaskResult:
        if intent.status == "APPROVED":
            if action == "approve":
                return TaskResult(
                    "unchanged", intent.task_id, intent.confirmation_id,
                    CONFIRMATION_ALREADY_CONSUMED,
                )
            return TaskResult.error(CONFIRMATION_MISMATCH, task_id=intent.task_id)
        if intent.status == "EXPIRED":
            return TaskResult.error(CONFIRMATION_EXPIRED, task_id=intent.task_id)
        return TaskResult.error(CONFIRMATION_MISMATCH, task_id=intent.task_id)

    def _write_terminal(self, cur, intent: TaskIntent, status: str, now: float) -> None:
        cur.execute(
            "UPDATE confirmations SET status=?, consumed_at=? WHERE confirmation_id=? "
            "AND status='PENDING' AND subject=? AND correlation_id=?",
            (status, now, intent.confirmation_id, intent.subject, intent.correlation_id),
        )
        if cur.rowcount != 1:
            raise sqlite3.OperationalError("conditional terminal update lost")
        cur.execute(
            "UPDATE idempotency SET status=? WHERE subject=? AND correlation_id=?",
            (status, intent.subject, intent.correlation_id),
        )

    def _commit_or_recover(self, intent, trusted_context, approve_result: bool):
        """提交失败后绝不猜测 rollback 结果，换新连接重读权威状态。"""
        try:
            _commit(self._conn)
            return None
        except sqlite3.Error:
            return self._recover_commit_state(
                intent.confirmation_id, trusted_context, approve_result
            )

    def _recover_commit_state(self, confirmation_id, trusted_context, approve_result: bool):
        self._rollback_quietly()
        try:
            _close(self._conn)
            self._conn = _make_connection(self._db_path)
            self._configure_connection(self._conn)
            intent = self._read_intent(confirmation_id)
        except sqlite3.Error:
            return TaskResult.error(TASK_WRITE_FAILED)
        if intent is None:
            return TaskResult.error(TASK_WRITE_FAILED)
        if (
            intent.subject != trusted_context.subject
            or intent.correlation_id != trusted_context.correlation_id
        ):
            return TaskResult.error(CONFIRMATION_IDENTITY_MISMATCH)
        if intent.status == "PUBLISHING":
            return self._recover_publishing(intent, trusted_context, approve_result)
        if intent.status == "APPROVED":
            return TaskResult(
                "unchanged", intent.task_id, intent.confirmation_id,
                CONFIRMATION_ALREADY_CONSUMED,
            )
        # PENDING / negative terminal after an unknown commit is intentionally not retried
        # inside this call: caller gets a stable failure and may make a new controlled request.
        return TaskResult.error(TASK_WRITE_FAILED, task_id=intent.task_id)

    def _payload(self, intent: TaskIntent) -> dict:
        return {
            "task_id": intent.task_id,
            "title": intent.title,
            "description": intent.description,
            "content_hash": intent.content_hash,
            "created_at": intent.created_at,
            "status": "created",
        }

    def _finish_publishing(self, intent, trusted_context, approve_result: bool) -> TaskResult:
        """在持有 BEGIN IMMEDIATE 写预约时发布并把 PUBLISHING 条件写为 APPROVED。"""
        try:
            outcome = self._publish_task_file(intent.task_id, self._payload(intent))
        except TaskPublishError as exc:
            # phase 1 的 PUBLISHING 已提交；D-2 的稳定码不能证明是否零残留。
            self._rollback_quietly()
            return TaskResult.error(exc.code, task_id=intent.task_id)
        cur = self._conn.cursor()
        try:
            cur.execute(
                "UPDATE confirmations SET status='APPROVED', consumed_at=? "
                "WHERE confirmation_id=? AND status='PUBLISHING' AND subject=? "
                "AND correlation_id=?",
                (self._now(), intent.confirmation_id, intent.subject, intent.correlation_id),
            )
            if cur.rowcount != 1:
                self._rollback_quietly()
                return TaskResult.error(TASK_WRITE_FAILED, task_id=intent.task_id)
            cur.execute(
                "UPDATE idempotency SET status='APPROVED' WHERE subject=? AND correlation_id=?",
                (intent.subject, intent.correlation_id),
            )
            recovered = self._commit_or_recover(intent, trusted_context, approve_result)
            if recovered is not None:
                return recovered
        except sqlite3.Error:
            self._rollback_quietly()
            return self._recover_commit_state(
                intent.confirmation_id, trusted_context, approve_result
            )
        self._audit_best_effort("approve_ok", None, intent)
        if approve_result:
            return TaskResult(outcome, intent.task_id, intent.confirmation_id, None)
        return TaskResult(
            "unchanged", intent.task_id, intent.confirmation_id,
            CONFIRMATION_ALREADY_CONSUMED,
        )

    def _recover_publishing(self, intent, trusted_context, approve_result: bool) -> TaskResult:
        """PUBLISHING 只可完成 APPROVED 或失败关闭，绝不可改负向/PENDING。"""
        self._rollback_quietly()
        try:
            self._begin_immediate()
            current = self._read_intent(intent.confirmation_id)
            if current is None:
                self._rollback_quietly()
                return TaskResult.error(TASK_WRITE_FAILED)
            if (
                current.subject != trusted_context.subject
                or current.correlation_id != trusted_context.correlation_id
            ):
                self._rollback_quietly()
                return TaskResult.error(CONFIRMATION_IDENTITY_MISMATCH)
            if current.status == "APPROVED":
                self._rollback_quietly()
                return TaskResult(
                    "unchanged", current.task_id, current.confirmation_id,
                    CONFIRMATION_ALREADY_CONSUMED,
                )
            if current.status != "PUBLISHING":
                self._rollback_quietly()
                return TaskResult.error(TASK_WRITE_FAILED, task_id=current.task_id)
            return self._finish_publishing(current, trusted_context, approve_result)
        except sqlite3.Error:
            self._rollback_quietly()
            return TaskResult.error(TASK_WRITE_FAILED, task_id=intent.task_id)

    def _audit_best_effort(self, event: str, error_code: Optional[str], intent: TaskIntent) -> None:
        """主事务成功后单独落最小审计；审计失败绝不推翻主结果。"""
        conn = None
        try:
            conn = _make_connection(self._db_path)
            self._configure_connection(conn)
            self._audit(conn.cursor(), event, error_code, intent.task_id, intent.confirmation_id)
            _commit(conn)
        except sqlite3.Error:
            pass
        finally:
            if conn is not None:
                try:
                    _close(conn)
                except sqlite3.Error:
                    pass

    def _terminalize(
        self, confirmation_id, trusted_context, new_status, event, outcome
    ) -> TaskResult:
        """将 PENDING 转为负向终态；PUBLISHING 只能恢复，绝不能覆盖。"""
        bad = _check_context(trusted_context)
        if bad is not None:
            return TaskResult.error(bad)
        if not _validate_confirmation_id(confirmation_id):
            return TaskResult.error(CONFIRMATION_INVALID_ID)
        intent = self._begin_for_terminal(confirmation_id, trusted_context)
        if isinstance(intent, TaskResult):
            return intent
        if intent.status == "PUBLISHING":
            recovered = self._recover_publishing(intent, trusted_context, approve_result=False)
            if recovered.error_code == TASK_WRITE_FAILED:
                return recovered
            # 已恢复为 APPROVED；调用 reject/cancel 不能伪装为成功的负向终态。
            return TaskResult.error(CONFIRMATION_MISMATCH, task_id=intent.task_id)
        if intent.status != "PENDING":
            self._rollback_quietly()
            if intent.status == new_status:
                return TaskResult(outcome, intent.task_id, intent.confirmation_id, None)
            return TaskResult.error(CONFIRMATION_MISMATCH, task_id=intent.task_id)

        now = self._now()
        cur = self._conn.cursor()
        try:
            if now >= intent.expires_at:
                self._write_terminal(cur, intent, "EXPIRED", now)
                recovered = self._commit_or_recover(intent, trusted_context, approve_result=False)
                if recovered is not None:
                    return recovered
                self._audit_best_effort(event + "_expired", CONFIRMATION_EXPIRED, intent)
                return TaskResult.error(CONFIRMATION_EXPIRED)
            self._write_terminal(cur, intent, new_status, now)
            recovered = self._commit_or_recover(intent, trusted_context, approve_result=False)
            if recovered is not None:
                return recovered
            self._audit_best_effort(event + "_ok", None, intent)
            return TaskResult(outcome, intent.task_id, intent.confirmation_id, None)
        except sqlite3.Error:
            self._rollback_quietly()
            return TaskResult.error(TASK_WRITE_FAILED, task_id=intent.task_id)

    def _row_to_intent(self, row) -> TaskIntent:
        (
            confirmation_id, task_id, subject, correlation_id, content_hash,
            title, description, status, created_at, expires_at,
        ) = row
        return TaskIntent(
            confirmation_id, task_id, subject, correlation_id, content_hash,
            title, description, status, created_at, expires_at,
        )

    def _audit(self, cur, event, error_code, task_id, confirmation_id) -> None:
        """写入最小审计事件（不含正文、路径、用户名或异常文本）。"""
        cur.execute(
            "INSERT INTO audit (occurred_at, event, error_code, task_id, confirmation_id) "
            "VALUES (?,?,?,?,?)",
            (self._now(), event, error_code, task_id, confirmation_id),
        )

    def _publish_task_file(self, task_id: str, payload: dict) -> str:
        """受控 no-replace 原子发布（委托 safe_task_write 句柄式写入层）。

        返回 "created" 或 "unchanged"；冲突 / 写失败 / 根不安全抛
        `TaskPublishError`（稳定码）。任务根 `self._task_root` 必须是部署配置中
        预存在的受控目录；生产代码**绝不**用字符串路径创建任务根或其祖先目录。
        任务根与祖先目录的 reparse / TOCTOU 防护、Windows 原生 no-replace 发布均由
        `safe_task_write.open_task_root` / `publish_task_file` 以句柄完成；根不存在 /
        非目录 / reparse / 原生不可用 → 失败关闭 `task-root-unsafe`，绝不写文件、绝不
        回退字符串路径方案。
        """
        try:
            return _safe_publish(self._task_root, task_id, payload)
        except SafeWriteError as exc:
            # 把受控写层稳定码原样透传为 TaskPublishError（不泄露路径 / 异常文本）
            raise TaskPublishError(exc.code)
