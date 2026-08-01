"""P3 默认网络阻断测试底座（纯标准库，离线）。

所有普通测试默认继承自 NetworkBlockedTestCase：在每个用例 setUp 时把 socket 的
核心网络入口替换为立即抛错的实现，tearDown 还原。任何 DNS、socket 连接、HTTP 或
SDK 网络尝试都会在测试中立即失败，满足 EVALUATION_DATA 第 5 节“普通测试默认安装
网络阻断器”的要求，且不写 URL/请求头。

仅拦截标准库 socket 层；文件系统操作（pathlib/os）不受影响，离线夹具照常运行。
"""

import socket
import unittest

_NETWORK_ERROR = "NETWORK_ACCESS_BLOCKED_IN_TESTS"


def _blocked(*_args, **_kwargs):
    raise RuntimeError(_NETWORK_ERROR)


class NetworkBlockedTestCase(unittest.TestCase):
    """默认阻断网络访问的 unittest 基类。"""

    def setUp(self):
        super().setUp()
        self._saved = {
            "socket": socket.socket,
            "create_connection": socket.create_connection,
            "getaddrinfo": socket.getaddrinfo,
            "gethostbyname": socket.gethostbyname,
        }
        socket.socket = _blocked  # type: ignore[assignment]
        socket.create_connection = _blocked  # type: ignore[assignment]
        socket.getaddrinfo = _blocked  # type: ignore[assignment]
        socket.gethostbyname = _blocked  # type: ignore[assignment]

    def tearDown(self):
        socket.socket = self._saved["socket"]  # type: ignore[assignment]
        socket.create_connection = self._saved["create_connection"]  # type: ignore[assignment]
        socket.getaddrinfo = self._saved["getaddrinfo"]  # type: ignore[assignment]
        socket.gethostbyname = self._saved["gethostbyname"]  # type: ignore[assignment]
        super().tearDown()
