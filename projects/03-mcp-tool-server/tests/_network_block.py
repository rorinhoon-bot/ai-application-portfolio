"""P3 默认网络阻断测试底座（纯标准库，离线）。

所有普通测试默认继承自 NetworkBlockedTestCase：在每个用例 setUp 时把网络入口替换为
立即抛错的实现，tearDown 还原。任何 DNS、socket 连接、HTTP 或 SDK 网络尝试都会在测试中
立即失败，满足 EVALUATION_DATA 第 5 节“普通测试默认安装网络阻断器”的要求，且不写
URL / 请求头。

阻断实现统一来自 `mcp_notes._network_block`（Server 子进程亦复用同一份），保证父进程与
stdio Server 子进程使用完全相同的 loopback-aware 阻断逻辑。

网络说明（P1-5）：运行时只用 stdio；测试中的父进程与 Server 子进程均默认阻断外部网络；
生产不受影响。
"""

import socket
import unittest

from mcp_notes._network_block import (
    NETWORK_ERROR,
    _blocked,
    _blocked_connect,
    install_network_block,
    restore_network,
)

# 向后兼容：原 tests 内部直接引用的哨兵与阻断函数
_BLOCKED = _blocked
_BLOCKED_CONNECT = _blocked_connect


class NetworkBlockedTestCase(unittest.TestCase):
    """默认阻断网络访问的 unittest 基类（仅阻断真实对外联网入口）。"""

    def setUp(self):
        super().setUp()
        install_network_block()

    def tearDown(self):
        restore_network()
        super().tearDown()
