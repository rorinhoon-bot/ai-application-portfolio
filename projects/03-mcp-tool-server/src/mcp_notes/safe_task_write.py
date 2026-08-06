r"""P3 Slice B2a：受控任务根 / 句柄式写入层（Windows 原生，B1 同等级安全）。

复用 safe_open 的句柄原语（OBJ_DONT_REPARSE + 相对父 HANDLE），提供：

- `open_task_root(task_root)`：从盘符根起，逐级用 OBJ_DONT_REPARSE 打开任务根及
  其祖先目录，返回已验证目录 HANDLE 链；任何 reparse point（symlink / junction）
  都会失败关闭（抛 `SafeWriteError("task-root-unsafe")`），**绝不**回退到字符串
  路径方案。
- `publish_task_file(task_root, task_id, payload)`：在已验证根 HANDLE 下用
  `NtCreateFile(FILE_CREATE, OBJ_DONT_REPARSE)` 原子无覆盖创建任务文件
  （满足 P0-3 “Windows 原生无覆盖 API”，无 os.replace、无 “exists 检查 + 覆盖”
  竞态窗口）；成功后写内容并 `FlushFileBuffers`（fsync）。目标已存在 → 不覆盖，
  读现有内容判定 unchanged / conflict。

所有失败映射为稳定错误码（`SafeWriteError.code`），不泄露路径 / 正文 / 异常文本。
非 Windows 或原生不可用 → 抛 `UnsafeOpenUnavailable`（失败关闭）。

设计依据：D-006（稳定 task_id + no-replace 发布）；P0-3（移除 os.replace 伪
no-replace，改 Windows 原生无覆盖 API）；P0-4（任务根 / 祖先目录 B1 同等级 reparse
与 TOCTOU 防护，句柄式写入）。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import json
import msvcrt
import os
import re

from .safe_open import (
    OBJ_DONT_REPARSE,
    IO_STATUS_BLOCK,
    NotAllowedReparse,
    NotARegularFile,
    OBJECT_ATTRIBUTES,
    PathEscape,
    UNICODE_STRING,
    UnsafeOpenUnavailable,
    _NATIVE_AVAILABLE,
    _close,
    _nt_open,
    _validate_component,
    configure_root,
    IoError,
    kernel32,
    ntdll,
    verify_native_support,
)

# 任务文件 id 形态（与 tasks.py 一致）
TASK_ID_RE = re.compile(r"^[A-Za-z0-9-]{4,64}$")

# 稳定错误码（对外不含路径 / 正文 / 异常文本）
TASK_INVALID_ID = "task-invalid-id"
TASK_CONFLICT = "task-conflict"
TASK_WRITE_FAILED = "task-write-failed"
TASK_ROOT_UNSAFE = "task-root-unsafe"


class SafeWriteError(Exception):
    """受控写层稳定错误；code 为对外错误码，不包裹原始系统异常文本。"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class NameCollision(Exception):
    """内部：NtCreateFile 返回 STATUS_OBJECT_NAME_COLLISION（目标已存在）。"""


# --------------------------------------------------------------------------- #
# NtCreateFile 绑定（仅 Windows 可用）
# --------------------------------------------------------------------------- #

# 访问与创建选项
FILE_WRITE_DATA = 0x0002
FILE_READ_ATTRIBUTES = 0x0080
SYNCHRONIZE = 0x100000
FILE_NON_DIRECTORY_FILE = 0x0040
FILE_SYNCHRONOUS_IO_NONALERT = 0x0020
FILE_CREATE = 0x00000002
FILE_OPEN = 0x00000001
FILE_ATTRIBUTE_NORMAL = 0x80

# NTSTATUS
STATUS_SUCCESS = 0x00000000
STATUS_OBJECT_NAME_COLLISION = 0xC0000034  # FILE_CREATE 已存在（部分文档 / 旧实现）
STATUS_OBJECT_NAME_EXISTS = 0xC0000035     # FILE_CREATE 已存在（本机实测返回此值）
STATUS_REPARSE_POINT_ENCOUNTERED = 0xC00004FA

if _NATIVE_AVAILABLE:
    ntdll.NtCreateFile.restype = ctypes.c_long
    ntdll.NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.ULONG,                       # DesiredAccess
        ctypes.POINTER(OBJECT_ATTRIBUTES),
        ctypes.POINTER(IO_STATUS_BLOCK),
        ctypes.c_void_p,                      # AllocationSize (PLARGE_INTEGER) - None
        wintypes.ULONG,                       # FileAttributes
        wintypes.ULONG,                       # ShareAccess
        wintypes.ULONG,                       # CreateDisposition
        wintypes.ULONG,                       # CreateOptions
        ctypes.c_void_p,                      # EaBuffer
        wintypes.ULONG,                       # EaLength
    ]
    _nt_create_file_fn = ntdll.NtCreateFile
else:
    _nt_create_file_fn = None


# 写入失败后清理：仅句柄原生操作（NtDeleteFile，相对已验证父目录 HANDLE），
# 绝不使用字符串路径 os.remove / os.replace / 任何回退。
if _NATIVE_AVAILABLE:
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,                      # hFile
        ctypes.c_void_p,                      # lpBuffer
        wintypes.DWORD,                       # nNumberOfBytesToWrite
        ctypes.POINTER(wintypes.DWORD),       # lpNumberOfBytesWritten
        ctypes.c_void_p,                      # lpOverlapped
    ]
    kernel32.FlushFileBuffers.restype = wintypes.BOOL
    kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]

    ntdll.NtDeleteFile.restype = ctypes.c_long
    ntdll.NtDeleteFile.argtypes = [ctypes.POINTER(OBJECT_ATTRIBUTES)]


# --------------------------------------------------------------------------- #
# 受控任务根：逐级 OBJ_DONT_REPARSE 打开（B1 同等级）
# --------------------------------------------------------------------------- #

def open_task_root(task_root: str) -> list:
    """逐级 OBJ_DONT_REPARSE 打开任务根，返回已验证目录 HANDLE 列表（含盘符根）。

    任何 reparse point（symlink / junction）/ 非法根字符串 / 原生不可用 → 失败关闭，
    抛 `SafeWriteError("task-root-unsafe")`，绝不回退字符串路径方案。
    """
    if not _NATIVE_AVAILABLE or not verify_native_support():
        # 原生不可用 → 失败关闭，绝不回退字符串路径方案
        raise SafeWriteError(TASK_ROOT_UNSAFE)
    try:
        root_name = configure_root(task_root)
    except (PathEscape, NotAllowedReparse, IoError):
        raise SafeWriteError(TASK_ROOT_UNSAFE)
    if not root_name.startswith("\\??\\"):
        raise SafeWriteError(TASK_ROOT_UNSAFE)
    body = root_name[4:]  # 去掉 "\\??\\"
    parts = body.split("\\")
    if len(parts) < 2:
        raise SafeWriteError(TASK_ROOT_UNSAFE)
    drive = parts[0]
    comps = parts[1:]
    drive_name = "\\??\\" + drive + "\\"
    handles: list = []
    try:
        h = _nt_open(0, drive_name, is_dir=True)
        handles.append(h)
        parent = h
        for comp in comps:
            # 每级目录都携带 OBJ_DONT_REPARSE：祖先或本级的 reparse 点都会被拒绝
            ch = _nt_open(parent, comp, is_dir=True)
            handles.append(ch)
            parent = ch
        return handles
    except (NotAllowedReparse, PathEscape, IoError, NotARegularFile):
        # 失败关闭：绝不回退字符串路径；关闭已打开的 HANDLE
        for h in handles:
            _close(h)
        raise SafeWriteError(TASK_ROOT_UNSAFE)
    except Exception:
        for h in handles:
            _close(h)
        raise


# --------------------------------------------------------------------------- #
# 句柄式文件创建 / 读取 / 写入
# --------------------------------------------------------------------------- #

def _nt_create_file(parent_handle: int, name: str, disposition: int) -> int:
    """相对父 HANDLE 用 NtCreateFile 创建 / 打开单个文件（OBJ_DONT_REPARSE）。

    返回新 HANDLE；目标已存在（FILE_CREATE）→ 抛 `NameCollision`；reparse →
    抛 NotAllowedReparse；其他失败 → `SafeWriteError("task-write-failed")`。
    """
    if not _NATIVE_AVAILABLE or _nt_create_file_fn is None:
        raise UnsafeOpenUnavailable()
    _validate_component(name)
    encoded = name.encode("utf-16-le")
    if len(encoded) + 2 > 0xFFFF:
        raise PathEscape()
    us = UNICODE_STRING()
    us.Length = len(encoded)
    us.MaximumLength = len(encoded) + 2
    _buf = ctypes.create_unicode_buffer(name)
    us.Buffer = ctypes.cast(_buf, ctypes.c_wchar_p)

    oa = OBJECT_ATTRIBUTES()
    oa.Length = ctypes.sizeof(OBJECT_ATTRIBUTES)
    oa.RootDirectory = ctypes.c_void_p(parent_handle) if parent_handle else None
    oa.ObjectName = ctypes.pointer(us)
    oa.Attributes = OBJ_DONT_REPARSE
    oa.SecurityDescriptor = None
    oa.SecurityQualityOfService = None

    h = wintypes.HANDLE()
    iosb = IO_STATUS_BLOCK()
    desired = SYNCHRONIZE | FILE_WRITE_DATA | FILE_READ_ATTRIBUTES
    options = FILE_NON_DIRECTORY_FILE | FILE_SYNCHRONOUS_IO_NONALERT
    try:
        status = _nt_create_file_fn(
            ctypes.byref(h),
            desired,
            ctypes.byref(oa),
            ctypes.byref(iosb),
            None,                      # AllocationSize
            FILE_ATTRIBUTE_NORMAL,
            0,                         # 独占共享（写入期间不共享）
            disposition,
            options,
            None,                      # EaBuffer
            0,                         # EaLength
        )
    except OSError:
        # 原生调用本身失败（如注入故障）→ 稳定写失败码，不泄露细节
        raise SafeWriteError(TASK_WRITE_FAILED)
    st = status & 0xFFFFFFFF
    if st == STATUS_SUCCESS:
        return h.value
    if st in (STATUS_OBJECT_NAME_COLLISION, STATUS_OBJECT_NAME_EXISTS):
        # 目标已存在：原子 no-replace 的核心；绝不覆盖（本机实测返回 EXISTS）
        raise NameCollision()
    if st == STATUS_REPARSE_POINT_ENCOUNTERED:
        raise NotAllowedReparse()
    raise SafeWriteError(TASK_WRITE_FAILED)


def _read_existing_json(parent_handle: int, name: str):
    """相对父 HANDLE 打开已存在文件并读取 JSON（OBJ_DONT_REPARSE）。

    `_nt_open` 阶段的 reparse / 路径非法 / IO / 非普通文件 → 返回 None（交由上层按
    conflict 保守处理，绝不覆盖）。已验证 HANDLE → fd 的只读转换（open_osfhandle）、
    fdopen / read / 关闭 阶段的任何异常 → 一律映射为稳定 `SafeWriteError(
    TASK_WRITE_FAILED)`，**绝不上抛原始 OSError / 系统细节**。

    单一资源所有权作用域：覆盖 `_nt_open → open_osfhandle → fdopen/read → JSON 解码`
    完整生命周期。任意失败路径都精确关闭一次“仍归本函数所有”的 HANDLE 或 fd，绝不
    重复关闭已转交文件对象的 fd；finally 内的关闭失败也不覆盖已确定的稳定错误码或
    泄露原始 OSError。保持“已验证 HANDLE → fd”只读转换；绝不字符串路径回退。
    """
    try:
        fh = _nt_open(parent_handle, name, is_dir=False)
    except (NotAllowedReparse, PathEscape, IoError, NotARegularFile):
        return None
    # 进入统一资源所有权作用域（_nt_open 已成功，fh 由本函数持有）。
    fh_owned = True   # open_osfhandle 成功前 fh 仍归本函数所有
    fd = -1           # open_osfhandle 结果；-1 = 未分配或已转交文件对象
    f = None          # os.fdopen 返回的文件对象；None = 未创建
    data = None
    try:
        # 阶段 1：已验证 HANDLE → fd 只读转换
        try:
            fd = msvcrt.open_osfhandle(fh, os.O_RDONLY | os.O_BINARY)
        except OSError:
            raise SafeWriteError(TASK_WRITE_FAILED)
        fh_owned = False  # fh 已转交 fd；本函数不再负责关闭 fh
        # 阶段 2：fdopen
        try:
            f = os.fdopen(fd, "rb")
        except OSError:
            raise SafeWriteError(TASK_WRITE_FAILED)
        fd = -1  # 所有权转交 f；本函数不再负责关闭 fd
        # 阶段 3：读取
        try:
            data = f.read()
        except OSError:
            raise SafeWriteError(TASK_WRITE_FAILED)
        # 阶段 4：JSON 解码（非 OSError；脏内容按原语义返回 None，绝不覆盖）
        try:
            return json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
    finally:
        # 精确关闭一次：按 f → fd → fh 顺序，仅关闭仍归本函数所有的资源。
        # 已转交（fd=-1 / fh_owned=False）或从未持有的（None）不重复关闭。
        # 关闭失败也不得覆盖稳定错误码或泄露原始 OSError。
        if f is not None:
            try:
                f.close()
            except OSError:
                pass
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        if fh_owned and fh is not None:
            try:
                _close(fh)
            except OSError:
                pass


def _write_all(handle: int, data: bytes) -> None:
    """循环 WriteFile 直到写完所有字节；任何失败抛 OSError（由 _write_handle 统一映射）。"""
    total = len(data)
    offset = 0
    written = wintypes.DWORD(0)
    while offset < total:
        ok = kernel32.WriteFile(
            handle,
            data[offset:],
            total - offset,
            ctypes.byref(written),
            None,
        )
        if not ok:
            raise OSError("WriteFile failed")
        n = written.value
        if n == 0:
            # 无法推进：避免死循环
            raise OSError("WriteFile progressed 0 bytes")
        offset += n


def _cleanup_failed_file(parent_handle: int, name: str) -> None:
    """写入失败后清理 0 字节 / 半成品文件：仅句柄原生操作，明确检查 NTSTATUS。

    用 `NtDeleteFile` 相对已验证父目录 HANDLE（OBJ_DONT_REPARSE）删除目标；绝不使用
    字符串路径 os.remove / os.replace / 任何回退（避免 reparse / TOCTOU）。name 由服务
    派生的 task_id 派生，经 TASK_ID_RE 校验，无路径注入。

    ctypes 不会因非零返回值抛异常，因此**必须**显式检查返回 NTSTATUS：仅 `STATUS_SUCCESS`
    才声明清理成功（无残留）。非成功状态（如 SHARING_VIOLATION / 其他）**不得静默吞掉**：
    上抛脱敏稳定 `SafeWriteError(TASK_WRITE_FAILED)`；上层据此失败关闭，**绝不**承诺
    “零残留 / 必可重试”，也绝不把路径或原始 NTSTATUS 文本带回调用方。
    """
    if not _NATIVE_AVAILABLE:
        return
    us = UNICODE_STRING()
    enc = name.encode("utf-16-le")
    us.Length = len(enc)
    us.MaximumLength = len(enc) + 2
    buf = ctypes.create_unicode_buffer(name)
    us.Buffer = ctypes.cast(buf, ctypes.c_wchar_p)
    oa = OBJECT_ATTRIBUTES()
    oa.Length = ctypes.sizeof(OBJECT_ATTRIBUTES)
    oa.RootDirectory = ctypes.c_void_p(parent_handle) if parent_handle else None
    oa.ObjectName = ctypes.pointer(us)
    oa.Attributes = OBJ_DONT_REPARSE
    oa.SecurityDescriptor = None
    oa.SecurityQualityOfService = None
    try:
        status = ntdll.NtDeleteFile(ctypes.byref(oa))
    except OSError:
        # 原生调用本身异常（如注入故障）：清理失败，稳定码上抛，不泄露原生细节
        raise SafeWriteError(TASK_WRITE_FAILED)
    st = status & 0xFFFFFFFF
    if st == STATUS_SUCCESS:
        return  # 清理成功：无残留
    # 非成功状态：清理失败，失败关闭；稳定码上抛，不回显 NTSTATUS / 路径
    raise SafeWriteError(TASK_WRITE_FAILED)


def _write_handle(handle: int, data: bytes, parent_handle: int, name: str) -> None:
    """通过 NT HANDLE 写入全部字节并 FlushFileBuffers（fsync），随后关闭 HANDLE。

    HANDLE 所有权在本函数内：无论成功失败均关闭恰好一次，绝不 open_osfhandle 转移
    后再 `_close` 同一 HANDLE（避免重复关闭 / 句柄泄露）。任何写入、刷新或关闭前失败
    → 先关闭本文件 HANDLE（释放独占锁），再以句柄原生操作 `NtDeleteFile`（相对已验证
    父目录 HANDLE）清理 0 字节 / 半成品文件，最后抛 `SafeWriteError("task-write-failed")`；
    不泄露原始异常文本。
    """
    closed = False
    try:
        _write_all(handle, data)
        if not kernel32.FlushFileBuffers(handle):
            raise OSError("FlushFileBuffers failed")
    except SafeWriteError:
        # 已是稳定错误：先关本 HANDLE、清理残留，原样上抛
        _close(handle)
        closed = True
        _cleanup_failed_file(parent_handle, name)
        raise
    except Exception:
        # 任何写入 / 刷新失败 → 稳定错误码 + 句柄原生清理，不泄露原生异常
        _close(handle)
        closed = True
        _cleanup_failed_file(parent_handle, name)
        raise SafeWriteError(TASK_WRITE_FAILED)
    finally:
        if not closed:
            _close(handle)


# --------------------------------------------------------------------------- #
# 公开：受控 no-replace 发布
# --------------------------------------------------------------------------- #

def publish_task_file(task_root: str, task_id: str, payload: dict) -> str:
    """受控 no-replace 发布 <task_id>.json。

    返回 "created" 或 "unchanged"；冲突 / 写失败 / 根不安全抛 `SafeWriteError`
    （稳定码）。最终文件名仅由服务生成的 task_id 派生；绝不接受外部路径。

    顺序：先序列化（序列化失败不创建任何文件），再 `open_task_root`（受控根验证），
    再 `NtCreateFile(FILE_CREATE)` 原子无覆盖创建，最后 `_write_handle`（句柄原生写入
    + fsync）。创建成功后任何写入 / 刷新 / 关闭失败映射为 `SafeWriteError("task-write-failed")`，
    且 0 字节 / 半成品文件由句柄原生 delete-on-close 清理，绝不残留；HANDLE 由
    `_write_handle` 内部恰好关闭一次，本函数不再 `_close(fh)`。
    """
    if not TASK_ID_RE.match(task_id):
        raise SafeWriteError(TASK_INVALID_ID)
    # 序列化在创建之前完成：序列化失败不创建任何文件（无半成品、无残留）
    try:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    except (TypeError, ValueError):
        # 内部 payload 异常：稳定错误码，不泄露正文
        raise SafeWriteError(TASK_WRITE_FAILED)
    handles = open_task_root(task_root)
    try:
        root_h = handles[-1]
        fname = task_id + ".json"
        try:
            fh = _nt_create_file(root_h, fname, FILE_CREATE)
        except (NotAllowedReparse, PathEscape, IoError, NotARegularFile):
            # 文件创建路径被 reparse / 非法 → 失败关闭，绝不回退或覆盖
            raise SafeWriteError(TASK_ROOT_UNSAFE)
        except NameCollision:
            # 目标已存在（含并发创建窗口）→ 不覆盖；读现有内容判定 unchanged / conflict
            existing = _read_existing_json(root_h, fname)
            if isinstance(existing, dict) and existing.get("content_hash") == payload.get("content_hash"):
                return "unchanged"
            raise SafeWriteError(TASK_CONFLICT)
        # 创建成功后写入；任何写入失败 → SafeWriteError(task-write-failed)，
        # _write_handle 内部已确保 0 字节文件被 NtDeleteFile 清理，无残留。
        # fh 的所有权与关闭由 _write_handle 负责（恰好一次），此处不再 _close(fh)。
        _write_handle(fh, data, root_h, fname)
        return "created"
    finally:
        for h in handles:
            _close(h)
