"""P3 Slice B1 链接（symlink / junction / reparse）专项测试——默认全部跳过。

按授权范围，本文件**绝不创建或运行**真实 symlink / junction / reparse point。
T7–T10 仅在显式设置环境变量 `P3_ALLOW_FS_LINK_FIXTURES=1` 时才**解除 skip 装饰**，
但它们目前只是**未实现的门控占位**（`NotImplementedError`）：即使设置了该环境变量，
真实链接夹具（real symlink / junction）仍**尚未具备**，本文件不创建、不运行任何
真实链接。待真实链接环境就绪并实现后，这些用例的预期统一为：

- 任何 `FILE_ATTRIBUTE_REPARSE_POINT`（symlink / junction / reparse point）条目
  **必须拒绝并令整个构建失败**（`NotAllowedReparse` → `build_index` 抛
  `IndexBuildFailed`），**绝不** `continue` 跳过、绝不登记、绝不发布部分索引。
- T7：根目录下存在 junction 子目录时，build_index 整体失败（reparse 拒绝），不进入/不登记。
- T8：笔记根本身为 symlink 指向真实目录时，configure_root / _nt_open 拒绝（reparse）。
- T9：.md 文件为 symlink（reparse）时，_walk 抛 NotAllowedReparse → build_index 失败
      （**不是**跳过该条目）。
- T10：junction 目标被替换（TOCTOU 形态）后，句柄级打开不会跟随到新目标（reparse 拒绝）。
"""

import os
import sys
import unittest

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_SRC))
_TESTS = os.path.dirname(__file__)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from _network_block import NetworkBlockedTestCase  # noqa: E402

# 即使设置为 1，也仅解除 skip 装饰；真实链接夹具仍不可用（占位 NotImplementedError）。
_LINKS_ENABLED = os.environ.get("P3_ALLOW_FS_LINK_FIXTURES") == "1"


@unittest.skipUnless(_LINKS_ENABLED, "link fixtures disabled: set P3_ALLOW_FS_LINK_FIXTURES=1 to un-skip (still unimplemented)")
class TestLinkFixtures(NetworkBlockedTestCase):
    def test_t7_junction_subdir_rejected_build_fails(self):
        # 占位：未实现。预期 junction 子目录 → reparse 拒绝 → build_index 整体失败。
        raise NotImplementedError("requires real junction fixture; expected: reparse rejected, build fails")

    def test_t8_symlink_root_rejected(self):
        # 占位：未实现。预期根本身为 symlink → configure_root / _nt_open 拒绝。
        raise NotImplementedError("requires real symlink fixture; expected: reparse rejected")

    def test_t9_symlink_md_rejected_build_fails(self):
        # 占位：未实现。预期 .md 为 symlink（reparse）→ _walk 抛 NotAllowedReparse
        # → build_index 整体失败（不是跳过该条目）。
        raise NotImplementedError("requires real symlink fixture; expected: reparse rejected, build fails (not skipped)")

    def test_t10_junction_target_swap_rejected(self):
        # 占位：未实现。预期 junction 目标替换（TOCTOU）→ 句柄级打开拒绝（不跟随新目标）。
        raise NotImplementedError("requires real junction fixture; expected: reparse rejected, not followed")


if __name__ == "__main__":
    unittest.main()
