# P3 依赖清单（已安装，C 阶段）

- 版本：v0.3（已批准安装、已锁定、已验证）
- 日期：2026-08-06
- 状态：**已安装并验证通过**。`mcp==2.0.0` 为唯一生产直接依赖；另有 29 个传递依赖，
  全部来自锁文件 `requirements.lock.txt`。Python 实际运行环境 **3.13.14**（Windows）；
  安装后 `.venv` 实际大小 **74.6 MiB（78.2 MB）**。

## 1. 原则

- 项目自有代码仅依赖标准库 + `mcp` SDK；其余 29 个均为 `mcp` 的传递依赖，按锁文件固定。
- 标准库（`pathlib` / `os` / `sqlite3` / `hashlib` / `json` / `tempfile` / `unicodedata` 等）
  不列为 pip 依赖。
- 运行时只用 **stdio** 本地传输；`mcp` 携带的 HTTP / SSE / ASGI 相关传递依赖（httpx2 /
  uvicorn / starlette / sse-starlette / h11 / python-multipart / truststore 等）随 SDK
  一并安装，但本项目 stdio 路径不触发它们；测试中的父进程与 Server 子进程均默认阻断
  外部网络（仅测试环境开关 `NETWORK_ACCESS_BLOCKED_IN_TESTS=1` 启用），生产网络能力不变。
- 不引入模型供应商 SDK、Agent / 多智能体、向量库 / Embedding、Web 框架（除 SDK 自带 ASGI
  外）、云数据库、ORM、任务队列等（见第 5 节）。

## 2. 生产直接依赖

| 包 | 精确版本 | 用途 | 必要性 | Python 3.13 / Windows 兼容性 | 许可证 |
|---|---|---|---|---|---|
| `mcp` | `2.0.0` | MCP Server / Tool / Resource / stdio transport / 本地 Client 集成（v2 高层 `MCPServer`） | P3 协议作品核心；不用 SDK 无法证明真实 MCP 互通 | 官方元数据 `requires-python >=3.10`，含 Windows wheel；已在本地 CPython 3.13.14 验证 stdio Server/Client 互通 | MIT |

## 3. 传递依赖（29 个，源自 `requirements.lock.txt`）

> Bootstrap 包 `pip` / `setuptools` / `wheel` 由 venv 包管理器提供，不计入下表、不写入锁文件。

| 包 | 精确版本 | 许可证 | 用途（mcp SDK 内） | Python 3.13 / Windows 兼容 |
|---|---|---|---|---|
| `mcp-types` | `2.0.0` | MIT | MCP 协议数据类型（Server/Client 共用） | 随 mcp 2.0.0 |
| `pydantic` | `2.13.4` | MIT | SDK 参数 / 结果数据校验 | >=3.10，Windows OK |
| `pydantic_core` | `2.46.4` | MIT | pydantic 校验引擎 | >=3.10，Windows OK |
| `typing_inspection` | `0.4.2` | MIT | pydantic 类型内省 | >=3.10，Windows OK |
| `typing_extensions` | `4.16.0` | PSF-2.0 | typing 向后移植 | 全平台 |
| `annotated-types` | `0.8.0` | MIT | pydantic 注解类型支持 | >=3.8，Windows OK |
| `anyio` | `4.14.2` | MIT | 异步 I/O（SDK / starlette） | >=3.9，Windows OK |
| `attrs` | `26.1.0` | MIT | opentelemetry / referencing 支持 | >=3.7，Windows OK |
| `click` | `8.4.2` | BSD-3-Clause | SDK CLI 入口 | >=3.9，Windows OK |
| `colorama` | `0.4.6` | MIT | Windows 终端颜色 | 全平台 |
| `cryptography` | `50.0.0` | Apache-2.0 OR BSD-3-Clause | TLS / 安全传输（SDK auth 路径） | >=3.10，Windows OK（含原生 wheel） |
| `cffi` | `2.1.1` | MIT-0 | cryptography 的 C 绑定 | >=3.8，Windows OK（含原生 wheel） |
| `pycparser` | `3.0` | BSD-3-Clause | cffi 依赖（C 头解析） | 全平台 |
| `idna` | `3.18` | BSD-3-Clause | 域名编码（httpx） | 全平台 |
| `httpx2` | `2.9.1` | BSD-3-Clause | 异步 HTTP 客户端（SDK streamable-http 客户端） | >=3.10，Windows OK |
| `httpcore2` | `2.9.1` | BSD-3-Clause | HTTP 核心（httpx2 依赖） | >=3.10，Windows OK |
| `h11` | `0.16.0` | MIT | HTTP/1.1 解析（SDK HTTP 传输） | 全平台 |
| `python-multipart` | `0.0.32` | Apache-2.0 | 表单解析（SDK HTTP 传输） | >=3.8，Windows OK |
| `starlette` | `1.4.1` | BSD-3-Clause | ASGI 框架（SDK HTTP 传输） | >=3.9，Windows OK |
| `sse-starlette` | `3.4.8` | BSD-3-Clause | SSE（SDK streamable-http） | >=3.8，Windows OK |
| `uvicorn` | `0.52.1` | BSD-3-Clause | ASGI 服务器（SDK HTTP 传输） | >=3.9，Windows OK |
| `truststore` | `0.10.4` | MIT | 平台信任库（SDK HTTPS 验证） | >=3.10，Windows OK |
| `jsonschema` | `4.26.0` | MIT | JSON Schema 校验（SDK） | >=3.9，Windows OK |
| `jsonschema-specifications` | `2025.9.1` | MIT | JSON Schema 规范数据 | >=3.9，Windows OK |
| `referencing` | `0.37.0` | MIT | JSON 引用解析（jsonschema） | >=3.9，Windows OK |
| `rpds-py` | `2026.6.3` | MIT | 持久化数据结构（referencing / jsonschema） | >=3.10，Windows OK（含原生 wheel） |
| `opentelemetry-api` | `1.44.0` | Apache-2.0 | 追踪 / 遥测 API（SDK 可选） | >=3.9，Windows OK |
| `PyJWT` | `2.13.0` | MIT | JWT 鉴权（SDK auth 路径） | >=3.8，Windows OK |
| `pywin32` | `312` | PSF | Windows 原生 API（SDK / uvicorn Windows 支持） | Windows 专用 |

## 4. 兼容性结论

- 实际运行环境：CPython **3.13.14**（Windows）。`mcp==2.0.0` 官方元数据声明
  `requires-python >=3.10`，并提供 Windows wheel；其余传递依赖均声明支持 3.10+ 且含
  Windows 构建。`pywin32` 为 Windows 专用（本项目运行平台即 Windows，符合）。
- 验证方式：在 P3 独立 `.venv` 安装锁文件全部条目，`python -m pip check` **无 warning、
  无 broken requirements**；`compileall` 通过；`unittest discover` 全部通过；`demo` 与
  固定 `eval` 全部通过（见各文档验证记录）。
- 磁盘占用：安装后 `.venv` 实际 **74.6 MiB（78.2 MB）**。

## 5. 明确不引入（应用层）

| 类型 | 不引入原因 |
|---|---|
| 模型供应商 SDK、`httpx`/`httpx2` 主动调用、网页抓取 | 当前不调用模型、不主动访问网络、不读取 URL；加入会扩大密钥与网络面（HTTP 相关传递依赖仅随 SDK 被动安装，stdio 路径不触发） |
| Agent、多智能体、LangGraph、AutoGen、CrewAI | P3 验证 MCP 工具边界，不需要自主规划或多角色协作 |
| 向量库、Embedding、Reranker | 小型固定笔记集用确定性关键词检索即可，且更容易验证路径和注入边界 |
| 公开 Web 框架 / 前端 UI | 当前演示是本地 stdio MCP Host/Client，不公开 HTTP 服务（SDK 自带的 ASGI/uvicorn 仅 SDK HTTP 传输路径使用，非本项目主动启用） |
| PostgreSQL、Redis、云数据库 | 不需要网络数据库服务；仅用标准库 `sqlite3` 保存本地确认与幂等状态 |
| ORM、任务队列、消息代理 | 单机、单服务、人工确认场景没有并发分布式需求 |

## 6. 锁文件与复验

- 锁文件：`requirements.lock.txt`（mcp==2.0.0 + 29 传递依赖，精确版本）。
- 复验命令（仅本地、离线测试）：
  - `.venv\Scripts\python.exe -m compileall -q src tests demo evals`
  - `.venv\Scripts\python.exe -m unittest discover -s tests`
  - `.venv\Scripts\python.exe evals\run_c_phase_eval.py`
  - `.venv\Scripts\python.exe demo\mcp_stdio_demo.py`
  - `.venv\Scripts\python.exe -m pip check`
- 批准边界（与历史决策一致）：仅创建 `projects/03-mcp-tool-server/.venv`、安装锁文件
  wheel、生成锁文件、执行 `pip check` 与本地离线测试；不包含真实模型、真实笔记、
  网络检索、公开部署、系统 Python 修改或未列依赖。
