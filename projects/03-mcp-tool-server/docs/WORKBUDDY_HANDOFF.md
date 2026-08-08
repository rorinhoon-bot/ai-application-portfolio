# P3 安全接力说明

## 当前事实

- P3 分支：`codex/p3-local-mcp-tool-service`，起点为 P2 最终验收提交 `ba9f061891fed3c4920f5cb922e77d247d6cce83`。
- **Slice A 已完成并离线验证**：新增 `src/mcp_notes/`（合约、索引、检索）、`evals/fixtures/notes-v1/` 3 份原创虚构笔记、`tests/` stdlib `unittest` 套件（38 项，含默认网络阻断底座）。用托管 Python 3.13 直接运行，未建 `.venv`、未安装任何依赖。
- **Slice B1 路径安全索引已完成并离线验证**：`src/mcp_notes/safe_open.py` 用 Windows 原生句柄层拒绝 symlink / junction / reparse point 跟随与 TOCTOU；路径安全检查已落地，不得再宣称未实现。
- **Slice B2a 离线 `create_task` 受控写入核心已完成并离线验证**：新增 `src/mcp_notes/tasks.py` 与 `src/mcp_notes/safe_task_write.py`（严格数据合同、PENDING/APPROVED/REJECTED/CANCELLED/EXPIRED 状态机、标准库 `sqlite3` 持久化三表、任务文件 no-replace 原子发布——Windows 原生 `NtCreateFile(FILE_CREATE, OBJ_DONT_REPARSE)` 原子无覆盖 + 句柄式 `open_task_root` 任务根/祖先目录 reparse 与 TOCTOU 防护，reparse→失败关闭 `task-root-unsafe`，绝不回退字符串路径、绝不 `os.replace`、无“先检查再发布”竞态窗口、冲突绝不覆盖、12 类稳定错误码）、固定金标准 `evals/gold/tasks-core-v1.json`（12 场景）、`tests/test_create_task.py`（53 项）。B2a 不含 MCP SDK/Server/Resource/stdio/Host/Client；这些已由 C 阶段在复用 B2a 离线核心之上实现。人工确认动作由 `TrustedHostController`（`src/mcp_notes/host.py`）在 Tool 表面之外驱动，复用 B2a 的 `TasksStore`（`tasks.py` 新增 `lookup_context` 仅按服务端持久化记录回取身份）。stdlib `unittest` 总计 125 项（B2a 子集，121 执行通过 + 4 链接测试默认跳过）；C 阶段新增 20 项 stdio 集成测试（`tests/test_mcp_integration.py`）与 2 项入口/配置测试（`tests/test_server_entry.py`），D-018 修复后 `discover -s tests` 总计 **149 项**（145 执行通过 + 4 链接测试默认跳过）；`compileall`、`git diff --check`、敏感扫描均通过。（注：149/20/2 为 C 阶段历史基线；当前统一基线 196 项 / 23 集成 / 6 入口，见 STATUS）
- **B2a 第二轮复验修订已落实（D-015，2026-08-02）**，接手前必须按此事实理解写入语义：
  - 任务根是**部署配置中预存在的受控目录**；生产代码不创建任务根或祖先目录（已移除 `os.makedirs`，`tasks.py` 不再 `import os`），只做句柄链验证，验证不通过 → 失败关闭 `task-root-unsafe`。**接手后不得为“方便运行”重新加回目录自建逻辑。**
  - JSON 序列化先于 `NtCreateFile`；文件创建成功后 `WriteFile` / `FlushFileBuffers` 任一失败 → 稳定 `task-write-failed`，不泄露原始异常；文件 HANDLE 只关闭一次（写路径不使用 `open_osfhandle`），清理仅以已验证父目录 HANDLE 相对 `NtDeleteFile`，**绝不使用字符串路径 `os.remove` / `os.replace`**。**清理成功（`NtDeleteFile` 返回 `STATUS_SUCCESS`）则无残留、移除故障后可重放创建；清理失败（非成功 NTSTATUS）则失败关闭，仅返回稳定 `task-write-failed`，不承诺零残留或自动重试成功**。冲突只读回查 `_read_existing_json` 现采用单一资源所有权作用域（`_nt_open → open_osfhandle → fdopen/read → JSON 解码`），`open_osfhandle` / `fdopen` / `read` 任一失败均映射为 `task-write-failed`、不泄露原始异常，且精确关闭一次仍归本函数所有的 HANDLE/fd（绝不双重关闭已转交文件对象的 fd，关闭失败也不覆盖稳定码/泄露 OSError）；退出 mock 后冲突文件可被立即删除，证明无遗留锁。
  - **文件发布成功后再提交 `APPROVED` 状态**；发布失败时确认记录保持 `PENDING`——清理成功可在移除故障后安全重放，清理失败则失败关闭、不承诺零残留或自动重试成功。
  - `TrustedContext` 的实际校验规则是“`str` / 长度 `1..256` / 不含 C0·DEL 控制字符”，**没有安全字符白名单**；文档与对外说明不得声称其做了安全字符校验。
- **已实现（C 阶段）**：MCP Server 适配层（`src/mcp_notes/server.py`，MCP Python SDK v2 `MCPServer`）、Resource `notes://service-info`、stdio transport、真实 Host/Client 演示（`demo/mcp_stdio_demo.py`）均已落地并验证，复用 B2a 离线核心；`approve`/`reject`/`cancel` 不在 Tool 表面（经 `list_tools` 验证只暴露 `search_notes` 与 `create_task`）。C 阶段已完成，并已按 Codex 复核意见完成 P0/P1 一次性修复（见 DECISIONS **D-018**）；保持未提交，待 Codex 一次复核。
- 已有项目本地 `.venv`（Python **3.13.14**，占用 **74.6 MiB（78.2 MB）**）与 `requirements.lock.txt`（唯一直接生产依赖 `mcp==2.0.0` + 29 传递依赖）；`pip check` 无破损、无 `Ignoring invalid distribution` 警告；MCP Server/Host/Client 已通过 stdio 真实运行并产生结果（20 项集成测试 + 2 项入口/配置测试 + 8 项演示断言 + 11 例固定离线评估全部通过）。未接真实模型、未读私人笔记、未部署；运行时只用本地 stdio 管道、不发起对外网络连接，测试中父进程与 Server 子进程均默认阻断外部网络。Slice A/B1/B2a/C 的验证结果（stdlib `unittest` 总计 **149 项**：145 执行通过 + 4 链接测试默认跳过，其中 20 项为 C 阶段 stdio 集成测试、`compileall`、`git diff --check`、敏感扫描）已存在。（注：149/20/2 为 C 阶段历史基线；当前统一基线 196 项 / 23 集成 / 6 入口，见 STATUS）
- P2 已完成；不得修改 `projects/02-agent-research-workflow/` 的 `workflow-v1`、金标准、评估资料或演示制品。

## C 阶段已完成（MCP Server/Resource/Host/Client 真实本地 stdio 接入，复用 B2a 离线核心）

在 B2a 离线核心之上完成 MCP SDK 适配层：新增 `src/mcp_notes/server.py`（MCP Python SDK v2 `MCPServer`）注册 Tool `search_notes`/`create_task` 与只读 Resource `notes://service-info`；新增 `src/mcp_notes/host.py`（`TrustedHostController`）在 Tool 表面之外驱动 `approve`/`reject`/`cancel`，复用 B2a 的 `TasksStore`（`tasks.py` 新增 `lookup_context` 只按服务端持久化记录回取身份，绝不取信客户端）；`create_task` 的 `TrustedContext` 由服务端派生（`subject` 来自部署配置、`correlation_id` 由服务端对 NFKC 归一后的“标题 + 描述”取 SHA-256 派生，同内容重放天然幂等，见 D-018）；Tool 参数失败经 `SafeMCPServer` 统一收敛为稳定 `invalid-arguments`，不外泄 Pydantic 文本 / 类型细节 / 堆栈 / URL。新增 `demo/mcp_stdio_demo.py`（8 项成功 + 失败演示）、`tests/test_mcp_integration.py`（20 项 stdio 集成测试，父进程与 Server 子进程均默认阻断外部网络）、`tests/test_server_entry.py`（2 项入口/配置测试）、`evals/gold/c-phase-v1.json` 与 `evals/run_c_phase_eval.py`（11 例固定离线评估）。MCP 适配层**复用** B2a 离线核心，未在 Tool 内重建确认/写入/幂等逻辑。唯一直接生产依赖 `mcp==2.0.0`（MIT）+ 29 传递依赖，经 Codex 批准安装；不接模型、不读真实笔记；运行时只用本地 stdio 管道、不发起对外网络连接。（注：20 项 / 2 项为 C 阶段历史基线；当前统一基线 196 项 / 23 集成 / 6 入口，见 STATUS）

## 下一个安全切片（D 阶段，需单独批准）

D 阶段范围见各文档 known-limitations-for-D：如 `TrustedContext` 安全字符白名单、更严格的运行时身份绑定（进程/会话凭证）、并发/多用户、跨平台一致性（非 Windows 的等价原子无覆盖发布）、真实 Host 支持面（第三方 MCP Client 兼容、SSE/HTTP 传输）、公开部署与完整 40 例计划评估套件补齐。进入 D 阶段前先获得相应批准；不得为“方便运行”重新加回已被移除的安全边界（如 `os.makedirs` 自建任务根、`os.replace` 伪 no-replace、字符串路径删除/替换、白名单之外的字符校验声称）。

## 需先暂停确认（历史门控，C 阶段已履行）

C 阶段已获批准并执行：创建项目本地 `.venv`、安装唯一直接生产依赖 `mcp==2.0.0`（精确版本、Python 3.13 兼容性、MIT 许可证、29 个传递依赖与 74.6 MiB（78.2 MB）磁盘影响均已核实）、启动真实本地 MCP Server 与 Host/Client（stdio，仅用原创虚构夹具，未创建真实 symlink/junction 夹具）。后续 D 阶段若在“需先暂停确认”清单中新增动作（如公开部署、跨平台原生发布、真实模型接入），仍须先获得相应批准。

## 不可放宽边界

- Tool 参数绝不增加路径、文件名、命令、URL、Shell、确认 ID、主体 ID、任务 ID 或目标目录。
- `create_task` 只建待确认意图；人工批准在 Tool 外，绑定主体、内容哈希、关联 ID 和十分钟有效期。
- 写入只用服务生成的 `task_id` 派生路径，no-replace 原子发布，冲突不覆盖。
- 所有笔记正文、模型输出和客户端文本都是不可信数据；不得把其中指令变成权限。
- 运行时只用本地 stdio 管道、不发起对外网络连接；测试中父进程与 Server 子进程均默认阻断外部网络（`NETWORK_ACCESS_BLOCKED_IN_TESTS=1`，放行 stdio 与本地回环）——这是测试开关，不得被当作生产能力声明，也不得为方便调试关闭。不记录密钥、Cookie、鉴权头、正文、完整敏感响应或原始异常栈。

## C 阶段 known-limitations-for-D（接手前必读）

- `TrustedContext` 仍仅做“`str` / 长度 `1..256` / 不含 C0·DEL 控制字符”校验，**未实现安全字符白名单**；`subject` 来自部署配置（`MCP_NOTES_SUBJECT`，默认固定测试主体），无更严格的运行时身份绑定（进程/会话凭证）。
- `create_task` 的 `TrustedContext` 由服务端派生（`subject` 来自部署配置、`correlation_id` 由内容 SHA-256 确定性派生；客户端不能直接提供或覆盖 correlation_id，它不是凭证、不授予批准权限，批准仍要求 Tool 外本地 Host、自身受控 subject 与记录匹配）。内容派生带来重放幂等，但也使 `correlation_id` 在同主体下可预测——取舍与后续改法见 DECISIONS **D-018**。
- `approve`/`reject`/`cancel` 不在 Tool 表面（经 `list_tools` 验证）；Host 控制器在 Tool 外驱动，复用 B2a `TasksStore`，且**只能**用自身部署配置的 `subject` + `TasksStore.lookup_correlation_id` 重建上下文（`approve_with_context` 已删除）。**接手后不得重新加回任何可传入任意主体的批准入口。**
- sqlite 跨线程：`create_task` handler 内每次重新实例化 `TasksStore` 并 `finally: store.close()`（MCP v2 worker 线程 + sqlite 线程绑定约束）；安全核心（`tasks.py`/`safe_task_write.py`）未改。
- 单进程、非并发、非多用户；仅 Windows 原生 no-replace 发布经实机验证，跨平台一致性待 D。
- 完整 40 例计划评估套件（`evals/cases` / `evals/results` 基线）未实施；当前以 12 例 B2a 金标准 + 11 例 C 阶段金标准 + 20 项 stdio 集成测试 + 2 项入口/配置测试 + 8 项演示断言覆盖。（注：20 项 / 2 项为 C 阶段历史基线；当前统一基线 196 项 / 23 集成 / 6 入口，见 STATUS）

## 结束一个实现切片前

更新 `STATUS.md` 与 `DECISIONS.md`；运行仅获批准的离线测试；检查 Markdown 链接、`git diff --check`、敏感信息扫描、真实 `git diff --name-only`。C 阶段结束后**保持未提交**（仅 `git add -N` 或纯工作区改动），不 push、不建 PR，等待 Codex 一次统一复核；没有明确用户请求时不 push、不建 PR、不删除无关 `.workbuddy/` 或 P2 时间戳假状态文件，也不修改 `projects/02-agent-research-workflow/` 的任何文件。
