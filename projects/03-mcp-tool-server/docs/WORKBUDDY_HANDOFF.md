# P3 安全接力说明

## 当前事实

- P3 分支：`codex/p3-local-mcp-tool-service`，起点为 P2 最终验收提交 `ba9f061891fed3c4920f5cb922e77d247d6cce83`。
- **Slice A 已完成并离线验证**：新增 `src/mcp_notes/`（合约、索引、检索）、`evals/fixtures/notes-v1/` 3 份原创虚构笔记、`tests/` stdlib `unittest` 套件（38 项，含默认网络阻断底座）。用托管 Python 3.13 直接运行，未建 `.venv`、未安装任何依赖。
- **Slice B1 路径安全索引已完成并离线验证**：`src/mcp_notes/safe_open.py` 用 Windows 原生句柄层拒绝 symlink / junction / reparse point 跟随与 TOCTOU；路径安全检查已落地，不得再宣称未实现。
- **Slice B2a 离线 `create_task` 受控写入核心已完成并离线验证**：新增 `src/mcp_notes/tasks.py` 与 `src/mcp_notes/safe_task_write.py`（严格数据合同、PENDING/APPROVED/REJECTED/CANCELLED/EXPIRED 状态机、标准库 `sqlite3` 持久化三表、任务文件 no-replace 原子发布——Windows 原生 `NtCreateFile(FILE_CREATE, OBJ_DONT_REPARSE)` 原子无覆盖 + 句柄式 `open_task_root` 任务根/祖先目录 reparse 与 TOCTOU 防护，reparse→失败关闭 `task-root-unsafe`，绝不回退字符串路径、绝不 `os.replace`、无“先检查再发布”竞态窗口、冲突绝不覆盖、12 类稳定错误码）、固定金标准 `evals/gold/tasks-core-v1.json`（12 场景）、`tests/test_create_task.py`（53 项）。B2a 不含 MCP SDK/Server/Resource/stdio/Host/Client；人工确认动作由可信本地上下文 `TrustedContext(subject, correlation_id)` 驱动。stdlib `unittest` 总计 125 项（121 执行通过 + 4 链接测试默认跳过）；`compileall`、`git diff --check`、敏感扫描均通过。
- **B2a 第二轮复验修订已落实（D-015，2026-08-02）**，接手前必须按此事实理解写入语义：
  - 任务根是**部署配置中预存在的受控目录**；生产代码不创建任务根或祖先目录（已移除 `os.makedirs`，`tasks.py` 不再 `import os`），只做句柄链验证，验证不通过 → 失败关闭 `task-root-unsafe`。**接手后不得为“方便运行”重新加回目录自建逻辑。**
  - JSON 序列化先于 `NtCreateFile`；文件创建成功后 `WriteFile` / `FlushFileBuffers` 任一失败 → 稳定 `task-write-failed`，不泄露原始异常；文件 HANDLE 只关闭一次（写路径不使用 `open_osfhandle`），清理仅以已验证父目录 HANDLE 相对 `NtDeleteFile`，**绝不使用字符串路径 `os.remove` / `os.replace`**。**清理成功（`NtDeleteFile` 返回 `STATUS_SUCCESS`）则无残留、移除故障后可重放创建；清理失败（非成功 NTSTATUS）则失败关闭，仅返回稳定 `task-write-failed`，不承诺零残留或自动重试成功**。冲突只读回查 `_read_existing_json` 现采用单一资源所有权作用域（`_nt_open → open_osfhandle → fdopen/read → JSON 解码`），`open_osfhandle` / `fdopen` / `read` 任一失败均映射为 `task-write-failed`、不泄露原始异常，且精确关闭一次仍归本函数所有的 HANDLE/fd（绝不双重关闭已转交文件对象的 fd，关闭失败也不覆盖稳定码/泄露 OSError）；退出 mock 后冲突文件可被立即删除，证明无遗留锁。
  - **文件发布成功后再提交 `APPROVED` 状态**；发布失败时确认记录保持 `PENDING`——清理成功可在移除故障后安全重放，清理失败则失败关闭、不承诺零残留或自动重试成功。
  - `TrustedContext` 的实际校验规则是“`str` / 长度 `1..256` / 不含 C0·DEL 控制字符”，**没有安全字符白名单**；文档与对外说明不得声称其做了安全字符校验。
- **仍未实现**：MCP Server 适配层、Resource `notes://service-info`、stdio transport、真实 Host/Client 演示（均属 B2b）。不得在 B2b 之前宣称 MCP 接入已完成。
- 没有 `.venv`、requirements、MCP Server、Host/Client 或 MCP Server/Host/Client 运行结果；未接模型、网络、真实笔记或部署。Slice A/B1/B2a 的离线验证结果（125 项 stdlib 测试、`compileall`、`git diff --check`、敏感扫描）已存在。
- P2 已完成；不得修改 `projects/02-agent-research-workflow/` 的 `workflow-v1`、金标准、评估资料或演示制品。

## 下一个安全切片（Slice B2b，需单独批准）

在 B2a 离线核心之上实现 MCP SDK 适配层：注册 Tool `create_task`/`approve`/`reject`/`cancel`、固定 Resource `notes://service-info`、stdio transport，并做真实本地 Host/Client 演示。MCP 适配层须**复用** B2a 离线核心（`TasksStore` 与 `TrustedContext`），不得在 Tool 内重建确认/写入/幂等逻辑。先写离线适配测试与原创夹具；之后安装经核实的最小依赖。不要先接模型、网络、真实笔记。

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
