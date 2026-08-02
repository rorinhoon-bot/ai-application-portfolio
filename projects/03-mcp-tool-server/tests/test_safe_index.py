"""P3 Slice B1 路径安全索引测试（stdlib unittest，继承默认网络阻断底座）。

覆盖（v6 合同 + Codex P0/P1 修订）：
- T0：真实机器原生 ABI 冒烟（R0/T0）+ 正常布局硬边界（构建 / 读取 / 字段一致）。
- T1：索引成功——条目字段（note_id / title / size / sha256）正确且确定性。
- T2：空子目录被忽略；非 .md 文件不登记。
- T3：句柄链读取——从根 HANDLE 沿多级相对组件读取字节正确。
- T4：reparse 分支——_nt_open 遇 reparse 抛 NotAllowedReparse；_walk 遇 reparse
      条目直接抛 NotAllowedReparse；**reparse 导致 build_index 整体失败**
      （IndexBuildFailed），不 continue 跳过、不发布部分索引（monkeypatch，
      绝不创建真实 symlink / junction）。
- T5：失败关闭 + 畸形缓冲 + 内容过大——枚举异常 → IndexBuildFailed；畸形缓冲 /
      Information==0 / info_end>buffer_length → IoError；内容过大（read 与
      **真实超大文件构建**）均导致失败（不跳过）。
- T6：静态断言——常量 / ctypes 偏移 / 枚举值 / 源码不含字符串路径遍历。
- T7（P0/P1 回归）：伪造 NoteIndexEntry 路径逃逸（../x.md、a/../x.md、x:stream、
      空段）一律被拒且无路径 / 用户名泄露。
- T8（P0/P1 回归）：_nt_open 文件属性判定——拒绝 DIRECTORY/DEVICE/REPARSE_POINT；
      查询失败 → IoError；EndOfFile > MAX → ContentTooLarge。
- T9（P0/P1 回归）：_validate_component 拒绝 `:` / 空段 / `.` / `..` / 尾随点空格 /
      保留设备名 / 控制字符；open_file_relative 拒绝空列表。

所有用例继承 NetworkBlockedTestCase，测试期间阻断网络（与 Slice A 一致）。
T7–T10（真实 symlink/junction 夹具）位于 test_safe_index_links.py，默认跳过；即使设置 `P3_ALLOW_FS_LINK_FIXTURES=1` 也仅为未实现门控占位（真实链接夹具尚不可用，不创建/不运行真实链接），预期为拒绝/构建失败而非跳过。
"""

import ctypes
import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# 让测试可直接 `python -m unittest` 运行，无需 .venv 或安装
_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_SRC))
_TESTS = os.path.dirname(__file__)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from mcp_notes import contracts, index, safe_open  # noqa: E402
from mcp_notes.index import build_index, compute_note_id, read_note_content  # noqa: E402
from mcp_notes.contracts import NoteIndexEntry  # noqa: E402
from _network_block import NetworkBlockedTestCase  # noqa: E402


_NATIVE = safe_open._NATIVE_AVAILABLE


def _write(path: str, name: str, content: str) -> str:
    full = os.path.join(path, name)
    with open(full, "wb") as f:  # 二进制写入，避免 Windows 文本模式 \r\n 换行干扰原始字节比对
        f.write(content.encode("utf-8"))
    return full


class _TreeMixin:
    def _make_tree(self) -> str:
        root = tempfile.mkdtemp()
        _write(root, "a.md", "# A\n内容 alpha")
        _write(root, "b.MD", "# B\n内容 BETA")  # 大小写不敏感 .MD
        _write(root, "notes.txt", "ignore me")  # 非 .md 不登记
        sub = os.path.join(root, "sub")
        os.mkdir(sub)
        _write(sub, "c.md", "# C\n内容 gamma")
        empty = os.path.join(root, "empty")
        os.mkdir(empty)
        return root

    def _rmtree(self, root: str) -> None:
        shutil.rmtree(root, ignore_errors=True)

    def _open_root(self, root: str) -> int:
        name = safe_open.configure_root(root)
        return safe_open._nt_open(0, name, is_dir=True)


# --------------------------------------------------------------------------- #
# T0：原生冒烟 + 正常布局硬边界
# --------------------------------------------------------------------------- #

class TestT0NativeSmoke(_TreeMixin, NetworkBlockedTestCase):
    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_native_support_verified(self):
        # R0/T0：真实机器 ABI 冒烟（完整工作流）必须通过，否则整体 unsafe-open-unavailable
        self.assertTrue(safe_open.verify_native_support())

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_normal_layout_hard_boundary(self):
        root = self._make_tree()
        try:
            entries = build_index(root)
            rels = sorted(e.relative_path for e in entries)
            # 仅 .md 登记；b.MD 大小写不敏感计入；空目录与 .txt 忽略
            self.assertEqual(rels, ["a.md", "b.MD", "sub/c.md"])

            by_rel = {e.relative_path: e for e in entries}
            # 读取内容一致（句柄级，无字符串路径）
            self.assertEqual(read_note_content(by_rel["a.md"], root), "# A\n内容 alpha")
            self.assertEqual(read_note_content(by_rel["sub/c.md"], root), "# C\n内容 gamma")

            # size / sha256 与直接读取一致
            with open(os.path.join(root, "a.md"), "rb") as fh:
                data = fh.read()
            self.assertEqual(by_rel["a.md"].size, len(data))
            self.assertEqual(by_rel["a.md"].sha256, hashlib.sha256(data).hexdigest())
        finally:
            self._rmtree(root)


# --------------------------------------------------------------------------- #
# T1：索引成功——条目字段正确且确定性
# --------------------------------------------------------------------------- #

class TestT1IndexSuccess(_TreeMixin, NetworkBlockedTestCase):
    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_entry_fields_deterministic(self):
        root = self._make_tree()
        try:
            e1 = build_index(root)
            e2 = build_index(root)
            # 确定性：两次构建结果一致
            self.assertEqual(
                [(x.relative_path, x.note_id, x.size, x.sha256) for x in e1],
                [(x.relative_path, x.note_id, x.size, x.sha256) for x in e2],
            )
            by_rel = {e.relative_path: e for e in e1}
            # note_id 由 relative_path 派生（Slice A 行为保留）
            self.assertEqual(by_rel["a.md"].note_id, compute_note_id("a.md"))
            self.assertEqual(len(by_rel["a.md"].note_id), 16)
            # 标题取自一级标题（净化后）
            self.assertEqual(by_rel["a.md"].title, "A")
            self.assertEqual(by_rel["b.MD"].title, "B")
            self.assertEqual(by_rel["sub/c.md"].title, "C")
            # 全部为已登记普通文件
            for e in e1:
                self.assertTrue(e.registered)
        finally:
            self._rmtree(root)


# --------------------------------------------------------------------------- #
# T2：空子目录被忽略；非 .md 不登记
# --------------------------------------------------------------------------- #

class TestT2EmptySubdirAndNonMd(_TreeMixin, NetworkBlockedTestCase):
    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_empty_dir_and_non_md_ignored(self):
        root = self._make_tree()
        try:
            rels = sorted(e.relative_path for e in build_index(root))
            # 空目录 empty/ 与 notes.txt 不出现
            self.assertNotIn("notes.txt", rels)
            self.assertNotIn("empty", rels)
            self.assertNotIn("empty/anything", rels)
            self.assertEqual(len(rels), 3)
        finally:
            self._rmtree(root)


# --------------------------------------------------------------------------- #
# T3：句柄链读取（多级相对组件）
# --------------------------------------------------------------------------- #

class TestT3HandleChainRead(_TreeMixin, NetworkBlockedTestCase):
    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_open_file_relative_multi_level(self):
        root = self._make_tree()
        try:
            root_h = self._open_root(root)
            try:
                data = safe_open.open_file_relative(root_h, ["sub", "c.md"])
            finally:
                safe_open._close(root_h)
            self.assertEqual(data.decode("utf-8"), "# C\n内容 gamma")
        finally:
            self._rmtree(root)


# --------------------------------------------------------------------------- #
# T4：reparse 分支（monkeypatch，不建真实链接）
# --------------------------------------------------------------------------- #

class TestT4ReparseBranch(NetworkBlockedTestCase):
    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_nt_open_reparse_raises(self):
        # _nt_open 遇 STATUS_REPARSE_POINT_ENCOUNTERED 抛 NotAllowedReparse
        reparse_status = -1073740550  # 0xC00004FA 的有符号值（正确换算）
        fake = mock.Mock(return_value=reparse_status)
        with mock.patch.object(safe_open, "_nt_open_file_fn", fake):
            with self.assertRaises(safe_open.NotAllowedReparse):
                safe_open._nt_open(0, "\\??\\C:\\dummy", is_dir=True)
        # 稳定错误码不泄露路径
        err = safe_open.NotAllowedReparse()
        self.assertEqual(err.code, "not-allowed-reparse")

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_walk_raises_on_reparse(self):
        # _walk 遇 reparse 条目直接抛 NotAllowedReparse（不 continue 跳过、不继续构建）
        reparse_attr = safe_open.FILE_ATTRIBUTE_REPARSE_POINT
        fake_entries = [("link.md", reparse_attr, False)]
        with mock.patch.object(safe_open, "_enumerate", lambda h: list(fake_entries)):
            with self.assertRaises(safe_open.NotAllowedReparse):
                safe_open._walk(0, [], lambda p: None)

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_build_fails_on_reparse(self):
        # reparse 条目导致整个构建失败（IndexBuildFailed），不发布部分索引
        mixin = _TreeMixin()
        root = mixin._make_tree()
        try:
            reparse_attr = safe_open.FILE_ATTRIBUTE_REPARSE_POINT
            fake_entries = [
                ("link.md", reparse_attr, False),  # reparse：构建必须失败
                ("real.md", 0, False),             # 普通 .md：不应被登记
            ]
            with mock.patch.object(safe_open, "_enumerate", lambda h: list(fake_entries)):
                with self.assertRaises(safe_open.IndexBuildFailed):
                    build_index(root)
        finally:
            mixin._rmtree(root)


# --------------------------------------------------------------------------- #
# T5：失败关闭 + 畸形缓冲 + 内容过大
# --------------------------------------------------------------------------- #

class TestT5FailClosed(_TreeMixin, NetworkBlockedTestCase):
    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_enumerate_error_aborts_build(self):
        # 枚举抛 IoError（模拟 BUFFER_OVERFLOW / IO 错误）→ 整体 IndexBuildFailed
        def boom(_h):
            raise safe_open.IoError()

        root = self._make_tree()
        try:
            with mock.patch.object(safe_open, "_enumerate", boom):
                with self.assertRaises(safe_open.IndexBuildFailed):
                    build_index(root)
        finally:
            self._rmtree(root)

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_file_as_root_aborts_build(self):
        # 把文件当根目录传入 → 打开失败 → IndexBuildFailed（不发布部分索引）
        root = self._make_tree()
        try:
            file_path = os.path.join(root, "a.md")
            with self.assertRaises(safe_open.IndexBuildFailed):
                build_index(file_path)
        finally:
            self._rmtree(root)

    def test_info_end_zero_raises(self):
        # §4.4：STATUS_SUCCESS 但 Information==0 → IoError（不返回部分结果）
        import ctypes as _ctypes
        buf = _ctypes.create_string_buffer(64)
        results = []
        with self.assertRaises(safe_open.IoError):
            safe_open._parse_buffer(buf, 0, 64, results)

    def test_buffer_length_bound_raises(self):
        # 0 < info_end <= buffer_length 必须成立，否则 IoError
        import ctypes as _ctypes
        buf = _ctypes.create_string_buffer(64)
        results = []
        with self.assertRaises(safe_open.IoError):
            safe_open._parse_buffer(buf, 65, 64, results)  # info_end > buffer_length

    def test_malformed_buffer_raises(self):
        # §4.4 硬边界：NextEntryOffset 小于 _HEADER_LEN 且非 8 字节对齐 → IoError
        import ctypes as _ctypes
        data = bytearray(64)
        data[0:4] = (3).to_bytes(4, "little")  # NextEntryOffset = 3（< _HEADER_LEN 且非对齐）
        buf = _ctypes.create_string_buffer(bytes(data), 64)
        results = []
        with self.assertRaises(safe_open.IoError):
            safe_open._parse_buffer(buf, len(buf), len(buf), results)

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_content_too_large_read(self):
        root = tempfile.mkdtemp()
        try:
            _write(root, "small.md", "0123456789")  # 10 字节
            root_h = self._open_root(root)
            try:
                with self.assertRaises(safe_open.ContentTooLarge):
                    # max_bytes=5 < 10 → 拒绝
                    safe_open.read_file_bytes(root_h, "small.md", max_bytes=5)
            finally:
                safe_open._close(root_h)
        finally:
            self._rmtree(root)

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_build_rejects_oversized_file(self):
        # 真实 > MAX_NOTE_BYTES 文件使整个构建失败（事务语义，不跳过/不发布部分）
        root = tempfile.mkdtemp()
        try:
            big = b"x" * (contracts.MAX_NOTE_BYTES + 1)
            _write(root, "big.md", big.decode("latin-1"))
            with self.assertRaises(safe_open.IndexBuildFailed):
                build_index(root)
        finally:
            self._rmtree(root)


# --------------------------------------------------------------------------- #
# T6：静态断言（常量 / 偏移 / 枚举 / 源码约束）
# --------------------------------------------------------------------------- #

class TestT6StaticAssertions(NetworkBlockedTestCase):
    def test_constants(self):
        self.assertEqual(contracts.MAX_NOTE_BYTES, 1_048_576)
        self.assertEqual(contracts.WIN32_FILE_BASIC_INFO, 0)
        self.assertEqual(contracts.WIN32_FILE_STANDARD_INFO, 1)
        self.assertEqual(contracts.NATIVE_FILE_DIRECTORY_INFORMATION, 1)
        self.assertEqual(safe_open.OBJ_DONT_REPARSE, 0x00001000)
        self.assertEqual(safe_open.STATUS_REPARSE_POINT_ENCOUNTERED, 0xC00004FA)

    def test_ctypes_offset(self):
        # FILE_DIRECTORY_INFORMATION 固定头长度（不含 FileName[1] 占位）= 64 字节，
        # §4.4 必须用 FileName.offset 而不是 sizeof。
        self.assertEqual(safe_open.FILE_DIRECTORY_INFORMATION.FileName.offset, 64)
        # FILE_STANDARD_INFO.EndOfFile 位于偏移 8（AllocationSize 之后）
        self.assertEqual(safe_open.FILE_STANDARD_INFO.EndOfFile.offset, 8)
        # IO_STATUS_BLOCK：Status 为 32 位 NTSTATUS（c_long），Information 为
        # 指针宽度（c_size_t，不写死 c_ulonglong）。以 _fields_ 类型断言。
        fields = dict(safe_open.IO_STATUS_BLOCK._fields_)
        self.assertIs(fields["Status"], ctypes.c_long)
        self.assertIs(fields["Information"], ctypes.c_size_t)

    def test_source_forbids_string_path_traversal(self):
        # v6 硬约束：安全层不得“调用”任何字符串路径遍历 API。
        # 用调用/导入形态匹配（避免与 docstring 中“禁止项说明”文本冲突）。
        path = os.path.join(os.path.dirname(__file__), "..", "src", "mcp_notes", "safe_open.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        forbidden_patterns = [
            "os.scandir(", "os.walk(", "glob.glob(", "import glob",
            ".rglob(", "realpath(", "os.path.realpath(",
        ]
        for pat in forbidden_patterns:
            self.assertNotIn(pat, src, f"safe_open.py 不得调用 {pat}")
        # 必须使用句柄级枚举与原生拒绝标志
        self.assertIn("NtQueryDirectoryFile", src)
        self.assertIn("OBJ_DONT_REPARSE", src)


# --------------------------------------------------------------------------- #
# T7（P0/P1 回归）：伪造 NoteIndexEntry 路径逃逸
# --------------------------------------------------------------------------- #

class TestT7PathEscapeRegression(_TreeMixin, NetworkBlockedTestCase):
    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def _assert_escape(self, relative_path, root):
        entry = NoteIndexEntry(
            note_id="deadbeefdeadbeef",
            title="evil",
            relative_path=relative_path,
            size=0,
            sha256="0" * 64,
        )
        with self.assertRaises(safe_open.PathEscape) as ctx:
            read_note_content(entry, root)
        # 错误不得泄露路径 / 用户名 / 环境变量
        msg = str(ctx.exception)
        self.assertNotIn(root, msg)
        self.assertNotIn("C:\\Users", msg)
        self.assertNotIn("Username", msg)
        self.assertNotIn("USERNAME", msg)
        self.assertEqual(ctx.exception.code, "path-escape")

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_dotdot_escape(self):
        root = self._make_tree()
        try:
            self._assert_escape("../x.md", root)
        finally:
            self._rmtree(root)

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_dotdot_mid(self):
        root = self._make_tree()
        try:
            self._assert_escape("a/../x.md", root)
        finally:
            self._rmtree(root)

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_stream_colon(self):
        root = self._make_tree()
        try:
            self._assert_escape("x:stream", root)
        finally:
            self._rmtree(root)

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_empty_segment(self):
        root = self._make_tree()
        try:
            self._assert_escape("a//x.md", root)  # 中间空段
            self._assert_escape("", root)         # 空字符串
        finally:
            self._rmtree(root)


# --------------------------------------------------------------------------- #
# T8（P0/P1 回归）：_nt_open 文件属性判定与容量上限
# --------------------------------------------------------------------------- #

class TestT8NtOpenFileChecks(_TreeMixin, NetworkBlockedTestCase):
    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def _nt_open_with_fake_query(self, root, fake_query):
        root_h = self._open_root(root)
        try:
            with mock.patch.object(safe_open, "_query_file_info", fake_query):
                return safe_open._nt_open(root_h, "a.md", is_dir=False)
        finally:
            safe_open._close(root_h)

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_rejects_directory(self):
        def fake_query(handle, class_id, info_struct):
            if class_id == safe_open.WIN32_FILE_BASIC_INFO:
                info_struct.FileAttributes = safe_open.FILE_ATTRIBUTE_DIRECTORY
            return True

        root = self._make_tree()
        try:
            with self.assertRaises(safe_open.NotARegularFile):
                self._nt_open_with_fake_query(root, fake_query)
        finally:
            self._rmtree(root)

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_rejects_device(self):
        def fake_query(handle, class_id, info_struct):
            if class_id == safe_open.WIN32_FILE_BASIC_INFO:
                info_struct.FileAttributes = safe_open.FILE_ATTRIBUTE_DEVICE
            return True

        root = self._make_tree()
        try:
            with self.assertRaises(safe_open.NotARegularFile):
                self._nt_open_with_fake_query(root, fake_query)
        finally:
            self._rmtree(root)

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_rejects_reparse_attr(self):
        def fake_query(handle, class_id, info_struct):
            if class_id == safe_open.WIN32_FILE_BASIC_INFO:
                info_struct.FileAttributes = safe_open.FILE_ATTRIBUTE_REPARSE_POINT
            return True

        root = self._make_tree()
        try:
            with self.assertRaises(safe_open.NotAllowedReparse):
                self._nt_open_with_fake_query(root, fake_query)
        finally:
            self._rmtree(root)

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_query_failure_is_io_error(self):
        def fake_query(handle, class_id, info_struct):
            return False  # 查询失败

        root = self._make_tree()
        try:
            with self.assertRaises(safe_open.IoError):
                self._nt_open_with_fake_query(root, fake_query)
        finally:
            self._rmtree(root)

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_rejects_oversized(self):
        def fake_query(handle, class_id, info_struct):
            if class_id == safe_open.WIN32_FILE_BASIC_INFO:
                info_struct.FileAttributes = 0  # 普通文件
            elif class_id == safe_open.WIN32_FILE_STANDARD_INFO:
                info_struct.EndOfFile = contracts.MAX_NOTE_BYTES + 1
            return True

        root = self._make_tree()
        try:
            with self.assertRaises(safe_open.ContentTooLarge):
                self._nt_open_with_fake_query(root, fake_query)
        finally:
            self._rmtree(root)


# --------------------------------------------------------------------------- #
# T9（P0/P1 回归）：组件级校验与 open_file_relative 校验
# --------------------------------------------------------------------------- #

class TestT9ComponentValidation(NetworkBlockedTestCase):
    def test_rejects_forbidden(self):
        for bad in ["", ".", "..", "a\\b", "a/b", "a:b", 'a<b', 'a>b',
                    'a"b', "a|b", "a?b", "a*b", "trailing. ", "trailing ",
                    "con", "CON", "prn", "aux", "NUL", "com1", "lpt9",
                    "a\x00b", "a\x1fb"]:
            with self.assertRaises(safe_open.PathEscape):
                safe_open._validate_component(bad)
        # 合法组件应通过
        for ok in ["a.md", "sub", "b.MD", "name with space", "中文", "a..b"]:
            safe_open._validate_component(ok)  # 不抛

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_open_file_relative_rejects_empty_list(self):
        mixin = _TreeMixin()
        root = mixin._make_tree()
        try:
            root_h = mixin._open_root(root)
            try:
                with self.assertRaises(safe_open.PathEscape):
                    safe_open.open_file_relative(root_h, [])
            finally:
                safe_open._close(root_h)
        finally:
            mixin._rmtree(root)

    @unittest.skipUnless(_NATIVE, "native APIs unavailable on this platform")
    def test_nt_open_rejects_oversized_name(self):
        # UNICODE_STRING.Length/MaximumLength 按真实 UTF-16LE 字节数判定 USHORT 上限：
        # - 字节数 65536（> 上限）→ PathEscape（不调用原生 API）
        # - 字节数恰为 65534 → MaximumLength=65536 在 c_ushort 回绕为 0（P0 回归）；
        #   必须在赋值前抛 PathEscape，绝不调用原生 API
        # - 非 BMP 字符（如 😀 = 4 字节代理对）按 UTF-16LE 字节数计数，而非 code point 数
        def expect_path_escape_before_native(name: str) -> None:
            sentinel = mock.Mock(side_effect=RuntimeError("native-should-not-be-called"))
            with mock.patch.object(safe_open, "_nt_open_file_fn", sentinel):
                with self.assertRaises(safe_open.PathEscape):
                    safe_open._nt_open(0, name, is_dir=True)
            # 证明原生 API（NtOpenFile）根本未被调用
            sentinel.assert_not_called()

        # 65536 字节（全 BMP）：超过 Length 上限
        expect_path_escape_before_native("a" * 32768)

        # 65534 字节（全 BMP）：MaximumLength 溢出边界回归（修复前静默截断为 0）
        name_65534 = "a" * 32767
        self.assertEqual(len(name_65534.encode("utf-16-le")), 65534)
        expect_path_escape_before_native(name_65534)

        # 非 BMP 混合：32765 个 BMP + 1 个 emoji（4 字节）= 65534 字节；
        # 必须以 UTF-16LE 字节长度（非 code point 数）触发上限判定
        name_nonbmp = "a" * 32765 + "\U0001F600"
        self.assertEqual(len(name_nonbmp.encode("utf-16-le")), 65534)
        self.assertNotEqual(len(name_nonbmp), len(name_nonbmp.encode("utf-16-le")) // 2)
        expect_path_escape_before_native(name_nonbmp)


if __name__ == "__main__":
    unittest.main()
