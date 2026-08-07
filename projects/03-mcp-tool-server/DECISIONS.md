# DECISIONS

## D-001：固定为本地 MCP 笔记检索与受控任务创建场景

- 状态：accepted
- 日期：2026-08-01
- 决定：后续只提供 `search_notes(keyword)`、`create_task(title, description)` 和一个只读服务说明 Resource。
- 原因：足以证明 MCP Tool、Resource、Schema、文件边界和写操作 Human-in-the-loop；不把作品扩展成通用文件系统或任务管理平台。

## D-002：Tool 参数不携带路径、文件名、命令、URL 或 Shell 参数

- 状态：accepted
- 日期：2026-08-01
- 决定：`search_notes` 仅接收受限字符串 `keyword`；`create_task` 仅接收受限纯文本 `title`、`description`。工具 Schema 拒绝未知字段、对象/数组、绝对路径、`..`、URL、命令和 Shell 语义输入。
- 原因：模型或客户端提出的内容不是权限。文件位置、任务 ID、写入目录和执行方式只能由服务配置或程序派生。

## D-003：笔记目录使用配置白名单和拒绝式文件系统检查

- 状态：accepted
- 日期：2026-08-01
- 决定：后续只从应用配置的笔记根目录建立受控索引；拒绝根目录及祖先或候选条目中的符号链接、Windows junction/reparse point、非普通文件、未登记文件和规范路径逃逸。
- 原因：仅做字符串前缀判断无法抵抗链接、junction、重解析点和 TOCTOU。
- 边界：若目标平台不能可靠验证最终打开对象，服务安全失败，不降级为“尽力读取”。

## D-004：写 Tool 只创建待确认意图，人工批准在 MCP Tool 外完成

- 状态：accepted
- 日期：2026-08-01
- 决定：`create_task` 返回待确认请求，不直接写任务文件。可信本地人工确认界面/命令在 Tool 外批准、拒绝或取消；批准绑定主体、请求、内容哈希和过期时间。
- 原因：MCP Client、模型和笔记正文都不能代表人类写入授权。

## D-005：确认有效期为十分钟，且只能消费一次

- 状态：accepted
- 日期：2026-08-01
- 决定：待确认请求在创建后十分钟失效；批准前验证同一可信主体、请求 ID、内容哈希和 `PENDING` 状态。旧确认、身份错绑、重复批准和已取消请求全部拒绝。
- 原因：确认必须对应人眼看过的具体内容，不能变成可重放的长期写入票据。

## D-006：服务生成稳定任务 ID，写入使用不可覆盖原子发布

- 状态：accepted
- 日期：2026-08-01
- 决定：首次意图创建即生成受限格式 `task_id`，持久化绑定可信调用关联 ID 与内容哈希；目标仅能由程序派生为受控任务目录中的 `<task_id>.json`。重复关联 ID 返回原结果；同一任务重复批准返回幂等结果；冲突绝不覆盖。
- 原因：稳定身份和 no-replace 发布同时处理协议重试、人工重复操作与进程崩溃窗口。

## D-007：使用标准库 SQLite 规划持久化，不引入数据库服务

- 状态：accepted
- 日期：2026-08-01
- 决定：后续若实施，确认记录、幂等映射和最小审计事件使用 CPython 标准库 `sqlite3`；不引入 PostgreSQL、Redis 或云数据库。
- 原因：本地单用户演示需要跨进程保持确认和幂等事实，但不值得增加服务进程、网络端口、凭据或运维面。

## D-008：首批数据与评估完全离线、原创、确定性

- 状态：accepted
- 日期：2026-08-01
- 决定：后续创建虚构笔记夹具、冻结快照和金标准；普通测试默认阻断网络。
- 原因：先验证协议与安全边界，不读取真实私人笔记，不把模型随机性或网页变化混入基线。

## D-009：默认单服务，不引入多智能体、向量库或 Web 框架

- 状态：accepted
- 日期：2026-08-01
- 决定：首版使用确定性关键词检索和 MCP SDK；不默认加入模型、Agent、多智能体、Embedding、向量库、Web UI 或 HTTP 服务。
- 原因：P3 要证明的是受控工具服务。额外系统会扩大依赖、安全面和学习负担，且不能改善当前验收。

## D-010：真实 MCP Host/Client 演示独立于当前规划

- 状态：accepted
- 日期：2026-08-01
- 决定：当前只设计未来 stdio 本地 Server 与真实 Host/Client 成功、拒绝和错误路径演示；不伪称已接入。
- 原因：规划文档不能替代协议运行证据。接入前必须先完成离线单元和集成测试。

## D-011：Slice A 实现范围与临时测试底座

- 状态：accepted
- 日期：2026-08-01
- 决定：Slice A 只实现 `search_notes` 的纯标准库数据合同、索引登记、离线检索与 stdlib `unittest`；不接触 MCP SDK、不建 `.venv`、不安装依赖、不读真实笔记、不发起对外网络连接。
- 参数锁定：note_id 由 relative_path 的 SHA-256 前 16 位派生；excerpt 内部文本上限 120 字符；匹配为大小写无关 + Unicode NFKC 归一；hits 上限 5，按索引顺序返回。
- 测试底座：当前用 CPython 标准库 `unittest`（`python -m unittest`）直接运行，避免提前引入 pytest 与安装步骤；后续统一测试框架待安装批准时再决定。
- 边界：`index.py` 当前仅做最小普通 `.md` 文件登记，未实现 symlink/junction/reparse point/路径穿越/TOCTOU 的拒绝式检查；这些属于 Slice B，未因 Slice A 提前放宽。
- 结果：`compileall` 通过；27 项 stdlib 单元测试全部通过；测试期默认阻断外部网络、无依赖、无密钥。

## D-012：P1 安全加固的确定性边界（Codex 验收项）

- 状态：accepted
- 日期：2026-08-01
- 决定：针对 Codex 验收列出的 P1 项，在 Slice A 基础上固化以下不可绕过边界：
  - **NFKC 优先于形态拒绝**：`validate_keyword` 先 `unicodedata.normalize("NFKC", raw)` 再 `strip`，随后才执行绝对路径/`..`/URL scheme/Shell 语义拒绝。防止全角 `／＼：｜＜＞＆＄（` 经归一后变成危险形态绕过。Keyword.value 存储归一化结果。
  - **匹配用 NFKC + casefold**：比 `lower()` 更强，覆盖德文 ß→ss 等 Unicode 大小写折叠，确定性、可逆解释。
  - **hits 与 excerpt 硬上限**：`MAX_HITS=5`、`EXCERPT_MAX=120` 为模块常量；`search_notes` 不再接收可放大的 `max_hits`/`excerpt_max` 参数。excerpt 以“最终转义文本 + 省略号”的真实长度计入预算，确保结果长度必 <= 120。
  - **非法参数返回稳定错误对象**：`validate_keyword` / `parse_search_notes_args` 非法时返回 `ArgumentError(error_code="invalid-arguments")`，不再返回 None；对外可稳定映射错误码，不泄露路径/正文/异常。
  - **标题按不可信数据净化**：`index.extract_title` 经 `sanitize_title` 去控制字符、转义 HTML、限长（TITLE_MAX=80，含省略号）；检索层直接复用已净化标题，不做二次转义以避免实体被重复转义。
  - **默认网络阻断底座**：新增 `tests/_network_block.py` 的 `NetworkBlockedTestCase`，在 `setUp` 替换 socket 核心入口并 `tearDown` 还原；普通单测默认继承，任何 DNS/socket/HTTP 尝试立即失败。
- 原因：这些边界是 Codex 验收明确指出的可被绕过或缺失项；固化后调用方与外部输入均无法放大长度、伪造路径/URL/Shell、或静默联网。
- 结果：`compileall` 通过；38 项 stdlib 单元测试全部通过（含 3 个全角绕过反例、1 个 casefold Unicode 反例、网络阻断验证 5 项）；测试期默认阻断外部网络、无依赖、无密钥。

## D-013：Slice B1 句柄级路径安全索引实现（v6 合同 + Codex P0/P1 修订）

- 状态：accepted
- 日期：2026-08-02
- 决定：路径安全检查通过 Windows 原生对象管理器 API 实现，而非字符串路径遍历：
  - 仅用 `NtOpenFile`（携带 `OBJ_DONT_REPARSE`，相对已验证父目录 HANDLE 打开）与 `NtQueryDirectoryFile`（class=1 = `FileDirectoryInformation`）做枚举与读取；**不**使用 `os.scandir` / `os.walk` / `glob` / `Path.rglob` / `os.path.realpath`，以抵御 reparse point 跟随与 TOCTOU（T6 静态校验源码不含这些 API）。
  - 缓冲区解析遵循 §4.4 硬边界逐字段断言（新增 `buffer_length` 参数并断言 `0 < Information <= buffer_length`；固定头长度用 `FileName.offset` 而非 `sizeof`；`FileNameLength` 偶数字节；`NextEntryOffset==0` → `record_end=Information` 且本批结束，`NextEntryOffset!=0` 须 `>= 固定头长`、`8` 字节对齐、`record_start < record_end <= Information`；`FileName` 区域不得越过 `record_end`；UTF-16LE 解码异常 → `io-error`）；任何越界 / 畸形 / `Information==0` / 非成功状态 / `BUFFER_OVERFLOW` 一律 `io-error`，绝不返回部分枚举结果。
  - 根配置门先拒绝 `..` / UNC / `\\?\` / `\\.\` / `\Device\` / 正斜杠混用 / 相对路径，再接受本地盘符绝对路径，`ObjectName = "\\??\\" + 归一化`；`UNICODE_STRING.Length/MaximumLength` 按真实 `name.encode("utf-16-le")` 字节数计算并拒绝超过 `USHORT` 上限，底层 UTF-16 缓冲（`create_unicode_buffer`）经 `cast` 持有引用并在 Native 调用期间存活。
  - 组件级校验（§4.6）拒绝空段、`.`、`..`、`\`、`/`、`:`、`< > " | ? *`、控制字符、尾随点 / 空格、保留设备名；`open_file_relative` 先校验 `rel_parts` 为非空列表并对每一级组件校验；`_nt_open` 在相对父 HANDLE 打开时**也自行校验组件**，不依赖调用方。
  - 文件打开（非目录）携带 `FILE_READ_ATTRIBUTES`，打开后查询 `WIN32_FILE_BASIC_INFO` 拒绝 DIRECTORY / REPARSE_POINT / DEVICE，再查询 `WIN32_FILE_STANDARD_INFO` 做容量上限（`> MAX_NOTE_BYTES`(1 MiB) → `content-too-large`）；任一查询失败 → `io-error`。Win32 与 Native 枚举使用不同具名常量（`WIN32_FILE_BASIC_INFO=0` / `WIN32_FILE_STANDARD_INFO=1` / `NATIVE_FILE_DIRECTORY_INFORMATION=1`），`GetFileInformationByHandleEx` 第二参数用 `wintypes.DWORD`，避免两类枚举数值巧合而混淆；`IO_STATUS_BLOCK` 的 `Status` 用 32 位 `c_long`、`Information` 用指针宽度 `c_size_t`（不写死 `c_ulonglong`）。
  - R0 / T0 真实机器 ABI 冒烟（根打开 + 枚举 + 相对文件打开 + `FileBasicInfo` + `FileStandardInfo` + HANDLE→fd 读取 + 关闭一次 + 清理临时目录）；若失败抛 `unsafe-open-unavailable`，**绝不回退**到字符串路径方案（满足 D-003 “安全失败，不降级为尽力读取”）。
  - 失败关闭与事务语义（§9）：reparse 条目 → `_walk` 抛 `not-allowed-reparse`（**不** `continue` 跳过、不继续构建）→ `build_index` 整体失败 `index-build-failed`；**超大文件使本次构建失败并丢弃新索引，绝不静默跳过或发布部分结果**；构建整体失败（原生不可用 / 配置非法 / IO 错误 / reparse / 超大）时整体失败、不发布部分索引。`index.py` 经该层构建 `.md` 索引与读取正文，保留 Slice A 全部字段（note_id / title / relative_path / size / sha256）与检索行为。
  - 所有失败映射为稳定错误码，不泄露路径、用户名、环境变量或原始系统错误文本。
- 原因：仅做字符串前缀判断无法抵抗链接、junction、重解析点和 TOCTOU；句柄级打开能在打开对象这一刻原子地拒绝 reparse，且不依赖不可信的路径字符串解析。
- 边界：链接专项测试（T7–T10）默认跳过，即使设置 `P3_ALLOW_FS_LINK_FIXTURES=1` 也仅为未实现门控占位（真实 symlink / junction 夹具尚不可用，按授权禁止创建或运行）；预期行为为拒绝/构建失败（任何 reparse → `not-allowed-reparse` → `index-build-failed`），而非跳过。B1 仅在 Windows 原生 API 可用时启用，非 Windows 平台 R0 安全失败。
- 结果：`compileall` 通过；B1 新增 T0–T9 共 30 项 + Slice A 既有测试全部保留并通过；stdlib `unittest` 共 72 项（68 执行通过 + 4 链接测试默认跳过）；测试期默认阻断外部网络、无依赖、无密钥。经 Codex 二次独立复验未通过后，按 P0/P1 清单修订 `UNICODE_STRING.MaximumLength` 溢出边界并补失败回归测试、统一真实链接测试合同与文档测试数，复跑 72 项全部通过。

## D-014：Slice B2a 离线 `create_task` 受控写入核心实现（纯标准库）

- 状态：accepted
- 日期：2026-08-02
- 决定：`create_task` 离线核心按 D-002/D-004/D-005/D-006/D-007 落地，新增 `src/mcp_notes/tasks.py`，**不**引入 MCP SDK/Server/Resource/stdio/Host/Client（属后续 C 阶段，现已实现，见 D-017）。
  - **数据合同**：`validate_task_field` 沿用 `validate_keyword` 的“NFKC 归一 → 去空白 → 长度 → 控制字符 → 路径形态”顺序；URL/Shell 判定由“前缀”改为“内含”（`prefix in low` + `_has_shell_token`），拦截中部文本（如 `参见 http://example.com`）；`title 1..120`、`description 1..1000`；绝对路径（`/`/`\` 开头）、盘符前缀（`X:`）、`..` 段均拒绝。空/超长/非字符串/含控制字符/路径/URL/Shell/未知字段 → `invalid-arguments`，不读不写。
  - **状态机**：PENDING →（approve 成功且任务文件经 no-replace 原子发布**成功**）才提交 `APPROVED`——即“**文件发布成功后再提交 APPROVED**”；发布失败（写入 / 刷新失败或任务根不安全）则保持 `PENDING`，不写 `APPROVED`。（reject/cancel）REJECTED/CANCELLED（终态负向，不可再消费）；（批准时已超过 10 分钟）EXPIRED（懒求值，仅 PENDING 转，已消费不动）。`create_task` 只建 PENDING 意图，绝不写文件。
  - **身份与过期绑定**：批准主体必须 == 创建主体（否则 `confirmation-identity-mismatch`）；缺失记录 / 已非 PENDING / 过期分别为 `confirmation-required` / `confirmation-mismatch` / `confirmation-expired`，均不写文件。`TrustedContext(subject, correlation_id)` 由本地 Host 适配器在 Tool 外注入，不在 Tool 参数内（满足 D-002/D-004）。
  - **稳定 ID 与幂等**：`content_hash = SHA256(规范title‖规范desc)`；`task_id = "task-" + SHA256(subject‖correlation_id‖content_hash)[:16]`；`confirmation_id = "conf-" + SHA256(task_id‖content_hash)[:16]`。同主体+同关联ID+同内容重放返回安全结果（PENDING→`pending`、APPROVED→`unchanged`、EXPIRED→`confirmation-expired`、REJECTED/CANCELLED→`confirmation-mismatch`）；同关联ID+不同内容 → `idempotency-conflict`（不新建意图）；重复批准 → `unchanged` + `confirmation-already-consumed`（绝不二次写）。
  - **no-replace 原子发布（P0-3/P0-4）**：最终路径仅由 `task_id` 派生为 `<task_root>/<task_id>.json`，**绝不接受外部路径**；发布由新增 `src/mcp_notes/safe_task_write.py` 用 Windows 原生 `NtCreateFile(FILE_CREATE, OBJ_DONT_REPARSE)` 原子无覆盖创建完成（**非** `os.replace`、无“先检查再发布”的竞态窗口），成功才写内容并 `FlushFileBuffers`；任务根与各级祖先目录经 `open_task_root` 逐级 `NtOpenFile(OBJ_DONT_REPARSE)` 句柄验证（B1 同等级 reparse/TOCTOU 防护），任何 reparse 点 → 失败关闭 `task-root-unsafe`，**绝不回退字符串路径方案**。目标已存在：同内容 → `unchanged`，不同内容 → `task-conflict`（绝不覆盖、目标字节不变）；写失败（`OSError`/`STATUS` 非成功）→ `task-write-failed`（创建成功后的写入失败处理与残留清理见 D-015）；`task_id` 形态不符（非 `^[A-Za-z0-9-]{4,64}$`）→ `task-invalid-id`。非 Windows 或原生 API 不可用 → 失败关闭 `task-root-unsafe`，不降级为字符串路径写。
  - **持久化（D-007）**：标准库 `sqlite3`，三表 `confirmations` / `idempotency` / `audit`；所有写包在 `try/except sqlite3.Error → rollback`；`audit` 仅存稳定事件类型、错误码、`task_id`/`confirmation_id` 的安全标识，**不存 title/description/正文**。
  - **稳定错误码（12 类）**：`invalid-arguments` / `confirmation-required` / `confirmation-identity-mismatch` / `confirmation-mismatch` / `confirmation-expired` / `confirmation-already-consumed` / `confirmation-invalid-id` / `idempotency-conflict` / `task-conflict` / `task-write-failed` / `task-invalid-id` / `task-root-unsafe`；均不泄露路径/正文/原始异常（P1-6：`confirmation-invalid-id` / `confirmation-required` 等错误结果绝不回显任意 `confirmation_id` 输入）。
  - **可测性**：所有时间经由构造注入的 `clock`（测试可前进 `advance`），不依赖真实 `time.time`；默认网络阻断底座对所有 B2a 用例生效；固定金标准 `evals/gold/tasks-core-v1.json`（12 场景）驱动场景测试。
- 原因：先用纯标准库把“确认状态机 + 幂等 + 不可覆盖原子发布 + 持久化”这一最难的安全核心离线钉死，再接 MCP 适配；避免把安全逻辑与 SDK/transport 混在一起难以审计。
- 边界：B2a 不创建真实 symlink/junction、不下载数据、不读私人笔记、不发起对外网络连接、不调模型、不部署；测试只使用系统临时目录与原创虚构夹具。MCP Server/Resource/Host/Client（C 阶段）现已实现，见 D-017。
- 结果：`compileall` 通过；`tests/test_create_task.py` **53 项**全部通过（含 D-015 新增的 3 项写入失败回归，及后续冲突只读转换失败 3 项 + 删除失败 1 项收口回归）；stdlib `unittest` 总计 **125 项**（121 执行通过 + 4 链接测试默认跳过）；新增源码与金标准经敏感扫描（`sk-` 负向后顾模式）无真实密钥命中；`git diff --check` 通过。

## D-015：任务文件发布的失败语义与任务根所有权（B2a 第二轮复验修订）

- 状态：accepted
- 日期：2026-08-02
- 背景：第一轮 B2a 实现虽然做到了 no-replace 原子创建，但“`NtCreateFile` 已成功创建最终文件之后再写入失败”这条路径没有被正确处理——序列化在创建之后、失败可能外泄原始异常、清理依赖字符串路径、且存在 `open_osfhandle` 转移后又关闭同一 HANDLE 的双重关闭隐患；同时生产代码用 `os.makedirs` 自建任务根，与“任务根是部署配置中的受控目录”这一安全前提冲突。
- 决定：
  - **序列化前置**：`json.dumps` 在 `NtCreateFile` **之前**执行；序列化失败直接 `SafeWriteError("task-write-failed")`，此时磁盘上不会出现任何文件。
  - **创建后失败统一语义**：文件创建成功后，`WriteFile`（循环写全量）与 `FlushFileBuffers` 任一失败一律映射稳定 `SafeWriteError("task-write-failed")`，上层 `TaskResult.error("task-write-failed", task_id=服务派生ID)`；**不向调用方泄露任何原始异常/系统错误文本**。
  - **HANDLE 所有权唯一**：文件 HANDLE 由写入函数独占，成功与失败路径都**只关闭一次**；移除写路径上的 `open_osfhandle`（避免 fd 与 HANDLE 双重所有权导致的双重关闭）。
  - **清理只用句柄原生操作**：失败后**先关闭文件 HANDLE**，再以**已验证的父目录 HANDLE** 为 `RootDirectory`、带 `OBJ_DONT_REPARSE` 调用 `NtDeleteFile` 删除残留；**绝不使用字符串路径 `os.remove` / `os.replace` 或任何字符串路径回退**。清理为 best-effort，其自身异常不改变已确定的稳定错误码。
    - 取舍说明：本机环境下句柄级 delete-on-close（`NtSetInformationFile(FileDispositionInformation/Ex)`、`SetFileInformationByHandle(FileDispositionInfo/Ex)`）即使 HANDLE 已授予 `DELETE` 也一律返回 `ACCESS_DENIED`，唯一可用且仍满足“仅句柄原生操作”的方式是相对父目录 HANDLE 的 `NtDeleteFile`；而 `NtDeleteFile` 在文件自身独占句柄未关闭时返回 `SHARING_VIOLATION`，故顺序固定为“先关句柄、后删除”。
  - **任务根所有权归部署配置**：生产代码移除 `os.makedirs(self._task_root, exist_ok=True)`（`tasks.py` 已不再 `import os`），**不创建任务根或任何祖先目录**；只做 `open_task_root` 句柄链原生验证。根不存在 / 非目录 / reparse / 原生不可用 → 失败关闭 `task-root-unsafe`，不写文件、不回退字符串路径。测试夹具在临时目录中自行预建任务根，属测试环境准备，不代表生产行为。
  - **发布与状态提交顺序**：确认记录仅在任务文件发布**成功**后才提交 `APPROVED`；发布失败则保持 `PENDING`——**清理成功（`NtDeleteFile` 返回 `STATUS_SUCCESS`）可移除故障后安全重放并成功创建；清理失败（非成功 NTSTATUS）则失败关闭，仅返回稳定 `task-write-failed`，不承诺零残留或自动重试成功**。
  - **`TrustedContext` 描述纠偏**：实际校验规则只有“必须是 `str`、长度 `1..256`、不含 C0/DEL 控制字符”，**未实现安全字符白名单**；本轮选择“文档改为实际规则”而非新增白名单实现（新增白名单会改变已固化的合法输入集合，属扩范围）。
- 原因：把“创建成功后失败”这条最容易留下半成品的路径钉死为可预测的稳定错误码 +（清理成功路径）零残留 + 可重试，是受控写核心可被信任的前提；任务根由部署配置预置则避免服务自身具备创建目录树的权限，缩小写权限面。清理失败（非成功 NTSTATUS）必须失败关闭、不承诺零残留或自动重试成功，绝不静默吞掉。
- 边界：不新增依赖、不发起对外网络连接、不改 P2；不因清理需求引入任何字符串路径删除；非 Windows / 原生不可用仍是失败关闭而非降级。
- 结果：新增 3 项真实回归（`WriteFile` 失败 / `FlushFileBuffers` 失败 / `approve` 路径写入失败，均为清理成功路径），断言无原始异常外泄、返回 `task-write-failed`、任务目录 `.json` 计数为 0 且无临时残留、确认状态保持 `PENDING`、移除故障后重放返回 `created`。`compileall` 通过；`test_create_task.py` 53 项通过；stdlib `unittest` 总计 125 项（121 执行通过 + 4 链接测试默认跳过）；`git diff --check` 通过。

## D-016：冲突只读回查 `_read_existing_json` 的 HANDLE/fd 所有权与关闭（B2a 第三轮复验修订）

- 状态：accepted
- 日期：2026-08-06
- 背景：第二轮复验（D-015 续）已将 `open_osfhandle` / `fdopen` / `read` 阶段的 `OSError` 统一映射为稳定 `SafeWriteError("task-write-failed")`，但资源释放的 `finally` 仍挂在 JSON 解码那一层的 `try` 上，不在 `open_osfhandle`/`fdopen`/`read` 失败路径上执行——于是这些阶段抛错时，仍由本函数持有的 `fh`（HANDLE）或 `fd` 不会被关闭，冲突文件被遗留锁住，且上层可能泄露原始异常文本。Codex 独立复现：预热 `verify_native_support()`、制造同 `task_id` 冲突文件、注入 `msvcrt.open_osfhandle` 抛 `OSError`，`store.approve()` 虽返回稳定码，但冲突文件仍被锁定（无法删除/重命名）。
- 决定：将 `_read_existing_json` 重构为**单一资源所有权作用域**，覆盖 `_nt_open → open_osfhandle → fdopen/read → JSON 解码` 完整生命周期：
  - `fh_owned` / `fd` / `f` 三个所有权标志在进入作用域前初始化；任意失败路径都精确关闭一次“仍归本函数所有”的资源，绝不重复关闭已转交文件对象的 `fd`。
  - `open_osfhandle` 失败 → `fh` 仍归本函数所有，`finally` 关闭 `fh`；`fdopen` 失败 → `fd` 仍归本函数所有，`finally` 关闭 `fd`；`read` 失败 → 真实 `fd` 已由 `f` 持有，`finally` 经 `f.close()` 关闭，不重复关闭 `fd`。
  - `finally` 内 `f.close()` / `os.close(fd)` / `_close(fh)` 各自包在 `try/except OSError` 中：关闭失败也**不**覆盖已确定的稳定错误码、不泄露原始 `OSError`。
  - 保持“已验证 HANDLE → fd”只读转换（保留 `open_osfhandle`），不改为纯 HANDLE 读取，绝不字符串路径回退。
- 新增回归（`tests/test_create_task.py::TestConflictReadonlyAndDeleteFailure`，均为真实冲突文件 → `approve` 分支）：`open_osfhandle` 失败 / `fdopen` 失败 / `read` 失败 三项，均断言返回稳定 `task-write-failed`、无原始异常文本、confirmation 保持 `PENDING`，且**退出 mock 后冲突文件可被立即 `os.remove`**（证明 HANDLE/fd 已释放、无遗留锁）。
- 原因：只读回查路径若泄漏 HANDLE/fd，会在写失败之外引入第二种“文件被锁、无法重试/清理”的故障面；把所有权钉死为单一作用域、关闭一次，是 no-replace 发布在冲突分支同样可被信任的前提。清理成功/失败的区分沿用 D-015：清理成功（`STATUS_SUCCESS`）无残留可重试，清理失败（非成功 NTSTATUS）失败关闭、不承诺零残留或自动重试成功。
- 边界：仅修 P0 + 文档，不扩范围、不新增依赖、不发起对外网络连接、不改 P2、不进入 C 阶段；未暂存/提交/push/PR。
- 结果：新增 2 项只读失败回归（`fdopen` / `read`），B2a 子集由 51 → **53** 项，stdlib `unittest` 总计 125 项（121 执行通过 + 4 链接测试默认跳过）；`compileall` 通过；`git diff --check` 通过。

## D-017：C 阶段 MCP Server / Resource / Host / Client 真实本地 stdio 接入（复用 B2a 离线核心）

- 状态：accepted
- 日期：2026-08-02
- 背景：B2a 把“确认状态机 + 幂等 + 不可覆盖原子发布 + 持久化”这一最难的安全核心离线钉死；C 阶段在其之上接入 MCP Python SDK v2（`mcp==2.0.0`），做真实本地 stdio 互通，证明协议边界、Tool/Resource 注册、Human-in-the-loop 与离线可评估性，且不复写安全核心。
- 决定：
  - **Server（v2 `MCPServer`，不用 FastMCP）**：`src/mcp_notes/server.py` 经 `build_server(config)` 构建，注册两个 Tool 与一个只读 Resource——`search_notes(keyword)`（复用 `search.py` 的 `search_notes`，只读已验证索引）、`create_task(title, description)`（仅建 PENDING 意图）、`notes://service-info`（静态 JSON 说明）。Tool 绝不接收路径、文件名、确认 ID、主体 ID、任务 ID 或目标目录（D-002/D-004 不变）。
  - **`TrustedContext` 服务端派生（关键不变量）**：`create_task` 内的 `TrustedContext(subject, correlation_id)` 中，`subject` 来自部署配置（`ServerConfig.subject`，可经 `MCP_NOTES_SUBJECT` 注入，默认固定测试主体）、`correlation_id` 由服务端对已验证、NFKC 规范化的 title/description 确定性派生；客户端不能直接提供或覆盖 correlation_id。它不是凭证、不授予批准权限；批准仍要求 Tool 外本地 Host、自身受控 subject 与记录匹配。这保证“谁发起写意图”由服务而非调用方决定。（`correlation_id` 的生成方式由 **D-018 取代**：从 `uuid4().hex` 改为内容派生 SHA-256，以获得重放幂等。）
  - **`approve`/`reject`/`cancel` 不在 Tool 表面（D-004 强化）**：这三个动作**绝不**注册为 MCP Tool（`list_tools` 验证只暴露 `search_notes` 与 `create_task`）；它们由本地可信 `TrustedHostController`（`src/mcp_notes/host.py`）在 Tool 外驱动，复用 B2a 的 `TasksStore`。（身份重建方式由 **D-018 取代**：删除 `approve_with_context`，改为 Host 用自身配置 `subject` + `TasksStore.lookup_correlation_id` 重建上下文。）
  - **sqlite 跨线程修复（安全核心零改动）**：MCP v2 在 worker 线程上跑 Tool handler，而 `sqlite3` 连接是线程绑定的；`create_task` handler 内**每次**重新实例化 `TasksStore`（并 `finally: store.close()`），不从 server-build 时复用连接。`safe_task_write.py` / `tasks.py` 的发布、no-replace、幂等、审计逻辑一律未改。
  - **stdio 集成测试（C4）**：`tests/test_mcp_integration.py` 用 v2 高层 `Client(stdio_client(StdioServerParameters(...)))` 真实拉起子进程 Server，覆盖——`list_tools` 不含确认动作、`search_notes` 成功 / 非法、`create_task` PENDING / 非法、`service-info` Resource、以及 Host `approve`/`reject`/`cancel`/`identity-mismatch`/`unknown` 全路径；默认仍继承网络阻断底座（仅放行本地 loopback 自管道）。
  - **固定离线评估（C5）**：`evals/gold/c-phase-v1.json`（11 场景固定期望）+ `evals/run_c_phase_eval.py`（v2 进程内 `Client(build_server(config))` 对比金标准）全部通过；评估只用原创虚构夹具，不读私人笔记、不调模型；运行时只用本地 stdio 管道、不发起对外网络连接。
  - **stdio 成功 + 失败演示（C3）**：`demo/mcp_stdio_demo.py` 真实子进程运行 8 项断言（含批准发布文件、未知确认 `confirmation-required`、身份错绑 `confirmation-identity-mismatch`），全部通过。
  - **依赖锁定**：唯一直接生产依赖 `mcp==2.0.0`（MIT）+ 29 传递依赖；安装经 Codex 批准，落盘 `requirements.lock.txt`，仅驻项目本地 `.venv`（约 74.6 MB）。测试中父进程与 Server 子进程均默认阻断外部网络。
- 原因：把“协议互通 + Human-in-the-loop”钉在已验证的安全核心之上，避免把确认/写入/幂等逻辑重新写进 Tool 表面，也不让调用方伪造身份。所有 B2a 安全不变量（no-replace 发布、审计不存正文、12 类稳定错误码、脱敏失败关闭）在 C 阶段全部沿用。
- 边界：C 阶段不复写 `safe_open.py`/`search.py`/`tasks.py`/`safe_task_write.py` 的安全逻辑；不接真实模型 API、不读私人笔记、不公开部署；运行时只用本地 stdio 管道、不发起对外网络连接；生产写仍只经句柄级 no-replace 发布层；不 push / 不建 PR，保持未提交待 Codex 统一复核。
- 结果（C7 已复跑确认）：`compileall` 通过；`tests/test_mcp_integration.py` **11 项**全部通过（默认网络阻断）；`evals/run_c_phase_eval.py` **11 例**全部通过；`demo/mcp_stdio_demo.py` **8 项**断言全部通过；stdlib `unittest` 总计 **138 项**（134 执行通过 + 4 链接测试默认跳过，其中 11 项为 C 阶段新增的 stdio 集成测试、2 项为网络阻断底座自校验）；新增源码与金标准经敏感扫描（`sk-` 负向后顾模式）无真实密钥命中；`git diff --check` 通过；未暂存/提交/push/PR。
- known-limitations-for-D：当前 `TrustedContext` 仍仅做“`str`/长度 1..256/无 C0·DEL 控制字符”校验，**未实现安全字符白名单**；`subject` 来自部署配置但尚无更严格的运行时身份绑定（如进程/会话凭证）；单进程、非并发、非多用户；仅 Windows 原生 no-replace 发布路径经实机验证，跨平台一致性待 D；真实 Host 支持面（如第三方 MCP Client 兼容）未在 D 评估；公开部署不在本次范围。
- **本条已被 D-018 部分修订**（C 阶段 Codex 复核未通过后的 P0/P1 一次性修复）：`correlation_id` 生成方式、Host 身份绑定入口、Tool 参数失败脱敏、生产入口不建任务根、子进程网络阻断、依赖文档与网络口径均以 D-018 为准；本条结果段的测试计数为修订前的历史值，最新计数见 D-018。

## D-018：C 阶段 Codex 复核未通过后的 P0/P1 一次性修复（不出 C 阶段、不新增依赖）

- 状态：accepted
- 日期：2026-08-06
- 背景：C 阶段（D-017）提交 Codex 复核未通过，列出 5 项 P0 与 5 项 P1。本条在**不进入 D 阶段、不新增依赖、不提交 / 不 push / 不建 PR** 的前提下，一次性修复并重新完整验证。
- 决定（P0）：
  - **P0-1 生产入口不创建任务根**：`server.main()` 删除 `os.makedirs(config.task_root)`，只创建状态库所在目录（`os.path.dirname(config.db_path)`）。这恢复 D-015 不变量“任务根必须由部署配置预先存在，生产代码绝不创建任务根 / 祖先目录”；根不存在 → `open_task_root` 失败关闭 `task-root-unsafe`。测试 / 演示里的临时目录创建只作为夹具，不在生产路径上。新增 `tests/test_server_entry.py::test_production_entry_does_not_create_task_root` 证明配置 / 构建路径不会自建任务根。
  - **P0-2 Tool 参数失败必须稳定且脱敏**：MCP SDK v2 的 `Tool.run` 会把 Pydantic `ValidationError` 的 `str(e)` 原样塞进 `CallToolResult`（含 `errors.pydantic.dev` 链接与字段类型细节），且 `ArgModelBase` 未设 `extra='forbid'`（未知字段被静默忽略）。因此新增 `SafeMCPServer(MCPServer)` 覆写 `_handle_call_tool`：进入 SDK 校验前做形状守卫（参数非 dict / 未知字段 / 缺必填 / 值非 `str` → 直接返回 `{"status":"error","error_code":"invalid-arguments"}`），并把任何非 `MCPError` 异常统一收敛为同一响应。允许字段由 `_TOOL_ARG_SPEC` 单点声明。新增 4 项真实 stdio 集成测试，断言响应中不含 `pydantic` / `errors.pydantic.dev` / `ValidationError` / `Traceback`。
  - **P0-3 `create_task` 重放幂等（取舍已记录）**：`correlation_id` 从 `uuid4().hex` 改为 `_derive_correlation_id(title, description)` —— 对 NFKC 归一后的 `title + US + description`（`US` = `\x1f` 单元分隔符）取 SHA-256 十六进制。这样同一规范化请求重放会命中 `tasks.py` 既有的 `(subject, correlation_id, content_hash)` 幂等映射，返回**同一** `task_id` / `confirmation_id` / 同一条安全 PENDING 记录；不同内容派生不同 `correlation_id`，形成彼此独立的意图。客户端**仍不能**提供 `subject` 或 `correlation_id`（两者都不是 Tool 参数）。
    - **取舍**：内容派生使 `correlation_id` 成为“同主体下内容的确定性函数”，牺牲了 `uuid4` 的不可预测性——同一部署主体下，知道明文内容即可推出 `correlation_id`。可接受，因为 (a) `correlation_id` 不是凭证、不授予任何权限，批准仍需本地人工确认 + 记录主体匹配；(b) 它只与 `subject` 组合用于幂等去重，跨主体天然隔离；(c) 换来的是协议层重放不再产生重复 PENDING 记录与重复 `task_id`，消除“客户端重试即制造多份待确认写意图”的放大面。若未来需要不可预测的关联 ID，须改为“服务端持久化的随机 ID + 独立内容指纹列”，绝不能靠客户端传值。
  - **P0-4 Host 只能绑定自身配置主体**：删除 `TrustedHostController.approve_with_context`（任何可传入任意 `subject` 的入口都被移除）。`approve` / `reject` / `cancel` 统一经私有 `_rebuild_context(confirmation_id)`，用 `self._subject`（Host 自身部署配置）+ `TasksStore.lookup_correlation_id(confirmation_id)`（只回取关联 ID，不回取记录主体）重建 `TrustedContext`；记录主体与 Host 主体不一致时，由 `tasks.py` 既有校验返回 `confirmation-identity-mismatch` 且不写任何文件。新增测试：service-A 的 Host 对 service-B 的记录做 approve / reject / cancel 全部拒绝、无文件产出；离线评估的 `host_identity_mismatch` 场景也改用“另一部署主体的 Host”而非伪造上下文。
  - **P0-5 stdio Server 子进程默认阻断外部网络**：抽出 `src/mcp_notes/_network_block.py` 作为唯一实现（回环感知），父进程测试底座 `tests/_network_block.py` 与 Server 子进程共用。`server.main()` 调用 `maybe_install_network_block()`，**仅当**环境变量 `NETWORK_ACCESS_BLOCKED_IN_TESTS=1` 时安装；集成测试在拉起子进程时注入该变量。阻断 DNS 与外部 socket / HTTP，放行 stdio 管道与本地回环。**不改变生产网络能力、不引入 HTTP transport**。新增 2 项集成测试：子进程连外部地址被 `NETWORK_ACCESS_BLOCKED_IN_TESTS` 拒绝，回环连接不被该机制拦截；同批测试同时验证 stdio Tool / Resource 正常工作。
- 决定（P1）：
  - **P1-1 默认 `notes_root` 修正**：`ServerConfig.from_env` 的默认笔记根从 `src/evals/...`（错误的一级向上）改为仓库内 `evals/fixtures/notes-v1`（两级向上）。新增测试断言该默认路径存在、是目录且至少含 1 个 `.md`。
  - **P1-2 `docs/DEPENDENCIES.md` 重写**：删除“未安装 / 未建 .venv”等过期表述；记录唯一直接依赖 `mcp==2.0.0`（MIT）与全部 **29 个传递依赖**的确切版本、许可证来源、用途、Python 3.13 / Windows 兼容性；实际环境 Python **3.13.14**；`.venv` 实际体积 **74.6 MiB（78.2 MB）**，单位口径一致。
  - **P1-3 清理文档残留规划语**：README / STATUS / DECISIONS / PRD / ARCHITECTURE / EVALUATION_DATA / WORKBUDDY_HANDOFF 中“C 阶段仍规划中 / 后续”类表述全部改为与实现一致（含 ARCHITECTURE 组件表与 mermaid 参与者标签、PRD §6 验收标准与 §7 失败分类标题）。
  - **P1-4 清理 `.venv` 无效发行版**：删除 `site-packages/~ip` 与 `~ip-26.1.2.dist-info`（pip 自升级残留，导致 `Ignoring invalid distribution` 警告）。仅动项目 `.venv`，不触碰全局 Python。
  - **P1-5 网络口径更正**：不再宣称“无网络”。统一表述为“**运行时只用本地 stdio 管道，不发起对外网络连接；测试中父进程与 Server 子进程均默认阻断外部网络（放行 stdio 与本地回环）**”，并说明这是测试开关而非生产能力声明。
- 原因：五项 P0 都是“文档承诺与代码实际不一致”或“安全边界可被调用方绕过”的真问题（自建任务根破坏预存在根不变量、Pydantic 文本外泄内部实现、重放放大待确认写、Host 可传任意主体、子进程未受网络约束）。修在 C 阶段内比带进 D 阶段成本更低，也避免 D 阶段在错误基线上继续叠加。
- 边界：不新增任何依赖（`SafeMCPServer` 只用 SDK 已有符号，未 fork SDK）；不改 B2a 安全核心（`tasks.py` 仅**新增** `lookup_correlation_id`，`safe_task_write.py` 零改动）；不进入 D 阶段；不 push / 不建 PR；保持未暂存、未提交，等 Codex 一次复核。
- 结果（2026-08-06 完整复跑）：`compileall` 通过；stdlib `unittest` 总计 **149 项**（145 执行通过 + 4 链接测试默认跳过），其中 `tests/test_mcp_integration.py` **20 项** stdio 集成测试、`tests/test_server_entry.py` **2 项**入口 / 配置测试；`evals/run_c_phase_eval.py` **11 例**全部通过；`demo/mcp_stdio_demo.py` **8 项**断言全部通过；`python -m pip check` → `No broken requirements found.`（无 `Ignoring invalid distribution` 警告）；`git diff --check` 通过；`git diff --cached --quiet` 通过（暂存区为空）；改动全部保持未暂存、未提交。

## D-019：D 阶段范围与切片排序决策（规划）

- 状态：accepted（规划）
- 日期：2026-08-07
- 背景：C 阶段已本地提交 `94dd90d`（`feat(p3): add local mcp stdio integration`，22 文件），并经 Codex 安全核心复核通过；用户决定进入 D 阶段，但先定计划再小步实现，且不立即 push（等 P3 全部完成后再统一处理 push / PR）。
- 决定：D 阶段在 known-limitations-for-D 范围内做 6 个加固 / 补齐切片，验收标准已收紧（见 PRD §11 / ARCHITECTURE §7）：① D-1 身份格式与安全字符白名单——`subject` 精确字符集+长度上限、配置启动非法/缺失即失败关闭，`correlation_id` 必须匹配服务端派生格式 `^[0-9a-f]{64}$`（无前缀）、客户端永远不能提供或覆盖，完全保留 C 阶段合同；② D-2 跨平台原子发布——fd 链式 `openat(dir_fd,O_NOFOLLOW)`+`fstat` 逐级验证，禁止字符串路径回退与 `realpath` 安全判断，平台缺能力稳定 `task-root-unsafe`，真实 symlink/junction 夹具须用户单独批准；③ D-3 先定唯一身份来源与信任边界、缺失/不可用失败关闭，不停在“部署配置/进程凭证”未决二选一；④ D-4 并发靠事务条件更新（`PENDING`→终态一次），不把连接池/WAL 当并发安全，跨进程并发批准仅一个发布、绝不写第二个文件、多用户隔离；⑤ D-5 传输扩展默认关闭、仅本地回环、绝不允许公网监听，`approve/reject/cancel` 仍绝不暴露为 Tool；⑥ D-6 补齐评估基线——**40 例为总数且含既有 11 例 C 基线**（新增 29 例），保留并重跑既有结果不改写。公开部署列为不在默认范围。依赖闸门：不新增运行时依赖，transport 扩展复用 SDK 已含传递依赖。推荐起点 D-1。
- 边界：不扩大 C 阶段已冻结安全合同与读写边界；不把模型输出/笔记正文/客户端输入当作路径·命令·URL·写入授权；`task_root` 仍须部署配置预存在；每片独立提交并交 Codex 复核；不 push 直到 P3 全部完成；每片必须保留并复跑 C 阶段基线（unittest 149 项、20 集成、2 入口、评估 11/11、演示 8/8、`pip check`、`git diff --check`）且不降低计数。
- 结果：本决策仅记录规划，尚未实现任何 D 切片；实现将在后续逐片进行并各自验证、提交、交 Codex 复核。
- known-limitations-for-D：`SafeMCPServer` 依赖 SDK v2 `_handle_call_tool` 的内部结构，SDK 升级需回归；`correlation_id` 内容派生使其在同主体下可预测（见上文取舍）；**`TrustedContext` 安全字符白名单已由 D-1 实现（见 D-020）**；网络阻断是测试期 monkeypatch 而非 OS 级沙箱；仍为单进程、非并发、非多用户，仅 Windows 原生发布路径经实机验证。

## D-020：D-1 身份格式与安全字符白名单（已实现）

- 状态：accepted（已实现）
- 日期：2026-08-07
- 背景：D 阶段起点切片（D-019 ①）。C 阶段 `TrustedContext` 仅做 `str`/长度 `1..256`/无 C0·DEL 控制字符校验，任意 Unicode（含空格、CJK、注入字符）均被接受；`correlation_id` 格式未在类型层约束。D-1 收紧为精确身份格式，且不破坏 C 阶段 11 例评估与 §11.5 基线。
- 决定：
  - subject 精确字符白名单 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`（首字符字母/数字，总长 1..128）；在 `TrustedContext.__init__`、`TasksStore._check_context`、`server.ServerConfig.from_env`（配置启动失败关闭）、`host.TrustedHostController.__init__`（配置启动失败关闭）四处统一校验。非法/缺失 subject 在配置启动即失败关闭（抛受控 `TaskPublishError(INVALID_ARGUMENTS)`，不泄露路径/正文）。
  - correlation_id 规范格式 `^[0-9a-f]{64}$`（服务端 `hashlib.sha256(...).hexdigest()` 派生，无前缀）；`_derive_correlation_id` 与存储记录均产出该格式。客户端永远不能直接提供或覆盖 correlation_id：它不是 Tool 参数，Server 仅本地派生、Host 仅从 `TasksStore.lookup_correlation_id(confirmation_id)` 取回。在 `server.create_task_tool` 派生后加 `_valid_correlation_id` 契约守卫。
  - **关键边界取舍**：`TrustedContext.__init__` 对 correlation_id 保留宽松校验（str/长度/无控制字符），**不**强制 `^[0-9a-f]{64}$`。原因：C 阶段 11 例评估与既有集成/核心单测使用虚构 correlation_id（如 `"b"*32`、`"c-1"`、`"c"*32`）直接构造 `TrustedContext`，这些夹具不走真实服务端派生；若在类型层强制 64-hex 将破坏“C 11 例评估与 §11.5 基线不变”的硬约束。因此 64-hex 契约仅在真实服务端派生边界（`server.create_task_tool`）守卫，满足“correlation_id 必须来自服务端派生、客户端不可注入”的安全意图，同时保留 C 基线。
  - 回归新增 8 项：subject 空格/CJK/前导连字符/超长拒收、合法特殊字符通过；`_derive_correlation_id` 输出 64-hex 且同内容幂等、不同内容独立；Host 非法 subject 构造失败关闭；`ServerConfig.from_env` 非法 subject 配置启动失败关闭。
- 边界：不新增任何依赖；不改 B2a 安全核心与 C 阶段已冻结合同；不进入 D-2 及以后；不 push / 不建 PR；保持与 C 基线计数一致（仅按新增测试增长）。
- 结果（2026-08-07 完整复跑）：`compileall` 通过；stdlib `unittest` 总计 **157 项**（153 执行通过 + 4 链接测试默认跳过，较 C 阶段 149 净增 8）；`tests/test_mcp_integration.py` **20 项** + `tests/test_server_entry.py` **3 项**（原 2 + D-1 新增 1） + `evals/run_c_phase_eval.py` **11 例** + `demo/mcp_stdio_demo.py` **8 项**断言全部通过；`python -m pip check` → `No broken requirements found.`；`git diff --check` 通过；本地提交（未 push）。
