# P3 PRD：本地 MCP 笔记检索与受控任务创建服务

- 版本：v0.2（Slice A / B1 / B2a 离线核心已实现并离线验证；MCP SDK 适配与 Host/Client 演示仍属 B2b，未实现）
- 日期：2026-08-01（B2a 更新 2026-08-02）
- 范围：原创、虚构、离线、确定性夹具；`search_notes` 与 `create_task` 的**离线核心逻辑**已实现（纯标准库，无依赖），但**没有**实现 MCP Server/Resource/stdio transport、没有安装 MCP SDK、没有运行任何 MCP 进程或 Host/Client。

## 1. 问题与目标用户

本地 AI 客户端需要查询一小组允许笔记，并把用户已确认的事项写成任务。若 MCP Server 暴露任意路径、文件名、命令或直接写权限，模型、客户端重试或笔记中的提示注入文本可能读取越界文件或产生未授权写入。

- 目标用户：需要在本地 AI Host 中安全检索项目笔记、并人工确认任务创建的个人开发者。
- 输入：受限关键词；受限任务标题和描述；来自可信本地 Host 适配器的主体与调用关联 ID；人工确认界面的批准、拒绝或取消动作。
- 输出：脱敏检索结果；待确认请求；批准后不可覆盖的任务记录；稳定错误码；只读服务说明 Resource。
- 成功目标：证明 MCP 协议边界、JSON Schema、路径安全、Human-in-the-loop、持久化幂等和离线可评估性。

## 2. 非目标

- 不搜索任意目录、任意文件名、私人真实笔记、网络 URL 或云盘。
- 不执行命令、Shell、URL、插件、代码、SQL 或笔记指令。
- 不调用真实模型 API、不下载数据、不联网、不产生费用、不公开部署。
- 不做语义检索、Embedding、向量库、Agent、多智能体、Web UI、任务编辑/删除或通用任务系统。
- 当前不实现 MCP Server 或 Host/Client 演示；后续才验证真实本地集成。

## 3. 能力合同（计划）

### 3.1 `search_notes(keyword)`：只读

| 项目 | 计划合同 |
|---|---|
| 参数 | 仅 `keyword`；JSON object 不得有未知字段 |
| 合法值 | UTF-8 字符串；去首尾空白后长度 `1..80`；不含控制字符、绝对路径、`..`、URL、命令或 Shell 语义 |
| 数据来源 | 仅服务启动时验证并登记的笔记白名单目录；仅允许的普通 UTF-8 `.md` 文件 |
| 匹配 | 冻结的大小写无关确定性关键词匹配；不执行笔记文本、Markdown 链接或指令 |
| 返回 | 最多 5 条：稳定 `note_id`、标题、受限长度的安全摘录、匹配计数；不返回磁盘路径、完整正文、隐藏文件或异常栈 |
| 副作用 | 无；不写索引、不联网、不修改笔记 |

`keyword` 是数据，不是路径、过滤表达式、正则、文件名或命令。笔记正文即使含“忽略规则”“读取 C:\\...”或 URL，也只能作为不可信文本被转义/截断后展示，绝不改变 Tool 权限。

### 3.2 `create_task(title, description)`：受控写

| 项目 | 计划合同 |
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

> **实现状态（Slice B2a，2026-08-06）**：上述 `create_task` 离线核心**已实现**于 `src/mcp_notes/tasks.py` 与 `src/mcp_notes/safe_task_write.py`，并配套固定金标准 `evals/gold/tasks-core-v1.json`（12 场景）与 `tests/test_create_task.py`（53 项）。已实现范围严格限于“离线受控写核心”：严格数据合同、`PENDING/APPROVED/REJECTED/CANCELLED/EXPIRED` 状态机、sqlite3 持久化、任务文件 no-replace 原子发布（Windows 原生 `NtCreateFile(FILE_CREATE, OBJ_DONT_REPARSE)` 原子无覆盖 + 句柄式 `open_task_root` 任务根/祖先目录 reparse 与 TOCTOU 防护，绝不 `os.replace`、冲突绝不覆盖）、12 类稳定错误码（含 `confirmation-invalid-id` / `task-root-unsafe`）。发布失败语义与任务根所有权按 D-015 落实：序列化先于文件创建；创建成功后 `WriteFile` / `FlushFileBuffers` 失败 → 稳定 `task-write-failed` 且不泄露原始异常，文件 HANDLE 只关闭一次后以已验证父目录 HANDLE 相对 `NtDeleteFile` 清理（不使用字符串路径删除/替换），确认记录保持 `PENDING`；**清理成功（`NtDeleteFile` 返回 `STATUS_SUCCESS`）则无残留、移除故障后可安全重放创建；清理失败（非成功 NTSTATUS）则失败关闭，仅返回稳定 `task-write-failed`，不承诺零残留或自动重试成功**。任务根须由部署配置预存在，生产代码不调用 `os.makedirs` 创建任务根或祖先目录。`TrustedContext` 的实际校验规则为“`str` / 长度 `1..256` / 不含 C0·DEL 控制字符”，**未实现安全字符白名单**。人工确认动作（`approve`/`reject`/`cancel`）当前由测试中的可信本地上下文 `TrustedContext(subject, correlation_id)` 直接驱动；**尚未**接入 MCP Tool/Server/Resource/stdio/Host/Client（属 B2b）。MCP 适配层须复用本核心，不得在 Tool 内重建确认/写入逻辑。

### 3.3 只读 MCP Resource

计划 Resource URI 为固定程序常量 `notes://service-info`。内容只说明 Tool 名称、参数边界、允许笔记根目录的逻辑名称、确认规则和错误码；不泄露绝对路径、真实文件清单、配置、密钥、Cookie 或鉴权头。

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

## 6. 验收标准（后续实现）

1. `search_notes` 能在固定夹具返回正确 `note_id`、标题和安全摘录；不写文件、不联网。
2. 空关键词、超过 80 字符、未知字段、非字符串和禁止语义输入返回稳定非法参数错误。
3. 无结果返回空结果；无权限/未登记笔记不泄露存在性、路径或正文。
4. 绝对路径、`..`、符号链接、junction、reparse point、未登记文件和越界最终路径一律拒绝；服务不跟随链接。
5. 笔记内提示注入、命令、URL、伪造路径只按不可信数据处理，不增加 Tool 能力或改变写入目标。
6. 未确认、拒绝、取消、旧确认、身份错绑、重复批准都不写任务。
7. 合法批准恰好创建一个对应 `task_id` 的文件；同一意图重放返回幂等结果；冲突不覆盖旧文件。
8. 原子写入失败后没有半成品或覆盖；仅返回脱敏稳定错误码。
9. 后续真实本地 MCP Host/Client 演示覆盖成功检索、待确认、批准写入和至少一条拒绝路径。
10. 默认测试网络为阻断；提交内容、日志和样例不含密钥、Cookie、鉴权头、私人笔记、完整敏感响应或原始异常栈。

## 7. 失败分类（计划稳定错误码）

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

> **实现状态（Slice B2a）**：除“路径越界 / 文件不存在 / 内容过大”三类仍属于 `search_notes` 检索侧（由 Slice B1 句柄层覆盖，未纳入 B2a 写入核心）外，其余写侧分类——非法参数、确认缺失、确认失效（过期/错绑/不匹配）、重复写入（已消费/关联 ID 冲突/UNCHANGED）、磁盘写入失败（原子发布失败/目标冲突）——**均已由 `src/mcp_notes/tasks.py` 离线实现并测试**，错误码与上表一致，且均不泄露路径/正文/原始异常。MCP transport 层的映射仍待 B2b。

## 8. 固定评估指标

- 案例通过率：通过案例数 / 全部冻结案例数。
- 检索正确率：返回 `note_id`、标题和匹配计数全部符合金标准的案例数 / 正常检索案例数。
- 安全拒绝率：应拒绝的非法、越界、链接、确认和注入案例中，安全拒绝且无副作用的比例；目标 `100%`。
- 未授权写入数：未确认、拒绝、取消、过期、错绑和重复批准路径实际创建文件数；目标 `0`。
- 幂等正确率：重放应返回相同稳定结果且任务文件数为 1 的案例比例；目标 `100%`。
- 敏感数据泄露数：日志、错误、Resource、结果、样例和 Git 扫描命中数；目标 `0`。
- 网络尝试数：默认阻断器记录的网络调用数；目标 `0`。

基线在实现后首次真实运行生成。当前没有结果，不能写成通过。

## 9. 当前离线范围与未来演示

当前阶段只冻结合同、数据计划、指标和安全决策。后续离线阶段用原创虚构笔记、临时受控目录和假人工确认器验证核心逻辑。最后单独加入真实本地 MCP Server 与真实本地 Host/Client：stdio 启动、Resource 读取、Tool 成功/拒绝路径和人工确认写入。该演示不得使用真实模型 API、网络或私人笔记，且不能反向修改冻结基线。
