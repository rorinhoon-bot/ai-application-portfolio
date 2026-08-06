# P3：本地 MCP 笔记检索与受控任务创建服务

系统集成作品。规划基线已完成；`search_notes` 的纯标准库核心（数据合同、索引登记、离线检索、单测）已实现并通过离线验证；路径安全、`create_task`、MCP SDK 适配仍为计划，未实现。

目标：后续实现一个本地 MCP Server，提供只读 `search_notes(keyword)`、受控写 `create_task(title, description)` 与一个只读 Resource。服务只能检索配置的笔记白名单目录；任务写入必须经过人工确认，且不能覆盖既有任务。

## 当前阶段

- 状态：`in_progress`（Slice A 已实现并离线验证；Slice B1 路径安全索引已实现并离线验证；Slice B2a 离线 `create_task` 受控写入核心已实现并离线验证；Slice B2b（MCP SDK 适配层与 Host/Client 演示）仍待批准）。
- 已实现（Slice A）：`src/mcp_notes/` 纯标准库合同与检索逻辑、`evals/fixtures/notes-v1/` 3 份原创虚构笔记、`tests/` stdlib `unittest` 套件（含默认网络阻断底座）。
- 已实现（Slice B1 路径安全索引）：新增 `src/mcp_notes/safe_open.py` —— 基于 Windows 原生句柄（`NtOpenFile` / `NtQueryDirectoryFile`，`OBJ_DONT_REPARSE` + 相对父 HANDLE）拒绝 symlink / junction / reparse point 跟随与 TOCTOU。具体已落实并通过测试（Codex P0/P1 修订）：
  - 组件级校验（§4.6）拒绝空段、`.`、`..`、`\`、`/`、`:`、`< > " | ? *`、控制字符、尾随点 / 空格、保留设备名；`open_file_relative` 先校验 `rel_parts` 为非空列表并对每一级组件校验；`_nt_open` 在相对父 HANDLE 打开时**也自行校验组件**，不依赖调用方。
  - 文件打开（非目录）携带 `FILE_READ_ATTRIBUTES`，打开后查询 `WIN32_FILE_BASIC_INFO` 拒绝 DIRECTORY / REPARSE_POINT / DEVICE，再查询 `WIN32_FILE_STANDARD_INFO` 做容量上限（`> MAX_NOTE_BYTES`(1 MiB) → `content-too-large`）；任一查询失败 → `io-error`。
  - 枚举（`NtQueryDirectoryFile`）缓冲区解析遵循 §4.4 硬边界逐字段断言（新增 `buffer_length` 参数并断言 `0 < Information <= buffer_length`；`NextEntryOffset` 非 0 时须 `>= 固定头长`、`8` 字节对齐、`record_start < record_end <= Information`；`FileName` 区域不得越过 `record_end`；UTF-16LE 解码异常 → `io-error`）；任何越界 / 畸形 / `Information==0` / 非成功状态 / `BUFFER_OVERFLOW` 一律 `io-error`，绝不返回部分枚举结果。
  - 根配置门拒绝 `..` / UNC / 设备前缀 / 正斜杠混用 / 相对路径；`UNICODE_STRING.Length/MaximumLength` 按真实 UTF-16LE 字节数计算并拒绝超过 `USHORT` 上限；`IO_STATUS_BLOCK` 的 `Status` 用 32 位 `c_long`、`Information` 用指针宽度 `c_size_t`（不写死 `c_ulonglong`）。
  - 失败关闭与事务语义（§9）：reparse 条目 → `_walk` 抛 `not-allowed-reparse`（不 `continue` 跳过）→ `build_index` 整体失败 `index-build-failed`；超大文件使本次构建失败并丢弃新索引，绝不静默跳过或发布部分结果；构建整体失败不发布部分索引。
  - R0/T0 真实机器 ABI 冒烟（根打开 + 枚举 + 相对文件打开 + FileBasicInfo + FileStandardInfo + HANDLE→fd 读取 + 关闭一次 + 清理临时目录），失败即 `unsafe-open-unavailable`，绝不回退到字符串路径方案；链接专项测试（T7–T10）默认跳过（即使设置 `P3_ALLOW_FS_LINK_FIXTURES=1` 也仅为未实现门控占位，真实链接夹具尚不可用，不创建/不运行真实 symlink / junction；预期为拒绝/构建失败而非跳过）。
- 已实现（Slice B2a 离线 `create_task` 受控写入核心）：新增 `src/mcp_notes/tasks.py` 与 `src/mcp_notes/safe_task_write.py` —— 纯标准库、离线的受控写核心：`create_task` 严格数据合同（NFKC 归一 + 内含 URL/Shell/路径形态拒绝，`title 1..120` / `description 1..1000`）、PENDING/APPROVED/REJECTED/CANCELLED/EXPIRED 人工确认状态机、sqlite3 持久化（`confirmations`/`idempotency`/`audit` 三表，审计不存正文）、任务文件 no-replace 原子发布（Windows 原生 `NtCreateFile(FILE_CREATE, OBJ_DONT_REPARSE)` 原子无覆盖，任务根/祖先目录经 `open_task_root` 逐级 `NtOpenFile(OBJ_DONT_REPARSE)` 句柄验证，reparse→失败关闭 `task-root-unsafe`，绝不回退字符串路径；冲突不覆盖）。固定金标准 `evals/gold/tasks-core-v1.json`（12 场景）+ `tests/test_create_task.py`（53 项）。`create_task` 只建待确认意图，不写任务文件；批准在 Tool 外由可信本地上下文（`TrustedContext(subject, correlation_id)`）执行。**B2a 不含 MCP SDK/Server/Resource/stdio/Host/Client（属 B2b，未实现）**。
  - **任务根须预存在**：生产代码不创建任务根或其祖先目录（已移除 `os.makedirs`），只做句柄链原生验证；根不存在 / 非目录 / reparse / 原生不可用 → 失败关闭 `task-root-unsafe`，不写文件。
  - **创建成功后写入失败的处理**：JSON 序列化先于 `NtCreateFile`；文件创建成功后 `WriteFile` / `FlushFileBuffers` 任一失败 → 稳定 `task-write-failed`（不泄露原始异常），文件 HANDLE 只关闭一次，随后对已验证父目录 HANDLE 相对 `NtDeleteFile` 清理（不使用 `os.remove` / `os.replace`）。经 3 项故障注入回归实测：无最终文件、无半成品 / 临时残留，确认记录保持 `PENDING`，移除故障后重放可成功创建。
  - **发布与状态提交顺序**：文件发布成功后再提交 `APPROVED` 状态；发布失败时确认记录保持 `PENDING`。
- 未做（仍属计划 / B2b）：MCP Server 适配层与 Resource `notes://service-info`、Tool 注册、stdio transport、真实 Host/Client 演示。
- 当前没有 `.venv`、依赖锁文件、MCP Server、MCP Host/Client、真实笔记、模型调用、网络访问或部署；Slice A+B1+B2a 仅用标准库，未安装任何依赖。
- 计划仅使用原创虚构离线笔记夹具；不读取用户私人笔记。

## Slice A 离线验证

Slice A 仅用 CPython 标准库实现，**无需 `.venv`、无需安装任何依赖**。在任意 Python 3.13/3.14 解释器下即可复跑：

```powershell
Set-Location projects\03-mcp-tool-server
python --version
python -m compileall -q src tests
python -m unittest discover -s tests -v
```

预期：`compileall` 通过；B2a 子集 **53 项**（`tests/test_create_task.py`，全部执行通过，无 skip）；stdlib `unittest` 总计 **125 项**（`discover -s tests`），其中 121 项执行通过、4 项链接专项测试（T7–T10）默认跳过（即使设置 `P3_ALLOW_FS_LINK_FIXTURES=1` 也仅为未实现门控占位，真实链接夹具尚不可用，绝不创建/运行真实 symlink / junction；预期为拒绝/构建失败而非跳过）。Slice A 既有检索/合同/网络阻断测试全部保留并通过；B1 新增句柄级路径安全测试（T0–T9，含原生冒烟、正常布局硬边界、句柄链读取、reparse 致构建失败、失败关闭、畸形缓冲、内容过大、伪造条目路径逃逸、文件属性判定、组件校验等失败回归）；B2a 新增受控写核心测试（12 金标准场景 + 非法参数、无确认不写文件、网络阻断、敏感扫描、字段校验、双绑定、已消费不被过期改写、真实 no-replace 竞态、任务根安全边界、上下文严格校验、confirmation_id 不回显，以及“创建成功后写入失败”3 项故障注入回归——`WriteFile` 失败 / `FlushFileBuffers` 失败 / `approve` 路径写入失败，均为清理成功路径，各自断言返回 `task-write-failed`、任务目录无残留、状态保持 `PENDING` 且重试可成功；另有 4 项收口回归——冲突文件只读回查的 `open_osfhandle` 失败 / `fdopen` 失败 / `read` 失败（各断言返回稳定 `task-write-failed`、不泄露原始异常、确认保持 `PENDING`，且退出 mock 后冲突文件可被立即删除、证明 HANDLE/fd 已释放无遗留锁）与 `NtDeleteFile` 非成功 NTSTATUS（断言返回脱敏稳定 `task-write-failed`、不回显 NTSTATUS/路径、确认保持 `PENDING`、且**不错误断言目录必空**））。真实 MCP Server/Host/Client 运行结果尚未产生，属于 Slice B2b 之后。

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
