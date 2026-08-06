r"""P3 网络阻断（纯标准库，仅测试环境启用）。

本模块提供一套 loopback-aware 的网络入口阻断器，供两处使用：

- 父进程测试底座（`tests/_network_block.py` 继承本模块）：所有普通测试默认安装，
  阻断 DNS / 外部 socket / HTTP。
- **stdio Server 子进程**：仅当环境变量 `NETWORK_ACCESS_BLOCKED_IN_TESTS=1` 时，
  由 `mcp_notes.server` 在启动早期安装，使测试启动的 Server 子进程也默认阻断外部
  网络；生产环境（无该变量）不受影响，网络能力不变。

阻断粒度（loopback-aware）：
- 阻断**实际对外联网动作**：`socket.connect`（非回环 / 非 Unix 套接字时抛错）、
  `create_connection`、`getaddrinfo`、`gethostbyname`。
- **允许**回环（127.0.0.1 / ::1 / localhost）与 Unix 域套接字连接——这些是本地内部
  机制（如 asyncio 事件循环的 self-pipe、`socket.socketpair`），不是对外网络访问。
  借此本地 stdio MCP Server/Client 可经管道通信而不触发阻断。
- 仅拦截标准库 socket 层；文件系统操作不受影响，离线夹具照常运行。
"""

from __future__ import annotations

import ipaddress
import socket

# 对外稳定哨兵字符串：任何被阻断的对外网络尝试都以该字符串的 RuntimeError 失败，
# 不泄露目标主机、端口或原始异常文本。
NETWORK_ERROR = "NETWORK_ACCESS_BLOCKED_IN_TESTS"

_orig_connect = socket.socket.connect


def _is_loopback(host) -> bool:
    """回环或 Unix 域套接字路径视为本地、允许；其余视为对外网络、阻断。"""
    if host is None:
        return False
    if isinstance(host, str):
        if host in ("", "localhost", "127.0.0.1", "::1"):
            return True
        # 形如 /path/to/sock 的 Unix 域套接字路径：本地，允许
        if host.startswith("/") or host.startswith("\\\\") or (":" not in host and "\\" in host):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False
    return False


def _blocked_connect(self, address, *args, **kwargs):
    host = None
    if isinstance(address, (tuple, list)) and len(address) >= 1:
        host = address[0]
    elif isinstance(address, str):
        host = address
    if not _is_loopback(host):
        raise RuntimeError(NETWORK_ERROR)
    return _orig_connect(self, address, *args, **kwargs)


def _blocked(*_args, **_kwargs):
    raise RuntimeError(NETWORK_ERROR)


def install_network_block() -> None:
    """安装网络阻断器（替换标准库 socket 层对外入口）。

    进程级、全局生效；应在 Server 子进程启动早期、任何网络尝试之前安装。
    回环 / Unix 套接字保持可用，不影响 stdio / asyncio 内部机制。
    """
    socket.socket.connect = _blocked_connect  # type: ignore[assignment]
    socket.create_connection = _blocked  # type: ignore[assignment]
    socket.getaddrinfo = _blocked  # type: ignore[assignment]
    socket.gethostbyname = _blocked  # type: ignore[assignment]


def maybe_install_network_block(environ=None) -> bool:
    """仅当测试环境开关置位时安装网络阻断；返回是否安装。

    生产环境（无 `NETWORK_ACCESS_BLOCKED_IN_TESTS=1`）不安装，网络能力不变。
    """
    env = environ if environ is not None else dict(__import__("os").environ)
    if env.get("NETWORK_ACCESS_BLOCKED_IN_TESTS") == "1":
        install_network_block()
        return True
    return False


def restore_network() -> None:
    """还原标准库 socket 层（仅测试拆卸用）。"""
    socket.socket.connect = _orig_connect  # type: ignore[assignment]
