# P2 架构设计：LangGraph 技术选型研究工作流

- 版本：v0.6
- 状态：accepted design baseline
- 日期：2026-07-29
- 实现状态：最小状态、需求确认、受控假工具执行、两轮证据评估、安全草稿和有限审校切片已实现；最终报告确认和导出尚未实现

## 1. 架构目标

使用单个 LangGraph 工作流完成需求确认、研究规划、证据检索、报告写作、审校、人工确认和安全导出。重点不是“让模型自由行动”，而是把状态、权限、循环和停止条件交给程序控制。

P2 不复制 P1 代码，不导入 P1 内部模块，不复用 P1 `.venv`。只复用已验证的设计原则：来源固定、引用由程序绑定、普通测试离线、失败显式暴露。未来若复用 P1 检索能力，必须通过独立只读接口和版本化数据合同，不直接耦合实现。

## 2. 系统边界

```text
用户输入
  │
  ▼
输入校验 ── 人工确认需求
  │
  ▼
LangGraph 编排器
  ├─ 规划与写作模型适配器
  ├─ 受控 Tool Calling 执行器
  ├─ 证据与引用绑定服务
  ├─ 审校与路由规则
  ├─ Checkpoint 持久化
  └─ 人工批准后的幂等导出器

外部边界：
- 模型、数据快照和依赖尚未批准
- 首版无开放式联网搜索
- 首版无任意写工具
```

## 3. 显式状态图

```mermaid
flowchart TD
    A["START"] --> B["validate_request"]
    B -->|完整| C["confirm_requirements"]
    B -->|缺字段| D["propose_clarification"]
    D --> C
    C -->|人工批准| E["plan_research"]
    C -->|人工修改| B
    C -->|人工取消| X["CANCELLED"]
    E --> F["execute_tools"]
    F -->|工具成功| G["assess_evidence"]
    F -->|可重试瞬时错误| F
    F -->|不可重试或耗尽| Y["FAILED"]
    G -->|证据充足| H["draft_report"]
    G -->|可补检索且未达上限| E
    G -->|证据不足且达上限| Y
    H --> J["review_report"]
    J -->|通过| K["confirm_report"]
    J -->|需修改且未达上限| H
    J -->|严重安全问题| Y
    J -->|修改耗尽| K
    K -->|人工批准| L["export_report"]
    K -->|人工退回且未达上限| H
    K -->|人工拒绝| X
    K -->|退回耗尽| Y
    L -->|成功或相同制品已存在| Z["COMPLETED"]
    L -->|冲突或写入失败| Y
```

`confirm_requirements` 和 `confirm_report` 使用 LangGraph 中断语义。进入节点前保存 checkpoint；恢复时必须提供同一 `run_id`、状态版本和合法人工动作。

### 3.1 当前已实现切片

```mermaid
flowchart TD
    A["START"] --> B["validate_request"]
    B --> C["confirm_requirements"]
    C --> D["await_human_requirements: interrupt"]
    D -->|approve| E["plan_research: deterministic placeholder"]
    D -->|edit| B
    D -->|reject| F["REJECTED"]
    D -->|cancel| G["CANCELLED"]
    E --> H["END"]
    F --> H
    G --> H
```

- 完整需求、缺候选和缺评价维度都进入持久化 `NEEDS_HUMAN`，不自动补猜。
- `confirm_requirements` 在中断节点前写入等待状态、revision 和请求哈希。
- `await_human_requirements` 只接受严格、revision 绑定的 `approve`、`edit`、`reject`、`cancel`。
- `approve` 只到 `PLANNED`；当前没有检索、模型、报告或导出副作用。

### 3.2 当前工具执行切片

```mermaid
flowchart TD
    A["人工批准需求"] --> B["plan_research"]
    B --> C["execute_tools"]
    C -->|success| D["EVIDENCE_READY"]
    C -->|transient error and budget remains| E["retry_tool"]
    E --> C
    C -->|deterministic error| F["FAILED"]
    C -->|third transient error| F
```

- 工具图是独立构建入口；上一阶段需求图仍保持批准后停在 `PLANNED`。
- `plan_research` 只持久化一个已验证、确定性的 `ToolCall`。
- `execute_tools` 先做业务作用域校验，再调用内存假执行器。
- 当前成功只表示证据 ID 已安全进入状态，不表示报告完成。

### 3.3 当前证据评估切片

```mermaid
flowchart TD
    A["plan_research: frozen call for current round"] --> B["execute_tools"]
    B -->|success| C["assess_evidence"]
    B -->|retryable| D["retry_tool"]
    D --> B
    B -->|deterministic error or budget exhausted| F["FAILED"]
    C -->|all frozen requirements satisfied| E["EVIDENCE_SUFFICIENT"]
    C -->|round 1 has gaps| A
    C -->|round 2 has gaps| F
```

- `evidence-policy-v1` 固定要求和可接受 evidence ID 组合；评估是本地集合判断，不调用模型。
- 第一轮有缺口只允许补检索一次；`retrieval_rounds` 最大为 2。
- 可接受组合为空表示固定快照中没有明确证明；评估器不能使用相近资料或常识补猜。
- 第二轮仍不足写入安全错误 `evidence-insufficient`，稳定停在 `FAILED`，不生成报告或制品。
- `graph_version` 在该路径固定为 `evidence-assessment-v1`；旧工具切片保持 `tool-execution-v1`。

### 3.4 当前安全草稿切片

```mermaid
flowchart TD
    A["assess_evidence"] -->|EVIDENCE_SUFFICIENT| B["draft_report"]
    A -->|FAILED| F["END"]
    B -->|valid proposal| C["DRAFTED"]
    B -->|invalid claim, evidence, candidate, or dimension| F
    C --> D["END"]
```

- `draft-proposal-v1` 只含结构化摘要、声明、推荐、限制和 evidence ID。
- `EvidenceCitationBinder` 验证固定声明、人工确认范围和本次 evidence ID，再从已验证来源目录绑定来源标题、版本、章节和 SHA-256。
- `report-draft-v1` 是 checkpoint 业务状态，不是人工批准的最终报告，也不是已导出制品。
- 非法草稿提案记录 `invalid-draft-proposal` 后稳定失败；证据不足路径不会调用写作者。
- 当前写作者和金标准匹配器都是确定性运行时夹具，不访问模型或网络，不进入 checkpoint。
- 新路径使用 `draft-report-v1` 图版本；当前终态为 `DRAFTED`，尚未进入审校和最终人工暂停。

### 3.5 当前有限审校切片

```mermaid
flowchart TD
    A["draft_report"] --> B["review_report"]
    B -->|PASS| C["REVIEWED"]
    B -->|REVISE and review_rounds < 2| D["revise_report"]
    D -->|valid new revision| B
    D -->|invalid revision| F["FAILED"]
    B -->|findings remain after round 2| F
    C --> E["END"]
    F --> E
```

- `review-policy-v1` 固定候选覆盖、维度覆盖和禁止断言检查。
- `review-result-v1` 绑定 `review_policy_id`、来源快照、报告 revision/hash 和当前修改轮次。
- `review_rounds` 只在新草稿成功绑定后增加；初始检查不占修改预算。
- 无发现项停在 `REVIEWED`；最多修改 2 次，仍不通过则记录 `review-limit-exhausted` 并失败。
- reviewer、reviser 和 binder 是运行时依赖；checkpoint 只保存规范草稿、策略 ID、轮次、发现项和安全结果。
- 当前不调用模型，不进入最终报告 Human-in-the-loop，不生成制品。

## 4. 状态模型

状态使用严格结构化模型。未知字段拒绝；节点只返回自己负责的字段更新。

| 字段组 | 关键字段 | 说明 |
|---|---|---|
| 身份 | `run_id`、`thread_id`、`state_schema_version`、`graph_version` | 一次研究任务和可恢复状态身份 |
| 需求 | `research_question`、`audience`、`constraints`、`candidates`、`evaluation_dimensions`、`deliverable_requirements` | 已校验的用户需求 |
| 人工动作 | `pending_approval`、`approval_revision`、`human_decisions` | 只保存结构化决定、时间和安全摘要 |
| 规划 | `research_questions`、`search_plan`、`source_policy`、`plan_revision` | 已确认范围内的研究计划 |
| 工具 | `tool_requests`、`tool_results`、`tool_attempts`、`tool_call_budget` | 只保存校验后的参数和标准化结果 |
| 证据 | `evidence_items`、`evidence_gaps`、`source_snapshot_id` | 证据按来源、章节和内容哈希去重 |
| 报告 | `draft_revision`、`draft_sections`、`claims`、`citations`、`review_findings` | 草稿、声明和程序绑定引用 |
| 循环计数 | `retrieval_round`、`review_round`、`human_revision_round`、`structured_output_retry` | 所有循环的硬上限依据 |
| 运行状态 | `status`、`current_node`、`last_error`、`started_at`、`updated_at` | 可观察运行状态 |
| 观测 | `node_metrics`、`model_usage`、`tool_usage` | 延迟、调用次数、token 和已知费用 |
| 制品 | `approved_content_hash`、`artifact_id`、`export_status` | 只在最终批准后生成 |

不得保存：

- API Key、Cookie、鉴权头或连接字符串。
- 未脱敏异常堆栈。
- 完整敏感供应商请求和响应。
- 模型生成的任意本地路径、命令或可执行内容。
- 未进入允许资料快照的私有原文。

### 4.1 当前 `runtime-state-v1`

当前实现把数据分成四类：

1. 可持久化业务状态：
   - 身份和版本：`schema_version`、`graph_version`、`run_id`、`thread_id`。
   - 路由：`status`、`current_node`、缺失需求字段。
   - 需求：`raw_request`、`confirmed_requirements`、人工确认 revision 和请求哈希。
   - 工具：`source_snapshot_id`、`pending_tool_call`、`last_tool_result`、`tool_call_budget`。
   - 有限循环：`tool_attempts`、`retrieval_rounds`、`review_rounds`、`human_revision_count`。
   - 证据评估：`evidence_ids`、`evidence_policy_id`、`evidence_gaps`、`last_evidence_assessment`。
   - 草稿与审校：`report_draft`、报告 revision/hash、`review_policy_id`、`last_review_result`、`review_rounds`；引用只保存已验证来源元数据。
   - 后续占位：安全 `errors`、`artifact_id`、`idempotency_key`。
2. 运行时依赖：
   - 编译后的 LangGraph、SQLite 连接/checkpointer、模型客户端、工具执行器和密钥提供器。
   - 这些对象由运行环境创建或注入，不是业务状态。
3. 密钥和敏感响应：
   - API Key、Cookie、鉴权头、连接字符串、完整供应商请求/响应和未脱敏堆栈一律禁止进入 checkpoint。
4. 不可序列化或不应持久化对象：
   - 打开的文件、socket、数据库连接、线程锁、回调、模型 SDK 响应对象和任意可执行对象。

所有初始输入先经严格 Pydantic 合同校验，再提交给图。节点接收统一 `RuntimeState`，只返回自己负责的字段增量；SQLite checkpoint 中只出现基础类型、列表和映射。计数都有硬上限，未知字段和非法字段组合被拒绝。

## 5. 节点职责

### `validate_request`

- 对长度、数量、枚举、候选重复、权重和来源策略做确定性校验。
- 区分“输入非法”和“信息不足”。非法输入失败；信息不足进入澄清提案。
- 不调用模型，不访问网络。

### `propose_clarification`

- 只提出最少必要问题或候选默认值。
- 结构化输出失败最多再生成 1 次；仍失败则停止。
- 不把模型提案视为用户批准。

### `confirm_requirements`

- 暂停并展示规范化需求、候选、维度、权重、来源范围和预计调用上限。
- 只接受 `approve`、`edit`、`cancel` 三类结构化动作。
- `edit` 后重新走输入校验。

### `plan_research`

- 把已批准需求拆成研究问题和有限检索计划。
- 每个检索项必须绑定候选、评价维度和预期证据类型。
- 不能新增未批准候选、来源域或写操作。

### `execute_tools`

- 执行模型提出、程序校验后的 allowlist 工具调用。
- 控制单轮和全局调用预算；标准化、去重并记录结果。
- 工具参数错误返回稳定错误，不把原始异常交给模型。

### `assess_evidence`

- 当前使用冻结规则检查每项要求是否有一个完整的可接受 evidence ID 组合。
- 默认最多 2 个检索轮次，含第一次检索。
- 达上限仍不足时进入稳定 `FAILED`，明确不能下强结论；不能伪装成成功检索。
- 当前不调用模型，不做语义推断或矛盾消解；这些能力必须另建版本化合同和评估。

### `draft_report`

- 只基于状态中的已验证证据写作。
- 写作者只引用 `evidence_id`；程序绑定来源 ID、标题、版本、章节和来源 SHA-256。
- 只有 `EVIDENCE_SUFFICIENT` 才能进入后续写作；证据不足路径不得生成草稿。
- 当前确定性夹具要求声明精确匹配固定金标准；这证明引用和范围边界，不替代未来语义审校。
- 当前成功只到 `DRAFTED`，不允许导出。

### `review_report`

审校包含两层：

1. 当前已实现：确定性检查引用集合、策略要求的候选/维度覆盖和禁止断言。
2. 尚未实现：模型审校比较公平性、证据与表述强度、矛盾、遗漏和可读性。

默认最多 2 次自动修改。初始审校不计修改次数；修改上限后仍有发现项则稳定失败。当前通过只到 `REVIEWED`。

### `confirm_report`

- 暂停并显示报告、证据缺口、审校警告、调用次数和已知费用。
- 只接受 `approve`、`request_changes`、`reject`。
- 人工退回最多 2 次。批准动作绑定具体 `draft_revision` 和内容哈希，旧批准不能授权新内容。

### `export_report`

- 不是模型可调用工具。
- 只接受状态中已批准的 revision 和内容哈希。
- 程序从 `artifact_id` 派生 allowlist 根目录下的安全路径。
- 临时文件完整写入并校验后原子替换；不执行报告内命令或链接。

## 6. Tool Calling

首版只允许三个只读或纯计算工具：

### `search_sources`

```text
输入：query、candidate_ids、source_types、top_k
输出：按固定快照检索的 EvidenceSummary 列表
```

边界：

- `query` 非空且最长 300 字符。
- `candidate_ids` 必须属于已批准候选。
- `source_types` 必须属于来源策略 allowlist。
- `top_k` 为 1～8。
- 不接收 URL、路径、命令或任意过滤表达式。

### `read_source`

```text
输入：source_id、section_id
输出：固定快照中的已验证章节、来源元数据和内容哈希
```

边界：

- 两个 ID 都必须来自已加载的来源目录。
- 不接收本地路径或 URL。
- 返回长度受限；完整来源响应不写入 checkpoint。

### `calculate_comparison`

```text
输入：候选、已批准维度权重、证据支持的标准化分值
输出：逐项加权结果、缺失值和计算过程
```

边界：

- 权重必须与人工批准版本一致，总和为 1。
- 分值范围固定；无证据时必须是缺失值，不能由工具补猜。
- 纯确定性计算，无网络和写操作。

Tool Calling 执行流程：

```text
模型提出调用
→ 工具名 allowlist
→ Schema 校验
→ 业务范围和权限校验
→ 调用预算检查
→ 幂等键/缓存检查
→ 执行
→ 标准化结果
→ 写入状态
```

### 6.1 当前实现合同

- `tool-call-v1`：稳定 `call_id`、allowlist `tool_name`、带 discriminator 的版本化参数。
- `search-sources-args-v1`：query 最长 300 字符，候选 1～4 个，来源类型 1～4 个，`top_k` 为 1～8。
- `read-source-args-v1`：只接受规范 `source_id` 与 `section_id`，不接受 URL 或文件路径。
- `calculate-comparison-args-v1`：权重总和 100；每个候选必须覆盖同一维度集合；无证据分值保持缺失。
- `tool-result-v1`：只保存 outcome、attempt、稳定错误码、安全摘要和 evidence ID；不保存完整工具响应。
- 逻辑调用键绑定规范调用与来源快照。重试不会更换 call key、候选、来源范围或参数。

当前 `DeterministicFakeToolExecutor` 是运行时依赖：

- 输入为已验证来源、固定脚本和持久化 attempt。
- Schema 合法后仍检查本次人工确认候选、来源章节、维度权重和返回证据作用域。
- 未知来源、越权候选或越界证据返回稳定确定性错误。
- 不访问网络、不读取任意路径、不产生写操作、不进入 checkpoint。

## 7. 路由条件和停止条件

| 条件 | 路由 | 上限或终态 |
|---|---|---|
| 需求缺字段 | `propose_clarification` | 等待人工，不自动猜测批准 |
| 人工修改需求 | `validate_request` | 每次生成新 approval revision |
| 瞬时工具错误 | 重试当前工具 | 初次加 2 次重试，共 3 次尝试 |
| 参数、权限、404 或内容哈希错误 | 失败或重新规划 | 不自动重试相同调用 |
| 第一轮证据不足 | `plan_research` | 只允许第 2 个检索轮次 |
| 第二轮证据不足 | `FAILED` | 稳定终态，不生成报告或制品 |
| 草稿声明、推荐、候选、维度或 evidence ID 越界 | `FAILED` | `invalid-draft-proposal`，不生成草稿 |
| 审校发现且修改预算剩余 | `revise_report` | 最多成功生成 2 个新 revision |
| 第 2 次修改后仍有审校发现 | `FAILED` | `review-limit-exhausted` |
| 审校需修改 | `draft_report` | 最多 2 轮自动修改 |
| 人工退回 | `draft_report` | 最多 2 次 |
| 结构化模型输出非法 | 重生成当前输出 | 最多 1 次 |
| 人工取消或拒绝 | `CANCELLED` | 终态 |
| 安全违规、冲突写入、重试耗尽 | `FAILED` | 终态 |
| 已批准制品导出成功 | `COMPLETED` | 终态 |

等待人工的 `NEEDS_HUMAN` 是持久化暂停状态，不是成功。调用预算先于各节点循环上限；任一预算耗尽即停止，不能靠换节点绕过。

## 8. 重试策略

- 只重试超时、连接中断、HTTP 429 和明确的 5xx 瞬时错误。
- 指数退避参数在实现阶段固定；普通测试用虚拟时钟，不真实等待。
- 同一工具重试使用相同规范参数和相同逻辑调用 ID。
- 401、403、404、Schema 错误、allowlist 拒绝、内容哈希冲突和预算不足不重试。
- 模型重试不得静默增加候选、资料范围或输出权限。
- 每次失败写稳定错误码、安全摘要、节点和尝试次数；不保存密钥或完整供应商响应。

当前工具图已实现前三条停止分类和 3 次硬上限。证据图另有 2 个检索轮次硬上限。普通测试不真实 sleep；attempt 直接选择固定脚本结果。

## 9. Human-in-the-loop

### 需求确认暂停

人工看到：

- 决策问题、候选、约束、评价维度和权重。
- 允许来源和禁止来源。
- 预计工具与模型调用上限。

人工可批准、修改或取消。批准记录绑定需求哈希。

### 最终报告暂停

人工看到：

- 完整草稿和引用。
- 证据缺口、冲突和审校警告。
- 运行耗时、调用次数、重试次数、token 和已知费用。

只有对当前内容哈希的 `approve` 能进入导出。恢复请求若 `run_id`、checkpoint 版本或批准哈希不匹配，安全失败。

## 10. 状态持久化

首版计划使用 P2 本地 SQLite checkpoint；具体 LangGraph checkpointer 包和精确版本在依赖提案阶段确认，不在本阶段安装。

规则：

- 每个节点成功后保存 checkpoint；人工暂停前强制保存。
- 使用稳定 `thread_id/run_id` 恢复，不用自然语言标题定位。
- checkpoint 带状态 Schema、图、Prompt 和来源快照版本。
- 版本不兼容时拒绝自动恢复；后续如需迁移，使用显式迁移脚本和测试。
- 并发恢复使用状态版本检查，旧客户端不能覆盖新状态。
- 持久化前脱敏；供应商原始响应只在内存解析，状态保存验证后字段和 usage。
- 测试可使用临时 SQLite 或内存替身；不得写入 P1 数据目录。

## 11. 幂等性

### 只读工具

- 规范参数加 `source_snapshot_id` 生成逻辑调用键。
- 相同调用优先返回已验证缓存。
- 证据以 `source_id + section_id + content_hash` 去重，节点重放不能重复追加。

### 节点重放

- 节点输出按 revision 替换，不盲目 append。
- checkpoint 恢复时，已完成且输出哈希匹配的确定性节点不重复执行。
- 模型节点重放是否允许由调用记录和预算共同决定；不把失败调用伪装成成功。

### 最终导出

```text
artifact_id = hash(run_id + approved_revision + approved_content_hash + format)
```

- 输出文件名由程序生成。
- 同一 `artifact_id` 已存在且内容哈希相同：返回 `UNCHANGED`。
- 同一 `artifact_id` 已存在但内容不同：返回冲突并失败，不覆盖。
- 写入过程使用同目录临时文件和原子替换。
- 未批准、批准已过期或哈希不匹配：拒绝写入。

## 12. 安全边界

- 工具 allowlist；无 shell、SQL、任意 HTTP、任意文件和部署工具。
- 模型不能决定 URL、路径、命令、工具实现、权限或最终写入。
- 来源目录保存可信 URL 和许可；模型只选择目录中的 ID。
- 所有路径先做相对路径语法校验，再解析并确认仍在允许根目录；拒绝符号链接和 junction 逃逸。
- 外部内容视为不可信数据。来源中的提示词不能改变系统规则、工具权限或输出边界。
- 最终报告中的命令和链接只作为文本，不自动执行或访问。
- API Key 只从环境变量读取并使用 Secret 类型；日志和 checkpoint 脱敏。
- 任何费用、真实下载、公开部署或高风险写操作继续需要单独批准。

## 13. 可观测性

每个节点记录：

- 节点名、开始和结束时间、结果状态。
- 模型与工具调用次数。
- 输入和输出 token；供应商提供时记录已知费用。
- 重试次数、稳定错误码和路由原因。
- checkpoint revision、来源快照和报告 revision。

不记录完整 Prompt、完整供应商响应或秘密。测试断言指标字段完整，但不依赖真实时钟。

## 14. 测试与评估设计

### 单元测试

- 状态 Schema、未知字段、版本和归并语义。
- 每条路由条件和所有循环上限。
- Tool Calling Schema、allowlist、预算和错误分类。
- 提示注入不能扩大工具权限。
- checkpoint 写入、恢复、版本冲突和脱敏。
- 人工批准绑定 revision 与内容哈希。
- 导出路径、原子性、重复调用和冲突。

### 集成测试

- 成功：需求批准、检索充分、审校通过、人工批准、导出一次。
- 失败：非法参数、权限拒绝、证据不足、重试耗尽、安全审校失败。
- 人工介入：需求修改、报告退回、取消、旧批准失效、恢复后继续。

全部普通测试使用假模型、固定工具夹具、预设人工动作和临时存储；不访问网络。

### 评估

- 固定至少 12 个场景，绑定图、Prompt、来源快照和评估集版本。
- 同时评估内容质量与工作流可靠性。
- 保存基线、失败样例、错误分类和同集回归。
- 真实模型评估单独标记；费用审批前不运行。

## 15. 依赖与实现边界

P2 独立 `.venv`、精确依赖和原创固定资料已安装或创建并验证，详见 `docs/DEPENDENCIES.md` 与 `docs/EVALUATION_DATA.md`。

当前边界：

- 不新增依赖。
- 不下载真实资料，不调用真实模型或外部工具。
- `langsmith` 只作为必要传递包存在；tracing 保持关闭。
- 不实现开放 HTTP、任意文件、shell、SQL、部署或写操作。
- 后续真实模型、真实资料和费用仍需独立提案与批准。

## 16. 后续可选扩展

只有固定评估证明多智能体在报告质量、成功率或成本效率上有净收益，才比较多智能体版本。比较必须使用同一评估集，并报告：

- 内容质量变化。
- 调用次数、token、费用和耗时。
- 新增失败模式。
- 调试和状态复杂度。

没有净收益，继续保留单工作流。
