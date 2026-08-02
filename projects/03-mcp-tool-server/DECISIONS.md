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
- 决定：Slice A 只实现 `search_notes` 的纯标准库数据合同、索引登记、离线检索与 stdlib `unittest`；不接触 MCP SDK、不建 `.venv`、不安装依赖、不读真实笔记、不联网。
- 参数锁定：note_id 由 relative_path 的 SHA-256 前 16 位派生；excerpt 内部文本上限 120 字符；匹配为大小写无关 + Unicode NFKC 归一；hits 上限 5，按索引顺序返回。
- 测试底座：当前用 CPython 标准库 `unittest`（`python -m unittest`）直接运行，避免提前引入 pytest 与安装步骤；后续统一测试框架待安装批准时再决定。
- 边界：`index.py` 当前仅做最小普通 `.md` 文件登记，未实现 symlink/junction/reparse point/路径穿越/TOCTOU 的拒绝式检查；这些属于 Slice B，未因 Slice A 提前放宽。
- 结果：`compileall` 通过；27 项 stdlib 单元测试全部通过；无网络、无依赖、无密钥。

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
- 结果：`compileall` 通过；38 项 stdlib 单元测试全部通过（含 3 个全角绕过反例、1 个 casefold Unicode 反例、网络阻断验证 5 项）；无网络、无依赖、无密钥。

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
- 结果：`compileall` 通过；B1 新增 T0–T9 共 30 项 + Slice A 既有测试全部保留并通过；stdlib `unittest` 共 72 项（68 执行通过 + 4 链接测试默认跳过）；无网络、无依赖、无密钥。经 Codex 二次独立复验未通过后，按 P0/P1 清单修订 `UNICODE_STRING.MaximumLength` 溢出边界并补失败回归测试、统一真实链接测试合同与文档测试数，复跑 72 项全部通过。
