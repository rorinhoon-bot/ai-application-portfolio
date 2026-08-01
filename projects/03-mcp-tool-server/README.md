# P3：本地 MCP 笔记检索与受控任务创建服务

系统集成作品，规划中。

目标：后续实现一个本地 MCP Server，提供只读 `search_notes(keyword)`、受控写 `create_task(title, description)` 与一个只读 Resource。服务只能检索配置的笔记白名单目录；任务写入必须经过人工确认，且不能覆盖既有任务。

## 当前阶段

- 状态：规划基线完成，尚未实现。
- 当前没有 `.venv`、依赖锁文件、MCP Server、MCP Host/Client、真实笔记、模型调用、网络访问或部署。
- 计划仅使用原创虚构离线笔记夹具；不读取用户私人笔记。

## 文档入口

- [需求与验收标准](docs/PRD.md)
- [计划架构与安全数据流](docs/ARCHITECTURE.md)
- [依赖提案（未安装）](docs/DEPENDENCIES.md)
- [固定离线评估方案](docs/EVALUATION_DATA.md)
- [后续安全接力说明](docs/WORKBUDDY_HANDOFF.md)
- [关键取舍](DECISIONS.md)
- [当前状态](STATUS.md)

## 后续才做

获得下一阶段批准后，先由学习者参与写最小数据合同、路径安全代码和测试；再安装经核实的最小依赖，最后做真实本地 MCP Host/Client 接入演示。任何阶段都不应把笔记正文、模型输出或客户端输入当作路径、命令、URL 或写入授权。
