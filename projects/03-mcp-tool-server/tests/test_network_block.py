"""验证默认网络阻断底座确实拦截真实外联（P1-6），同时放行本地 loopback 自管道（stdio 所需）。

本用例自身证明 NetworkBlockedTestCase 能在测试期间阻断 DNS 解析、socket 对外连接与
创建连接入口；任何意外对外网络调用都会立即 RuntimeError，使测试失败而非静默联网。

设计（v2，兼容 stdio 子进程）：构造 socket 对象本身不被阻断（stdio 本地自管道需创建
socket），但向非回环地址 `connect` 会被拦截；向回环（127.0.0.1 / ::1 / localhost）或
Unix 域套接字 `connect` 被放行——这些是本地内部机制（asyncio 事件循环 self-pipe、
socketpair），不是对外网络访问。
"""

import socket
import unittest

from _network_block import NetworkBlockedTestCase, _blocked, _blocked_connect


class TestNetworkBlock(NetworkBlockedTestCase):
    def test_socket_construction_allowed(self):
        # 构造不被阻断，以便 stdio 本地自管道使用；阻断发生在 connect
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.close()

    def test_non_loopback_connect_blocked(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with self.assertRaises(RuntimeError):
                s.connect(("93.184.216.34", 80))  # example.com 非回环
        finally:
            s.close()

    def test_loopback_connect_not_blocked(self):
        # 回环连接不被网络阻断拦截（stdio 子进程 self-pipe 依赖）
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with self.assertRaises(OSError) as cm:
                s.connect(("127.0.0.1", 9))
            self.assertNotIsInstance(cm.exception, RuntimeError)
        finally:
            s.close()

    def test_network_block_sentinels_active(self):
        # 运行期网络入口应被替换为阻断哨兵（connect 为回环感知版）
        self.assertIs(socket.socket.connect, _blocked_connect)
        self.assertIs(socket.create_connection, _blocked)
        self.assertIs(socket.getaddrinfo, _blocked)
        self.assertIs(socket.gethostbyname, _blocked)

    def test_create_connection_blocked(self):
        with self.assertRaises(RuntimeError):
            socket.create_connection(("example.com", 80), timeout=1)

    def test_getaddrinfo_blocked(self):
        with self.assertRaises(RuntimeError):
            socket.getaddrinfo("example.com", 80)

    def test_gethostbyname_blocked(self):
        with self.assertRaises(RuntimeError):
            socket.gethostbyname("example.com")
