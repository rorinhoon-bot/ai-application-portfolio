# P3：本地 MCP 笔记检索与受控任务创建服务

系统集成作品。规划基线已完成；`search_notes` 的纯标准库核心（数据合同、索引登记、离线检索、单测）已实现并通过离线验证；路径安全、`create_task`、MCP SDK 适配仍为计划，未实现。

目标：后续实现一个本地 MCP Server，提供只读 `search_notes(keyword)`、受控写 `create_task(title, description)` 与一个只读 Resource。服务只能检索配置的笔记白名单目录；任务写入必须经过人工确认，且不能覆盖既有任务。

## 当前阶段

- 状态：`in_progress`（Slice A 已实现并离线验证；待进入 Slice B）。
- 已实现（Slice A）：`src/mcp_notes/` 纯标准库合同与检索逻辑、`evals/fixtures/notes-v1/` 3 份原创虚构笔记、`tests/` stdlib `unittest` 套件（38 项，含默认网络阻断底座）。
- 未做（仍属计划）：路径安全检查（symlink/junction/reparse point/TOCTOU）、`create_task` 待确认意图与人工确认状态机、sqlite3 持久化、MCP Server 适配层与 Resource、真实 Host/Client 演示。
- 当前没有 `.venv`、依赖锁文件、MCP Server、MCP Host/Client、真实笔记、模型调用、网络访问或部署；Slice A 仅用标准库，未安装任何依赖。
- 计划仅使用原创虚构离线笔记夹具；不读取用户私人笔记。

## Slice A 离线验证

Slice A 仅用 CPython 标准库实现，**无需 `.venv`、无需安装任何依赖**。在任意 Python 3.13/3.14 解释器下即可复跑：

```powershell
Set-Location projects\03-mcp-tool-server
python --version
python -m compileall -q src tests
python -m unittest discover -s tests -v
```

预期：`compileall` 通过；`unittest` 全部 38 项通过（含默认网络阻断底座）。真实 MCP Server/Host/Client 运行结果尚未产生，属于 Slice B 之后。

## 文档入口

- [需求与验收标准](docs/PRD.md)
- [计划架构与安全数据流](docs/ARCHITECTURE.md)
- [依赖提案（未安装）](docs/DEPENDENCIES.md)
- [固定离线评估方案](docs/EVALUATION_DATA.md)
- [后续安全接力说明](docs/WORKBUDDY_HANDOFF.md)
- [关键取舍](DECISIONS.md)
- [当前状态](STATUS.md)

## 后续才做

获得下一阶段批准后，先实现路径安全代码与测试，再由学习者参与 `create_task` 确认状态机；之后安装经核实的最小依赖，最后做真实本地 MCP Host/Client 接入演示。任何阶段都不应把笔记正文、模型输出或客户端输入当作路径、命令、URL 或写入授权。
