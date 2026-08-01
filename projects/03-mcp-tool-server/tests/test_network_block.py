"""验证默认网络阻断底座确实拦截 socket 网络入口（P1-6）。

本用例自身证明 NetworkBlockedTestCase 能在测试期间阻断 DNS 解析、socket 创建与
连接尝试；任何意外网络调用都会立即 RuntimeError，使测试失败而非静默联网。
"""

import socket
import unittest

from _network_block import NetworkBlockedTestCase, _blocked


class TestNetworkBlock(NetworkBlockedTestCase):
    def test_socket_creation_blocked(self):
        with self.assertRaises(RuntimeError):
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def test_create_connection_blocked(self):
        with self.assertRaises(RuntimeError):
            socket.create_connection(("example.com", 80), timeout=1)

    def test_getaddrinfo_blocked(self):
        with self.assertRaises(RuntimeError):
            socket.getaddrinfo("example.com", 80)

    def test_gethostbyname_blocked(self):
        with self.assertRaises(RuntimeError):
            socket.gethostbyname("example.com")

    def test_socket_replaced_by_blocked_sentinel(self):
        # 运行期 socket.socket 应被替换为阻断哨兵，而非真实实现
        self.assertIs(socket.socket, _blocked)
