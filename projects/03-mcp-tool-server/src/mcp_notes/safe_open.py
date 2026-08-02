r"""P3 Slice B1：基于句柄（handle-based）的 Windows 原生路径安全打开层。

设计合同 v6（经 Codex 验收修订），要点：

- 仅使用原生对象管理器 API（`NtOpenFile` / `NtQueryDirectoryFile`）与 Win32
  `GetFileInformationByHandleEx` / `CloseHandle`；**绝不**使用字符串路径遍历
  （`os.scandir` / `os.walk` / `glob` / `Path.rglob` / `os.path.realpath`），
  以抵御 reparse point（symlink / junction）跟随与 TOCTOU。
- 每一级目录 / 文件打开都携带 `OBJ_DONT_REPARSE`：任何 reparse point 会令
  `NtOpenFile` 返回 `STATUS_REPARSE_POINT_ENCOUNTERED`，从而拒绝式拦截；
  枚举时若某条目的 `FILE_ATTRIBUTE_REPARSE_POINT` 被置位，`_walk` 直接抛
  `NotAllowedReparse`，不 `continue` 跳过、不继续构建。
- 目录枚举**仅**通过 `NtQueryDirectoryFile`
  （`FileInformationClass = FileDirectoryInformation = 1`）；缓冲区解析遵循
  §4.4 硬边界逐字段断言，任何越界 / 畸形 / UTF-16 解码失败 / `Information==0`
  一律抛 `IoError`，绝不返回部分枚举结果。
- 根路径配置门：先审计原始字符串（拒绝 `..` / UNC / `\\?\` / `\\.\` /
  `\Device\` / 正斜杠混用 / 相对路径），再接受本地盘符绝对路径；
  `ObjectName = "\\??\\" + 归一化`。
- 组件级校验（§4.6）：拒绝空段、`.`、`..`、`\`、`/`、`:`、`< > " | ? *`、
  控制字符、尾随点 / 空格、保留设备名。`_nt_open` 在相对父 HANDLE 打开时
  也自行校验组件，不依赖调用方。
- 文件打开（相对父 HANDLE，非根）后必须查询 `WIN32_FILE_BASIC_INFO`
  拒绝 DIRECTORY / REPARSE_POINT / DEVICE，并查询 `WIN32_FILE_STANDARD_INFO`
  做容量上限（`MAX_NOTE_BYTES`）；任一查询失败或超大 → `IoError` /
  `NotARegularFile` / `NotAllowedReparse` / `ContentTooLarge`。
- 文件读取经 `msvcrt.open_osfhandle` 转 fd，最终只读字节读取并防御性限容。
- R0 / T0：真实机器 ABI 冒烟（根打开 + 枚举 + 相对文件打开 + FileBasicInfo +
  FileStandardInfo + HANDLE→fd 读取 + 关闭一次 + 清理）；若失败抛
  `UnsafeOpenUnavailable`，**绝不回退**到字符串路径方案。
- 不泄露路径、用户名、环境变量或原始系统错误文本；所有失败映射为稳定错误码。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import msvcrt
import os

from .contracts import (
    MAX_NOTE_BYTES,
    NATIVE_FILE_DIRECTORY_INFORMATION,
    WIN32_FILE_BASIC_INFO,
    WIN32_FILE_STANDARD_INFO,
)

# --------------------------------------------------------------------------- #
# 具名常量（v6：Native 与 Win32 枚举分开设具名常量，防止数值巧合混淆）
# --------------------------------------------------------------------------- #

# 访问与打开选项
FILE_READ_DATA = 0x0001
FILE_LIST_DIRECTORY = 0x0001  # 与 FILE_READ_DATA 同 bit，但语义为目录枚举
FILE_READ_ATTRIBUTES = 0x0080
SYNCHRONIZE = 0x100000
FILE_DIRECTORY_FILE = 0x0001
FILE_NON_DIRECTORY_FILE = 0x0040
FILE_SYNCHRONOUS_IO_NONALERT = 0x0020
FILE_SHARE_READ = 0x0001

# OBJECT_ATTRIBUTES.Attributes
OBJ_DONT_REPARSE = 0x00001000

# 文件属性（仅用于判定，不依赖它做最终安全结论）
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_DEVICE = 0x40

# NTSTATUS（按无符号比较；restype 为 c_long，返回时已是有符号值）
STATUS_SUCCESS = 0x00000000
STATUS_REPARSE_POINT_ENCOUNTERED = 0xC00004FA
STATUS_BUFFER_OVERFLOW = 0x80000005
# 本机 NtQueryDirectoryFile 枚举结束返回 0x80000006（实测）；作为终止条件。
STATUS_NO_MORE_FILES = 0x80000006

# 保留 DOS 设备名（组件级校验，避免被解析为设备而非文件）
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# 组件级禁止字符（Windows 文件名非法字符；`:` 亦禁用以拒绝 NTFS 流语法）
_FORBIDDEN_CHARS = set("\\/:<>\"|?*")

# UNICODE_STRING.Length / MaximumLength 上限（USHORT）
_USHORT_MAX = 0xFFFF


# --------------------------------------------------------------------------- #
# 原生库加载（仅 Windows 可用；非 Windows 时置空，verify_native_support 返回 False）
# --------------------------------------------------------------------------- #

try:
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _NATIVE_AVAILABLE = True
except (AttributeError, OSError):  # 非 Windows 或加载失败
    ntdll = None
    kernel32 = None
    _NATIVE_AVAILABLE = False

_native_verified = False  # T0 冒烟结果缓存


# --------------------------------------------------------------------------- #
# ctypes 结构定义
# --------------------------------------------------------------------------- #

class UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("MaximumLength", ctypes.c_ushort),
        ("Buffer", ctypes.c_wchar_p),
    ]


class OBJECT_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ulong),
        ("RootDirectory", ctypes.c_void_p),
        ("ObjectName", ctypes.POINTER(UNICODE_STRING)),
        ("Attributes", ctypes.c_ulong),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    ]


class IO_STATUS_BLOCK(ctypes.Structure):
    # union { NTSTATUS Status; PVOID Pointer } + ULONG_PTR Information
    # 64 位下 union 占 8 字节（Status 为 32 位 + 4 字节填充），Information 为
    # 指针宽度（64 位下 8 字节）。用 c_long（32 位 NTSTATUS）与 c_size_t
    # （指针宽度），不使用写死的 c_ulonglong。
    _fields_ = [
        ("Status", ctypes.c_long),
        ("Information", ctypes.c_size_t),
    ]


class FILE_DIRECTORY_INFORMATION(ctypes.Structure):
    # 注意：FileName 为占位 1 字符数组；固定头长度必须用 FileName.offset，
    # 不能用 sizeof（会多算 1 个 wchar）。保留该结构仅用于 T6 偏移断言；
    # 解析使用下方 _DIR_INFO_HEADER（无 FileName 占位，sizeof==64）。
    _fields_ = [
        ("NextEntryOffset", ctypes.c_ulong),
        ("FileIndex", ctypes.c_ulong),
        ("CreationTime", ctypes.c_int64),
        ("LastAccessTime", ctypes.c_int64),
        ("LastWriteTime", ctypes.c_int64),
        ("ChangeTime", ctypes.c_int64),
        ("EndOfFile", ctypes.c_int64),
        ("AllocationSize", ctypes.c_int64),
        ("FileAttributes", ctypes.c_ulong),
        ("FileNameLength", ctypes.c_ulong),
        ("FileName", ctypes.c_wchar * 1),
    ]


class _DIR_INFO_HEADER(ctypes.Structure):
    # 固定头（不含 FileName 占位），sizeof == 64 == FileName.offset。
    _fields_ = [
        ("NextEntryOffset", ctypes.c_ulong),
        ("FileIndex", ctypes.c_ulong),
        ("CreationTime", ctypes.c_int64),
        ("LastAccessTime", ctypes.c_int64),
        ("LastWriteTime", ctypes.c_int64),
        ("ChangeTime", ctypes.c_int64),
        ("EndOfFile", ctypes.c_int64),
        ("AllocationSize", ctypes.c_int64),
        ("FileAttributes", ctypes.c_ulong),
        ("FileNameLength", ctypes.c_ulong),
    ]


_HEADER_LEN = ctypes.sizeof(_DIR_INFO_HEADER)  # 64


class FILE_BASIC_INFO(ctypes.Structure):
    _fields_ = [
        ("CreationTime", ctypes.c_int64),
        ("LastAccessTime", ctypes.c_int64),
        ("LastWriteTime", ctypes.c_int64),
        ("ChangeTime", ctypes.c_int64),
        ("FileAttributes", ctypes.c_ulong),
    ]


class FILE_STANDARD_INFO(ctypes.Structure):
    # EndOfFile 位于偏移 8（AllocationSize 之后）。
    _fields_ = [
        ("AllocationSize", ctypes.c_int64),
        ("EndOfFile", ctypes.c_int64),
        ("NumberOfLinks", ctypes.c_ulong),
        ("DeletePending", wintypes.BOOLEAN),
        ("Directory", wintypes.BOOLEAN),
    ]


if _NATIVE_AVAILABLE:
    ntdll.NtOpenFile.restype = ctypes.c_long
    ntdll.NtOpenFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.ULONG,                       # DesiredAccess
        ctypes.POINTER(OBJECT_ATTRIBUTES),
        ctypes.POINTER(IO_STATUS_BLOCK),
        wintypes.ULONG,                       # ShareAccess
        wintypes.ULONG,                       # OpenOptions
    ]

    ntdll.NtQueryDirectoryFile.restype = ctypes.c_long
    ntdll.NtQueryDirectoryFile.argtypes = [
        wintypes.HANDLE,                      # FileHandle
        wintypes.HANDLE,                      # Event (NULL)
        ctypes.c_void_p,                      # ApcRoutine (NULL)
        ctypes.c_void_p,                      # ApcContext (NULL)
        ctypes.POINTER(IO_STATUS_BLOCK),      # IoStatusBlock
        ctypes.c_void_p,                      # FileInformation (buffer)
        wintypes.ULONG,                       # Length
        wintypes.DWORD,                       # FileInformationClass (DWORD=1)
        wintypes.BOOLEAN,                     # ReturnSingleEntry
        ctypes.c_void_p,                      # FileName (NULL = 全部)
        wintypes.BOOLEAN,                     # RestartScan
    ]

    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,                      # hFile
        wintypes.DWORD,                       # FileInformationClass (Win32)
        ctypes.c_void_p,                      # lpFileInformation
        wintypes.DWORD,                       # dwBufferSize
    ]

    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    # 模块级别名：便于测试在真实原生函数处注入（不改变安全语义）
    _nt_open_file_fn = ntdll.NtOpenFile
else:
    _nt_open_file_fn = None


# --------------------------------------------------------------------------- #
# 稳定错误类型（不泄露路径 / 用户名 / 环境变量 / 原始系统错误文本）
# --------------------------------------------------------------------------- #

class UnsafeOpenUnavailable(Exception):
    """R0 / T0：原生 API 不可用或 ABI 冒烟失败。绝不回退到字符串路径方案。"""
    code = "unsafe-open-unavailable"


class SafeOpenError(Exception):
    """路径安全层基类；code 为稳定错误码。"""
    code = "io-error"


class NotAllowedReparse(SafeOpenError):
    code = "not-allowed-reparse"


class NotARegularFile(SafeOpenError):
    code = "not-a-regular-file"


class PathEscape(SafeOpenError):
    code = "path-escape"


class ContentTooLarge(SafeOpenError):
    code = "content-too-large"


class IndexBuildFailed(SafeOpenError):
    code = "index-build-failed"


class IoError(SafeOpenError):
    code = "io-error"


# --------------------------------------------------------------------------- #
# 根配置门（先拒绝危险段，再接受本地盘符绝对路径）
# --------------------------------------------------------------------------- #

def configure_root(raw: str) -> str:
    """审计根路径原始字符串，返回对象管理器名称（"\\??\\" + 归一化绝对路径）。

    顺序：先拒绝任何危险原始段（在任何归一之前），再接受本地盘符绝对路径。
    失败抛 `PathEscape`（稳定错误码，不泄露具体路径）。
    """
    if not isinstance(raw, str):
        raise PathEscape()
    s = raw.replace("/", "\\")
    # 先拒绝危险原始段
    if ".." in s:
        raise PathEscape()
    if s.startswith("\\\\"):  # UNC 或 \\?\ 或 \\.
        raise PathEscape()
    if "\\\\?\\" in s or "\\\\.\\" in s:
        raise PathEscape()
    if s.lower().startswith("\\device\\"):
        raise PathEscape()
    # 接受本地盘符绝对路径：^[A-Za-z]:\\...（已统一为反斜杠）
    if len(s) < 3 or not s[0].isalpha() or s[1] != ":" or s[2] != "\\":
        raise PathEscape()
    return "\\??\\" + s


# --------------------------------------------------------------------------- #
# 组件级校验（§4.6）
# --------------------------------------------------------------------------- #

def _validate_component(name: str) -> None:
    """校验单个目录 / 文件名组件；非法抛 `PathEscape`（不泄露组件内容）。"""
    if not isinstance(name, str) or name == "":
        raise PathEscape()
    if name in (".", ".."):
        raise PathEscape()
    for ch in name:
        if ch in _FORBIDDEN_CHARS:  # \ / : < > " | ? *
            raise PathEscape()
        if ord(ch) < 0x20:  # 控制字符
            raise PathEscape()
    # Windows 会剥离末尾的点 / 空格，导致实际打开不同对象
    if name.endswith(".") or name.endswith(" "):
        raise PathEscape()
    base = name.split(".", 1)[0].upper()
    if base in _RESERVED_NAMES:
        raise PathEscape()


# --------------------------------------------------------------------------- #
# 核心：句柄级打开（OBJ_DONT_REPARSE + 相对父 HANDLE）
# --------------------------------------------------------------------------- #

def _nt_open(parent_handle: int, name: str, is_dir: bool) -> int:
    """打开一个对象并返回新 HANDLE（调用方负责 CloseHandle）。

    - 若 parent_handle == 0：name 已是 "\\??\\..." 形式的绝对对象名称（根）。
    - 否则：name 为单个组件名，相对已验证父目录 HANDLE 打开；**无论调用方是否
      校验过，本函数都会对组件自行校验**（§4.6）。
    - 携带 `OBJ_DONT_REPARSE`：任何 reparse point 返回
      `STATUS_REPARSE_POINT_ENCOUNTERED` → 抛 `NotAllowedReparse`。
    - 非目录打开成功后，查询 `WIN32_FILE_BASIC_INFO` 拒绝 DIRECTORY /
      REPARSE_POINT / DEVICE，再查询 `WIN32_FILE_STANDARD_INFO` 做容量上限
      （> MAX_NOTE_BYTES → `ContentTooLarge`）；任一查询失败 → `IoError`。
    """
    if not _NATIVE_AVAILABLE:
        raise UnsafeOpenUnavailable()

    # 相对父 HANDLE 打开时自行校验组件（根打开不校验，name 为完整对象名）
    if parent_handle != 0:
        _validate_component(name)

    encoded = name.encode("utf-16-le")  # 真实 UTF-16LE 字节数（含代理对；非 BMP 占 4 字节）
    # UNICODE_STRING.Length = 字节数；MaximumLength = 字节数 + 2（null 终止符）。
    # 必须保证 Length 与 MaximumLength 在 c_ushort(USHORT, 上限 0xFFFF) 内均不截断：
    # 若仅校验 len(encoded) > _USHORT_MAX，则 len==65534 时 MaximumLength=65536 在
    # c_ushort 中回绕为 0（静默截断，破坏结构），故改为校验 len(encoded) + 2 > _USHORT_MAX。
    if len(encoded) + 2 > _USHORT_MAX:
        raise PathEscape()
    us = UNICODE_STRING()
    us.Length = len(encoded)
    us.MaximumLength = len(encoded) + 2  # 预留 null 终止符
    _buf = ctypes.create_unicode_buffer(name)
    us.Buffer = ctypes.cast(_buf, ctypes.c_wchar_p)  # 保持 _buf 存活至 Native 调用结束

    oa = OBJECT_ATTRIBUTES()
    oa.Length = ctypes.sizeof(OBJECT_ATTRIBUTES)
    oa.RootDirectory = ctypes.c_void_p(parent_handle) if parent_handle != 0 else None
    oa.ObjectName = ctypes.pointer(us)  # 真实指针对象（结构字段不接受 byref）
    oa.Attributes = OBJ_DONT_REPARSE
    oa.SecurityDescriptor = None
    oa.SecurityQualityOfService = None

    h = wintypes.HANDLE()
    iosb = IO_STATUS_BLOCK()
    desired = SYNCHRONIZE | FILE_READ_ATTRIBUTES | \
        (FILE_LIST_DIRECTORY if is_dir else FILE_READ_DATA)
    options = (FILE_DIRECTORY_FILE if is_dir else FILE_NON_DIRECTORY_FILE) | \
        FILE_SYNCHRONOUS_IO_NONALERT

    status = _nt_open_file_fn(
        ctypes.byref(h),
        desired,
        ctypes.byref(oa),
        ctypes.byref(iosb),
        FILE_SHARE_READ,
        options,
    )
    st = status & 0xFFFFFFFF
    if st != STATUS_SUCCESS:
        if st == STATUS_REPARSE_POINT_ENCOUNTERED:
            raise NotAllowedReparse()
        raise IoError()
    handle = h.value

    # 仅对“文件”打开做普通文件判定与容量上限（目录本身就是目录，不必拒绝）
    if not is_dir:
        basic = FILE_BASIC_INFO()
        if not _query_file_info(handle, WIN32_FILE_BASIC_INFO, basic):
            _close(handle)
            raise IoError()
        attrs = basic.FileAttributes
        if attrs & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_DEVICE):
            _close(handle)
            raise NotARegularFile()
        if attrs & FILE_ATTRIBUTE_REPARSE_POINT:  # 双重保险（OBJ_DONT_REPARSE 之外）
            _close(handle)
            raise NotAllowedReparse()
        std = FILE_STANDARD_INFO()
        if not _query_file_info(handle, WIN32_FILE_STANDARD_INFO, std):
            _close(handle)
            raise IoError()
        if std.EndOfFile > MAX_NOTE_BYTES:
            _close(handle)
            raise ContentTooLarge()

    return handle


def _query_file_info(handle: int, class_id: int, info_struct) -> bool:
    """封装 GetFileInformationByHandleEx（Win32 FILE_INFO_BY_HANDLE_CLASS）。

    返回 True/False；不泄露原始系统错误文本。便于测试注入。
    """
    ok = kernel32.GetFileInformationByHandleEx(
        handle, class_id, ctypes.byref(info_struct), ctypes.sizeof(info_struct)
    )
    return bool(ok)


def _close(handle: int) -> None:
    if kernel32 is not None and handle not in (None, 0):
        kernel32.CloseHandle(handle)


# --------------------------------------------------------------------------- #
# 核心：句柄级目录枚举（仅 NtQueryDirectoryFile，§4.4 硬边界）
# --------------------------------------------------------------------------- #

def _enumerate(parent_handle: int) -> list[tuple[str, int, bool]]:
    """枚举已验证目录 HANDLE 的直接子项。

    返回 [(name, file_attributes, is_directory), ...]。仅用 NtQueryDirectoryFile；
    任何异常（BUFFER_OVERFLOW / 非成功状态 / Information==0 / 硬边界失败 /
    UTF-16 解码失败）一律抛 `IoError`，**绝不返回部分枚举结果**。
    """
    buffer = ctypes.create_string_buffer(8192)
    buffer_length = len(buffer)
    results: list[tuple[str, int, bool]] = []
    restart = True
    while True:
        iosb = IO_STATUS_BLOCK()
        status = ntdll.NtQueryDirectoryFile(
            parent_handle,
            None,                       # Event
            None,                       # ApcRoutine
            None,                       # ApcContext
            ctypes.byref(iosb),
            buffer,
            buffer_length,
            NATIVE_FILE_DIRECTORY_INFORMATION,  # DWORD = 1
            False,                      # ReturnSingleEntry
            None,                       # FileName（全部）
            restart,
        )
        st = status & 0xFFFFFFFF
        if st == STATUS_BUFFER_OVERFLOW:
            # 单个条目放不进缓冲：整次构建失败，不 resize 重试（B1 范围）
            raise IoError()
        if st == STATUS_NO_MORE_FILES:
            break
        if st != STATUS_SUCCESS:
            raise IoError()
        info_end = iosb.Information
        if info_end == 0:
            # 异常：STATUS_SUCCESS 但无数据；绝不作为“正常结束”而返回部分结果
            raise IoError()
        _parse_buffer(buffer, info_end, buffer_length, results)
        restart = False
    return results


def _parse_buffer(buf, info_end: int, buffer_length: int, results: list) -> None:
    """§4.4 缓冲区解析硬边界：逐记录严格断言，任何越界 / 畸形 / 解码失败抛 `IoError`。

    先断言 `0 < info_end <= buffer_length`；每条记录必须：
    - NextEntryOffset==0 → record_end=info_end 且本批结束；
    - NextEntryOffset!=0 → next_off>=_HEADER_LEN、next_off%8==0、
      record_end=record_start+next_off、record_start<record_end<=info_end；
    - header_end + FileNameLength <= record_end；
    - UTF-16LE 解码异常 → IoError；
    通过全部边界检查后才 append 当前记录。
    """
    if not (0 < info_end <= buffer_length):
        raise IoError()
    addr = ctypes.addressof(buf)
    record_start = 0
    while True:
        if record_start < 0 or record_start >= info_end:
            raise IoError()
        header_end = record_start + _HEADER_LEN
        if header_end > info_end:
            raise IoError()
        # 固定头恰好 _HEADER_LEN 字节（无 FileName 占位干扰）
        header = _DIR_INFO_HEADER.from_buffer_copy(
            ctypes.string_at(addr + record_start, _HEADER_LEN)
        )
        next_off = header.NextEntryOffset
        fn_len = header.FileNameLength
        attrs = header.FileAttributes

        if fn_len % 2 != 0:  # UTF-16LE 必须为偶数字节
            raise IoError()

        if next_off == 0:
            record_end = info_end
        else:
            if next_off < _HEADER_LEN:
                raise IoError()
            if next_off % 8 != 0:
                raise IoError()
            record_end = record_start + next_off
            if not (record_start < record_end <= info_end):
                raise IoError()

        # FileName 区域必须完整落在 [header_end, record_end)
        fn_start = record_start + _HEADER_LEN
        fn_end = fn_start + fn_len
        if fn_end > record_end:
            raise IoError()

        try:
            name = ctypes.string_at(addr + fn_start, fn_len).decode("utf-16-le")
        except UnicodeDecodeError:
            raise IoError()

        is_dir = bool(attrs & FILE_ATTRIBUTE_DIRECTORY)
        # 通过全部边界检查后才登记
        results.append((name, attrs, is_dir))

        if next_off == 0:
            break
        record_start = record_end


# --------------------------------------------------------------------------- #
# 核心：递归遍历（拒绝 reparse、校验组件、登记 .md）
# --------------------------------------------------------------------------- #

def _walk(parent_handle: int, prefix_parts: list[str], consumer) -> None:
    """递归枚举已验证目录 HANDLE；对每个 `.md` 普通文件调用 consumer(rel_parts)。

    - 跳过 `.` / `..`。
    - 任何 `FILE_ATTRIBUTE_REPARSE_POINT` 条目 → 抛 `NotAllowedReparse`
      （不 `continue` 跳过、不继续构建）。
    - 对每个组件做 §4.6 校验（亦由 `_nt_open` 内部兜底）。
    """
    for name, attrs, is_dir in _enumerate(parent_handle):
        if name in (".", ".."):
            continue
        if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
            # 拒绝式拦截 reparse（NtOpenFile 的 OBJ_DONT_REPARSE 之外双重保险）
            raise NotAllowedReparse()
        _validate_component(name)
        if is_dir:
            child = _nt_open(parent_handle, name, is_dir=True)
            try:
                _walk(child, prefix_parts + [name], consumer)
            finally:
                _close(child)
        elif name.lower().endswith(".md"):
            consumer(prefix_parts + [name])


# --------------------------------------------------------------------------- #
# 核心：文件读取（msvcrt.open_osfhandle 转 fd，限容 MAX_NOTE_BYTES）
# --------------------------------------------------------------------------- #

def read_file_bytes(parent_handle: int, name: str, max_bytes: int = MAX_NOTE_BYTES) -> bytes:
    """在已验证父目录 HANDLE 下打开单文件（OBJ_DONT_REPARSE + 普通文件判定 +
    容量上限），返回至多 max_bytes+1 字节。

    普通文件判定与容量上限由 `_nt_open` 负责（拒绝非普通文件 / 超大文件）；
    此处仅做 HANDLE→fd 只读读取，并防御性多读 1 字节以检出超限。
    """
    h = _nt_open(parent_handle, name, is_dir=False)
    fd = -1
    try:
        fd = msvcrt.open_osfhandle(h, os.O_RDONLY | os.O_BINARY)
        h = None  # 所有权已转交 fd
        f = os.fdopen(fd, "rb")
        fd = -1
        try:
            data = f.read(max_bytes + 1)
        finally:
            f.close()
        if len(data) > max_bytes:
            raise ContentTooLarge()
        return data
    finally:
        if h is not None:
            _close(h)
        if fd != -1:
            os.close(fd)


def open_file_relative(root_handle: int, rel_parts) -> bytes:
    """从已验证根 HANDLE 出发，沿 rel_parts（目录链 + 文件名）打开文件并返回字节。

    先校验 rel_parts 为非空列表，并对每一级组件做 §4.6 校验（双重兜底）；
    沿途打开的目录 HANDLE 在本函数内关闭。
    """
    if not isinstance(rel_parts, (list, tuple)) or len(rel_parts) == 0:
        raise PathEscape()
    for part in rel_parts:
        _validate_component(part)

    parent = root_handle
    opened: list[int] = []
    try:
        for part in rel_parts[:-1]:
            child = _nt_open(parent, part, is_dir=True)
            opened.append(child)
            parent = child
        return read_file_bytes(parent, rel_parts[-1])
    finally:
        for h in opened:
            _close(h)


# --------------------------------------------------------------------------- #
# R0 / T0：真实机器 ABI 冒烟（完整工作流 + 清理）
# --------------------------------------------------------------------------- #

def verify_native_support() -> bool:
    """R0 / T0：真实机器 ABI 冒烟。失败返回 False（绝不可信通过）。

    完整验证：根打开 → 目录枚举 → 相对文件打开 → FileBasicInfo →
    FileStandardInfo → HANDLE→fd 读取 → 关闭一次；完成后清理临时目录。
    任一步失败返回 False，触发 `unsafe-open-unavailable`，绝不回退字符串路径。
    """
    global _native_verified
    if not _NATIVE_AVAILABLE:
        return False
    if _native_verified:
        return True

    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="p3_native_")
    try:
        note = os.path.join(tmp, "sample.md")
        payload = b"safe-open-smoke\r\n"
        with open(note, "wb") as f:
            f.write(payload)

        root_name = configure_root(tmp)
        root_h = _nt_open(0, root_name, is_dir=True)
        try:
            # 目录枚举
            entries = _enumerate(root_h)
            names = [e[0] for e in entries]
            if "sample.md" not in names:
                return False

            # 相对文件打开（内含文件属性与容量判定）
            fh = _nt_open(root_h, "sample.md", is_dir=False)
            try:
                # 显式验证 Win32 FILE_INFO_BY_HANDLE_CLASS 调用
                basic = FILE_BASIC_INFO()
                if not kernel32.GetFileInformationByHandleEx(
                    fh, WIN32_FILE_BASIC_INFO, ctypes.byref(basic), ctypes.sizeof(basic)
                ):
                    return False
                if basic.FileAttributes & (
                    FILE_ATTRIBUTE_DIRECTORY
                    | FILE_ATTRIBUTE_REPARSE_POINT
                    | FILE_ATTRIBUTE_DEVICE
                ):
                    return False
                std = FILE_STANDARD_INFO()
                if not kernel32.GetFileInformationByHandleEx(
                    fh, WIN32_FILE_STANDARD_INFO, ctypes.byref(std), ctypes.sizeof(std)
                ):
                    return False
                if std.EndOfFile != len(payload):
                    return False

                # HANDLE → fd 读取（所有权转交，关闭一次）
                fd = msvcrt.open_osfhandle(fh, os.O_RDONLY | os.O_BINARY)
                fh = None
                with os.fdopen(fd, "rb") as f:
                    data = f.read()
                if data.rstrip(b"\r\n") != b"safe-open-smoke":
                    return False
            finally:
                if fh is not None:
                    _close(fh)
        finally:
            _close(root_h)

        _native_verified = True
        return True
    except Exception:
        _native_verified = False
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
