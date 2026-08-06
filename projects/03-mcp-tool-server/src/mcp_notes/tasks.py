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


def _check_context(trusted_context) -> Optional[str]:
    """校验可信上下文是否合法；非法返回稳定 INVALID_ARGUMENTS（不抛异常）。"""
    if not isinstance(trusted_context, TrustedContext):
        return INVALID_ARGUMENTS
    if not _valid_trusted_value(trusted_context.subject):
        return INVALID_ARGUMENTS
    if not _valid_trusted_value(trusted_context.correlation_id):
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

    构造即校验：subject / correlation_id 必须为非空 str，长度 1.._TRUSTED_MAX，
    且不含控制字符。非法值（如 `TrustedContext(123, 456)`）抛受控的
    `TaskPublishError(INVALID_ARGUMENTS)`，绝不抛原始 TypeError 或泄露异常。
    """

    subject: str
    correlation_id: str

    def __init__(self, subject, correlation_id):
        if not _valid_trusted_value(subject) or not _valid_trusted_value(correlation_id):
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
        self._conn = sqlite3.connect(db_path)
        self._init_schema()

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def _now(self) -> float:
        return self._clock()

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
        """可信本地人工批准一次。成功则 no-replace 原子发布任务文件。

        状态判断顺序（P0-2）：先处理已消费终态（APPROVED 永远 unchanged +
        confirmation-already-consumed，不改库、不二次写）；仅 PENDING 且到期才转
        EXPIRED；REJECTED / CANCELLED / EXPIRED 保持终态（返回 mismatch）。身份绑定
        （P0-1）要求 subject 与 correlation_id 同时等于创建意图的值。confirmation_id
        先校验服务生成的严格格式（P1-6），错误结果不得回显任意输入。
        """
        bad = _check_context(trusted_context)
        if bad is not None:
            return TaskResult.error(bad)
        if not _validate_confirmation_id(confirmation_id):
            # 格式非法 / 未知：稳定错误码，绝不回显原始 confirmation_id
            return TaskResult.error(CONFIRMATION_INVALID_ID)
        now = self._now()
        cur = self._conn.cursor()
        try:
            row = cur.execute(
                "SELECT confirmation_id, task_id, subject, correlation_id, content_hash, "
                "title, description, status, created_at, expires_at FROM confirmations "
                "WHERE confirmation_id=?",
                (confirmation_id,),
            ).fetchone()
            if row is None:
                self._audit(cur, "approve_no_record", CONFIRMATION_REQUIRED, None, None)
                self._conn.commit()
                return TaskResult.error(CONFIRMATION_REQUIRED)
            intent = self._row_to_intent(row)
            # P0-1：身份绑定 subject + correlation_id 同时相等
            if (
                trusted_context.subject != intent.subject
                or trusted_context.correlation_id != intent.correlation_id
            ):
                self._audit(
                    cur, "approve_identity_mismatch", CONFIRMATION_IDENTITY_MISMATCH,
                    intent.task_id, None,
                )
                self._conn.commit()
                return TaskResult.error(CONFIRMATION_IDENTITY_MISMATCH)

            # P0-2：先处理已消费终态，过期逻辑绝不改写已 APPROVED 记录
            if intent.status == "APPROVED":
                # 永远 unchanged + already_consumed；不改库、不二次写
                return TaskResult(
                    "unchanged", intent.task_id, intent.confirmation_id,
                    CONFIRMATION_ALREADY_CONSUMED,
                )
            if intent.status != "PENDING":
                # REJECTED / CANCELLED / EXPIRED：保持终态，不可再消费
                self._audit(
                    cur, "approve_not_consumable", CONFIRMATION_MISMATCH,
                    intent.task_id, None,
                )
                self._conn.commit()
                return TaskResult.error(CONFIRMATION_MISMATCH)

            if now >= intent.expires_at:
                # 懒求值过期：仅 PENDING 转 EXPIRED
                cur.execute(
                    "UPDATE confirmations SET status='EXPIRED', consumed_at=? "
                    "WHERE confirmation_id=?",
                    (now, confirmation_id),
                )
                cur.execute(
                    "UPDATE idempotency SET status='EXPIRED' "
                    "WHERE subject=? AND correlation_id=?",
                    (intent.subject, intent.correlation_id),
                )
                self._audit(
                    cur, "approve_expired", CONFIRMATION_EXPIRED, intent.task_id, None
                )
                self._conn.commit()
                return TaskResult.error(CONFIRMATION_EXPIRED)

            payload = {
                "task_id": intent.task_id,
                "title": intent.title,
                "description": intent.description,
                "content_hash": intent.content_hash,
                "created_at": intent.created_at,
                "status": "created",
            }
            try:
                outcome = self._publish_task_file(intent.task_id, payload)
            except TaskPublishError as exc:
                # 发布失败：意图保持 PENDING，可重试（重放返回 UNCHANGED）。
                # 携带服务派生的 task_id（不含路径 / 用户名 / 正文），便于调用方
                # 定位既有的、未被覆盖的目标文件。
                self._audit(
                    cur, "approve_write_failed", exc.code, intent.task_id, None
                )
                self._conn.commit()
                return TaskResult.error(exc.code, task_id=intent.task_id)

            cur.execute(
                "UPDATE confirmations SET status='APPROVED', consumed_at=? "
                "WHERE confirmation_id=?",
                (now, confirmation_id),
            )
            cur.execute(
                "UPDATE idempotency SET status='APPROVED' "
                "WHERE subject=? AND correlation_id=?",
                (intent.subject, intent.correlation_id),
            )
            self._audit(cur, "approve_ok", None, intent.task_id, intent.confirmation_id)
            self._conn.commit()
            return TaskResult(outcome, intent.task_id, intent.confirmation_id, None)
        except sqlite3.Error:
            self._conn.rollback()
            raise

    def reject(self, confirmation_id, trusted_context) -> TaskResult:
        return self._terminalize(
            confirmation_id, trusted_context, "REJECTED", "reject", "rejected"
        )

    def cancel(self, confirmation_id, trusted_context) -> TaskResult:
        return self._terminalize(
            confirmation_id, trusted_context, "CANCELLED", "cancel", "cancelled"
        )

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _terminalize(
        self, confirmation_id, trusted_context, new_status, event, outcome
    ) -> TaskResult:
        """将 PENDING 意图转为 REJECTED / CANCELLED 终态；绝不发布任务文件。

        P0-1：身份绑定 subject + correlation_id 同时相等。P0-2：先处理已终态
        （含已 APPIRED），过期逻辑绝不改写已消费记录；仅 PENDING 到期转 EXPIRED。
        P1-6：confirmation_id 先校验格式，错误结果不回显任意输入。
        """
        bad = _check_context(trusted_context)
        if bad is not None:
            return TaskResult.error(bad)
        if not _validate_confirmation_id(confirmation_id):
            return TaskResult.error(CONFIRMATION_INVALID_ID)
        now = self._now()
        cur = self._conn.cursor()
        try:
            row = cur.execute(
                "SELECT confirmation_id, task_id, subject, correlation_id, status, expires_at "
                "FROM confirmations WHERE confirmation_id=?",
                (confirmation_id,),
            ).fetchone()
            if row is None:
                self._audit(cur, event + "_no_record", CONFIRMATION_REQUIRED, None, None)
                self._conn.commit()
                return TaskResult.error(CONFIRMATION_REQUIRED)
            (cid, task_id, subject, corr, status, expires_at) = row
            # P0-1：身份绑定 subject + correlation_id 同时相等
            if trusted_context.subject != subject or trusted_context.correlation_id != corr:
                self._audit(
                    cur, event + "_identity_mismatch", CONFIRMATION_IDENTITY_MISMATCH,
                    task_id, None,
                )
                self._conn.commit()
                return TaskResult.error(CONFIRMATION_IDENTITY_MISMATCH)
            # P0-2：终态（含已 APPROVED）保持；不再被过期逻辑改写
            if status == new_status:
                # 幂等：已是该终态，不改库
                self._audit(cur, event + "_already", None, task_id, cid)
                self._conn.commit()
                return TaskResult(outcome, task_id, cid, None)
            if status != "PENDING":
                # REJECTED / CANCELLED / EXPIRED / APPROVED：不可再消费
                self._audit(
                    cur, event + "_not_consumable", CONFIRMATION_MISMATCH, task_id, None
                )
                self._conn.commit()
                return TaskResult.error(CONFIRMATION_MISMATCH)
            if now >= expires_at:
                # 懒求值过期：仅 PENDING 转 EXPIRED
                cur.execute(
                    "UPDATE confirmations SET status='EXPIRED', consumed_at=? "
                    "WHERE confirmation_id=?",
                    (now, confirmation_id),
                )
                cur.execute(
                    "UPDATE idempotency SET status='EXPIRED' "
                    "WHERE subject=? AND correlation_id=?",
                    (subject, corr),
                )
                self._audit(cur, event + "_expired", CONFIRMATION_EXPIRED, task_id, None)
                self._conn.commit()
                return TaskResult.error(CONFIRMATION_EXPIRED)
            cur.execute(
                "UPDATE confirmations SET status=?, consumed_at=? WHERE confirmation_id=?",
                (new_status, now, confirmation_id),
            )
            cur.execute(
                "UPDATE idempotency SET status=? WHERE subject=? AND correlation_id=?",
                (new_status, subject, corr),
            )
            self._audit(cur, event + "_ok", None, task_id, cid)
            self._conn.commit()
            return TaskResult(outcome, task_id, cid, None)
        except sqlite3.Error:
            self._conn.rollback()
            raise

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
