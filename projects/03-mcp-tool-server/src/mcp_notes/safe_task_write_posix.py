r"""P3 Slice D-2：POSIX 安全发布核心（纯 stdlib，不依赖 Windows-only safe_open）。

设计依据：`docs/D-2-design.md`（修订版 v5）§1–§4。与 Windows 原生分支收敛到同一组
稳定错误语义与同一 `publish_task_file(task_root, task_id, payload)` 接口，使 `tasks.py`
调用点不感知平台。

安全算法（§1）：
- 从可信锚点（`os.open("/", O_RDONLY | O_DIRECTORY)`，即 `/` 的目录 fd）开始；
- `task_root` 必须是绝对路径；拆分后拒绝空段、`.`、`..`、尾 `/`、相对路径、`/` 本身；
- 每一级目录只允许相对已验证父 fd 的 `os.open(comp, O_RDONLY | O_DIRECTORY |
  O_NOFOLLOW)`，随后 `os.fstat` 断言目录；
- **所有父 fd 保持打开**，直到最终创建、冲突读取、失败清理、父目录 `fsync` 完成，
  才逆序关闭（严禁验证后关闭父 fd 再按名重新打开）；
- 禁止 `os.path.realpath` 作安全判断；除锚点一次性 `open("/")` 外禁止字符串路径回退；
- `dir_fd` / `O_NOFOLLOW` / `O_DIRECTORY` / 目录 `fsync` 能力缺失时稳定
  `task-root-unsafe`，绝不降级字符串路径方案。

最终文件（§1/§3）：相对已验证父 fd 用 `O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW`；
命中 `EEXIST` 后做安全分类（先 `os.stat(follow_symlinks=False)` 预筛，再
`O_NOFOLLOW` 打开 + `fstat`）；symlink/目录/FIFO/设备/类型变化/不可归类 →
`task-root-unsafe`；仅常规文件才比对内容（unchanged / conflict）；权限/IO/读/解码
失败 → `task-write-failed`。

fsync / 清理（§4）：写 → 文件 `fsync` → `close` → 父目录 `fsync` 才返回 `created`；
任一失败 → 仅 `close` 一次 + 身份复核后 `unlink(name, dir_fd=...)` + 父目录 `fsync`；
清理成功/失败两种语义合同不同；无唯一写入者前提时禁止按名 `unlink`。

所有失败映射为稳定错误码（`SafeWriteError.code`），不泄露路径 / 正文 / 异常文本。
复用 `safe_task_write` 的 `SafeWriteError` / `TASK_*` / `NameCollision` / `TASK_ID_RE`。

注意：本模块仅在 POSIX 平台经 `safe_task_write.publish_task_file` 的 dispatch 进入。
Windows 上 `os.open` 不支持 `dir_fd` / `O_NOFOLLOW` / `O_DIRECTORY`，故不可达；Windows
走 `safe_task_write` 内的 Windows 原生分支。真实 POSIX 链接 / TOCTOU 验证须在
Linux / WSL 执行（见 D-2-design.md blocked-until-approved）。
"""

from __future__ import annotations

import errno
import json
import os
import stat

# 复用门面的稳定错误类型与常量（门面先于本模块完成这些定义后再 import 本模块，
# 不存在循环导入问题；Windows 上不 import 本模块，故无副作用）。
from .safe_task_write import (  # noqa: E402
    SafeWriteError,
    TASK_INVALID_ID,
    TASK_CONFLICT,
    TASK_WRITE_FAILED,
    TASK_ROOT_UNSAFE,
    NameCollision,
    TASK_ID_RE,
)


def _posix_supported() -> bool:
    """能力探测：逐项确认 open/stat/unlink 支持 dir_fd、stat 支持 follow_symlinks=False、
    O_NOFOLLOW / O_DIRECTORY / fsync 存在。

    仅 `bool(os.supports_dir_fd)` 不够——必须逐项确认，否则部分平台能力缺失会在运行时
    抛 `TypeError`（如某 syscall 不支持 dir_fd）。任一缺失 → 调用方应稳定
    `task-root-unsafe`，绝不回退字符串路径方案、绝不泄露 TypeError。
    """
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        return False
    if not hasattr(os, "fsync"):
        return False
    # 防御：关键 syscall 属性本身缺失 → 提前稳定失败，避免后续 AttributeError
    for _name in ("open", "stat", "unlink", "fstat"):
        if not hasattr(os, _name):
            return False
    dir_fd_caps = getattr(os, "supports_dir_fd", ())
    if os.open not in dir_fd_caps:
        return False
    if os.stat not in dir_fd_caps:
        return False
    if os.unlink not in dir_fd_caps:
        return False
    follow_caps = getattr(os, "supports_follow_symlinks", ())
    if os.stat not in follow_caps:
        return False
    return True


# --------------------------------------------------------------------------- #
# §4 跨平台共同部署前提（D-2-design.md §4）：task_root 由可信部署管理、服务是唯一
# 写入者、非服务主体无写/改名/删权限。inode 复核仅纵深防御，不替代目录权限隔离。
# 若部署无法保证该前提，失败清理禁止按名 unlink（避免删除被替换对象）。
#
# 重要：`_SINGLE_WRITER` 是**可信部署前提的声明**（由部署方通过环境变量断言），并非
# 运行时 ACL 验证——本模块不查询系统用户/权限，也不做进程级排他锁。非唯一写入者时
# 严格禁止按名 unlink（防止删除被替换对象）。真实 POSIX 链接 / TOCTOU 验证须在
# Linux / WSL 执行（见 D-2-design.md blocked-until-approved），不声称整个 MCP Server 已
# 跨平台（仅发布核心可按平台分发）。
# --------------------------------------------------------------------------- #

_SINGLE_WRITER = os.environ.get("P3_TASK_ROOT_SINGLE_WRITER", "1") == "1"


# --------------------------------------------------------------------------- #
# §1 受控根 fd 锚定：从 / 的目录 fd 起，逐段 openat + fstat，所有父 fd 持有到清理结束
# --------------------------------------------------------------------------- #

def _split_root(task_root: str) -> list:
    """§1：仅接受单个开头 `/`；移除该 `/` 后按单 `/` 分割。

    拒绝：双 `//` 开头（body 首段空）、空段、`/` 本身（body 为空）、`.`、`..`、相对路径。
    返回非空组件列表；任何非法 → 稳定 `task-root-unsafe`。
    """
    if not isinstance(task_root, str) or not task_root.startswith("/"):
        # 相对路径或非法类型
        raise SafeWriteError(TASK_ROOT_UNSAFE)
    body = task_root[1:]  # 移除结构性单个 `/`
    if body == "":
        # task_root == "/" 本身：拆分后无合法组件
        raise SafeWriteError(TASK_ROOT_UNSAFE)
    comps = body.split("/")
    for comp in comps:
        if comp == "":  # 双 `//`、空段
            raise SafeWriteError(TASK_ROOT_UNSAFE)
        if "\x00" in comp:  # 含 NUL：非法组件，绝不传入 os.open（避免原始 ValueError / 路径注入）
            raise SafeWriteError(TASK_ROOT_UNSAFE)
        if comp == "." or comp == "..":  # 当前/上级目录
            raise SafeWriteError(TASK_ROOT_UNSAFE)
    return comps


def _open_root(task_root: str) -> list:
    """§1：从 `/` 的目录 fd 起，逐级 openat(O_DIRECTORY|O_NOFOLLOW)+fstat，返回已验证 fd 链。

    返回 `[root_fd, ..., task_root_dir_fd]`（含中间目录 fd，全部保持打开）。
    任何 reparse / 非目录 / 打开失败 → 关闭已开 fd，稳定 `task-root-unsafe`。
    绝不回退字符串路径方案。
    """
    comps = _split_root(task_root)
    fds: list = []  # 预置空：根 fd 打开失败即进入 except 时不会引用未绑定变量
    try:
        try:
            root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        except OSError:
            raise SafeWriteError(TASK_ROOT_UNSAFE)
        fds = [root_fd]
        parent = root_fd
        for comp in comps:
            try:
                h = os.open(
                    comp,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent,
                )
            except OSError:
                raise SafeWriteError(TASK_ROOT_UNSAFE)
            try:
                st = os.fstat(h)
            except OSError:
                # fstat 失败：best-effort 关闭 h，稳定 task-root-unsafe；
                # 关闭失败也绝不泄露原始 OSError / 覆盖稳定错误码
                try:
                    os.close(h)
                except OSError:
                    pass
                raise SafeWriteError(TASK_ROOT_UNSAFE)
            if not stat.S_ISDIR(st.st_mode):
                # 非目录：best-effort 关闭 h，稳定 task-root-unsafe
                try:
                    os.close(h)
                except OSError:
                    pass
                raise SafeWriteError(TASK_ROOT_UNSAFE)
            fds.append(h)
            parent = h
        return fds
    except SafeWriteError:
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass
        raise


# --------------------------------------------------------------------------- #
# §3 EEXIST 安全分类（始终用已验证 parent_fd，不 exists/realpath/字符串重开）
# --------------------------------------------------------------------------- #

def _handle_existing(parent_fd: int, fname: str, payload: dict) -> str:
    """§3：命中 `EEXIST` 后，用仍持有的 parent_fd 做安全分类（精确错误语义）。

    预筛 `os.stat(follow_symlinks=False)`：
    - `PermissionError`（权限不足）/ 其他 IO（`OSError` 非 `ELOOP`）→ `task-write-failed`；
    - `FileNotFoundError`（竞态消失，无法安全归类）/ `ELOOP` / `ValueError`
      → `task-root-unsafe`。
    仅常规文件才 `O_NOFOLLOW` 打开：
    - `PermissionError` / 其他 IO（`OSError` 非 `ELOOP`）→ `task-write-failed`；
    - `FileNotFoundError` / `ELOOP` → `task-root-unsafe`。
    symlink/目录/FIFO/设备/类型不一致 → `task-root-unsafe`；内容同 → `unchanged`、
    内容异 → `task-conflict`；读取/解码失败 → `task-write-failed`。
    """
    # 预筛：不跟随最终组件
    try:
        st = os.stat(fname, dir_fd=parent_fd, follow_symlinks=False)
    except PermissionError:
        raise SafeWriteError(TASK_WRITE_FAILED)      # 权限不足，读取失败
    except FileNotFoundError:
        raise SafeWriteError(TASK_ROOT_UNSAFE)        # 竞态消失，无法安全归类
    except OSError as exc:
        if getattr(exc, "errno", None) == errno.ELOOP:
            raise SafeWriteError(TASK_ROOT_UNSAFE)    # 仍为 symlink
        raise SafeWriteError(TASK_WRITE_FAILED)       # 其他 IO（如 EIO）→ 读取失败
    except ValueError:
        raise SafeWriteError(TASK_ROOT_UNSAFE)        # 参数异常，无法安全归类

    mode = st.st_mode
    if stat.S_ISLNK(mode):  # 已经是 symlink（follow_symlinks=False 下 S_ISLNK 为真）
        raise SafeWriteError(TASK_ROOT_UNSAFE)
    if (
        stat.S_ISDIR(mode)
        or stat.S_ISFIFO(mode)
        or stat.S_ISCHR(mode)
        or stat.S_ISBLK(mode)
        or stat.S_ISSOCK(mode)
    ):
        raise SafeWriteError(TASK_ROOT_UNSAFE)
    if not stat.S_ISREG(mode):
        raise SafeWriteError(TASK_ROOT_UNSAFE)

    # 仅常规文件：O_NOFOLLOW 打开（拒绝任何 reparse 跟随）
    try:
        fd = os.open(fname, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except PermissionError:
        raise SafeWriteError(TASK_WRITE_FAILED)      # 权限不足，读取失败
    except FileNotFoundError:
        raise SafeWriteError(TASK_ROOT_UNSAFE)        # 竞态消失，无法安全归类
    except OSError as exc:
        if getattr(exc, "errno", None) == errno.ELOOP:
            raise SafeWriteError(TASK_ROOT_UNSAFE)    # 仍为 symlink
        raise SafeWriteError(TASK_WRITE_FAILED)       # 其他 IO（如 EIO）→ 读取失败

    try:
        try:
            st2 = os.fstat(fd)
        except OSError:
            # fstat 失败：读取失败，稳定 task-write-failed，绝不泄露原始 OSError
            raise SafeWriteError(TASK_WRITE_FAILED)
        if not stat.S_ISREG(st2.st_mode):
            # 打开前后类型不一致
            raise SafeWriteError(TASK_ROOT_UNSAFE)
        data = b""
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            data += chunk
    except OSError:
        raise SafeWriteError(TASK_WRITE_FAILED)       # 读取失败
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        existing = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        # 读取/解码失败
        raise SafeWriteError(TASK_WRITE_FAILED)
    if isinstance(existing, dict) and existing.get("content_hash") == payload.get("content_hash"):
        return "unchanged"
    raise SafeWriteError(TASK_CONFLICT)


# --------------------------------------------------------------------------- #
# §4 写入 + fsync + 失败清理（身份保护）
# --------------------------------------------------------------------------- #

def _write_all(fd: int, data: bytes) -> None:
    """循环写直到写完所有字节；任何失败抛 OSError（由调用方映射稳定码）。"""
    total = len(data)
    offset = 0
    while offset < total:
        n = os.write(fd, data[offset:])
        if n == 0:
            raise OSError("write progressed 0 bytes")
        offset += n


def _cleanup_failed_file(
    parent_fd: int, fname: str, created_dev, created_ino
) -> None:
    """§4：写入失败后清理。仅当满足部署前提且身份相同时才 unlink。

    - 无唯一写入者前提（`P3_TASK_ROOT_SINGLE_WRITER!=1`）：禁止按名 unlink，
      返回 `False`（清理未执行，上层失败关闭、不承诺零残留）。
    - 有前提：清理前以相对 parent_fd + follow_symlinks=False 复核目标仍为同一 inode；
      仅身份完全相同才 `os.unlink(name, dir_fd=parent_fd)`，随后 `os.fsync(parent_fd)`。
      目标缺失/替换/变成 symlink·目录·设备/无法复核 → 不删除，返回 `False`。
    - 返回 `True` 表示清理及其目录 fsync 全成功；`False` 表示未清理或清理失败。
    """
    if not _SINGLE_WRITER:
        # 部署无法保证服务是唯一写入者：禁止按名 unlink，避免删除被替换对象
        return False
    if created_dev is None or created_ino is None:
        # 无已保存身份（创建前/打开失败）：不做 inode 复核，保守不删除
        return False
    # 身份复核：相对已验证 parent_fd、不跟随
    try:
        st = os.stat(fname, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        # 目标缺失 / 无法复核 → 不删除
        return False
    if (st.st_dev, st.st_ino) != (created_dev, created_ino):
        # 目标被替换 / 类型变化 → 不删除
        return False
    if not stat.S_ISREG(st.st_mode):
        # 变成 symlink/目录/设备 → 不删除
        return False
    try:
        os.unlink(fname, dir_fd=parent_fd)
    except OSError:
        return False
    try:
        os.fsync(parent_fd)
    except OSError:
        return False
    return True


def _write_and_fsync(fd: int, parent_fd: int, fname: str, data: bytes) -> None:
    """§4：写全部字节 → 文件 fsync → close → 父目录 fsync 才返回。

    文件 fd 只尝试 close 一次（close 失败也绝不重复 close 同一 fd）。任一写入 / 文件
    fsync / close / 父目录 fsync 失败 → 进入失败清理（身份复核后 unlink + 父目录
    fsync），映射 `task-write-failed`。
    """
    created_dev = created_ino = None
    try:
        # 创建成功后立即取身份（fd 已指向新建文件）；即便后续写入/fsync 失败，
        # 也能据此做 inode 复核后安全 unlink，而非保守放弃清理。
        cst = os.fstat(fd)
        created_dev, created_ino = cst.st_dev, cst.st_ino
        _write_all(fd, data)
        os.fsync(fd)
    except OSError:
        # 写入 / 文件 fsync 失败：fd 尚未关闭 → 恰好关闭一次后清理
        try:
            os.close(fd)
        except OSError:
            pass
        _cleanup_failed_file(parent_fd, fname, created_dev, created_ino)
        raise SafeWriteError(TASK_WRITE_FAILED)
    # 写入与文件 fsync 成功：关闭 fd（仅一次）；关闭失败同样进入清理
    try:
        os.close(fd)
    except OSError:
        _cleanup_failed_file(parent_fd, fname, created_dev, created_ino)
        raise SafeWriteError(TASK_WRITE_FAILED)
    # 父目录 fsync 失败 → 创建未持久化，清理
    try:
        os.fsync(parent_fd)
    except OSError:
        _cleanup_failed_file(parent_fd, fname, created_dev, created_ino)
        raise SafeWriteError(TASK_WRITE_FAILED)


# --------------------------------------------------------------------------- #
# 公开：受控 no-replace 发布（POSIX 分支）
# --------------------------------------------------------------------------- #

def publish_task_file(task_root: str, task_id: str, payload: dict) -> str:
    """§1–§4：受控 no-replace 发布 <task_id>.json（POSIX）。

    返回 "created" 或 "unchanged"；冲突 / 写失败 / 根不安全抛 `SafeWriteError`
    （稳定码）。最终文件名仅由 task_id 派生；绝不接受外部路径。
    """
    if not TASK_ID_RE.match(task_id):
        raise SafeWriteError(TASK_INVALID_ID)
    # 序列化在创建之前完成：序列化失败不创建任何文件（无半成品、无残留）
    try:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    except (TypeError, ValueError):
        raise SafeWriteError(TASK_WRITE_FAILED)
    # 能力缺失：稳定失败关闭，绝不回退字符串路径
    if not _posix_supported():
        raise SafeWriteError(TASK_ROOT_UNSAFE)
    fds: list = []  # _open_root 失败时已自行关闭已开 fd；预置空，避免 finally 引用未绑定变量
    fds = _open_root(task_root)
    try:
        parent_fd = fds[-1]
        fname = task_id + ".json"
        try:
            fd = os.open(
                fname,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
        except FileExistsError:
            # §3 EEXIST 安全分类（始终用已验证 parent_fd）
            return _handle_existing(parent_fd, fname, payload)
        except OSError as exc:
            # ELOOP（最终组件为 symlink）或其他打开失败
            if getattr(exc, "errno", None) == errno.ELOOP:
                raise SafeWriteError(TASK_ROOT_UNSAFE)
            raise SafeWriteError(TASK_ROOT_UNSAFE)
        # 创建成功后写入 + fsync（§4）
        _write_and_fsync(fd, parent_fd, fname, data)
        return "created"
    finally:
        # 所有父 fd（含根 fd）保持到此处才逆序关闭
        for fd in reversed(fds):
            try:
                os.close(fd)
            except OSError:
                pass
