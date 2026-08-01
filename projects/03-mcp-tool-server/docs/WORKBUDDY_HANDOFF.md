# P3 安全接力说明

## 当前事实

- P3 分支：`codex/p3-local-mcp-tool-service`，起点为 P2 最终验收提交 `ba9f061891fed3c4920f5cb922e77d247d6cce83`。
- **Slice A 已完成并离线验证**：新增 `src/mcp_notes/`（合约、索引、检索）、`evals/fixtures/notes-v1/` 3 份原创虚构笔记、`tests/` stdlib `unittest` 套件（38 项，含默认网络阻断底座）。用托管 Python 3.13 直接运行，未建 `.venv`、未安装任何依赖。
- **仍未实现**：路径安全检查（symlink/junction/reparse point/`..` 越界/TOCTOU）、`create_task` 待确认意图与人工确认状态机、sqlite3 持久化、MCP Server 适配层与 Resource、真实 Host/Client 演示。当前 `index.py` 仅为最小普通 `.md` 登记，不得宣称路径安全已实现。
- 没有 `.venv`、requirements、MCP Server、Host/Client 或 MCP Server/Host/Client 运行结果；未接模型、网络、真实笔记或部署。Slice A 的离线验证结果（38 项 stdlib 测试、`compileall`、`git diff --check`、敏感扫描）已存在。
- P2 已完成；不得修改 `projects/02-agent-research-workflow/` 的 `workflow-v1`、金标准、评估资料或演示制品。

## 下一个安全切片

先实现路径安全索引（symlink/junction/reparse point/`..` 越界/TOCTOU 拒绝式检查），再让学习者参与 `create_task` 的意图/确认/结果合同与确认状态机。先写离线测试和原创夹具；之后安装经核实的最小依赖并实现 MCP 适配层。不要先接模型、网络、真实笔记或 MCP Host。

## 需先暂停确认

在创建 `.venv`、安装/下载依赖、核实 MCP SDK 元数据、创建真实文件链接/junction 夹具、启动真实 MCP Server 或 Host/Client 前，先获得相应批准。当前 `mcp` 精确版本、Python 3.14 兼容性、许可证、传递依赖和磁盘影响均待离线/官方证据核实。

## 不可放宽边界

- Tool 参数绝不增加路径、文件名、命令、URL、Shell、确认 ID、主体 ID、任务 ID 或目标目录。
- `create_task` 只建待确认意图；人工批准在 Tool 外，绑定主体、内容哈希、关联 ID 和十分钟有效期。
- 写入只用服务生成的 `task_id` 派生路径，no-replace 原子发布，冲突不覆盖。
- 所有笔记正文、模型输出和客户端文本都是不可信数据；不得把其中指令变成权限。
- 默认测试阻断网络；不记录密钥、Cookie、鉴权头、正文、完整敏感响应或原始异常栈。

## 结束一个实现切片前

更新 `STATUS.md` 与 `DECISIONS.md`；运行仅获批准的离线测试；检查 Markdown 链接、`git diff --check`、敏感信息扫描、真实 `git diff --name-only`。没有明确用户请求时不 push、不建 PR、不删除无关 `.workbuddy/` 或 P2 时间戳假状态文件。
