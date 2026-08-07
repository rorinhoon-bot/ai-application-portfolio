r"""D-2 POSIX 发布核心算法级单测（Windows 可跑，非真实链接验证）。

重要：本文件所有 `TestPosix*` 用例均通过 `unittest.mock` 模拟 syscall-adapter
（`os.open` / `os.fstat` / `os.stat` / `os.fsync` / `os.unlink` / `os.write` /
`os.read` / `os.close`），验证调用顺序、错误映射、fsync/清理分支。**它们不是真实
链接安全验证**——真实 POSIX symlink / junction / TOCTOU 必须在 Linux / WSL 执行
（见 `docs/D-2-design.md` blocked-until-approved）。

真实链接专项 `TestPosixLinkFixtures`（D2-L1…D2-L4）默认 skip，仅当环境变量
`P3_ALLOW_POSIX_PUBLISH_LINK_FIXTURES=1` 且运行于 Linux / WSL 时启用；Windows 上永远
跳过，绝不创建或运行真实 symlink / junction。

路径约定：统一用单组件根 `/tasks`（walk = 根 fd + 1 个目录组件 = 2 次 open +
2 次 fstat）。最终文件 open 为第 3 次；EEXIST 重开为第 4 次。
"""

from __future__ import annotations

import errno
import os
import stat
import unittest
from unittest import mock

from mcp_notes import safe_task_write_posix as px
from mcp_notes.safe_task_write import (
    SafeWriteError,
    TASK_ROOT_UNSAFE,
    TASK_INVALID_ID,
    TASK_CONFLICT,
    TASK_WRITE_FAILED,
)


def _s(mode: int, dev: int = 1, ino: int = 1):
    """构造一个最小 stat 结果对象（提供 st_mode / st_dev / st_ino）。"""
    obj = mock.MagicMock()
    obj.st_mode = mode
    obj.st_dev = dev
    obj.st_ino = ino
    return obj


def _make_fake_os() -> mock.MagicMock:
    """构造 fake os 适配器：提供 O_* 常量与可调 syscall mock。"""
    fake = mock.MagicMock()
    fake.O_RDONLY = 0
    fake.O_WRONLY = 1
    fake.O_CREAT = 64
    fake.O_EXCL = 128
    fake.O_DIRECTORY = 1 << 16
    fake.O_NOFOLLOW = 0o100000
    fake.O_BINARY = 0
    fake.supports_dir_fd = True
    # 默认：open 返回假 fd；write 一次写完
    fake.open.return_value = 10
    fake.write.side_effect = lambda fd, b: len(b)
    fake.read.side_effect = [b"{}", b""]
    fake.fstat.return_value = _s(stat.S_IFREG)
    fake.stat.return_value = _s(stat.S_IFREG)
    fake.fsync.return_value = None
    fake.unlink.return_value = None
    fake.close.return_value = None
    return fake


class TestPosixCapabilityAndPath(unittest.TestCase):
    """§1 / §2：能力缺失与路径拆分（算法级）。"""

    def test_capability_missing_maps_root_unsafe(self):
        # dir_fd / O_NOFOLLOW / O_DIRECTORY 缺失 → 稳定 task-root-unsafe，不调用 os.open
        with mock.patch.object(px, "_posix_supported", return_value=False):
            fake = _make_fake_os()
            with mock.patch.object(px, "os", fake):
                with self.assertRaises(SafeWriteError) as cm:
                    px.publish_task_file("/tasks", "id01", {"content_hash": "h"})
        self.assertEqual(cm.exception.code, TASK_ROOT_UNSAFE)
        fake.open.assert_not_called()

    def test_relative_root_rejected(self):
        with mock.patch.object(px, "_posix_supported", return_value=True):
            with self.assertRaises(SafeWriteError) as cm:
                px.publish_task_file("tasks", "id01", {"content_hash": "h"})
        self.assertEqual(cm.exception.code, TASK_ROOT_UNSAFE)

    def test_double_slash_rejected(self):
        with mock.patch.object(px, "_posix_supported", return_value=True):
            with self.assertRaises(SafeWriteError) as cm:
                px.publish_task_file("//tasks", "id01", {"content_hash": "h"})
        self.assertEqual(cm.exception.code, TASK_ROOT_UNSAFE)

    def test_dot_or_dotdot_rejected(self):
        with mock.patch.object(px, "_posix_supported", return_value=True):
            with self.assertRaises(SafeWriteError) as cm:
                px.publish_task_file("/a/../tasks", "id01", {"content_hash": "h"})
        self.assertEqual(cm.exception.code, TASK_ROOT_UNSAFE)

    def test_root_itself_rejected(self):
        with mock.patch.object(px, "_posix_supported", return_value=True):
            with self.assertRaises(SafeWriteError) as cm:
                px.publish_task_file("/", "id01", {"content_hash": "h"})
        self.assertEqual(cm.exception.code, TASK_ROOT_UNSAFE)

    def test_invalid_task_id_rejected(self):
        with mock.patch.object(px, "_posix_supported", return_value=True):
            with self.assertRaises(SafeWriteError) as cm:
                px.publish_task_file("/tasks", "../escape", {"content_hash": "h"})
        self.assertEqual(cm.exception.code, TASK_INVALID_ID)


class TestPosixRootWalk(unittest.TestCase):
    """§1：从 / 起逐级 openat + fstat，任何 reparse / 非目录失败关闭。"""

    def test_non_directory_component_fails_closed(self):
        fake = _make_fake_os()
        # / 打开成功（fd 1），tasks 组件打开成功（fd 2）但 fstat 非目录
        fake.open.side_effect = [1, 2]
        # walk 仅 fstat tasks 组件（1 次）；tasks 非目录 → walk 失败关闭
        fake.fstat.side_effect = [_s(stat.S_IFREG), _s(stat.S_IFDIR)]
        with mock.patch.object(px, "_posix_supported", return_value=True), \
                mock.patch.object(px, "os", fake):
            with self.assertRaises(SafeWriteError) as cm:
                px.publish_task_file("/tasks", "id01", {"content_hash": "h"})
        self.assertEqual(cm.exception.code, TASK_ROOT_UNSAFE)
        # 所有已开 fd 应被关闭（/ 与 tasks）
        self.assertEqual(fake.close.call_count, 2)


class TestPosixEexistClassification(unittest.TestCase):
    """§3：EEXIST 后安全分类（始终用已验证 parent_fd）。"""

    def _walk_ok(self, fake):
        # / 与 tasks 目录 fd 打开成功且为目录；最终文件 open 命中 EEXIST 需再补第 3 值
        fake.open.side_effect = [1, 2, FileExistsError()]
        fake.fstat.side_effect = [_s(stat.S_IFDIR), _s(stat.S_IFDIR)]
        fake.stat.return_value = _s(stat.S_IFREG)

    def test_existing_symlink_is_root_unsafe(self):
        fake = _make_fake_os()
        self._walk_ok(fake)
        fake.stat.return_value = _s(stat.S_IFLNK)  # 预筛 stat 返回 symlink
        with mock.patch.object(px, "_posix_supported", return_value=True), \
                mock.patch.object(px, "os", fake):
            with self.assertRaises(SafeWriteError) as cm:
                px.publish_task_file("/tasks", "id01", {"content_hash": "h"})
        self.assertEqual(cm.exception.code, TASK_ROOT_UNSAFE)

    def test_existing_directory_is_root_unsafe(self):
        fake = _make_fake_os()
        self._walk_ok(fake)
        fake.stat.return_value = _s(stat.S_IFDIR)  # 预筛 stat 返回目录
        with mock.patch.object(px, "_posix_supported", return_value=True), \
                mock.patch.object(px, "os", fake):
            with self.assertRaises(SafeWriteError) as cm:
                px.publish_task_file("/tasks", "id01", {"content_hash": "h"})
        self.assertEqual(cm.exception.code, TASK_ROOT_UNSAFE)

    def test_existing_regular_same_hash_unchanged(self):
        fake = _make_fake_os()
        # walk：/、tasks（1 次 fstat=S_IFDIR）；文件 EEXIST；重开常规文件 fd 3（2 次 fstat=S_IFREG）
        fake.open.side_effect = [1, 2, FileExistsError(), 3]
        fake.fstat.side_effect = [
            _s(stat.S_IFDIR),
            _s(stat.S_IFREG),  # 重开文件 fstat
        ]
        fake.stat.return_value = _s(stat.S_IFREG)
        fake.read.side_effect = [b'{"content_hash": "h"}', b""]
        with mock.patch.object(px, "_posix_supported", return_value=True), \
                mock.patch.object(px, "os", fake):
            result = px.publish_task_file("/tasks", "id01", {"content_hash": "h"})
        self.assertEqual(result, "unchanged")

    def test_existing_regular_diff_hash_conflict(self):
        fake = _make_fake_os()
        fake.open.side_effect = [1, 2, FileExistsError(), 3]
        fake.fstat.side_effect = [
            _s(stat.S_IFDIR),
            _s(stat.S_IFREG),
        ]
        fake.stat.return_value = _s(stat.S_IFREG)
        fake.read.side_effect = [b'{"content_hash": "other"}', b""]
        with mock.patch.object(px, "_posix_supported", return_value=True), \
                mock.patch.object(px, "os", fake):
            with self.assertRaises(SafeWriteError) as cm:
                px.publish_task_file("/tasks", "id01", {"content_hash": "h"})
        self.assertEqual(cm.exception.code, TASK_CONFLICT)

    def test_existing_regular_decode_failure_is_write_failed(self):
        fake = _make_fake_os()
        fake.open.side_effect = [1, 2, FileExistsError(), 3]
        fake.fstat.side_effect = [
            _s(stat.S_IFDIR),
            _s(stat.S_IFREG),
        ]
        fake.stat.return_value = _s(stat.S_IFREG)
        fake.read.side_effect = [b"{not valid json", b""]
        with mock.patch.object(px, "_posix_supported", return_value=True), \
                mock.patch.object(px, "os", fake):
            with self.assertRaises(SafeWriteError) as cm:
                px.publish_task_file("/tasks", "id01", {"content_hash": "h"})
        self.assertEqual(cm.exception.code, TASK_WRITE_FAILED)


class TestPosixCreateAndCleanup(unittest.TestCase):
    """§4：创建成功路径与失败清理合同（含单写入者前提）。"""

    def _walk_ok(self, fake):
        fake.open.side_effect = [1, 2]  # / 与 tasks
        fake.fstat.side_effect = [_s(stat.S_IFDIR), _s(stat.S_IFDIR)]

    def test_create_success_returns_created(self):
        fake = _make_fake_os()
        self._walk_ok(fake)
        # walk：/ 与 tasks 目录 fd（1、2）；最终文件 open 成功返回 fd 3
        fake.open.side_effect = [1, 2, 3]
        # walk 2 次 fstat 为目录 + 最终文件 fstat 为常规文件（携带 dev/ino 供身份复核）
        fake.fstat.side_effect = [
            _s(stat.S_IFDIR),
            _s(stat.S_IFREG, dev=1, ino=7),
        ]
        with mock.patch.object(px, "_posix_supported", return_value=True), \
                mock.patch.object(px, "os", fake):
            result = px.publish_task_file("/tasks", "id01", {"content_hash": "h"})
        self.assertEqual(result, "created")
        # 写入 + 文件 fsync + close + 父目录 fsync 均被调用
        fake.write.assert_called()
        fake.fsync.assert_any_call(3)        # 文件 fsync
        fake.fsync.assert_any_call(2)        # 父目录 fsync
        # 所有 fd（/、tasks、最终文件）已关闭
        self.assertGreaterEqual(fake.close.call_count, 3)

    def test_write_failure_triggers_cleanup_single_writer(self):
        fake = _make_fake_os()
        self._walk_ok(fake)
        fake.open.side_effect = [1, 2, 3]
        fake.fstat.side_effect = [
            _s(stat.S_IFDIR),
            _s(stat.S_IFREG, dev=1, ino=7),
        ]
        fake.stat.return_value = _s(stat.S_IFREG, dev=1, ino=7)  # 身份复核通过
        fake.write.side_effect = OSError("write failed")
        # 单写入者前提满足（默认）：清理应调用 unlink + 父目录 fsync
        with mock.patch.object(px, "_posix_supported", return_value=True), \
                mock.patch.object(px, "os", fake), \
                mock.patch.object(px, "_SINGLE_WRITER", True):
            with self.assertRaises(SafeWriteError) as cm:
                px.publish_task_file("/tasks", "id01", {"content_hash": "h"})
        self.assertEqual(cm.exception.code, TASK_WRITE_FAILED)
        fake.unlink.assert_called_once()

    def test_write_failure_no_unlink_without_single_writer(self):
        fake = _make_fake_os()
        self._walk_ok(fake)
        fake.open.side_effect = [1, 2, 3]
        fake.fstat.side_effect = [
            _s(stat.S_IFDIR),
            _s(stat.S_IFREG, dev=1, ino=7),
        ]
        fake.write.side_effect = OSError("write failed")
        # 无唯一写入者前提：禁止按名 unlink（防止删除被替换对象）
        with mock.patch.object(px, "_posix_supported", return_value=True), \
                mock.patch.object(px, "os", fake), \
                mock.patch.object(px, "_SINGLE_WRITER", False):
            with self.assertRaises(SafeWriteError) as cm:
                px.publish_task_file("/tasks", "id01", {"content_hash": "h"})
        self.assertEqual(cm.exception.code, TASK_WRITE_FAILED)
        fake.unlink.assert_not_called()


# --------------------------------------------------------------------------- #
# 真实链接专项：D2-L1…D2-L4。默认 skip；仅 Linux/WSL + P3_ALLOW_POSIX_PUBLISH_LINK_FIXTURES=1
# 时启用。绝不创建/运行真实 symlink / junction。Windows 上永远跳过。
# --------------------------------------------------------------------------- #

_ALLOW_LINK_FIXTURES = os.environ.get("P3_ALLOW_POSIX_PUBLISH_LINK_FIXTURES") == "1"
_IS_POSIX = os.name == "posix"


@unittest.skipUnless(
    _ALLOW_LINK_FIXTURES and _IS_POSIX,
    "real POSIX link fixtures require Linux/WSL + P3_ALLOW_POSIX_PUBLISH_LINK_FIXTURES=1",
)
class TestPosixLinkFixtures(unittest.TestCase):
    """D2-L1…D2-L4：真实 Linux/WSL POSIX 链接专项（当前 skip）。

    仅记录意图与命令骨架，不执行。链接目标只放在同一 TemporaryDirectory 内、task_root
    外的虚构 sentinel，绝不指向用户或系统路径。详见 docs/D-2-design.md §4/§5。
    """

    def test_D2_L1_final_file_symlink_escape(self):
        # 最终文件为 symlink → task-root-unsafe，绝不跟随/写入/读取 sentinel
        raise unittest.SkipTest("placeholder: real link fixture, run on Linux/WSL only")

    def test_D2_L2_ancestor_dir_symlink_escape(self):
        # task_root="$base/task_root/sub"；先建真实空 sub，再 rmdir 并替换为指向
        # $base/sentinel_dir 的 symlink → task-root-unsafe
        raise unittest.SkipTest("placeholder: real link fixture, run on Linux/WSL only")

    def test_D2_L3_ancestor_replaced_after_verify(self):
        # 确定性同步钩子（禁 sleep）：祖先替换后若实现仅用旧 parent fd 在旧 inode 创建，
        # 不等于逃逸；sentinel 未被读写、未跟随新 symlink；若实现额外名称—inode 复核检测
        # 替换，可返回 task-root-unsafe（非唯一必然结果）
        raise unittest.SkipTest("placeholder: real link fixture, run on Linux/WSL only")

    def test_D2_L4_existing_target_no_overwrite(self):
        # 预建冲突常规文件（独占创建）；发布前后原始字节完全一致；绝不覆盖
        raise unittest.SkipTest("placeholder: real link fixture, run on Linux/WSL only")


if __name__ == "__main__":
    unittest.main()
