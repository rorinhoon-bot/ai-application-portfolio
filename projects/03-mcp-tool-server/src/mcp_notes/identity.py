r"""P3 D-3：唯一身份来源与信任边界（纯标准库、离线）。

唯一权威 subject 来源 = 受控身份根下、由可信部署操作者带外预置的 `identity.json`
（见 docs/D-3-design.md §1）。本模块**仅**提供：

- `RuntimeIdentity`：不可变身份值对象；仅由 `load_runtime_identity()` 经私有哨兵产出
  （私有哨兵为受信代码内的类型/API 防呆，**不是安全边界**，见 §5.4）。
- `load_runtime_identity(environ, identity_file_path=None) -> RuntimeIdentity`：
  §1.2 路径校验 → §1.3 平台分派 fd/HANDLE 链安全读取 → §1.4 schema 校验 →
  §1.1 env 相等性断言；任何失败 `raise TaskPublishError(INVALID_ARGUMENTS)`。
- `write_identity_file(path, subject, ...)`：仅供测试 / 演示 / 评估夹具使用，生产路径
  从不调用（受控身份文件必须由可信部署带外预置，见 §1.2）。

安全读取**只读复用** D-2 原语 `safe_task_write.open_task_root` / `_nt_open`（Windows）与
`safe_task_write_posix._posix_supported` / `_open_root`（POSIX），**零修改**（见 §1.3）。
所有 D-2 稳定错误在 identity 边界统一映射为 `invalid-arguments`，不改变发布路径语义。

不新增网络连接；不记录用户名 / 绝对路径 / 密钥 / 异常；不把模型输出或环境变量当作可信
身份（`MCP_NOTES_SUBJECT` 仅作可选相等性断言，永不产生值）。
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field

from .safe_task_write import SafeWriteError, TASK_ROOT_UNSAFE, open_task_root
# POSIX 安全读取核心（包内内部复用；算法级 / mock 已验证，真实链接仍 blocked-until-approved）
from . import safe_task_write_posix as _posix
from .tasks import INVALID_ARGUMENTS, TaskPublishError, _valid_subject

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
MAX_IDENTITY_BYTES = 4096
IDENTITY_SCHEMA_VERSION = 1
_ALLOWED_SUBJECT_KIND = "deployment-provisioned"

# §1.2：<name> 必须匹配单路径组件白名单（不得含分隔符 / .. / \x00 / 驱动器或 UNC 前缀）
_IDENTITY_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.json$")

# 缺省身份文件路径（与默认 control.db 共置；缺省路径下无文件 → 失败关闭，不回退默认主体）
_DEFAULT_IDENTITY_PATH = os.path.abspath(os.path.join(".mcp-notes", "identity.json"))


# --------------------------------------------------------------------------- #
# RuntimeIdentity：不可变身份值对象（私有哨兵防呆，非安全边界）
# --------------------------------------------------------------------------- #
_SENTINEL = object()


@dataclass(frozen=True)
class RuntimeIdentity:
    """不可变身份值对象；仅由 `load_runtime_identity()` 经私有哨兵产出。

    私有哨兵 `_make_token` 仅为受信代码内的类型 / API 防呆（防止调用点误传裸字符串、
    防止未来重构悄悄绕开校验），**不是安全边界**——同进程代码仍可访问私有成员或
    直接调用内部构造（见 D-3 §5.4）。真正边界是 MCP 客户端 / 模型无法在服务进程内
    执行代码、无法写受控身份根、无法控制受控启动器环境。
    """

    subject: str
    _make_token: object = field(repr=False, compare=False, default=None)

    def __post_init__(self):
        # 防呆（非安全边界）：仅经私有哨兵私有构造，公共 API 直接传 str 会失败
        if self._make_token is not _SENTINEL:
            raise TypeError(
                "RuntimeIdentity must be created via load_runtime_identity()"
            )

    @classmethod
    def _create(cls, subject: str) -> "RuntimeIdentity":
        return cls(subject=subject, _make_token=_SENTINEL)


# --------------------------------------------------------------------------- #
# 内部：安全读取（§1.3）
# --------------------------------------------------------------------------- #
def _read_fd(fd: int) -> bytes:
    """对已打开 fd 做类型断言（防 TOCTOU）并限长读取（§1.3 D/E）。

    类型断言基于 `os.fstat(fd)`（fd 指向的实际对象），不是路径；任何失败 /
    超限 → 抛 `SafeWriteError(TASK_ROOT_UNSAFE)`，由边界映射为 `invalid-arguments`。
    """
    try:
        st = os.fstat(fd)
    except OSError:
        raise SafeWriteError(TASK_ROOT_UNSAFE)
    if not stat.S_ISREG(st.st_mode):
        # 目录 / FIFO / 设备 / socket / symlink / 无法归类 → 失败关闭
        raise SafeWriteError(TASK_ROOT_UNSAFE)
    data = b""
    while True:
        # 每次仅读「还能接受的上限 + 1」字节（最多读 4097 字节即拒绝），避免一次性
        # 读取超大块；累计超过 4096 字节 → 失败关闭（防超大 / 无穷文件占用与内存放大）
        to_read = (MAX_IDENTITY_BYTES + 1) - len(data)
        if to_read <= 0:
            raise SafeWriteError(TASK_ROOT_UNSAFE)
        chunk = os.read(fd, to_read)
        if not chunk:
            break
        data += chunk
        if len(data) > MAX_IDENTITY_BYTES:
            raise SafeWriteError(TASK_ROOT_UNSAFE)
    return data


def _read_identity_bytes(identity_dir: str, name: str) -> bytes:
    """§1.3：打开已验证身份根 → 相对父句柄 / fd 打开身份文件 → 类型断言 → 读取。

    全程拒绝链接跟随、拒绝字符串路径回退；任何失败抛 `SafeWriteError`
    （能力缺失 / reparse / 非普通文件 / IO / 权限），由边界统一映射为
    `invalid-arguments`。所有已打开 HANDLE / fd 在 finally 中精确关闭一次。
    """
    if sys.platform == "win32":
        import msvcrt  # Windows-only：HANDLE → fd 转换

        from .safe_task_write import _close, _nt_open

        handles = open_task_root(identity_dir)  # 可能抛 SafeWriteError
        parent = handles[-1]
        try:
            try:
                fh = _nt_open(parent, name, is_dir=False)
            except (SafeWriteError, OSError):
                raise SafeWriteError(TASK_ROOT_UNSAFE)
            try:
                fd = msvcrt.open_osfhandle(fh, os.O_RDONLY | os.O_BINARY)
            except OSError:
                # open_osfhandle 失败：fh 未转交为 fd，必须显式关闭，否则 HANDLE 泄漏
                try:
                    _close(fh)
                except OSError:
                    pass
                raise SafeWriteError(TASK_ROOT_UNSAFE)
            # fh 已转交 fd；本函数不再关闭 fh，仅由下方 os.close(fd) 关闭
            try:
                return _read_fd(fd)
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass
        finally:
            for h in handles:
                try:
                    _close(h)
                except OSError:
                    pass
    else:
        if not _posix._posix_supported():
            # 能力缺失 → 失败关闭，绝无字符串路径回退
            raise SafeWriteError(TASK_ROOT_UNSAFE)
        fds = _posix._open_root(identity_dir)  # 可能抛 SafeWriteError
        parent = fds[-1]
        try:
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            except OSError:
                # ELOOP（仍为 symlink）或其他打开失败 → 失败关闭
                raise SafeWriteError(TASK_ROOT_UNSAFE)
            try:
                return _read_fd(fd)
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass
        finally:
            for f in fds:
                try:
                    os.close(f)
                except OSError:
                    pass


# --------------------------------------------------------------------------- #
# 内部：schema 校验（§1.4）
# --------------------------------------------------------------------------- #
def _validate_schema(doc) -> str:
    """严格校验 identity.json（§1.4）。通过返回已验证 subject；否则抛
    `TaskPublishError(INVALID_ARGUMENTS)`（不泄露任何细节）。"""
    if not isinstance(doc, dict):
        raise TaskPublishError(INVALID_ARGUMENTS)
    # 未知键严格拒绝 + 缺失键：两者都会使键集合不等于三键集合
    if set(doc.keys()) != {"version", "subject", "subject_kind"}:
        raise TaskPublishError(INVALID_ARGUMENTS)
    version = doc.get("version")
    # 显式拒绝 bool（bool 是 int 子类）；必须 int 且 == 1
    if isinstance(version, bool) or not isinstance(version, int) or version != IDENTITY_SCHEMA_VERSION:
        raise TaskPublishError(INVALID_ARGUMENTS)
    subject = doc.get("subject")
    # 类型 str + 匹配 D-1 白名单（长度 1..128）
    if not isinstance(subject, str) or not _valid_subject(subject):
        raise TaskPublishError(INVALID_ARGUMENTS)
    kind = doc.get("subject_kind")
    if not isinstance(kind, str) or kind != _ALLOWED_SUBJECT_KIND:
        raise TaskPublishError(INVALID_ARGUMENTS)
    return subject


# --------------------------------------------------------------------------- #
# 公开：加载器
# --------------------------------------------------------------------------- #
def _load_impl(environ, identity_file_path=None) -> RuntimeIdentity:
    # §1.2 解析身份文件路径
    raw = identity_file_path if identity_file_path is not None else environ.get(
        "MCP_NOTES_IDENTITY_FILE"
    )
    if not raw:
        # 缺省 <state_dir>/identity.json（与 control.db 共置）；若仍不存在 → 失败关闭
        raw = _DEFAULT_IDENTITY_PATH
    # 拆分 identity_dir + <name>
    identity_dir, name = os.path.split(raw)
    if not identity_dir:
        identity_dir = os.getcwd()
    # §1.2：name 须匹配单路径组件白名单；含分隔符 / .. / \x00 / UNC / 驱动器前缀 → 失败
    if not _IDENTITY_NAME_RE.match(name):
        raise TaskPublishError(INVALID_ARGUMENTS)
    if "\x00" in raw:
        raise TaskPublishError(INVALID_ARGUMENTS)
    if not os.path.isabs(identity_dir):
        identity_dir = os.path.abspath(identity_dir)

    # §1.3 安全读取（fd/HANDLE 链；拒绝链接跟随、拒绝字符串路径回退）
    data_bytes = _read_identity_bytes(identity_dir, name)

    # §1.4 解析 + schema 校验（UTF-8 不接受 BOM；JSON 解析失败 → 失败关闭）
    if not data_bytes:
        raise TaskPublishError(INVALID_ARGUMENTS)  # 空文件
    try:
        text = data_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise TaskPublishError(INVALID_ARGUMENTS)
    try:
        doc = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        raise TaskPublishError(INVALID_ARGUMENTS)
    subject = _validate_schema(doc)

    # §1.1 env 相等性断言（MCP_NOTES_SUBJECT 永不产生值，仅可选比对）
    env_subject = environ.get("MCP_NOTES_SUBJECT")
    if env_subject is not None and env_subject != subject:
        raise TaskPublishError(INVALID_ARGUMENTS)

    return RuntimeIdentity._create(subject)


def load_runtime_identity(environ, identity_file_path=None) -> RuntimeIdentity:
    """加载唯一可信 subject 来源（见 docs/D-3-design.md §1）。

    流程：§1.2 路径校验 → §1.3 平台分派安全读取 → §1.4 schema 校验 →
    §1.1 env 相等性断言。任何失败 `raise TaskPublishError(INVALID_ARGUMENTS)`
    （不泄露路径 / 正文 / 用户名 / 异常 / 原始系统细节）。

    `environ` 为 dict-like（os.environ 或受信调用方提供的映射）；`MCP_NOTES_SUBJECT`
    只作可选相等性断言，**永不产生值**。`identity_file_path` 为受控启动器显式注入的
    受控身份文件路径（仅测试 / 演示 / 评估使用；生产经 `MCP_NOTES_IDENTITY_FILE`）。
    """
    try:
        return _load_impl(environ, identity_file_path)
    except SafeWriteError:
        # D-2 原语错误 → 边界映射为 invalid-arguments（不改变发布路径对外语义）
        raise TaskPublishError(INVALID_ARGUMENTS) from None
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise TaskPublishError(INVALID_ARGUMENTS) from None


def write_identity_file(
    path: str,
    subject: str,
    subject_kind: str = _ALLOWED_SUBJECT_KIND,
    version: int = IDENTITY_SCHEMA_VERSION,
) -> None:
    """仅供测试 / 演示 / 评估夹具：写入受控 identity.json。

    **生产路径从不调用**——受控身份文件必须由可信部署带外预置（见 §1.2）。
    """
    doc = {"version": version, "subject": subject, "subject_kind": subject_kind}
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, sort_keys=True)
