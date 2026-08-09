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
- 结果（2026-08-06 完整复跑）：`compileall` 通过；stdlib `unittest` 总计 **149 项**（145 执行通过 + 4 链接测试默认跳过），其中 `tests/test_mcp_integration.py` **20 项** stdio 集成测试、`tests/test_server_entry.py` **2 项**入口 / 配置测试；`evals/run_c_phase_eval.py` **11 例**全部通过；`demo/mcp_stdio_demo.py` **8 项**断言全部通过；`python -m pip check` → `No broken requirements found.`（无 `Ignoring invalid distribution` 警告）；`git diff --check` 通过；`git diff --cached --quiet` 通过（暂存区为空）；改动全部保持未暂存、未提交。（注：149/20/2 为 C 阶段历史基线；当前统一基线 196 项 / 23 集成 / 6 入口，见 STATUS / ARCHITECTURE §7）

## D-019：D 阶段范围与切片排序决策（规划）

- 状态：accepted（规划）
- 日期：2026-08-07
- 背景：C 阶段已本地提交 `94dd90d`（`feat(p3): add local mcp stdio integration`，22 文件），并经 Codex 安全核心复核通过；用户决定进入 D 阶段，但先定计划再小步实现，且不立即 push（等 P3 全部完成后再统一处理 push / PR）。
- 决定：D 阶段在 known-limitations-for-D 范围内做 6 个加固 / 补齐切片，验收标准已收紧（见 PRD §11 / ARCHITECTURE §7）：① D-1 身份格式与安全字符白名单——`subject` 精确字符集+长度上限、配置启动非法/缺失即失败关闭，`correlation_id` 必须匹配服务端派生格式 `^[0-9a-f]{64}$`（无前缀）、客户端永远不能提供或覆盖，完全保留 C 阶段合同；② D-2 跨平台原子发布——fd 链式 `openat(dir_fd,O_NOFOLLOW)`+`fstat` 逐级验证，禁止字符串路径回退与 `realpath` 安全判断，平台缺能力稳定 `task-root-unsafe`，真实 symlink/junction 夹具须用户单独批准；③ D-3 先定唯一身份来源与信任边界、缺失/不可用失败关闭，不停在“部署配置/进程凭证”未决二选一；④ D-4 并发靠事务条件更新（`PENDING`→终态一次），不把连接池/WAL 当并发安全，跨进程并发批准仅一个发布、绝不写第二个文件、多用户隔离；⑤ D-5 传输扩展默认关闭、仅本地回环、绝不允许公网监听，`approve/reject/cancel` 仍绝不暴露为 Tool；⑥ D-6 补齐评估基线——**40 例为总数且含既有 11 例 C 基线**（新增 29 例），保留并重跑既有结果不改写。公开部署列为不在默认范围。依赖闸门：不新增运行时依赖，transport 扩展复用 SDK 已含传递依赖。推荐起点 D-1。
- 边界：不扩大 C 阶段已冻结安全合同与读写边界；不把模型输出/笔记正文/客户端输入当作路径·命令·URL·写入授权；`task_root` 仍须部署配置预存在；每片独立提交并交 Codex 复核；不 push 直到 P3 全部完成；每片必须保留并复跑当前统一基线（unittest 196 项（188 执行通过 + 8 链接测试默认跳过）、23 集成、6 入口、评估 11/11、演示 8/8、`pip check`、`git diff --check`）且不降低计数。（注：原 D-019 边界写「C 阶段基线 149/20/2」，该数为历史 C 阶段结果，D-1 后升 164、D-2 后升 196）
- 结果：本决策仅记录规划，尚未实现任何 D 切片；实现将在后续逐片进行并各自验证、提交、交 Codex 复核。
- known-limitations-for-D：`SafeMCPServer` 依赖 SDK v2 `_handle_call_tool` 的内部结构，SDK 升级需回归；`correlation_id` 内容派生使其在同主体下可预测（见上文取舍）；**`TrustedContext` 安全字符白名单已由 D-1 实现（见 D-020）**；网络阻断是测试期 monkeypatch 而非 OS 级沙箱；仍为单进程、非并发、非多用户，仅 Windows 原生发布路径经实机验证。

## D-020：D-1 身份格式与安全字符白名单（已实现）

- 状态：accepted（已实现）
- 日期：2026-08-07
- 背景：D 阶段起点切片（D-019 ①）。C 阶段 `TrustedContext` 仅做 `str`/长度 `1..256`/无 C0·DEL 控制字符校验，任意 Unicode（含空格、CJK、注入字符）均被接受；`correlation_id` 格式未在类型层约束。D-1 收紧为精确身份格式，且不破坏 C 阶段 11 例评估与 §11.5 基线。
- 决定：
  - subject 精确字符白名单 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`（首字符字母/数字，总长 1..128）；在 `TrustedContext.__init__`、`TasksStore._check_context`、`server.ServerConfig`（构造期 `__post_init__` 统一校验：`from_env({})` 缺失与直接 `ServerConfig(subject="bad subject")` 非法均失败关闭）、`host.TrustedHostController.__init__`（配置启动失败关闭）四处统一校验。非法/缺失 subject 在配置启动即失败关闭（抛受控 `TaskPublishError(INVALID_ARGUMENTS)`，不泄露路径/正文）；`server.main()` 入口对配置期 `TaskPublishError` 统一捕获失败关闭：`stdout` 保持空、`stderr` 仅输出稳定码 `invalid-arguments`、非零退出，禁止 `str(e)` / traceback / 绝对路径泄露（P0-2 入口泄露修复：Codex 复核指出原 D-1 未捕获 `main()` 配置期异常，导致 traceback 暴露绝对路径与 `server.py` 行号）。
  - correlation_id 规范格式 `^[0-9a-f]{64}$`（服务端 `hashlib.sha256(...).hexdigest()` 派生，无前缀）；`_derive_correlation_id` 与存储记录均产出该格式。客户端永远不能直接提供或覆盖 correlation_id：它不是 Tool 参数，Server 仅本地派生、Host 仅从 `TasksStore.lookup_correlation_id(confirmation_id)` 取回。该格式在**核心类型层强制**——`TrustedContext.__init__` 与 `TasksStore._check_context` 均改用 `_valid_correlation_id` 校验（不再保留宽松例外）；Host 从 `lookup_correlation_id()` 取回值后须经 `_valid_correlation_id` 格式校验，损坏/旧格式失败关闭、不写文件、不泄露原始值。为满足核心强制校验，C 阶段虚构夹具的 correlation_id（`"c-1"`、`"b"*32`、`"c"*32` 等）已全部更新为合法固定 64 位小写十六进制（如 `"b"*64`），场景语义/结果/案例数不变。
  - **修正说明（替换原“关键边界取舍”）**：原 D-1 在 `TrustedContext.__init__` 对 correlation_id 保留宽松校验（“为兼容 C 夹具”），不在类型层强制 64-hex。该取舍经 Codex 复核不予接受——安全格式约束应在核心类型层强制，C 基线夹具应同步更新为合法 64-hex 而非放宽类型层。本条以 D-1 修正提交撤销该取舍：`TrustedContext` 与 `_check_context` 都强制 `^[0-9a-f]{64}$`，不再保留任何宽松例外，且 C 评估/集成/核心测试中的虚构 correlation_id 已全部改为合法 64-hex，C 基线语义与案例数保持不变。
  - 回归新增（较 C 基线净增 14 项）：subject 精确字符集拒收/合法（5 项，`test_create_task`）；correlation_id 64-hex 在类型层拒收非法/接受合法、`create_task` 阻断非法 correlation_id（3 项，`test_create_task`）；Host 遇损坏/旧格式持久化 correlation_id 失败关闭且不写文件（1 项，`test_mcp_integration`）；`ServerConfig.from_env` 缺失 subject 失败关闭、直接构造非法 subject 失败关闭（2 项，`test_server_entry`）；`_derive_correlation_id` 输出 64-hex 且同内容幂等、不同内容独立（2 项，`test_create_task`，属原 D-1）；Host 非法 subject 构造失败关闭（1 项，`test_mcp_integration`，属原 D-1）。
- 边界：不新增任何依赖；仅收紧 B2a `tasks.py` 的 `TrustedContext.__init__` 与 `TasksStore._check_context` 身份格式校验（correlation_id 强制 `^[0-9a-f]{64}$`、subject 精确字符集），不改变确认状态机、sqlite 持久化、审计与 Windows no-replace 发布合同，不改动 `safe_task_write.py`；不进入 D-2 及以后；不 push / 不建 PR；保持与 C 基线计数一致（仅按新增测试增长）。（注：C 基线=149 为历史 C 阶段结果；当前统一基线 196 项 / 23 集成 / 6 入口，见 STATUS / ARCHITECTURE §7）
- 结果（D-1 修正提交（二）：P0-2 入口泄露修复，2026-08-07 复跑）：`compileall` 通过；stdlib `unittest` 总计 **164 项**（160 执行通过 + 4 链接测试默认跳过，较 C 阶段 149 净增 15）；`tests/test_mcp_integration.py` **23 项**（C 基线 20 + D-1 阶段累计新增 3：原 D-1 2 项 + 本修正 1 项“损坏/旧格式持久化 correlation_id 失败关闭”） + `tests/test_server_entry.py` **6 项**（原 2 + D-1 阶段累计新增 4：原 D-1 1 项 + 本修正 3 项“缺失 subject / 直接构造非法 subject 失败关闭 / 入口缺失 subject 非零退出且 stdout 空、stderr 仅含稳定码无路径泄露”） + `tests/test_create_task.py` **61 项**（原 53 + D-1 阶段累计新增 8） + `evals/run_c_phase_eval.py` **11 例** + `demo/mcp_stdio_demo.py` **8 项**断言全部通过；`python -m pip check` → `No broken requirements found.`；`git diff --check` 与 `git diff --cached --check` 通过；本地修正提交（未 push）。（注：164 为 D-1 阶段历史基线；当前统一基线已升至 196 项 / 23 集成 / 6 入口，见 STATUS / ARCHITECTURE §7）

## D-021：D-2 跨平台原子发布一致性（已实现 · Windows 可验证部分）

- 状态：accepted（已实现 · Windows 可验证部分；真实链接夹具 blocked-until-approved）
- 日期：2026-08-07
- 背景：D 阶段切片 ②（D-019 ②）。C 阶段仅有 Windows 原生 `safe_task_write.py`（句柄式 `NtCreateFile(FILE_CREATE, OBJ_DONT_REPARSE)` + 句柄式 `open_task_root`）。设计 `docs/D-2-design.md` v5 经 Codex 复核 PASS（结论：可进入 D-2 实现，真实 symlink/junction、WSL/Linux/远程 runner、Win mklink/Dev-Mode/管理员、公网 CI 四类仍 blocked-until-approved）。目标：新增 POSIX 等价 no-replace 分支，与 Windows 收敛到同一组稳定错误语义（`task-invalid-id` / `task-root-unsafe` / `task-conflict` / `task-write-failed`）与同一 `publish_task_file(task_root, task_id, payload)` 接口，`tasks.py` 调用点不感知平台。
- 决定：
  - 新增 `src/mcp_notes/safe_task_write_posix.py`（纯 stdlib，覆盖设计 §1–§4）：从 `/` 目录 fd 起逐段 `os.open(comp, O_RDONLY|O_DIRECTORY|O_NOFOLLOW, dir_fd=parent)` + `fstat` 复核；所有父 fd 持有到清理结束；EEXIST 后先 `os.stat(follow_symlinks=False)` 预筛再 `O_NOFOLLOW` 打开，symlink/目录/FIFO/设备/不可归类→`task-root-unsafe`，仅常规文件比对内容（unchanged/conflict），读/解码失败→`task-write-failed`；fsync 顺序 文件→close→父目录；失败清理做 inode 身份保护（创建后立即取身份，即便写入失败也可安全 unlink）且受单写入者前提门控（`P3_TASK_ROOT_SINGLE_WRITER` 默认为 1，非唯一写入者时禁止按名 unlink）；`dir_fd`/`O_NOFOLLOW`/`O_DIRECTORY`/目录 fsync 缺失→`task-root-unsafe`，绝不降级字符串路径方案；禁止 `realpath` 作安全判断。
  - `safe_task_write.py` 改为 `sys.platform=="win32"` 条件导入 `msvcrt`/`safe_open`（POSIX 上 `import safe_task_write` 不崩），非 win32 经 dispatch 进入 POSIX 分支；并把 Windows 原生 `_read_existing_json` 的 reparse / 非普通文件读取失败由保守 `task-conflict` 收紧为 `task-root-unsafe`（§2/§3，与「目标不安全则失败关闭」方向一致，且不破坏既有「创建/根阶段 reparse→task-root-unsafe」断言）。
  - **保 164 基线零改动**：现有 164 测试直接 mock `safe_task_write` 模块全局符号（`kernel32`/`ntdll`/`msvcrt`/`_nt_create_file`/`_nt_open`/`os.fdopen` 等），故 Windows 实现逻辑与符号保留在 `safe_task_write.py` 内、未物理移出成独立 win 模块；仅把 POSIX 算法落到独立 `safe_task_write_posix.py`，满足设计「平台门面 + 独立分支」可验证意图且不影响 164 mock 路径。
  - 测试：`tests/test_create_task.py` 新增 1 项 Windows 回归 `test_existing_file_reparse_fails_root_unsafe`；`tests/test_safe_publish_posix.py` 新增 19 项算法级/mock 单测（15 执行 + 4 真实链接占位 skip）。
- 边界：不新增任何依赖；不改动 P2/C 安全核心合同与 sqlite 持久化；不进入 D-3 及以后；不创建/运行真实 symlink 或 junction、不触碰 `02-agent-research-workflow/` 与 `.workbuddy/`；不 push / 不建 PR；四类 blocked 事项（真实 symlink/junction、WSL/Linux/远程 runner、Win mklink/Dev-Mode/管理员、公网 CI）仍待用户单独批准，其对应 D2-L1…L4 为默认 skip 占位。
- 结果（2026-08-07 复跑）：`compileall` 通过；`discover -s tests` 总计 **184 项**（176 执行通过 + 8 链接测试默认跳过，较 D-1 基线 164 净增 20）；`tests/test_mcp_integration.py` **23 项** + `tests/test_server_entry.py` **6 项** + `tests/test_create_task.py` **62 项** + `tests/test_safe_publish_posix.py` **19 项** + `evals/run_c_phase_eval.py` **11 例** + `demo/mcp_stdio_demo.py` **8 项**断言全部通过；`python -m pip check` → `No broken requirements found.`；`git diff --check` 通过（仅 CRLF 规范化提示，非错误）；改动保持未暂存、未提交、未 push、未建 PR。

## D-022：D-2 P0/P1 Codex 复核修复（未提交）

- 状态：pending Codex 复核（改动保持未暂存、未提交、未 push、未建 PR）
- 日期：2026-08-07
- 背景：在 `ba17a2d`（D-2 Windows 可验证部分，D-021 结果 184 项）之上，Codex 对实现给出 5 项 P0 + 1 项 P1 缺口。本决定记录修复内容与验证结果；范围严格限定 D-2 相关文件，不进 D-3、不装依赖、不创/跑真实 symlink/junction、不改 P2/C 安全核心与 sqlite 状态机、`.workbuddy/` 不碰。
- 修复（仅 D-2 文件：`src/mcp_notes/safe_task_write.py`、`src/mcp_notes/safe_task_write_posix.py`、`tests/test_safe_publish_posix.py`；文档 `STATUS.md`/`DECISIONS.md`/`docs/PRD.md`/`docs/D-2-design.md` 同步计数与口径）：
  - **P0-1 循环导入 / Windows 名称泄露**：核心符号（`TASK_ID_RE`/`TASK_*`/`SafeWriteError`/`NameCollision`）先于平台分发定义；`NtCreateFile`/`WriteFile`/`FlushFileBuffers`/`NtDeleteFile` 绑定与所有 Windows-only 导入（`msvcrt`/`safe_open` 全部符号）移入 `if sys.platform=="win32":` 分支；POSIX 上 `import safe_task_write` 不再触发 `_NATIVE_AVAILABLE` NameError，且导入门面不循环。既有 164 mock 路径（模块级 `kernel32`/`ntdll`/`msvcrt`/`_NATIVE_AVAILABLE`/`_nt_open`/`_nt_create_file`/`_nt_create_file_fn`）保持不变。新增回归：子进程伪装 `sys.platform="linux"` 导入门面，断言无循环导入、无 `_NATIVE_AVAILABLE` NameError（Windows 宿主可跑，不依赖真实 Linux/链接）。
  - **P0-2 `_open_root` 根 fd 打开失败泄露**：进入 try 前预置 `fds=[]`；根 `os.open("/")` 失败时只抛 `task-root-unsafe`，无 `UnboundLocalError`。新增回归：mock 根 anchor `os.open("/")` 抛 OSError，断言稳定 unsafe、无未绑定变量异常、无 fd 泄漏。
  - **P0-3 能力探测**：由「`bool(os.supports_dir_fd)`」改为逐项确认 `os.open`/`os.stat`/`os.unlink` 支持 `dir_fd`、`os.stat` 支持 `follow_symlinks=False`、`O_NOFOLLOW`/`O_DIRECTORY`/`fsync` 存在；任一缺失稳定 `task-root-unsafe`，不泄露 `TypeError`、不降级字符串路径。新增回归：仅部分 dir_fd 能力存在 → `_posix_supported()` 返回 False，且 `publish_task_file` 稳定 unsafe、无 TypeError。
  - **P0-4 文件 fd 重复 close**：写入 / 文件 fsync / close / 父目录 fsync 任一失败均进入失败清理；文件 fd 只尝试 close 一次（close 失败绝不重复 close 同一 fd）。新增回归：文件 fd 的 `os.close` 失败 → 断言该 fd 恰好被尝试关闭一次、最终 `task-write-failed`。
  - **P0-5 EEXIST 错误语义**：`_handle_existing` 精确区分——`FileNotFoundError`/`ELOOP`/symlink/目录/FIFO/设备/类型不一致/无法安全归类 → `task-root-unsafe`；`PermissionError`/其他 IO（如 EIO）/读取/解码失败 → `task-write-failed`（不再把所有 `os.stat`/`os.open` 的 OSError 一律映射 `task-root-unsafe`）。新增回归：预筛 `os.stat(follow_symlinks=False)` 权限失败 → write-failed；`O_NOFOLLOW` 打开权限失败 → write-failed。
  - **P1 文案**：`safe_task_write.py`/`safe_task_write_posix.py` 去除「delete-on-close」「绝不残留」等不实表述，改为「相对已验证父 HANDLE 的 NtDeleteFile 清理；清理失败时失败关闭，不承诺零残留或自动重试」；明确 `_SINGLE_WRITER` 是可信部署前提声明（非运行时 ACL 验证），非唯一写入者禁止按名 unlink；不声称整个 MCP Server 已跨平台，真实 POSIX 链接验证仍 blocked-until-approved。
- 边界：同 D-021（不新增依赖；不改动 P2/C；不进 D-3；不创/跑真实 symlink/junction；不碰 `02-agent-research-workflow/` 与 `.workbuddy/`；不 push/PR）；四类 blocked 事项仍待用户单独批准。
- 结果（2026-08-07 复跑，未提交）：`compileall` 通过；`discover -s tests` 总计 **191 项**（183 执行通过 + 8 链接测试默认跳过，较 D-1 基线 164 净增 27；其中 D-2 相关 27 项：create_task +1 + posix 26，含 4 真实链接占位 skip）；`tests/test_mcp_integration.py` **23 项** + `tests/test_server_entry.py` **6 项** + `tests/test_create_task.py` **62 项** + `tests/test_safe_publish_posix.py` **26 项**（22 执行 + 4 链接占位跳过） + `evals/run_c_phase_eval.py` **11 例** + `demo/mcp_stdio_demo.py` **8 项**断言全部通过；`python -m pip check` → `No broken requirements found.`；`git diff --check` 通过（仅 CRLF 提示）；`git diff --cached --quiet` 退出 0（未暂存）；敏感扫描（`api_key`/`secret`/`password`/`token`/`sk-`/私钥）无真实凭据（仅 `DECISIONS.md` 误命中函数名 `_has_shell_token`，非密钥）。等待 Codex 再复核。

## D-023：D-2 P0/P1 Codex 复核修复（第二轮，未提交）

- 状态：pending Codex 再复核（改动保持未暂存、未提交、未 push、未建 PR）
- 日期：2026-08-07 晚
- 背景：在 D-022 未提交修复之上，Codex 再复核指出一批**与 D-022 口径不同**的新 P0/P1（非 Windows `open_task_root` 泄露 `_NATIVE_AVAILABLE` NameError；冲突读取 `fstat` 失败原始异常；根目录 walk 失败路径仍泄露原始异常；能力探测缺 `os.fstat` 存在性与属性缺失防御；设计文档顶部仍写「未实现代码」）。本决定记录本輪修复与验证结果；范围严格限定 D-2 相关文件，不进 D-3、不装依赖、不创/跑真实 symlink/junction、不改 P2/C 安全核心与 sqlite 状态机、不 stage/commit/push/PR、`.workbuddy/` 不碰。
- 修复（仅 D-2 文件：`src/mcp_notes/safe_task_write.py`、`src/mcp_notes/safe_task_write_posix.py`、`tests/test_safe_publish_posix.py`、`docs/D-2-design.md`；文档 `STATUS.md`/`DECISIONS.md`/`docs/PRD.md` 同步计数与口径）：
  - **P0-1 非 Windows `open_task_root()` 泄露 `_NATIVE_AVAILABLE` NameError**：在 `open_task_root()` 开头加 `if sys.platform != "win32": raise SafeWriteError(TASK_ROOT_UNSAFE)`——非 Windows 直接调用公开 `open_task_root()` 稳定抛 `task-root-unsafe`，绝不触碰 Windows-only 符号（`_NATIVE_AVAILABLE`/`verify_native_support` 仅在 win32 分支绑定），不破坏既有 164 mock 路径与 Windows 行为。新增回归：子进程伪装 `sys.platform="linux"` 后直接调用 `open_task_root('/tmp')`，断言仅得稳定 `task-root-unsafe`、无 `NameError`/`_NATIVE_AVAILABLE`/`Traceback`（Windows 宿主可跑，不依赖真实 Linux）。
  - **P0-2 冲突读取 `fstat` 失败原始异常泄露**：`_handle_existing()` 中 `os.fstat(fd)` 失败现精确映射 `SafeWriteError(TASK_WRITE_FAILED)`；fd 仍只关闭一次（finally 中 best-effort），不泄露原始 OSError。新增回归：模拟已存在常规文件，`O_NOFOLLOW` 打开成功后 `os.fstat(fd)` 抛 OSError，断言 `task-write-failed`、无原始异常、fd 恰好关闭一次。
  - **P0-3 根目录 walk 失败路径仍泄露原始异常**：① walk 中所有错误清理 `close` 改 best-effort——`os.fstat(h)` 失败后的 `os.close(h)` 与「非目录」后的 `os.close(h)` 各自包 `try/except OSError`，关闭失败绝不覆盖稳定 `task-root-unsafe`、绝不泄露原始 OSError；② `_split_root()` 明确拒绝含 `\x00` 的组件（避免 `os.open()` 抛原始 `ValueError` / 路径注入），仍拒绝空段/`.`/`..`、不回退字符串路径方案。新增回归：子目录 `fstat` 失败且关闭该 fd 也失败 → 仍 `task-root-unsafe`；`task_root="/bad\x00name"` → `task-root-unsafe`、无原始 `ValueError`。
  - **P1-1 能力探测补全**：`_posix_supported()` 除既有检查外，新增实际使用的 `os.fstat` 存在性检查，并防御 `os.open`/`os.stat`/`os.unlink` 属性本身缺失（避免 `AttributeError`）；任一关键能力缺失稳定 `task-root-unsafe`。新增回归：缺失 `fstat` 时 `_posix_supported()` 为 False，且 `publish_task_file()` 不泄露 `AttributeError`/`TypeError`。
  - **P1-2 文档状态纠正**：`docs/D-2-design.md` 顶部由「未实现代码」改为准确表述——v5 为原设计；D-2 Windows 可验证实现已存在（提交 `ba17a2d`，未 push）；D-022 修复未暂存、待 Codex 复核；保留真实链接专项仍 blocked-until-approved、不宣称整个 MCP Server 已跨平台。
- 边界：同 D-021/D-022（不新增依赖；不改动 P2/C；不进 D-3；不创/跑真实 symlink/junction；不碰 `02-agent-research-workflow/` 与 `.workbuddy/`；不 stage/commit/push/PR）；四类 blocked 事项仍待用户单独批准。
- 结果（2026-08-07 复跑，未提交）：`compileall` 通过；`discover -s tests` 总计 **196 项**（188 执行通过 + 8 链接测试默认跳过，较 D-1 基线 164 净增 32；其中 D-2 相关 32 项：create_task +1 + posix 31，含 4 真实链接占位 skip）；`tests/test_mcp_integration.py` **23 项** + `tests/test_server_entry.py` **6 项** + `tests/test_create_task.py` **62 项** + `tests/test_safe_publish_posix.py` **31 项**（27 执行 + 4 链接占位跳过，较 D-022 +5） + `evals/run_c_phase_eval.py` **11 例** + `demo/mcp_stdio_demo.py` **8 项**断言全部通过；`python -m pip check` → `No broken requirements found.`；`git diff --check` 通过（仅 CRLF 提示）；`git diff --cached --quiet` 退出 0（未暂存）；敏感扫描（`api_key`/`secret`/`password`/`token`/`sk-`/私钥）无真实凭据（仅 `DECISIONS.md` 误命中函数名 `_has_shell_token`，非密钥）。等待 Codex 再复核。

## D-024：D-2 文档事实修正（纯文档 follow-up，本地提交）

- 背景：Codex 对 D-2 收尾提交 `905886a`（`feat(p3): complete D-2 atomic publish consistency`）复核通过——提交恰 7 文件（524 insertions / 137 deletions，无 P2/`.workbuddy/`/`.venv/`）、`compileall` 通过、`unittest` 196 项（188 通过 + 8 跳过）、评估 11/11、演示 8/8、`pip check` 干净、暂存区空、164 基线 mock 路径全绿、敏感扫描无真实凭据。唯一 P1：`docs/D-2-design.md` 顶部（及 STATUS.md / PRD.md 对应表述）仍写 D-022/D-023「未暂存、未提交」，但已于 `905886a` 落地，文档事实过期。
- 修复（仅文档，不 amend `905886a`、不动代码/测试、不进 D-3）：
  - `docs/D-2-design.md` 顶部状态：D-022/D-023 已由本地提交 `905886a` 统一落地（未 push），Codex 再复核通过，文档事实已修正；第 4 行「当前修复轮约束」改为「D-022/D-023 修复轮约束（当时，已随 `905886a` 落地）」。
  - `STATUS.md` 阶段行：「均未提交」→「已由本地提交 `905886a` 统一落地，未 push」。
  - `docs/PRD.md` §11 D-2 行：「均未提交」→「已由本地提交 `905886a` 统一落地，未 push」，并补 `D-024` 决策引用。
  - DECISIONS.md 内 D-022/D-023 带日期的「当时未提交」验证记录**保留为历史**，本条目补记后续已由 `905886a` 统一本地提交。
- 边界：同 D-021/D-022/D-023（不新增依赖；不改 P2/C/代码/测试；不进 D-3；不创/跑真实 symlink/junction；不碰 `02-agent-research-workflow/` 与 `.workbuddy/`；D2-L1…D2-L4 仍默认 skip、blocked-until-approved）。
- 结果：纯文档提交（4 文件：DECISIONS.md / STATUS.md / docs/D-2-design.md / docs/PRD.md）；`git diff --check` 通过（仅 CRLF 提示）；`git diff --cached --quiet` 退出 0（仅这 4 文件暂存）；未 push、未建 PR、未 amend `905886a`。

## D-025：D-3 唯一身份来源与信任边界（设计包 v1，**已被 D-026 取代**）

> **⚠️ 本条为历史记录（2026-08-08 当时的 v1 设计）。经 Codex 复核结论为「需修改，3 个 P0」，其中三项决定已被 D-026 推翻，勿按本条实施**：
> ① 「`MCP_NOTES_SUBJECT` 在身份文件缺失时作后备」——**已废止**，env 永不产生最终 subject（详见 D-026）；
> ② 「Server 与 Host 启动期一致性断言」——**已废止**，分离进程下不可实现，改为单进程 bootstrap（详见 D-026）；
> ③ 身份文件安全读取仅有函数签名、无算法——**已由 D-026 补齐** fd/HANDLE 链方案。
> 当前有效设计以 **D-026 + `docs/D-3-design.md` v2** 为准。

- 状态：superseded by D-026（设计包 v1；从未实现；未提交 / 未 push / 未建 PR）
- 最终设计复核更正（2026-08-09，D-4 实现前）：上段第三轮历史记录中“D-2 证明无残留回退 `PENDING`”不再成立。`publish_task_file` 的公开稳定错误码不能证明清理结果；发布报错后一律保留 `PUBLISHING` 并返回 `task-write-failed`。仅后续受控恢复再次成功发布后才可写 `APPROVED`；绝不由 D-4 回退 `PENDING` 或写负向终态。

- 日期：2026-08-08
- 背景：D 阶段切片 ③（D-019 ③）。C / D-1 阶段 `subject` 仅由 `MCP_NOTES_SUBJECT` 环境变量提供（D-1 已加精确字符白名单与配置启动失败关闭），但「唯一可信 subject 来源」始终停在「部署配置 / 进程凭证」未决二选一；D-3 须一次性收敛为**单一可审计来源 + 明确信任边界 + 稳定失败关闭**。本轮**仅做设计与文档，不写代码、不装依赖、不提交、不 push、不建 PR**；不进 D-4 / D-5 / D-6。
- 决定：
  - **唯一权威来源 = 部署预置本地身份清单文件（`MCP_NOTES_IDENTITY_FILE`）**：由可信本地部署操作者在带外写入，Server 与 Host 在进程启动期各读取一次，路径由部署配置固定，绝不来自任何请求数据。进程环境变量 `MCP_NOTES_SUBJECT` 被**降级为同一加载路径的部署期启动覆盖**——仅当身份文件缺失时作为后备；文件存在时若 env 同时给出则须与文件一致，否则失败关闭。**环境变量不再是独立第二来源**；系统只有单一 `load_subject()` 加载函数、一条代码路径。身份文件最小 schema：`{ "subject": "...", "subject_kind": "deployment-provisioned", "version": 1 }`，当前仅消费 `subject`，向前兼容未来多用户 `subjects: [...]` 表。
  - **信任边界**：subject 从不作为 Tool 参数 / 模型文本 / MCP 消息字段（`create_task` 仅 `title`/`description`；`notes://service-info` 只说明派生方式）；Host 用自身加载的 `self._subject` 重建 `TrustedContext`、记录只存 subject+correlation_id 哈希、不提供权威 subject；MCP 客户端 / 模型对 subject 无任何写或注入路径，系统中唯一的 subject 就是启动期加载的那一个。
  - **启动期失败关闭（复用 D-1 稳定码 `invalid-arguments`，保持合同字节稳定；可选加性 `identity-unavailable` 非必须）**：缺失（无文件且无 env 覆盖）/ 非法（不符 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` 或长度越界）/ 来源不可用（文件非普通文件 / reparse / 符号链接 / 权限拒绝 / 不可读 / JSON 损坏 / 含非预期字段）/ 来源不一致（env 与文件冲突）/ Server-Host subject 不一致 → 均在启动期失败关闭，不回退默认主体、不泄露路径/正文/用户名/异常；`server.main()` 复用既有 `TaskPublishError` 捕获写稳定码退出路径（D-1 P0-2）。
  - **`correlation_id` 保持服务端确定性派生**（SHA-256(NFKC(title) + 0x1f + NFKC(description))，64 位小写十六进制），**不是凭证、不可由客户端提供或覆盖**；D-3 不改其派生方式与格式，仅明确其身份语义（请求级绑定标识，不授权批准）。
  - **Host 绑定（设计层新增）**：Server 与 Host 经同一 `load_subject()` 加载、启动期一致性断言相等；`_rebuild_context` 仍用 `self._subject` + 记录 `correlation_id`，`TasksStore._check_context` 维持 subject 匹配 → `confirmation-identity-mismatch` 合同（D-004 / D-018 不变）。
  - **范围差异**：本地单用户为当前设计交付目标（无需 OS 凭证）；多用户 / OS 凭证绑定（Windows 令牌 SID、POSIX uid）/ PKI 签名清单列为**需用户单独批准**（blocked-until-approved），D-3 不实现、不声称；Windows 与非 Windows 同机制、无原生 OS 凭证硬依赖。绝不公开部署、绝不新增网络连接（身份加载仅为本地文件读取）。
  - **最小改动（供后续实现）**：新增 `src/mcp_notes/identity.py`（`load_subject`，纯标准库离线）；`server.py` / `host.py` 改调 `load_subject` 并新增 `MCP_NOTES_IDENTITY_FILE` 配置；`contracts.py` / `tasks.py` / `safe_task_write*` / sqlite 状态机完全不改（D-1/D-2 合同不变）；可选 `identity-unavailable` 加性稳定码（默认不引入）。测试新增 `tests/test_identity.py`（缺失/非法/不可用/不一致/Server-Host 一致/correlation_id 不可覆盖；需真实 OS 账户的测试标默认 skip 占位）。保 196 基线零删除。DoD 与回归命令见 `docs/D-3-design.md` §7。
- 边界：同 D-021 / D-022 / D-023 / D-024（不新增依赖；不改 P2/C 安全核心与 sqlite 状态机；不进 D-4 / D-5 / D-6；不创/跑真实 symlink/junction；不碰 `02-agent-research-workflow/` 与 `.workbuddy/`；不 push / PR / 提交）；D2-L1…D2-L4 仍默认 skip、blocked-until-approved；OS 凭证绑定 / PKI / 真实多用户环境 / 公网监听仍待用户单独批准。
- 结果：设计包 v1 完成（新增 `docs/D-3-design.md`；更新 `docs/PRD.md` §10 过期白名单说明 + §11.2 D-3 行、`docs/ARCHITECTURE.md` 信任边界章节、`STATUS.md` D-3 状态行）；**从未实现、未提交、未 push、未建 PR**。经 Codex 复核判为「需修改，3 个 P0 + 3 个 P1，D-3 不能进入实现」，**本条已由 D-026 取代**（`docs/D-3-design.md` 已重写为 v2）。

---

## D-026：D-3 设计包 v2 —— 修复 Codex 复核的 3 个 P0（取代 D-025，**已被 D-027 取代**）

> **⚠️ 本条为历史记录（2026-08-08 当时的 v2 设计）。经 Codex 复核结论为「需修改，2 个 P0 + 3 个 P1，D-3 v2 不能进入实现」，其中两项决定已被 D-027 推翻，勿按本条实施**：
> ① 「二选一写死为**单进程本地 bootstrap** + Server/Host 共享**同一 `RuntimeIdentity` 对象实例**」——**已废止**，与现有 C 阶段分离进程 stdio 演示冲突（`demo/mcp_stdio_demo.py:85` spawn 子进程、`:126` 父进程建 Host），却同时承诺演示 8/8；D-027 改为「每进程一次加载（M1）、支持分离进程」；
> ② 「Server 与 Host **所有**启动入口只输出稳定码」（DoD 第 4 条 + 测试 26/27）——**已废止**，`host.py:39` 是库类、无 `main()`，「所有 Host 启动入口」是空集合上的全称承诺、不可验收；D-027 收敛为 `server.main()` + 受控启动器两类可测入口 + 前瞻性约束条款。
> 另有两项**表述性收紧**（非推翻）：私有哨兵不得称为安全边界；测试 24「构造不同 `RuntimeIdentity`」与「同一实例/每进程一次」矛盾，已按 D-027 改为「两次真实加载、两个受控身份根」。
> **本条的 §1 身份来源部分（env 退化为相等性断言、`identity.json` schema、fd/HANDLE 链读取、`SafeWriteError→invalid-arguments` 映射）经 Codex 判定已闭环，D-027 原样保留。**
> 当前有效设计以 **D-027 + `docs/D-3-design.md` v3** 为准。

- 状态：superseded by D-027（设计包 v2；从未实现；未提交 / 未 push / 未建 PR）
- 日期：2026-08-08
- 背景：D-025（D-3 设计包 v1）经 Codex 复核判为**需修改、不能进入实现**。Codex 确认正确的部分：`create_task` 仅接受 `title`/`description`（`SafeMCPServer` 形状守卫，`server.py:231`）、Host 用自身 subject + 存储 `correlation_id` 重建上下文不拿记录 subject 授权（`host.py:41`）、`correlation_id` 仍服务端派生 64-hex 未改动、离线约束正确。但**身份来源本身仍有 3 个 P0**。本轮仍**只做设计与文档，不写代码、不装依赖、不暂存、不提交、不 push、不建 PR**；不进 D-4 / D-5 / D-6。
- 决定（逐条对应 Codex 意见）：
  - **P0-1 修复 —— `MCP_NOTES_SUBJECT` 彻底退出值来源**：身份文件**必须存在**，缺失即失败关闭；env **在任何情况下都不产生最终 subject、不作后备**，仅保留为「身份文件安全读取成功之后」的**可选相等性断言**（给出且不等 → 失败关闭；未给出 → 忽略）。理由：MCP stdio 下客户端若能控制 spawn 即可注入 env，故 env 只能否决、不能提供。新增可验证的**等价不变量**：删除 env 后重新加载结果必须逐字节相同（写入测试矩阵 A-6）。「`load_subject()` 是单一函数」不等于单一权威来源——权威性由「值只能来自受控文件」保证。
  - **P0-2 修复 —— 定义受控身份根与 fd/HANDLE 链读取算法**：新增「受控身份根」概念（`<identity_dir>` 由可信部署带外预置、客户端不可写、生产代码绝不创建）；`<name>` 必须为单组件且匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.json$`（拒分隔符 / `..` / `\x00` / UNC / 驱动器前缀）。读取算法**复用 D-2 已验证原语、零修改 D-2 文件**：Windows 用 `safe_task_write.open_task_root`（盘符根起逐级 `OBJ_DONT_REPARSE`）+ `_nt_open(is_dir=False)`；POSIX 用 `safe_task_write_posix._posix_supported()` + `_open_root`（`/` 起逐级 `O_RDONLY|O_DIRECTORY|O_NOFOLLOW`+`fstat`）+ `os.open(..., O_NOFOLLOW, dir_fd=parent_fd)`。**防检查后替换**：类型断言对**已打开 fd** 做 `fstat`（`S_ISREG`），身份由句柄固定而非路径固定；明令禁止 `os.path.exists` / `os.stat(path)` / `realpath` 作安全判断后按路径 open。**能力缺失（POSIX 无 `O_NOFOLLOW`/`O_DIRECTORY`/`dir_fd`/`fstat`；Windows 原生不可用）→ 失败关闭，绝无字符串路径回退**。限长读取 4096 B（第 4097 字节即超限）。D-2 抛出的 `SafeWriteError` 在 identity 边界统一映射为 `TaskPublishError(INVALID_ARGUMENTS)`，不上抛原始 `OSError`，且不改变 D-2 对外语义。
  - **P0-3 修复 —— 二选一写死为「单进程本地 bootstrap」**：新增唯一入口 `load_runtime_identity()`，**每进程调用恰好一次**，产出不可变 `RuntimeIdentity`（frozen，私有哨兵构造，只能由加载器产出），再**注入**同一实例给 `ServerConfig` 与 `TrustedHostController`；**生产构造器不再接受裸 `str` subject**（传 `str`/非 `RuntimeIdentity` → `invalid-arguments`）。一致性由「同进程同实例」的构造保证，不再需要运行期比较。**分离 Server/Host 进程的「启动期一致性断言」明确不支持**（无比较通道、D-3 零网络不引入 IPC、两次读取之间文件可变，声称能做即为虚称），该场景仅保留既有请求期 `confirmation-identity-mismatch` 失败关闭；真正的跨进程一致性列入待用户单独批准事项。
  - **P1-1 —— `identity.json` 完整 schema**：顶层必须为 object；必填三键 `version`（`int`，显式拒 `bool`，必须 `== 1`）、`subject`（`str`，D-1 白名单 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`）、`subject_kind`（`str`，v1 唯一合法值 `"deployment-provisioned"`，仅作审计标注不进授权判定）；**未知顶层键严格拒绝**（宽松忽略会造成「以为配置生效实则被无视」的安全错觉，向前兼容改由 `version` 递增承担）；最大 4096 B；UTF-8 且不接受 BOM。多用户留待 `version: 2` + `subjects` 表，D-3 遇 `version != 1` 一律失败关闭、不解析、不声称。
  - **P1-2 —— 路径来源与信任模型边界**：`MCP_NOTES_IDENTITY_FILE` **只能来自受控启动器**（可信部署控制的启动脚本 / 服务定义 / 计划任务）。**若 MCP 客户端能控制服务进程的整个环境（env、工作目录、启动参数），该部署不在 D-3 信任模型之内**，D-3 不提供身份保证、也不得声称其受保护——这是部署前提，不是代码可弥补的缺口。
  - **P1-3 —— 不新增 `identity-unavailable`**：全部身份失败复用 `invalid-arguments`（对外信息更少、避免探测、不扩大 D-1/D-2 冻结合同）。**其强制前提升级为 DoD 第 4 条 + 测试项 26/27**：Server 与 Host 的**所有**启动入口必须 `stdout` 为空、`stderr` 仅稳定码、非零退出，禁止 `str(e)` / traceback / 绝对路径 / 用户名 / 环境值；某入口若做不到，必须修好该入口，而不是退回新增细分码。
  - **改动面与基线**：新增 `src/mcp_notes/identity.py` + `tests/test_identity.py`；仅改 `server.py`（新增 `MCP_NOTES_IDENTITY_FILE`、持有 `RuntimeIdentity`）与 `host.py`（构造器接 `RuntimeIdentity`）；调用点机械更新 `TrustedHostController(` **12 处**（demo 3 / tests 4 / evals 5）、`ServerConfig(` **2 处**（evals 1 / tests 1），测试与演示改为写真实临时 `identity.json` 夹具后调真实加载器，**不提供绕过加载器的测试后门**。`contracts.py` / `tasks.py` / `safe_task_write*.py` / sqlite 状态机**完全不改**（新增 DoD 第 10 条：D-2 两文件 diff 必须为空）。保 196 基线零删除。
- 边界：同 D-021…D-025（不新增依赖；不改 P2/C 安全核心与 sqlite 状态机；不进 D-4 / D-5 / D-6；不创/跑真实 symlink/junction；不碰 `02-agent-research-workflow/` 与 `.workbuddy/`；不 push / PR / 提交）；D2-L1…D2-L4 仍默认 skip、blocked-until-approved；新增待批准项：**跨进程 Server/Host 身份一致性（IPC/共享凭据/启动握手）**、真实 symlink/junction 身份根夹具（测试 14 的 4 项占位）；OS 凭证绑定 / PKI / 真实多用户环境 / 公网监听仍待用户单独批准。
- 结果：`docs/D-3-design.md` 重写为 **v2**（文首含 v2 修订说明表，逐条映射 P0-1/P0-2/P0-3/P1-1/P1-2/P1-3 的落点）；同步更新 `docs/PRD.md` §11.2 D-3 行、`docs/ARCHITECTURE.md` §7 D-3 收紧行与 §6 known-limitations、`STATUS.md` D-3 状态行与阶段行；D-025 加被取代标记。**从未实现、未提交、未 push、未建 PR**。经 Codex 复核判为「需修改，2 个 P0 + 3 个 P1，D-3 v2 不能进入实现」，**本条已由 D-027 取代**（`docs/D-3-design.md` 已重写为 v3）。另记：实际分支名为 `codex/p3-local-mcp-tool-service`（上一轮报告误写为 `...tool-server`，已更正）。

---

## D-027：D-3 设计包 v3 —— 进程模型改为「每进程一次加载」并收敛不可验收承诺（取代 D-026）

- 状态：accepted（设计包 v3；Codex 第三轮复核 PASS，2026-08-08；核心已实现（仅 Windows 可验证部分，已由本地提交 d14341d 落地，见 D-027-impl）；本次 Codex 复核中）
- 日期：2026-08-08
- 背景：D-026（D-3 设计包 v2）经 Codex 复核判为**需修改、不能进入实现**。Codex 判定**已闭环**的部分（v3 原样保留，不得回退）：① `MCP_NOTES_SUBJECT` 仅作文件读取后的相等性断言、不再后备产生 subject；② `identity.json` schema、4096 B 上限、UTF-8 无 BOM、未知字段拒绝；③ fd/HANDLE 链读取、对已打开对象 `fstat`、能力缺失失败关闭、identity 边界映射 `invalid-arguments` 且不改 D-2 对外语义；④ D-025 已正确标为 superseded；⑤ 工作区符合文档阶段（暂存区空、`git diff --check` 通过）。但**进程模型本身有 2 个 P0**，另有 3 个 P1。本轮仍**只做设计与文档，不写代码、不装依赖、不暂存、不提交、不 push、不建 PR**；不进 D-4 / D-5 / D-6。
- 决定（逐条对应 Codex 意见）：
  - **P0-1 修复 —— 进程模型改为 M1「每进程一次加载」，支持现有分离进程演示**（采纳 Codex 推荐的方案 1，保住已完成的 C 演示）：v2 的「单进程唯一模式 + Server/Host 共享同一 `RuntimeIdentity` 对象实例」与现有 stdio 演示直接冲突——演示以 `StdioServerParameters(command=sys.executable, args=["-m","mcp_notes.server"])` **spawn 独立 Server 子进程**（`demo/mcp_stdio_demo.py:83-88`），随后在**父进程**构造 `TrustedHostController`（`demo/mcp_stdio_demo.py:126`），两个 OS 进程不可能共享同一 Python 对象，而 v2 同时承诺演示 8/8。**v3 定义 M1**：`load_runtime_identity()` 是**无全局状态、可重入的纯加载函数**（不缓存、不设进程级单例）；**每个参与进程在自身 bootstrap 处调用恰好一次**，注入本进程的 `ServerConfig` 或 `TrustedHostController`；单进程内嵌（tests/evals）是 M1 的**特例**而非独立模型。**删除「同一对象实例 ⇒ 一致」的论据**，改述为「**同一受控身份文件 + 确定性加载算法 ⇒ 同一 subject 值**」的**部署级**保证（非密码学保证、非对象同一性）。**如实标注已知限制**：两进程被指向不同文件、或文件在两次加载之间被有权限者修改时，`subject` 可能不同，D-3 **启动期检测不到**，唯一保护是请求期 `confirmation-identity-mismatch`。
  - **P0-2 修复 —— 消除测试矩阵矛盾**：v2 的测试 24 要求构造「不同 `RuntimeIdentity`」，与「同一实例 / 每进程一次 / 禁绕过加载器」自相矛盾。v3 先由 P0-1 定死进程模型，再把测试 24 改为该模型**真实允许**的路径：在受信测试进程内**两次独立调用真实 `load_runtime_identity()`**、分别读取**两个不同的受控身份根**（模拟两个进程各自加载），用身份 B 的 Host 消费身份 A 的 confirmation → 仍 `confirmation-identity-mismatch`、不写文件；**全程不绕过加载器**。并明确写入设计：**「每进程一次」是生产 bootstrap 入口的约束，不是加载器的技术限制**——加载器可重入，受信代码多次调用是模拟多进程的正当手段。配套新增测试 25（demo 保持分离进程形态且 8/8，作为 P0-1 的验收现场）与 §5.3「多身份加载与受控启动器约束」，含实现陷阱：受控启动器**自身进程不得设置** `MCP_NOTES_SUBJECT`（否则加载第二身份时相等性断言必然失败），或加载第二身份时显式传不含该键的映射。
  - **P1-1 —— 「私有哨兵」降级为防呆，不再作为安全边界**：Python 无进程内语言级隔离，同进程代码可访问私有成员、直接调用内部构造或 monkeypatch 模块符号。v3 明确：私有构造哨兵**仅为受信代码内部的类型/API 防呆**（防调用点误传裸字符串、防未来重构绕开校验），**不是安全边界**、**不证明「只能由加载器产出」**。**真正的边界**是：MCP 客户端/模型无法在服务进程内执行代码（形状守卫 `server.py:231` 只放行 `title`/`description`）、无法写入受控身份根、无法控制受控启动器环境。推论：若攻击者已能在服务进程内执行任意代码，则整个进程已失守，不在 D-3 威胁模型内。测试 22 断言口径同步收紧（只证防呆生效，不得表述为「客户端无法伪造身份对象」）。
  - **P1-2 —— 稳定码 DoD 收敛到可验收入口**：v2 的「Server 与 Host **所有**启动入口只输出稳定码」不可验收——`host.py:39` 是库类，**没有 `main()`、没有任何已定义启动入口**，该承诺落在空集合上、写不出测试。v3 收敛为**当前真实存在且可 subprocess 断言**的两类入口：① `server.main()`（`src/mcp_notes/server.py:358`，已实现 `stderr` 写 `invalid-arguments` + `sys.exit(2)`，见 `server.py:376-378`），D-3 新增的身份失败必须走同一路径；② **受控启动器**（`demo/mcp_stdio_demo.py`、`evals/run_c_phase_eval.py`、测试夹具——Host 侧当前唯一实际启动路径）。**本轮明确不为 `host.py` 新增 `main()`/CLI**（不扩大实现面）。另立**前瞻性约束条款**：今后若新增任何 Host 启动入口，必须捕获 `TaskPublishError` 并仅输出稳定码、非零退出，且同时补等价 subprocess 断言；在该入口出现前，D-3 **不声称**「Host 所有启动入口已满足稳定码要求」。测试项相应改为 27（`server.main()`）与 28（受控启动器），总数由 27 增至 28。
  - **P1-3 —— 清理旧决策引用**：`docs/ARCHITECTURE.md:81` 与 `docs/PRD.md:128` 仍指向已 superseded 的 D-025，本轮改为指向 **D-027 / `docs/D-3-design.md` v3**，并显式标注 D-025(v1) / D-026(v2) 为历史、勿按其实施。
  - **改动面与基线（相对 v2 的增量）**：新增文件与源文件改动范围不变（`identity.py` + `tests/test_identity.py`；仅改 `server.py` / `host.py`）；调用点仍为 `TrustedHostController(` **12 处**、`ServerConfig(` **2 处**，但按适配类型细分并逐处点名（主身份 / **第二受控身份根** / 非 `RuntimeIdentity` 拒绝），其中 `tests/test_mcp_integration.py:439` 的 `"bad subject"` 用例改为「传非 `RuntimeIdentity` → `invalid-arguments`」，**非法 subject 字符串的覆盖迁移到「身份文件内 `subject` 非法 → 加载失败关闭」（测试 C-17），断言强度不降低**；demo / evals **新增受控身份根夹具准备代码**（不再是纯机械替换），demo 子进程 env 由 `MCP_NOTES_SUBJECT` 改设 `MCP_NOTES_IDENTITY_FILE`。DoD 由 11 条增至 12 条：第 4 条改为可验收入口范围、第 9 条强调演示保持分离进程 8/8、**新增第 11 条「进程模型自洽」**（文档 / 测试矩阵 / demo 实际形态三者一致）。回归命令新增 `grep -n "StdioServerParameters" demo/mcp_stdio_demo.py`（必须仍存在，证明演示未被改成单进程）。`contracts.py` / `tasks.py` / `safe_task_write*.py` / sqlite 状态机仍**完全不改**（DoD 第 10 条：D-2 两文件 diff 必须为空）。保 196 基线零删除、评估 11/11、演示 8/8。
- 边界：同 D-021…D-026（不新增依赖；不改 P2/C 安全核心与 sqlite 状态机；不进 D-4 / D-5 / D-6；不创/跑真实 symlink/junction；不碰 `02-agent-research-workflow/` 与 `.workbuddy/`；不 push / PR / 提交）；D2-L1…D2-L4 仍默认 skip、blocked-until-approved。**待用户单独批准事项（本轮整理为 9 项）**：OS 原生凭证绑定、签名清单/PKI、真实多用户环境、**跨进程身份一致性断言机制（IPC/共享凭据/启动握手）**、真实 symlink/junction 身份根夹具、**为 `host.py` 新增 CLI/服务启动入口**、身份文件移至共享/网络位置、**WSL/Linux/远程 runner 真实 POSIX 验证**、公开部署/网络传输。
- 结果：`docs/D-3-design.md` 重写为 **v3**（文首含 v3 修订说明表 + 折叠的 v2 历史表；§5 全面重写为 M1 进程模型、新增 §5.3 多身份加载与 §5.4 哨兵定位；§3 稳定码前提收敛；§7.1 调用点适配类型表；§7.2 D/E 组重写、测试总数 27→28；§7.4 DoD 11→12 条；§9 待批准 7→9 项）；同步更新 `DECISIONS.md`（D-026 加被取代标记 + 本条）、`docs/PRD.md`（§10 第 1 条 + §11.2 D-3 行）、`docs/ARCHITECTURE.md`（§2 校验边界注、§6 known-limitations、§7 D-3 收紧行）、`STATUS.md`（阶段行 + v2 历史条目标注 + v3 新条目）。**原为设计包：未实现、未暂存、未提交**（D-027 设计阶段历史结果记录）；**D-3 实现已由本地提交 d14341d 落地（未 push、未建 PR；本次 Codex 复核中），见 D-027-impl**。Codex 第三轮已 PASS（2026-08-08），设计可进入实现阶段，用户已许可实现。本轮仅运行文档 / Git 检查（`git diff --check` / `git diff --cached --quiet` / `git diff --name-only` / `git status --short`）。

## D-027-impl：D-3 唯一身份来源与信任边界 · 实现（v3 设计落地，仅 Windows 可验证核心）

- 状态：accepted（已实现 · 仅 Windows 可验证核心；已由本地提交 d14341d 落地（未 push、未建 PR）；本次 Codex 复核中）
- 日期：2026-08-08
- 背景：D-027（v3 设计）经 Codex 第三轮复核 PASS（2026-08-08），用户经 AskUserQuestion 选择「进入实现（仅 Windows 可验证核心）」。本决定记录实现落地与验证结果；范围严格限定 D-3（不进 D-4/D-5/D-6、不碰 P2/`02-agent-research-workflow`/`.workbuddy`/`safe_task_write*.py`、不 push/不建 PR，待 P3 全部阶段完成统一处理），四类 blocked 事项（真实 symlink/junction、WSL/Linux 实机、跨进程一致性机制、OS 凭证/PKI/多用户/公网部署）继续 skip/占位。
- 实现：
  - **新增 `src/mcp_notes/identity.py`**（M1 进程模型核心）：`load_runtime_identity(env, identity_file_path=None)` 无全局状态、可重入纯加载函数；`RuntimeIdentity` 为 frozen dataclass + 私有哨兵 `_SENTINEL`/`_make_token`（仅防呆、非安全边界，生产唯一构造器 `RuntimeIdentity._create`）；唯一权威 subject 来源 = 受控身份根下带外预置 `identity.json`，`MCP_NOTES_SUBJECT` 仅在文件安全读取后作相等性断言、永不产生值、不作后备；schema 校验 `version:int==1`（显拒 bool）/`subject`(D-1 白名单 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)/`subject_kind=="deployment-provisioned"`、未知顶层键严格拒绝、≤4096 B、UTF-8 无 BOM；fd/HANDLE 链安全读取复用 D-2 原语零修改——Windows `open_task_root`+`_nt_open`+`msvcrt.open_osfhandle`+`_read_fd`，POSIX `_posix_supported()` 判否即失败 + `_open_root`+`os.open(name, O_RDONLY|O_NOFOLLOW, dir_fd=parent)`+`os.fstat(fd)` 防 TOCTOU，禁止字符串路径/`realpath` 安全判断，能力缺失稳定 `task-root-unsafe`；`SafeWriteError`/`OSError`/`ValueError`/`UnicodeDecodeError`/`json.JSONDecodeError` 在 identity 边界统一映射 `TaskPublishError(INVALID_ARGUMENTS) from None` 且不泄露原始异常；`write_identity_file()` 仅夹具用。
  - **改 `src/mcp_notes/host.py`**：`TrustedHostController.__init__(self, db_path, task_root, identity: RuntimeIdentity, clock=None)`——`if not isinstance(identity, RuntimeIdentity): raise TaskPublishError(INVALID_ARGUMENTS)`；`subject = identity.subject`，`_valid_subject` 失败关闭；不新增 `main()`。
  - **改 `src/mcp_notes/server.py`**：`ServerConfig.subject: str` → `ServerConfig.identity: RuntimeIdentity`，`__post_init__` 校验 `isinstance` 与 `_valid_subject`；`from_env` 经 `identity = load_runtime_identity(env, identity_file_path=env.get("MCP_NOTES_IDENTITY_FILE"))` 注入，`config = cls(..., identity=identity)`；`build_server` 由 `config.subject` 改为 `config.identity.subject`；`main()` 稳定码路径（`server.py:376-378` 写 `stderr="invalid-arguments\n"`+`sys.exit(2)`）未改。
  - **适配调用点**：12 处 `TrustedHostController(`（demo 3 / tests 4 / evals 5，按「主身份」与「第二受控身份根」两类加载真实 `RuntimeIdentity`）+ 2 处 `ServerConfig(`（evals 1 / tests 1）；demo/evals/tests 全部改为写真实临时 `identity.json` 夹具后调真实 `load_runtime_identity()`，**不留绕过加载器后门**；`demo/mcp_stdio_demo.py` 移除 `MCP_NOTES_SUBJECT`、改设 `MCP_NOTES_IDENTITY_FILE`，保留分离进程形态（`StdioServerParameters` 仍存在 line 39/104）；测试 28 用独立 `_identity_bootstrap_launcher.py` 受测启动包装器（不设 `subject=` 入口、仅经 `MCP_NOTES_IDENTITY_FILE` 注入，满足 D-027 §5.3 禁止绕过要求）。
  - **新增 `tests/test_identity.py`**：30 方法（A1-6/B7-14/B-handle-leak/C15-20/D21-26/E27-28）；`test_b14_real_symlink_junction` 标 `@unittest.skip("blocked-until-approved...")` 占位（真实 symlink/junction 待单独批准）；`test_b_handle_leak_on_open_osfhandle_failure`（win32，mock 回归）断言 `open_osfhandle(fh)` 失败时 `fh` 泄漏被恰好关闭一次且边界稳定 `invalid-arguments`；覆盖 identity.json 合法/非法 schema/越限/BOM/未知键、`MCP_NOTES_SUBJECT` 断言、`RuntimeIdentity` 防呆、分离加载两身份根→`confirmation-identity-mismatch`、`server.main()`（E27）与受控启动器（E28）失败关闭 stdout 空/stderr 含 `invalid-arguments`/非零退出/无 traceback/路径泄露。
  - **D-2 两文件 `safe_task_write*.py` 零修改**（验证：`git diff --stat -- src/mcp_notes/safe_task_write.py src/mcp_notes/safe_task_write_posix.py` 为空）；`contracts.py`/`tasks.py`/sqlite 状态机零修改。
- 边界：同 D-021…D-027（不新增依赖；不进 D-4/D-5/D-6；不创/跑真实 symlink/junction；不碰 `02-agent-research-workflow/` 与 `.workbuddy/`；不 push/PR/提交）；四类 blocked 事项仍待用户单独批准；`MCP_NOTES_SUBJECT` 仅作相等性断言、不作后备。
- 结果（2026-08-08 全量复跑）：`compileall` 通过；`discover -s tests` 总计 **225 项**（216 执行通过 + 9 链接测试默认跳过，较 D-2 基线 196 净增 29；新增 test_identity 29 方法含 1 真实链接 skip）；`tests/test_identity.py` **29（28 执行 + 1 skip）** + `tests/test_server_entry.py` **6 项** + `tests/test_mcp_integration.py` **23 项** + `tests/test_create_task.py` **62 项** + `tests/test_safe_publish_posix.py` **31 项**（27 执行 + 4 链接占位跳过） + `evals/run_c_phase_eval.py` **11 例** + `demo/mcp_stdio_demo.py` **8 项**断言全部通过；`python -m pip check` → `No broken requirements found.`；`git diff --check` 通过（仅 CRLF 提示）；`grep -n "StdioServerParameters" demo/mcp_stdio_demo.py` → line 39/104 仍存在（分离进程形态保持）；`git diff --stat -- src/mcp_notes/safe_task_write.py src/mcp_notes/safe_task_write_posix.py` → 空（D-2 零修改）；敏感扫描（`api_key`/`secret`/`password`/`token`/`sk-`/私钥）无真实凭据。待 Codex 再复核（复核提示词见下方「Codex 复核提示词」）。
- **2026-08-08 复核修复轮**（Codex 风格复核发现 1 P0 + 2 P1，已全部修复，未暂存/未提交/未 push）：
  - P0-1：`test_d23`/`test_d24` 未关闭 `TasksStore`/`TrustedHostController` 连接 → 全量复跑输出含本机绝对路径的 SQLite `ResourceWarning`，违反「测试日志不出用户名/绝对路径」；改 try/finally 分别 `store.close()`/`host.close()`，复跑零 `ResourceWarning`。
  - P1-1：Windows `msvcrt.open_osfhandle(fh)` 失败时未关闭已打开 `fh` HANDLE → 泄漏；改为仅当 `fh` 未转交为 `fd` 时 `_close(fh)`，转交成功后仅由 `os.close(fd)` 关闭；新增 `test_b_handle_leak_on_open_osfhandle_failure`（win32）mock 回归。
  - P1-2：`_read_fd` 原每次读 1 MiB 再判 4096B 上限，与「最多读 4097B 后拒绝」设计不符且 `test_b13` 用 mock 桩非真实边界；改为每次仅读 `MAX_IDENTITY_BYTES + 1 - len(data)`，重写 `test_b13_size_boundary` 以合法 JSON + 空白填充构造真实 4096B（通过）/4097B（失败关闭）文件。
  - 修复后复跑：`discover -s tests` 总计 **226 项**（217 执行 + 9 skip，较 225 基线净增 1：`test_b_handle_leak_on_open_osfhandle_failure`），以 `-W error::ResourceWarning` 运行**零 ResourceWarning**、exit 0；eval **11/11**、demo **8/8**、`compileall`/`pip check`/`git diff --check` 全绿；D-2 `safe_task_write*.py` 仍零改动。仍不提交/不 push/不建 PR（待 P3 全部阶段完成统一处理）。

### Codex 复核提示词（D-027-impl 实现轮）

> Please re-review the D-3 implementation in branch `codex/p3-local-mcp-tool-service` (HEAD currently `09038cd`, working tree adds D-3 implementation uncommitted) of the P3 local MCP Notes tool service.
>
> **What changed this round (implementation only, no design changes):**
> 1. NEW `src/mcp_notes/identity.py` — M1 process model: `load_runtime_identity(env, identity_file_path=None)` is a stateless, re-entrant pure loader (no global state, no singleton); called exactly once per process at bootstrap and injected into `ServerConfig` / `TrustedHostController`. Produces immutable `RuntimeIdentity` (frozen dataclass + private sentinel `_SENTINEL`/`_make_token`, sentinel is defensive typing only, NOT a security boundary). The ONLY authoritative subject source is a controlled identity root with an out-of-band provisioned `identity.json`; `MCP_NOTES_SUBJECT` is used ONLY as an equality assertion AFTER safe file read, never produces a value, never a fallback. Schema enforcement: `version:int==1` (rejects bool), `subject` (D-1 whitelist `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`), `subject_kind=="deployment-provisioned"`, strict rejection of unknown top-level keys, ≤4096 B, UTF-8 no BOM. Secure read uses fd/HANDLE chain reusing D-2 primitives UNMODIFIED — Windows `open_task_root`+`_nt_open`+`msvcrt.open_osfhandle`+`_read_fd`; POSIX `_posix_supported()` false→fail + `_open_root`+`os.open(name, O_RDONLY|O_NOFOLLOW, dir_fd=parent)`+`os.fstat(fd)` (TOCTOU-safe), forbids string-path/`realpath` safety checks, capability-missing fails closed. `SafeWriteError`/`OSError`/`ValueError`/`UnicodeDecodeError`/`json.JSONDecodeError` mapped at the identity boundary to `TaskPublishError(INVALID_ARGUMENTS) from None` with no original exception leaked.
> 2. MODIFIED `src/mcp_notes/host.py` — `TrustedHostController.__init__(db_path, task_root, identity: RuntimeIdentity, clock=None)` rejects bare `str` / non-`RuntimeIdentity` with `invalid-arguments`; no new `main()`.
> 3. MODIFIED `src/mcp_notes/server.py` — `ServerConfig.subject: str` → `ServerConfig.identity: RuntimeIdentity`, `__post_init__` validates `isinstance(identity, RuntimeIdentity)` + `_valid_subject`; `from_env` injects `load_runtime_identity(env, identity_file_path=env.get("MCP_NOTES_IDENTITY_FILE"))`; `build_server` uses `config.identity.subject`; `main()` stable-code path (`:376-378`, stderr `invalid-arguments` + `sys.exit(2)`) unchanged.
> 4. ADAPTED call sites: 12× `TrustedHostController(` (demo 3 / tests 4 / evals 5, split into main-identity and second-controlled-identity-root) + 2× `ServerConfig(` (evals 1 / tests 1). demo/evals/tests now write a real temp `identity.json` fixture then call the real `load_runtime_identity()` — NO backdoor bypassing the loader. `demo/mcp_stdio_demo.py` drops `MCP_NOTES_SUBJECT`, sets `MCP_NOTES_IDENTITY_FILE`, keeps separate-process shape (`StdioServerParameters` still present at lines 39/104). Test 28 uses a dedicated `tests/_identity_bootstrap_launcher.py` (no `subject=` entry point; only `MCP_NOTES_IDENTITY_FILE` injection) satisfying D-027 §5.3.
> 5. NEW `tests/test_identity.py` — 29 methods (A1-6/B7-14/C15-20/D21-26/E27-28); `test_b14_real_symlink_junction` is `@unittest.skip` placeholder (real symlink/junction still blocked-until-approved).
>
> **Hard constraints (must hold):**
> - `contracts.py` / `tasks.py` / `safe_task_write*.py` / sqlite state machine UNCHANGED — verify with `git diff --stat -- src/mcp_notes/safe_task_write.py src/mcp_notes/safe_task_write_posix.py` returns EMPTY.
> - `MCP_NOTES_SUBJECT` must never produce a subject value (only equality-assert after file read); the invariant "delete the env and reload → byte-identical result" must hold.
> - All identity failures reuse stable code `invalid-arguments` (no new `identity-unavailable`); `server.main()` and the controlled launcher must output empty stdout, stderr containing only `invalid-arguments`, non-zero exit, no traceback/path/username/env leak.
> - No new runtime dependency; no file creation of the identity root or task root in production code; no network egress; four blocked-until-approved classes remain skip/placeholder.
>
> **Verify:**
> - `cd projects/03-mcp-tool-server && .venv/Scripts/python.exe -m compileall -q src tests demo evals`
> - `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"` → expect **225 tests, 9 skipped, OK**
> - `.venv/Scripts/python.exe evals/run_c_phase_eval.py` → 11/11
> - `demo/mcp_stdio_demo.py` → 8/8
> - `.venv/Scripts/python.exe -m pip check` → clean
> - `git diff --check`
>
> **Expected:** all green; D-2 diff empty; separate-process demo still 8/8; identity failures fail closed with stable code only. Report any P0/P1 you find, especially: (a) any path where `MCP_NOTES_SUBJECT` can produce a subject; (b) any string-path/`realpath` safety check sneaking into the identity read; (c) any original exception/OSError/absolute-path leaking through `TaskPublishError`; (d) any `RuntimeIdentity` construction bypassing `load_runtime_identity`; (e) any regression in the 196 baseline (must stay non-deleted, now 225 total with +29 identity tests).

## D-028：D-4 并发确认消费与多用户隔离（设计包 v1，design-only）

- 状态：accepted（设计包 v1；初版交 Codex 设计复核，结论 **NEEDS-FIX（1 P0 并发设计漏洞 + 若干 P1）**，已按复核意见第一轮修正；并据用户更严格反馈做第二轮收紧——P0-1 COMMIT 未知恢复 / P1-1 对齐防死锁 / P1-2 T2 双确定性顺序 / P1-3 T5 语义 / P1-5 过期事务守卫 / P1-4 审计表述 / 独立反向安全审计，design-only、未实现、未暂存、未提交、未 push、未建 PR，待 Codex 集中复核）
- 日期：2026-08-08
- 背景：D-3 实现已由本地提交 `d14341d` 落地（未 push、未建 PR；本次 Codex 复核中）。当前 `src/mcp_notes/tasks.py` 的 `approve`/`reject`/`cancel` 为 check-then-act（`SELECT` 读 `PENDING` → 发布 → 无 `WHERE status` 守卫的 `UPDATE`），无跨进程唯一消费保证；`reject`/`cancel` 的无守卫 `UPDATE` 还可能把已 `APPROVED` 覆盖为 `REJECTED`。本轮**仅做设计与文档**（不写代码、不装依赖、不暂存、不提交、不 push、不建 PR；不进 D-5/D-6）。
- 决定（D-4 关键设计取舍，详见 `docs/D-4-design.md` v1）：
  - **并发确认消费靠事务条件更新（唯一消费闸门）**：跨进程唯一性来自两点且**都不是** WAL/连接池/Python 锁——① D-2 `publish_task_file` 的 no-replace 原子无覆盖（物理文件至多创建一次，其余得 `unchanged`，绝不二次写入）；② sqlite3 条件 `UPDATE ... WHERE confirmation_id=? AND status='PENDING' AND subject=? AND correlation_id=?`，以 `cur.rowcount` 判定唯一消费者（1 行=胜者、0 行=已消费，返回稳定 `confirmation-already-consumed`、不写 `APPROVED`、不二次发布）。**明确否定把 WAL/连接池/Python 锁描述为并发安全方案**。
  - **保持「文件发布成功后才写 APPROVED」合同 + 持久化 PUBLISHING 中间态（第三轮修正）**：顺序 = `BEGIN IMMEDIATE` → 权威重读 `PENDING` → 阶段 1 条件 `UPDATE` 写 `PUBLISHING` + 提交（发布前持久，不写 `consumed_at`）→ `BEGIN IMMEDIATE` → 发布文件(no-replace) → 成功则阶段 2 条件 `UPDATE` 写 `APPROVED` + 提交；D-2 对外稳定错误码不能证明“无残留”，故发布错误一律保留 `PUBLISHING`、失败关闭，后续仅可受控恢复完成 `APPROVED`。`reject`/`cancel`/`expiry` 读到 `PUBLISHING` 不得写负向终态，须走 PUBLISHING 恢复。不绕过 D-2 `publish_task_file`/句柄安全层。
  - **`reject`/`cancel` 同步加条件 `UPDATE` 守卫**：已 `APPROVED` 的 confirmation 不被覆盖为 `REJECTED`/`CANCELLED`（解决 approve/reject 竞争）。
  - **崩溃恢复矩阵**：发布后/提交前崩溃 → 重放幂等、文件恰好一次；**非分布式事务**，不声称跨机原子性。
  - **多用户隔离边界（本轮）**：本地单 subject 模型下，**`confirmations` 表与派生 `task_id` 受 `subject` 绑定**（行级，双重断言）；`task_id` 由 subject 派生天然 per-subject 命名空间；但**当前 `audit` 表不存 `subject` 列**，只能称「**单 subject 审计**」，**跨 subject 审计隔离属 blocked**；物理 `task_root` 共享、多 OS 账户隔离亦 blocked——真实多用户（多 subject/多 OS 账户/per-subject task_root/audit 增 subject 列）**标 blocked-until-approved**，D-4 不实现。客户端/模型仍不能提供或覆盖 subject/correlation_id/确认身份。
  - **错误语义与审计**：复用既有 12 类稳定码；提案新增 `database-busy`（仅设计、不实现，为加法码）；审计仅存 event/error_code/task_id/confirmation_id，不记路径/用户名/正文/密钥/Cookie/鉴权头/原始异常。
  - **测试与评估计划**：确定性多进程并发（用 `multiprocessing.Barrier` 或「发布后/条件 UPDATE 前」测试 seam 对齐竞态窗口，**严禁 sleep 赌时序**）；覆盖双进程 approve、approve/reject 竞争、重复重放、SQLite busy、发布冲突、崩溃恢复、subject 隔离；不创建真实 symlink/junction；D-6 的 40 例仍不实现（D-4 仅规划贡献案例）；保 226 项（217+9 skip）基线零删除。
- 边界：同 D 阶段约束（不新增依赖；不改 P2/C 安全核心与 sqlite 状态机 schema 以外部分；不进 D-5/D-6；不创/跑真实 symlink/junction；不碰 `02-agent-research-workflow/` 与 `.workbuddy/`；不修改 `safe_task_write*.py`；不 push/PR/提交）；保 226/9 基线、eval 11/11、demo 8/8。
- 结果：新增 `docs/D-4-design.md`（设计包 v1）；更新 `docs/PRD.md`（§10 + §11.2 D-4 行）、`docs/ARCHITECTURE.md`（§7 D-4 收紧行 + 基线）、`STATUS.md`（D-4 设计阶段条目 + 阶段行）。**仅运行文档/Git 检查（`git diff --check` / `git diff --cached --quiet` / `git diff --name-only` / `git status --short`），未暂存、未提交、未 push、未建 PR，等待 Codex 设计复核**。
- 复核修正（2026-08-08，Codex 设计复核结论 NEEDS-FIX → 已修正，待再审）：**P0**——原 `approve`「先发布、后条件 `UPDATE`」在 `BEGIN IMMEDIATE` 之外，存在交错「A 发布文件、B 改状态为 REJECTED、A 才条件 UPDATE（rowcount=0）」→ 文件在但 DB 为 REJECTED。修正：所有终态动作在读状态前 `BEGIN IMMEDIATE` 抢占 SQLite 写预约（RESERVED 锁），同一事务内完成「重读 → 发布（仅 approve）→ 条件 UPDATE → idempotency/audit → COMMIT」，彻底串行化；保留 `WHERE status='PENDING'` + `rowcount` 纵深。**关键澄清：`busy_timeout` 只是缓解 `SQLITE_BUSY` 的等待窗口，绝非正确性保证——正确性来自写预约串行化 + 条件 UPDATE**。**P1**——(a) T1 `created` 定义修正：条件 UPDATE 胜者、本次首次提交 `APPROVED` 即 `created`（即便崩溃恢复文件为 `unchanged` 仍 `created`），仅之后重放已 `APPROVED` 才 `unchanged`+`already_consumed`；(b) T4 增**真实双进程写预约竞争**（`Barrier`/`Event` 对齐、无 sleep）+ commit 失败 monkeypatch；(c) 明确 `BEGIN IMMEDIATE` 超时 / `COMMIT` 失败语义：文件可能已存在、~~DB 回 `PENDING`~~（**此表述已被第二轮 §1.5 修正为「`COMMIT` 异常后持久化状态视为未知，不得宣称必回 `PENDING`」**）、返回稳定码、后续重放恢复、不承诺本次无残留；(d) §8 审计 subject 表述修正为「单 subject 审计，真实跨 subject 审计隔离 blocked」。详见 `docs/D-4-design.md` §10。
- 结果（修正版）：`docs/D-4-design.md` 已重写（§1.1 / §1.2 / §1.3 / §1.4 / §2.1 / §2.2 / §2.3 / §4.3 / §5.1 / §5.2 / §6 / §8 同步修正）。DECISIONS D-028 本段追加复核修正。**仍仅文档改动、未暂存、未提交、未 push、未建 PR，待 Codex 再审**。
- 复核修正（第二轮，2026-08-08，据用户更严格反馈 + 独立反向安全审计）：**P0-1（核心）**——删除所有「`COMMIT` 失败 → 事务回滚、DB 必回 `PENDING`」的错误断言（原 §1.4 / §2.2 / §2.3 / §4.3 / §5.2 T4）。新增 `docs/D-4-design.md` **§1.5 恢复合同**：`commit()` 异常后持久化状态**视为未知**；区分 commit 阶段 `SQLITE_BUSY` 与一般 I/O 异常（不得混为「必回滚」）；恢复 = 尽力 `rollback`（仅释放本连接存活事务、不构成「已证明 PENDING」）→ 关连接 → **新连接重读权威状态**（APPROVED→不发布；PENDING→安全重放；读失败/无法关连接→`task-write-failed` 失败关闭）；不承诺无残留、不承诺重试必成。§2.2 / §2.3 / §4.3 全面改为「未知」语义。**P1-1**：§5.1 明确对齐点角色——协调器只经 `Queue` 观测（不查持锁 DB）、胜者 signal `Event B` + wait `release_B`、败者只等 DB 锁（非 `Event B` 参与者）；整体超时防死锁，不用 sleep 赌时序。**P1-2**：§5.2 T2 拆 T2a（approve 先提交→APPROVED+文件；reject 不覆盖）/ T2b（reject 先提交→终态+无文件；approve 不发布）两确定性顺序，gate Event 控制先后。**P1-3**：§5.2 T5 语义修正——正常并发第二进程归 T1（持锁重读已 APPROVED→`already_consumed`，不调用发布层）；T5 改为 D-2 `publish_task_file` 单独回归 + 崩溃后恢复发布。**P1-5**：过期（`EXPIRED`）持久化写必须落在 `BEGIN IMMEDIATE` 事务内、受 `WHERE status='PENDING' AND subject=? AND correlation_id=?` 守卫；乐观预读**不写** `EXPIRED`/`audit`/`commit`（无副作用，见 §1.3 步骤 2、§2.1、§6）。**P1-4**：本 D-028「多用户隔离边界」表述由「审计按 subject 行级绑定」修正为「`confirmations` 与 `task_id` 受 subject 绑定；当前 `audit` 表无 subject 列，仅称单 subject 审计；跨 subject 审计隔离 blocked」；与 §3.2 一致。**反向审计**：逐项核对无「未知事务结果写成确定状态」、无「发布后终态被另一动作覆盖」路径、乐观读无副作用、失败仅稳定码（无路径/用户名/正文/原始异常）、T1–T8 可测无 sleep、单 subject/真实多用户边界一致、基线 226=217+9、无 WAL/池/锁作跨进程正确性、未写成已实现、未声称分布式事务/多用户/链接/部署。详见 `docs/D-4-design.md` §10。**本轮仅文档改动、未暂存、未提交、未 push、未建 PR，待 Codex 集中复核**。

- 复核修正（第三轮，2026-08-09，Codex 集中复核结论 NEEDS-FIX → 已修正，待 Codex 最终复核 / 接力实现）：**P0（崩溃恢复竞态，本轮核心）**——原 `BEGIN IMMEDIATE` 内「发布 + 条件 UPDATE」仍可被崩溃恢复击穿：A 发布后、`COMMIT` 前崩溃回滚为 `PENDING`（文件已存在），随后 B `reject`/`cancel`/`expiry` 读 `PENDING` 写负向终态 → 又成「文件存在 + 负向终态」。修正：引入**持久化 `PUBLISHING` 中间态**（状态机 `PENDING → PUBLISHING`(阶段 1 提交，发布前) → `APPROVED`(阶段 2 提交，文件成功后)）；`reject`/`cancel`/`expiry` 读到 `PUBLISHING` **不得写负向终态**，须走 `_recover_publishing`（完成 `APPROVED` / 或 D-2 证明无残留回退 `PENDING` / 或残留不可判定失败关闭）。详见 `docs/D-4-design.md` §1.2(第4层纵深)/§1.3(两阶段+`_recover_publishing`)/§1.5(PUBLISHING 重读)/§2.1-2.3/§4.3/§5.2(T9)/§6/§10。**P1-a**：审计不在会被 `ROLLBACK` 丢弃的同事务内当已提交事实——成功路径在主事务 `COMMIT` 后以**独立 best-effort 事务**写入、失败不影响主结果（§4.2）。**P1-b**：`created` 定义改为「逻辑审批提交胜者」，删「文件创建者=SQL 胜者同进程」误导（崩溃恢复物理文件可来自旧进程）。**P1-c**：测试 seam 改为私有连接工厂 `_make_connection` + 包装 `_commit(conn)`/`_close(conn)`，不直接 monkeypatch `sqlite3.Connection`（C 实现不可实例替换）（§5.2 T4/§6）。**database-busy 采纳**：COMMIT 失败路径固定复用 `task-write-failed`；`database-busy`/`confirmation-in-progress` 仍属可选加法码，实现阶段决策（§4.1/T4）。**高层文档同步**：`STATUS.md`/`ARCHITECTURE.md`/`DECISIONS.md` 中「`PENDING` 一律可重放」改为「`PENDING` 仅文件未发布时安全重放；文件已存在时按 `PUBLISHING` 契约（完成/回退）处理，不得写负向终态」。本轮仅文档改动、未暂存、未提交、未 push、未建 PR；用户已决定后续本地 MCP 工具服务开发全交 Codex 接力（见 `docs/HANDOFF-TO-CODEX.md`）。

## D-029：D-4 实现结果（并发确认消费）

- 状态：accepted（已实现，待本地提交；不 push、不建 PR）。
- 决定：所有 `approve` / `reject` / `cancel` / expiry 持久化写均先 `BEGIN IMMEDIATE` 并权威重读。批准采用 `PENDING → PUBLISHING → APPROVED` 两阶段；阶段 1 在发布前提交，阶段 2 仅在 D-2 发布成功后条件更新。D-2 只暴露稳定错误码，不能证明清理是否无残留，故发布失败始终保留 `PUBLISHING`、返回稳定错误并失败关闭；恢复仅可再次受控发布后完成 `APPROVED`，绝不回退 `PENDING` 或写负向终态。
- 取舍：`busy_timeout` 只缓解 `SQLITE_BUSY`；跨进程正确性来自 SQLite 写预约、条件 UPDATE + `rowcount`、D-2 no-replace 与持久状态机，而非 WAL、连接池或 Python 锁。终态审计在主提交成功后另开 best-effort 事务，审计失败不回滚已提交状态。
- 验证：新增 `tests/test_d4_concurrency.py` 九项离线确定性回归（含 `multiprocessing.Barrier` 双进程批准、批准/拒绝顺序、未知 COMMIT 重读恢复、审计失败与 `PUBLISHING` 防负向终态）；不创建真实链接。当前 `unittest` 235 项（226 通过 + 9 skip）、评估 11/11、demo 8/8、`compileall` / `pip check` / `git diff --check` 通过；`safe_task_write*.py` 零改动。真实多用户与跨 subject 审计隔离仍 blocked-until-approved。

## D-030：D-5 本机回环 streamable-HTTP

- 状态：accepted（已实现，待本地提交；不 push、不建 PR）。
- 决定：stdio 保持默认。仅部署配置显式选择 `streamable-http` 时启用 MCP SDK v2 内置 HTTP；只允许 `127.0.0.1` 或 `::1`、端口 `1..65535` 与固定 `/mcp` 端点。SSE、未知 transport、空 transport、`0.0.0.0`、局域网地址和非法端口均复用 `invalid-arguments` 失败关闭。
- 取舍：不额外启用 legacy SSE，避免重复传输面；不新增依赖，复用已锁定 SDK 的传递依赖。此能力仅服务本机 Host/Client 互通，绝不构成公网部署或多用户授权。
- 验证：新增 `tests/test_d5_transport.py` 四项测试：默认 stdio、配置拒绝三类、以及真实 127.0.0.1 streamable-HTTP Client 的 `list_tools` 与 `create_task` PENDING 路径。确认 Tool 列表仍只有 `search_notes` / `create_task`，确认动作不暴露。当前总测试 239 项（230 通过 + 9 skip）。

## D-031：D-6 40 例固定离线评估

- 状态：accepted（已实现，待本地提交；不 push、不建 PR）。
- 决定：40 例是总数，保留并真实复跑 C 阶段既有 11 例，新增 29 例；案例、金标准、运行器和结果基线分别版本化，全部只用原创虚构夹具与临时受控目录。禁止模型输出、真实私人笔记、外网、真实链接夹具进入评估。
- 验证：`evals/run_d6_eval.py` 真实运行 40/40；`tests/test_d6_eval.py` 自动验证运行器，当前 unittest 240 项（231 通过 + 9 skip）。安全指标：未授权写入 0、敏感泄露 0、外网尝试 0；C 评估 11/11 与 stdio 演示 8/8 保持通过。
