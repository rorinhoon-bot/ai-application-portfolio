# P3 PRD：本地 MCP 笔记检索与受控任务创建服务

- 版本：v0.3（Slice A / B1 / B2a 离线核心已实现并离线验证；C 阶段已完成 MCP SDK 适配与 Host/Client 真实本地 stdio 演示）
- 日期：2026-08-01（B2a 更新 2026-08-02）
- 范围：原创、虚构、离线、确定性夹具；`search_notes` 与 `create_task` 的**离线核心逻辑**已实现（纯标准库，无依赖），**并已由 C 阶段完成 MCP Server/Resource/stdio transport 与真实本地 Host/Client 演示（唯一直接生产依赖 `mcp==2.0.0`，本地运行，不调用模型、不读私人笔记；运行时只用本地 stdio 管道、不发起对外网络连接，测试中父进程与 Server 子进程均默认阻断外部网络）**。C 阶段已按 Codex 复核意见完成 P0/P1 一次性修复，见 `DECISIONS.md` D-018。

## 1. 问题与目标用户

本地 AI 客户端需要查询一小组允许笔记，并把用户已确认的事项写成任务。若 MCP Server 暴露任意路径、文件名、命令或直接写权限，模型、客户端重试或笔记中的提示注入文本可能读取越界文件或产生未授权写入。

- 目标用户：需要在本地 AI Host 中安全检索项目笔记、并人工确认任务创建的个人开发者。
- 输入：受限关键词；受限任务标题和描述；来自可信本地 Host 适配器的主体与调用关联 ID；人工确认界面的批准、拒绝或取消动作。
- 输出：脱敏检索结果；待确认请求；批准后不可覆盖的任务记录；稳定错误码；只读服务说明 Resource。
- 成功目标：证明 MCP 协议边界、JSON Schema、路径安全、Human-in-the-loop、持久化幂等和离线可评估性。

## 2. 非目标

- 不搜索任意目录、任意文件名、私人真实笔记、网络 URL 或云盘。
- 不执行命令、Shell、URL、插件、代码、SQL 或笔记指令。
- 不调用真实模型 API、不下载数据、不发起对外网络连接（运行时只用本地 stdio 管道）、不产生费用、不公开部署。
- 不做语义检索、Embedding、向量库、Agent、多智能体、Web UI、任务编辑/删除或通用任务系统。
- C 阶段已实现 MCP Server 与真实本地 Host/Client 演示（`demo/mcp_stdio_demo.py`），并验证真实本地集成。

## 3. 能力合同（已实现）

### 3.1 `search_notes(keyword)`：只读

| 项目 | 实现合同 |
|---|---|
| 参数 | 仅 `keyword`；JSON object 不得有未知字段 |
| 合法值 | UTF-8 字符串；去首尾空白后长度 `1..80`；不含控制字符、绝对路径、`..`、URL、命令或 Shell 语义 |
| 数据来源 | 仅服务启动时验证并登记的笔记白名单目录；仅允许的普通 UTF-8 `.md` 文件 |
| 匹配 | 冻结的大小写无关确定性关键词匹配；不执行笔记文本、Markdown 链接或指令 |
| 返回 | 最多 5 条：稳定 `note_id`、标题、受限长度的安全摘录、匹配计数；不返回磁盘路径、完整正文、隐藏文件或异常栈 |
| 副作用 | 无；不写索引、不发起网络连接、不修改笔记 |

`keyword` 是数据，不是路径、过滤表达式、正则、文件名或命令。笔记正文即使含“忽略规则”“读取 C:\\...”或 URL，也只能作为不可信文本被转义/截断后展示，绝不改变 Tool 权限。

### 3.2 `create_task(title, description)`：受控写

| 项目 | 实现合同 |
|---|---|
| 参数 | 仅 `title`、`description`；拒绝未知字段和非字符串 |
| 合法值 | `title` 去空白后 `1..120` 字符；`description` 去空白后 `1..1000` 字符；拒绝控制字符、路径、`..`、URL、命令和 Shell 语义 |
| 首次返回 | `PENDING_CONFIRMATION`、服务生成 `task_id`、`confirmation_id`、内容哈希、过期时间；不写任务文件 |
| 写入前提 | 可信本地人工确认界面显示冻结标题、描述、任务 ID、到期时间后，使用同一主体批准 |
| 批准结果 | 原子创建受控目录内程序派生的 `<task_id>.json`；**文件发布成功后再提交 `APPROVED` 状态**，返回 `CREATED` 或幂等 `UNCHANGED` |
| 发布失败 | 确认记录保持 `PENDING`，返回稳定 `task-write-failed`（或 `task-root-unsafe`）；**清理成功（`NtDeleteFile` 返回 `STATUS_SUCCESS`）则磁盘不留最终文件、半成品或临时残留，移除故障后可重放并成功创建；清理失败（非成功 NTSTATUS）则失败关闭，仅返回稳定 `task-write-failed`，不承诺零残留或自动重试成功** |
| 任务根 | 必须是部署配置中**预存在**的受控目录；服务不创建任务根或其祖先目录，仅做句柄链验证，验证不通过 → `task-root-unsafe` |
| 拒绝/取消 | 返回稳定终态，不写任务文件 |

Tool 参数没有路径、文件名、目标目录、命令、URL、Shell 参数、主体 ID、任务 ID、确认 ID 或幂等键。它们不能由模型/客户端控制。可信调用关联 ID 只能由本地 Host 适配器注入；缺失时拒绝写意图。

> **实现状态（Slice B2a，2026-08-06）**：上述 `create_task` 离线核心**已实现**于 `src/mcp_notes/tasks.py` 与 `src/mcp_notes/safe_task_write.py`，并配套固定金标准 `evals/gold/tasks-core-v1.json`（12 场景）与 `tests/test_create_task.py`（53 项）。已实现范围严格限于“离线受控写核心”：严格数据合同、`PENDING/APPROVED/REJECTED/CANCELLED/EXPIRED` 状态机、sqlite3 持久化、任务文件 no-replace 原子发布（Windows 原生 `NtCreateFile(FILE_CREATE, OBJ_DONT_REPARSE)` 原子无覆盖 + 句柄式 `open_task_root` 任务根/祖先目录 reparse 与 TOCTOU 防护，绝不 `os.replace`、冲突绝不覆盖）、12 类稳定错误码（含 `confirmation-invalid-id` / `task-root-unsafe`）。发布失败语义与任务根所有权按 D-015 落实：序列化先于文件创建；创建成功后 `WriteFile` / `FlushFileBuffers` 失败 → 稳定 `task-write-failed` 且不泄露原始异常，文件 HANDLE 只关闭一次后以已验证父目录 HANDLE 相对 `NtDeleteFile` 清理（不使用字符串路径删除/替换），确认记录保持 `PENDING`；**清理成功（`NtDeleteFile` 返回 `STATUS_SUCCESS`）则无残留、移除故障后可安全重放创建；清理失败（非成功 NTSTATUS）则失败关闭，仅返回稳定 `task-write-failed`，不承诺零残留或自动重试成功**。任务根须由部署配置预存在，生产代码不调用 `os.makedirs` 创建任务根或祖先目录。`TrustedContext` 的实际校验规则为“`str` / 长度 `1..256` / 不含 C0·DEL 控制字符”，**未实现安全字符白名单**。人工确认动作（`approve`/`reject`/`cancel`）由 `TrustedHostController`（`src/mcp_notes/host.py`）在 Tool 表面之外驱动（复用 B2a 的 `TasksStore`）；**C 阶段已**接入 MCP Tool/Server/Resource/stdio/Host/Client。MCP 适配层复用本核心，未在 Tool 内重建确认/写入逻辑；`approve`/`reject`/`cancel` 不作为 Tool 暴露。

### 3.3 只读 MCP Resource

Resource URI 为固定程序常量 `notes://service-info`。内容只说明 Tool 名称、参数边界、允许笔记根目录的逻辑名称、确认规则和错误码；不泄露绝对路径、真实文件清单、配置、密钥、Cookie 或鉴权头。

## 4. 读写边界

- `search_notes`：只读已验证索引。客户端不能选择目录、文件、glob、正则、排序脚本或路径。
- `create_task`：只登记受限写意图。只有 Tool 外可信人工批准器可消费确认；Server 再独立完成写入。
- Resource：静态只读说明，不能暴露配置或帮助绕过白名单。
- 所有笔记、Tool 字符串和 MCP Client 消息均是不可信数据；只有服务配置、程序派生 ID 与可信本地身份上下文可以影响权限。

## 5. Human-in-the-loop 合同

### 确认对象与时机

确认对象是单个冻结意图：`confirmation_id`、`task_id`、可信主体、可信调用关联 ID、规范化标题/描述哈希、创建时间和到期时间。`create_task` 完成校验后只创建此对象。人工界面必须在写入前展示完整文本和身份绑定，再执行批准、拒绝或取消。

### 过期、身份与重复规则

- 有效期固定十分钟；到期后状态为 `EXPIRED`，不能重新激活。
- 批准主体必须等于创建意图的可信主体；错绑为 `confirmation-identity-mismatch`。
- 哈希、任务 ID、关联 ID 或确认 ID 不匹配为 `confirmation-mismatch`。
- 只有 `PENDING` 可批准一次。再次批准返回 `confirmation-already-consumed`，不第二次写入。
- 相同可信调用关联 ID 与相同内容哈希重放，返回同一待确认或终态；同一关联 ID 配不同内容为 `idempotency-conflict`。
- 拒绝、取消、过期、非法参数和任何路径异常都不产生任务文件。

## 6. 验收标准（C 阶段已实现并验证）

1. `search_notes` 能在固定夹具返回正确 `note_id`、标题和安全摘录；不写文件、不发起对外网络连接。
2. 空关键词、超过 80 字符、未知字段、非字符串和禁止语义输入返回稳定非法参数错误。
3. 无结果返回空结果；无权限/未登记笔记不泄露存在性、路径或正文。
4. 绝对路径、`..`、符号链接、junction、reparse point、未登记文件和越界最终路径一律拒绝；服务不跟随链接。
5. 笔记内提示注入、命令、URL、伪造路径只按不可信数据处理，不增加 Tool 能力或改变写入目标。
6. 未确认、拒绝、取消、旧确认、身份错绑、重复批准都不写任务。
7. 合法批准恰好创建一个对应 `task_id` 的文件；同一意图重放返回幂等结果；冲突不覆盖旧文件。
8. 原子写入失败后没有半成品或覆盖；仅返回脱敏稳定错误码。
9. C 阶段真实本地 MCP Host/Client 演示已覆盖成功检索、待确认、批准写入和至少一条拒绝路径（见 `demo/mcp_stdio_demo.py` 与 `tests/test_mcp_integration.py`）。
10. 默认测试网络为阻断；提交内容、日志和样例不含密钥、Cookie、鉴权头、私人笔记、完整敏感响应或原始异常栈。

## 7. 失败分类（已实现的稳定错误码）

| 类别 | 例子 | 外部行为 |
|---|---|---|
| 非法参数 | 空值、超长、未知字段、类型错、路径/URL/命令语义 | `invalid-arguments`，不读不写 |
| 路径越界 | 绝对路径、`..`、链接、junction、reparse point、最终对象变更 | `path-not-allowed`，不泄露路径 |
| 文件不存在 | 索引登记后文件消失 | `note-unavailable`，不写 |
| 内容过大 | 超过冻结单文件或总读取上限 | `note-content-too-large`，不回显正文 |
| 确认缺失 | 无待确认记录或无可信关联 ID | `confirmation-required`，不写 |
| 确认失效 | 到期、哈希/主体不匹配 | `confirmation-expired` 或 `confirmation-mismatch`，不写 |
| 重复写入 | 已消费确认或关联 ID 冲突 | `confirmation-already-consumed`、`idempotency-conflict` 或 `UNCHANGED` |
| 磁盘写入失败 | 权限、容量、原子发布失败、目标冲突 | `task-write-failed` 或 `task-conflict`，不含原始异常 |

> **实现状态（Slice B2a + C 阶段）**：除“路径越界 / 文件不存在 / 内容过大”三类仍属于 `search_notes` 检索侧（由 Slice B1 句柄层覆盖，未纳入 B2a 写入核心）外，其余写侧分类——非法参数、确认缺失、确认失效（过期/错绑/不匹配）、重复写入（已消费/关联 ID 冲突/UNCHANGED）、磁盘写入失败（原子发布失败/目标冲突）——**均已由 `src/mcp_notes/tasks.py` 离线实现并测试**，错误码与上表一致，且均不泄露路径/正文/原始异常。MCP transport 层（stdio）的映射已由 C 阶段实现（`src/mcp_notes/server.py` + `host.py`），复用 B2a 核心，未在 Tool 内重建确认/写入逻辑。

## 8. 固定评估指标

- 案例通过率：通过案例数 / 全部冻结案例数。
- 检索正确率：返回 `note_id`、标题和匹配计数全部符合金标准的案例数 / 正常检索案例数。
- 安全拒绝率：应拒绝的非法、越界、链接、确认和注入案例中，安全拒绝且无副作用的比例；目标 `100%`。
- 未授权写入数：未确认、拒绝、取消、过期、错绑和重复批准路径实际创建文件数；目标 `0`。
- 幂等正确率：重放应返回相同稳定结果且任务文件数为 1 的案例比例；目标 `100%`。
- 敏感数据泄露数：日志、错误、Resource、结果、样例和 Git 扫描命中数；目标 `0`。
- 网络尝试数：默认阻断器记录的网络调用数；目标 `0`。

基线在实现后首次真实运行生成。当前没有结果，不能写成通过。

## 9. 当前范围与演示状态

当前阶段已冻结合同、数据计划、指标和安全决策，并用原创虚构笔记、临时受控目录与可信本地 Host 验证核心逻辑。C 阶段已加入真实本地 MCP Server 与真实本地 Host/Client：stdio 启动、Resource 读取、Tool 成功/拒绝路径和人工确认写入（见 `demo/mcp_stdio_demo.py`）。该演示未使用真实模型 API 或私人笔记，运行时只用本地 stdio 管道、不发起对外网络连接，且未反向修改冻结基线。

## 10. known-limitations-for-D（C 阶段已知边界，待 D 阶段处理）

- `TrustedContext` 的 `subject`/`correlation_id` 已由 **D-1** 收紧为精确字符白名单（`subject` 须匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`、`correlation_id` 须为服务端派生的 `^[0-9a-f]{64}$`，缺失/非法在配置启动失败关闭）；唯一身份来源已由 D-3 收口为受控身份根下部署预置的 identity.json；MCP_NOTES_SUBJECT 仅作文件安全读取后的可选相等性断言，永不产生或后备 subject。该信任边界由 **D-3** 设计收口，**D-3 实现已由本地提交 `d14341d` 落地（未 push、未建 PR；本次 Codex 复核中）**（见 `docs/D-3-design.md` **v3**、DECISIONS **D-027**；D-025(v1) 与 D-026(v2) 均已 superseded，属历史引用，勿按其实施）。
- 单进程、非并发、非多用户；`TasksStore` 连接为每 handler 重建，未做连接池或跨进程并发控制。
- 仅 Windows 原生 `NtCreateFile(FILE_CREATE, OBJ_DONT_REPARSE)` no-replace 发布路径经实机验证；跨平台一致性（非 Windows 的等价原子无覆盖发布）待 D 阶段补。
- 真实 Host 支持面（第三方 MCP Client 兼容性、传输扩展如 SSE/HTTP）未在 C 阶段评估。
- 公开部署、生产多用户身份、并发负载、真实模型质量不在本次范围。
- 固定评估目前以原创虚构夹具 + 11 例 C 阶段离线评估 + **23 项** stdio 集成测试 + **6 项**入口/配置测试 + 8 项演示断言覆盖；完整 40 例计划套件（`evals/cases` / `evals/results` 基线）仍未实施，可在 D 阶段补齐。（注：20 项 / 2 项为历史 C 阶段基线；当前基线为 196 项 / 23 集成 / 6 入口，见 ARCHITECTURE §7。）

## 11. D 阶段计划（规划中，待逐片实现与 Codex 复核）

D 阶段不扩大 C 阶段已冻结的安全合同与读写边界（§3 / §4），只在 §10 的 known-limitations 范围内做加固与补齐。原则：每片小步实现、独立测试、固定评估、交 Codex 复核；不新增运行时依赖；不把模型输出 / 笔记正文 / 客户端输入当作路径·命令·URL·写入授权。

### 11.1 依赖闸门
- 唯一直接生产依赖 `mcp==2.0.0` 及其 29 个传递依赖不变；D 阶段**不新增任何依赖**。
- 任何 transport 扩展（如 SSE / streamable-HTTP）必须复用 SDK 已含的 `starlette` / `uvicorn` / `httpx` 等传递依赖，不得新增；若确需新依赖，先走 Codex 依赖批准闸门（见 `docs/DEPENDENCIES.md`）。

### 11.2 切片与量化验收标准
| 切片 | 目标 | 量化验收标准 | 风险 / 前置 |
|---|---|---|---|
| **D-1 身份格式与安全字符白名单** | 给 `TrustedContext.subject` / `correlation_id` 实现精确身份格式校验（当前仅拦 C0·DEL 控制字符） | 定义并落地精确身份格式：① `subject` 精确格式 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`（首字符字母/数字，后续 0..127 个字母/数字/`.`/`_`/`-`，总长 1..128）；非法字符（空格、CJK、控制字符、注入字符等）或长度越界在**配置启动时**即稳定失败关闭；② `correlation_id` 必须符合服务端派生格式 `^[0-9a-f]{64}$`（由 `_derive_correlation_id` 经 `hashlib.sha256(...).hexdigest()` 产生，无前缀），客户端永远不能直接提供或覆盖（Tool 参数中不含该字段，Host 只从 `TasksStore.lookup_correlation_id(confirmation_id)` 取得）；③ Tool 参数 `title`/`description` 非法或构造 `TrustedContext` 失败时稳定返回 `invalid-arguments`，不泄露格式细节；④ 完全保留 C 阶段合同（服务端按 NFKC 规范化 title/description 确定性派生 correlation_id；Tool 外 Host 自身受控 subject 审批）。`tests/test_create_task.py` 与 `tests/test_mcp_integration.py` 新增回归覆盖：subject 非法字符拒收、超长 subject 拒收、配置启动缺失/非法 subject 失败关闭、correlation_id 无法从客户端注入；既有 B2a 金标准（ASCII 测试主体）与 C 阶段 11 例评估不受影响 | 低；改 `tasks.py` 校验 + `host.py` / `server.py` 派生点 |
| **D-2 跨平台原子发布一致性** | 非 Windows 的等价 no-replace 发布（fd 链式 `openat`+`O_NOFOLLOW`+`fstat`） | 新增 POSIX 分支：从**受控根目录 fd** 开始，每一级目录都用**已验证父 fd** 经 `openat(dir_fd=..., O_NOFOLLOW)` 打开，再 `fstat` 验证其确为目录且未 reparse/junction；最终文件也相对**已验证父 fd** 用 `open(O_CREAT\|O_EXCL\|O_NOFOLLOW)` 创建。禁止任何字符串路径回退，禁止把 `realpath` 用于安全判断（`realpath` 不能作为路径安全权威，`O_NOFOLLOW` 只覆盖单次打开组件）。平台缺少必要能力（如无法获取根 fd / 不支持 `O_NOFOLLOW` / `openat` 不可用）时稳定 `task-root-unsafe` 失败关闭。新增跨平台测试（Linux/macOS runner 或 WSL 实机），发布失败语义与 Windows 一致。**真实 symlink/junction 夹具须先获用户单独批准**；未批准时绝不创建、绝不运行。未来测试覆盖明确为四类：最终文件链接逃逸、祖先目录链接逃逸、检查后祖先替换（TOCTOU）、目标已存在冲突不覆盖 | 中；需 CI 矩阵 / 实机；不降级字符串路径方案。**（2026-08-07：Windows 可验证部分已实现——新增 `safe_task_write_posix.py` POSIX 分支 + Windows `reparse→task-root-unsafe` 收紧 + 31 项算法级/mock 单测（27 执行 + 4 链接占位 skip）；真实链接夹具 D2-L1…L4 仍为默认 skip 占位，blocked-until-approved；设计见 `docs/D-2-design.md` v5、决策见 DECISIONS D-021；2026-08-07 经 Codex 两轮 P0/P1 复核修复（D-022：5 P0 + 1 P1；D-023：3 P0 + 2 P1，已由本地提交 `905886a` 统一落地，未 push），单测总计 196（188 通过 + 8 skip），决策见 DECISIONS D-022 / D-023 / D-024）** |
| **D-3 唯一身份来源与信任边界** | 确定唯一身份来源、信任边界、缺失/不可用失败关闭（**设计 v3 已定，已由本地提交 d14341d 落地（未 push、未建 PR；本次 Codex 复核中）**） | **设计 v3**（见 `docs/D-3-design.md` v3、DECISIONS **D-027**；v1/D-025「需修改、3 个 P0」与 v2/D-026「需修改、2 个 P0 + 3 个 P1」均已被取代，勿按其实施）：**唯一值来源 = 受控身份根下部署预置的 `identity.json`，必须存在**；`MCP_NOTES_SUBJECT` **永不产生最终 subject、不作后备**，仅在文件安全读取成功后作可选相等性断言（不等即失败关闭），不变量为「删除该 env 后加载结果逐字节相同」。**安全读取算法**：`<name>` 单组件白名单校验 → fd/HANDLE 链打开身份根（Windows `OBJ_DONT_REPARSE` HANDLE 链 / POSIX `O_NOFOLLOW`+`fstat` fd 链，**只读复用 D-2 原语、零修改 `safe_task_write*.py`**）→ 相对已验证父句柄打开文件 → 对**已打开 fd** 做 `fstat` 类型断言（防检查后替换）→ 限长 4096 B 读取 → 严格 schema（`version==1` / `subject` D-1 白名单 / `subject_kind=="deployment-provisioned"` / 未知键拒绝）；**禁字符串路径读取与 `realpath` 安全判断；能力缺失即失败关闭**。**身份注入 = M1「每进程一次加载」（v3 修正，支持现有分离进程 stdio 演示）**：`load_runtime_identity()` 是无全局状态、可重入的纯加载函数，每个参与进程在自身 bootstrap 处调用一次 → 不可变 `RuntimeIdentity`（私有构造哨兵仅作受信代码内类型/API 防呆，非安全边界）→ 注入本进程 `ServerConfig` 或 `TrustedHostController`，**生产构造器不再接受裸 `str` subject**；单进程内嵌（tests/evals）是 M1 特例。**一致性论据不是「同一对象实例」**（v2 说法已废止，与 spawn 子进程的演示冲突），而是「同一受控身份文件 + 确定性加载算法 ⇒ 同 subject 值」的部署级保证；**跨进程「启动期一致性断言」明确不支持**（无通道、零网络不引入 IPC、两次读取间文件可变），两进程被指向不同文件或文件变动时，唯一保护是请求期 `confirmation-identity-mismatch`。信任边界：subject 从不作为 Tool 参数 / 模型文本 / MCP 消息字段，Host 用自身 `RuntimeIdentity` 重建 `TrustedContext`、记录不提供权威 subject。全部身份失败复用 `invalid-arguments`（**不新增 `identity-unavailable`**），前提收敛为当前可验收的两类入口——`server.main()`（已实现稳定码退出，`server.py:376-378`）与受控启动器（demo/evals/测试夹具）只输出稳定码（DoD 第 4 条 + 测试 27/28；`host.py` 是库类、本轮不新增 `main()`，另有前瞻性条款约束未来 Host 入口）。部署前提：受控身份根客户端不可写、`MCP_NOTES_IDENTITY_FILE` 只来自受控启动器；**客户端可控整个进程环境的部署不在 D-3 信任模型内**。改动面：新增 `identity.py` + `tests/test_identity.py`；仅改 `server.py`/`host.py` 与 `TrustedHostController(`/`ServerConfig(` 调用点（v3 按适配类型细分：主身份 6 / 第二受控身份根 2[`demo/mcp_stdio_demo.py:145`+`evals:208`] / 非 `RuntimeIdentity` 拒绝 1[`tests/test_mcp_integration.py:439`] / `ServerConfig(` 2；demo/evals 新增受控身份根夹具准备代码）；`contracts.py`/`tasks.py`/`safe_task_write*`/sqlite 状态机零修改。多用户 / OS 凭证绑定 / PKI / 跨进程身份一致性（IPC/共享凭据/启动握手）/ 真实链接身份根夹具 / 为 host.py 新增 CLI / 公网部署 列为需用户单独批准（blocked-until-approved；详见 `docs/D-3-design.md` §9）。**当前设计已完成、已实现（仅 Windows 可验证核心）、未提交/未 push、待 Codex 复核；不破坏 D-1/D-2 合同与 196 测试基线** | 中；涉及配置与部署文档 |
| **D-4 并发 / 多用户隔离** | 跨进程并发与多用户隔离（事务条件更新，非连接池/WAL） | DoD 必须要求：① 确认消费使用**事务中的条件更新**，只允许 `PENDING` → 终态一次（SQL `UPDATE ... WHERE status='PENDING'` 影响行数判定）；② 跨进程并发批准同一 confirmation 时，**只允许一个发布**（其余返回 `confirmation-already-consumed` 且绝不写第二个文件）；③ 其他调用返回稳定已消费结果且绝不写第二个文件；④ 多用户之间确认记录、任务文件、审计事件均隔离（按 subject 分隔，不串号）。**不得把“连接池 / WAL”描述为并发安全方案**（它们只是 IO 吞吐，不提供原子消费）。并发竞态测试（多进程同时消费同一 confirmation → 仅一个成功发布）为 DoD 必过项 | 高；需仔细设计事务/锁 |
| **D-5 真实 Host 支持面 / 传输扩展** | 第三方 MCP Client 兼容与可选 SSE/HTTP | 传输扩展**默认关闭**，仅允许**本地回环绑定**（`127.0.0.1`/`::1`），**绝不允许公网监听**；复用 SDK 已含 `starlette`/`uvicorn` 提供 SSE/streamable-HTTP 入口（不新增依赖）；`list_tools` / 协议兼容性冒烟；`approve`/`reject`/`cancel` **仍绝不暴露为 Tool**，`correlation_id` 仍只来自服务端持久化记录。公网监听视为安全违规，必须在配置与测试中显式禁止并断言 | 中；复用 SDK 已含依赖 |
| **D-6 补齐评估基线** | 固定离线评估扩展到 40 例 | **总数 40 例，包含既有 11 例 C 阶段基线**（即新增 29 例）；保留 `evals/gold/c-phase-v1.json` 与 `evals/run_c_phase_eval.py` 的 11 例既有结果，**不改写既有结果**；新增 `evals/cases/`、`evals/results/` 基线，脚本支持加载全部 40 例；通过率 / 安全拒绝率 / 未授权写入数 / 幂等正确率均达 §8 目标 | 低；纯评估扩展，不碰安全逻辑 |
| 公开部署 | 生产多用户身份、并发负载、真实模型质量 | **不在 D 阶段默认范围**：当前安全模型依赖本地可信边界、不对外暴露写权限；若要做需独立风险评估与 Codex 批准 | 高；推迟 |

### 11.3 推荐起点
建议从 **D-1 身份格式与安全字符白名单** 起步：最内聚、最贴近已通过 Codex 复核的安全核心、低风险、易补测试，且立刻消除 §10 中“未实现安全字符白名单”的明确缺口。随后按 D-2 → D-3 → D-4 → D-5 → D-6 推进；D-4 / D-5 视需要再排期。

### 11.4 每片完成定义
- 新环境按 README 启动；核心测试通过（总 196 + 本片新增；注：149 为历史 C 阶段基线，D-1 后升 164、D-2 后升 196）。
- 本片固定评估有基线与结果；失败路径已验证。
- 架构 / 取舍能被解释；不引入密钥 / 私密数据 / 大模型文件进 Git。
- 每片独立提交并交 Codex 复核；**不 push**，直到 P3 全部阶段完成（用户决定统一处理）。

### 11.5 统一验证闸门（每片必保留并复跑当前统一基线）
每实现一个 D 切片，除本片新增测试外，**必须保留并复跑当前统一基线（196 项 / 23 项集成 / 6 项入口）**，全部通过方可提交（149/20/2 仅为历史 C 阶段基线注释，见各下行）：
- `unittest` 当前 **196 项**全绿（188 执行通过 + 8 链接测试默认跳过；后续仅按新增测试增长，不破坏既有；注：149 为历史 C 阶段基线，D-1 后升 164、D-2 后升 196）；
- **23 项** stdio 集成测试（`tests/test_mcp_integration.py`；注：20 项为历史 C 阶段基线，D-1 后升至 23）；
- **6 项** 入口 / 配置测试（`tests/test_server_entry.py`；注：2 项为历史 C 阶段基线，D-1 后升至 6）；
- C 阶段评估 **11/11**（`evals/run_c_phase_eval.py`）；
- stdio 演示 **8/8**（`demo/mcp_stdio_demo.py`）；
- `python -m pip check` → 无 broken requirements、无 `Ignoring invalid distribution` 警告；
- `git diff --check` 通过。
任何切片不得降低上述基线计数或放宽 `pip check` / 空白检查。
