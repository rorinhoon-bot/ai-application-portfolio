# P3：本地 MCP 笔记检索与受控任务创建服务

系统集成作品。规划基线已完成；`search_notes` 的纯标准库核心（数据合同、索引登记、离线检索、单测）已实现并通过离线验证；路径安全、`create_task`、MCP SDK 适配仍为计划，未实现。

目标：后续实现一个本地 MCP Server，提供只读 `search_notes(keyword)`、受控写 `create_task(title, description)` 与一个只读 Resource。服务只能检索配置的笔记白名单目录；任务写入必须经过人工确认，且不能覆盖既有任务。

## 当前阶段

- 状态：`in_progress`（Slice A 已实现并离线验证；Slice B1 路径安全索引已实现并离线验证；待进入 Slice B2 `create_task` 状态机与 MCP SDK 适配）。
- 已实现（Slice A）：`src/mcp_notes/` 纯标准库合同与检索逻辑、`evals/fixtures/notes-v1/` 3 份原创虚构笔记、`tests/` stdlib `unittest` 套件（含默认网络阻断底座）。
- 已实现（Slice B1 路径安全索引）：新增 `src/mcp_notes/safe_open.py` —— 基于 Windows 原生句柄（`NtOpenFile` / `NtQueryDirectoryFile`，`OBJ_DONT_REPARSE` + 相对父 HANDLE）拒绝 symlink / junction / reparse point 跟随与 TOCTOU。具体已落实并通过测试（Codex P0/P1 修订）：
  - 组件级校验（§4.6）拒绝空段、`.`、`..`、`\`、`/`、`:`、`< > " | ? *`、控制字符、尾随点 / 空格、保留设备名；`open_file_relative` 先校验 `rel_parts` 为非空列表并对每一级组件校验；`_nt_open` 在相对父 HANDLE 打开时**也自行校验组件**，不依赖调用方。
  - 文件打开（非目录）携带 `FILE_READ_ATTRIBUTES`，打开后查询 `WIN32_FILE_BASIC_INFO` 拒绝 DIRECTORY / REPARSE_POINT / DEVICE，再查询 `WIN32_FILE_STANDARD_INFO` 做容量上限（`> MAX_NOTE_BYTES`(1 MiB) → `content-too-large`）；任一查询失败 → `io-error`。
  - 枚举（`NtQueryDirectoryFile`）缓冲区解析遵循 §4.4 硬边界逐字段断言（新增 `buffer_length` 参数并断言 `0 < Information <= buffer_length`；`NextEntryOffset` 非 0 时须 `>= 固定头长`、`8` 字节对齐、`record_start < record_end <= Information`；`FileName` 区域不得越过 `record_end`；UTF-16LE 解码异常 → `io-error`）；任何越界 / 畸形 / `Information==0` / 非成功状态 / `BUFFER_OVERFLOW` 一律 `io-error`，绝不返回部分枚举结果。
  - 根配置门拒绝 `..` / UNC / 设备前缀 / 正斜杠混用 / 相对路径；`UNICODE_STRING.Length/MaximumLength` 按真实 UTF-16LE 字节数计算并拒绝超过 `USHORT` 上限；`IO_STATUS_BLOCK` 的 `Status` 用 32 位 `c_long`、`Information` 用指针宽度 `c_size_t`（不写死 `c_ulonglong`）。
  - 失败关闭与事务语义（§9）：reparse 条目 → `_walk` 抛 `not-allowed-reparse`（不 `continue` 跳过）→ `build_index` 整体失败 `index-build-failed`；超大文件使本次构建失败并丢弃新索引，绝不静默跳过或发布部分结果；构建整体失败不发布部分索引。
  - R0/T0 真实机器 ABI 冒烟（根打开 + 枚举 + 相对文件打开 + FileBasicInfo + FileStandardInfo + HANDLE→fd 读取 + 关闭一次 + 清理临时目录），失败即 `unsafe-open-unavailable`，绝不回退到字符串路径方案；链接专项测试（T7–T10）默认跳过（即使设置 `P3_ALLOW_FS_LINK_FIXTURES=1` 也仅为未实现门控占位，真实链接夹具尚不可用，不创建/不运行真实 symlink / junction；预期为拒绝/构建失败而非跳过）。
- 未做（仍属计划）：`create_task` 待确认意图与人工确认状态机、sqlite3 持久化、MCP Server 适配层与 Resource、真实 Host/Client 演示。
- 当前没有 `.venv`、依赖锁文件、MCP Server、MCP Host/Client、真实笔记、模型调用、网络访问或部署；Slice A+B1 仅用标准库，未安装任何依赖。
- 计划仅使用原创虚构离线笔记夹具；不读取用户私人笔记。

## Slice A 离线验证

Slice A 仅用 CPython 标准库实现，**无需 `.venv`、无需安装任何依赖**。在任意 Python 3.13/3.14 解释器下即可复跑：

```powershell
Set-Location projects\03-mcp-tool-server
python --version
python -m compileall -q src tests
python -m unittest discover -s tests -v
```

预期：`compileall` 通过；B1 新增 30 项；总计 72 项（`discover -s tests`），其中 68 项执行通过、4 项链接专项测试（T7–T10）默认跳过（即使设置 `P3_ALLOW_FS_LINK_FIXTURES=1` 也仅为未实现门控占位，真实链接夹具尚不可用，绝不创建/运行真实 symlink / junction；预期为拒绝/构建失败而非跳过）。Slice A 既有检索/合同/网络阻断测试全部保留并通过；B1 新增句柄级路径安全测试（T0–T9，含原生冒烟、正常布局硬边界、句柄链读取、reparse 致构建失败、失败关闭、畸形缓冲、内容过大、伪造条目路径逃逸、文件属性判定、组件校验等失败回归）。真实 MCP Server/Host/Client 运行结果尚未产生，属于 Slice B2 之后。

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
