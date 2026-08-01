# P3 依赖提案

- 版本：v0.1（提案，未批准安装）
- 日期：2026-08-01
- 当前动作：不安装、不创建 `.venv`、不写 `requirements*.txt`、不访问网络。

## 1. 原则

P3 当前只做规划。后续实现应优先使用 CPython 标准库：`pathlib`、`os`、`sqlite3`、`hashlib`、`json`、`tempfile`、`logging` 和 `unittest.mock`。标准库不列为 pip 依赖。

唯一预期生产直接依赖是 MCP Python SDK；它提供协议 Server、Tool、Resource 和后续本地 Client 集成所需接口。当前离线环境没有可信包元数据或 wheel，因此不能编造 SDK 的版本、Python 3.14 支持、许可证、传递依赖或磁盘占用。以下内容是待核实提案，不能用于安装。

## 2. 生产直接依赖

| 包 | 精确版本 | 用途 | 必要性 | Python 3.14 兼容性证据 | 许可证 | 预计磁盘影响 |
|---|---|---|---|---|---|---|
| `mcp` | `待核实；不得以浮动版本安装` | MCP Server、Tool、Resource、stdio transport、后续本地 Client 集成 | P3 协议作品核心；不用 SDK 无法证明真实 MCP 互通 | 待核实：下一阶段须取得所选精确版本的官方 PyPI 元数据、Windows wheel/构建说明，并在独立 CPython 3.14 `.venv` wheel-only dry-run 与最小 Server/Client 测试验证 | 待核实：以所选版本发布包 `License-Expression` 和上游 LICENSE 为准 | 待核实：先做 `pip --dry-run --only-binary=:all:`，记录下载 wheel 与安装后 `.venv` 大小 |

### 选择说明

- 不在本阶段猜测 `mcp` 版本号。精确版本必须来自下一阶段可复核的官方元数据，随后写入锁文件与本表。
- 先检查 SDK 是否支持所需 Tool/Resource 与 stdio；若不能满足 Windows 路径安全或本地 Host/Client 演示，停止并重新决策，不临时换包。
- MCP SDK 不能替代 Schema、路径安全、Human-in-the-loop、幂等或文件原子写入；这些是项目自有代码与测试责任。

## 3. 开发直接依赖

| 包 | 精确版本 | 用途 | 必要性 | Python 3.14 兼容性证据 | 许可证 | 预计磁盘影响 |
|---|---|---|---|---|---|---|
| `pytest` | `9.1.1`（候选） | 离线单元、集成、安全和固定评估测试 | 仓库完成标准要求自动测试 | P2 在同一仓库的 CPython 3.14.3 独立环境已验证 `pytest==9.1.1`，P2 依赖记录还注明官方元数据声明 `>=3.10` 并列出 Python 3.14/Windows；P3 仍须独立验证 | MIT（P2 已核实；P3 安装前仍复核所下载包） | 待核实：P3 的最终依赖树由 MCP SDK 版本决定，不能从 P2 环境推算 |

不提案 formatter、linter、HTTP 测试库或数据库 ORM。若后续需要，必须先新建决策和依赖条目；当前不默认扩展。

## 4. 传递依赖

`mcp` 的传递依赖当前为待核实，不能假定为空，也不能从网上记忆填写。下一阶段批准后必须：

1. 固定生产与开发直接版本。
2. 在 P3 独立 `.venv` 进行 `--dry-run --only-binary=:all:`。
3. 导出全部传递依赖的精确版本、wheel 类型、许可证来源、Python 3.14/Windows 兼容性证据和磁盘大小。
4. 拒绝未知许可证、无可接受 Windows 构建、源码构建需求或未解释的网络客户端。
5. 生成可复现锁文件，再安装并运行 `pip check` 与离线安全烟雾测试。

在这些步骤完成前，生产、开发和传递依赖均未安装，也没有兼容性结论。

## 5. 明确不引入

| 类型 | 不引入原因 |
|---|---|
| 模型供应商 SDK、`httpx`、网页抓取 | 当前不调用模型、不访问网络、不读取 URL；加入会扩大密钥与网络面 |
| Agent、多智能体、LangGraph、AutoGen、CrewAI | P3 验证 MCP 工具边界，不需要自主规划或多角色协作 |
| 向量库、Embedding、Reranker | 小型固定笔记集用确定性关键词检索即可，且更容易验证路径和注入边界 |
| Web 框架、前端 UI | 后续演示是本地 stdio MCP Host/Client，不公开 HTTP 服务 |
| PostgreSQL、Redis、云数据库 | 不需要网络数据库服务；计划仅在必要时用标准库 `sqlite3` 保存本地确认与幂等状态 |
| ORM、任务队列、消息代理 | 单机、单服务、人工确认场景没有并发分布式需求 |

## 6. 下一阶段安装批准边界

另行批准后，允许的最小动作应限于：创建 `projects/03-mcp-tool-server/.venv`、下载/安装本表最终核实的 wheel、生成锁文件、执行 `pip check` 和不联网的本地测试。批准不包含真实模型、真实笔记、网络检索、公开部署、系统 Python 修改或未列依赖。
