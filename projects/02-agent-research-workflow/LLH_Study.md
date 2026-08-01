# P2《LangGraph 研究报告工作流》面试学习手册

- 项目：AI 应用技术选型研究报告
- 当前证据范围：原创离线 `workflow-v1`
- 学习目标：能在五分钟内讲清问题、状态图、Human-in-the-loop、恢复、幂等、测试、评估和限制
- 诚实边界：当前没有真实模型、真实资料、联网搜索、真实 token/费用或公开部署

## 1. 项目事实卡

### 一句话

把“确认需求、规划、检索、证据检查、写作、审校、人工确认、导出”实现为可暂停、可恢复、可评估的显式 LangGraph 工作流。

### 目标用户

- 需要比较 2～4 个 AI 应用技术方案的工程师、技术负责人和产品负责人。
- 需要回查结论依据、限制和决策前提的人。

### 输入

- 研究问题。
- 报告读者。
- 业务约束。
- 候选方案。
- 评价维度及权重。
- 固定来源策略。

### 输出

- 人工批准后的 Markdown 技术选型报告。
- 带声明、证据 ID、可信来源元数据和限制的结构化草稿。
- 可机器校验的运行摘要、节点事件、报告哈希和制品 ID。

### 当前量化证据

- 原创虚构来源：10 份。
- 稳定证据章节：40 个。
- 固定案例：12 个。
- 案例通过：`12/12`。
- 固定路径正确：`12/12`。
- 引用绑定有效：`10/10`。
- 重试和停止正确：`12/12`。
- checkpoint 恢复一致：`1/1`。
- 无证据声明：`0/10`。
- 未批准导出：`0`。
- 提示注入扩大权限：`0`。
- 最近一次普通测试：`144 passed`。

### 不能声称

- 不能说“真实模型准确率 100%”。
- 不能说“报告能用于现实技术选型”。
- 不能说“已经实现开放网页研究”。
- 不能说“token 和费用为零代表生产成本为零”。
- 不能说“完全独立手写全部代码”。

## 2. 面试时怎么介绍

### 2.1 十秒版本

我做了一个 LangGraph 技术选型研究工作流，重点验证显式状态、两个人工暂停点、有限重试、SQLite 恢复和幂等导出。

### 2.2 三十秒版本

团队做 AI 技术选型时，资料分散、比较口径容易变化，一次聊天回答又难恢复和审计。我把研究过程实现成显式 LangGraph：先人工确认需求，再执行受控只读工具，检查证据是否充分，生成并审校报告，最后按具体 revision 和内容哈希人工批准后导出。离线固定集 12 个案例全部通过，未批准导出和权限扩大都是 0。当前只证明工作流可靠性，不证明真实模型质量。

### 2.3 两分钟版本

这个项目解决“长流程研究不能只靠一次模型回答”的问题。核心是把业务过程交给程序控制，而不是让模型自由决定下一步。

`runtime-state-v1` 保存运行身份、当前节点、已确认需求、循环计数、证据 ID、报告 revision/hash、安全错误和制品绑定。编译图、SQLite 连接、工具执行器、模型客户端、密钥和完整响应不进入 checkpoint。

工作流有两个人工门。第一个确认候选、评价维度和范围；缺候选或维度时停在 `NEEDS_HUMAN`，不能自己猜。第二个确认最终报告；决定同时绑定 `run_id`、`thread_id`、报告确认 revision、报告 revision 和 `report_hash`。报告修改后旧批准失效。

工具层只允许 `search_sources`、`read_source` 和 `calculate_comparison`。参数先经过 Pydantic Schema，再检查候选、维度、来源、章节、预算和证据作用域。瞬时错误最多三次尝试；确定性错误不重试。证据最多两轮，仍不足就以 `evidence-insufficient` 停止。

写作者只提交结构化声明和 evidence ID，程序从已验证目录绑定来源标题、章节、版本和 SHA-256。自动审校最多修改两次。人工批准后，导出器使用内容寻址 `artifact_id` 和不可覆盖硬链接发布；崩溃后重放返回 `UNCHANGED`。

固定 12 案例真实执行图，路径、引用、重试/停止和恢复指标全部达到当前目标。限制是全部内容仍来自确定性假对象和原创资料。

### 2.4 五分钟版本

按以下顺序讲：

1. 30 秒：问题和目标用户。
2. 45 秒：为什么一次聊天和普通 RAG 不够。
3. 45 秒：显式状态和 checkpoint 边界。
4. 45 秒：两个 Human-in-the-loop 暂停点。
5. 45 秒：工具 allowlist、业务作用域和证据门。
6. 45 秒：结构化草稿、程序绑定引用和有限审校。
7. 45 秒：内容寻址、不可覆盖导出和崩溃恢复。
8. 30 秒：量化结果。
9. 30 秒：限制和真实模型接入条件。

现场演示使用 `scripts/run_demo.py`，不要临时输入未冻结案例。

## 3. 项目真正解决什么问题

### 表面问题

自动生成一份技术选型报告。

### 真正问题

- 需求可能不完整，系统不能擅自扩大范围。
- 检索结果“相关”不等于足以支持结论。
- 模型可能提出合法但未授权的工具参数。
- 草稿有引用不等于引用真实或属于本次检索。
- 人工批准可能在报告修改后过期。
- 暂停恢复会重放节点，可能重复副作用。
- 漂亮输出不等于工作流路由、重试和停止正确。

### 业务价值

- 研究过程可暂停、恢复和审计。
- 决策前提、证据和限制可回查。
- 失败显式暴露，不用猜测制造成功。
- 重复执行不会静默覆盖已有制品。
- 固定评估能发现路由和权限回归。

## 4. 核心概念快速复习

### 4.1 Agent

Agent 是“模型或程序根据状态选择下一步，并可调用工具”的系统。P2 首版不是自由 Agent，而是受控工作流：允许的节点、边、工具和循环上限由代码固定。

### 4.2 LangGraph

LangGraph 用状态图组织长任务：

- State：跨节点共享、可持久化的业务数据。
- Node：读取状态并返回状态增量的函数。
- Edge：节点之间的固定连接。
- Conditional Edge：根据状态选择下一条边。
- Checkpointer：保存每步状态，支持暂停和恢复。
- `interrupt()`：暂停图，把结构化数据交给人工。
- `Command(resume=...)`：把人工决定送回暂停节点。

### 4.3 Tool Calling

Tool Calling 不是“模型可以执行任何函数”。正确边界：

```text
模型提出调用
名称 allowlist
参数 Schema
业务作用域与权限
预算
执行
结果标准化
写入状态
```

### 4.4 Human-in-the-loop

关键决定必须由人确认。人工不是聊天备注，而是带版本、身份和哈希的结构化输入。

### 4.5 幂等性

同一已批准报告重复导出，最终效果仍等价于执行一次。P2 的结果是：

- 文件不存在：`CREATED`。
- 文件存在且字节相同：`UNCHANGED`。
- 同 ID 但字节不同：冲突并失败，不覆盖。

### 4.6 确定性夹具

相同输入、状态和脚本产生相同输出。它能隔离验证工作流，但不能替代真实模型评估。

## 5. 整体架构

```text
START
  |
validate_request
  |
confirm_requirements
  |
await_human_requirements  [人工门 1]
  |
plan_research
  |
execute_tools -- transient --> retry_tool --+
  |                                      |
  +--------------------------------------+
  |
assess_evidence -- 缺口且未到上限 --> plan_research
  |
draft_report
  |
review_report -- 需修改且未到上限 --> revise_report
  |
confirm_report
  |
await_human_report  [人工门 2]
  |          |
  |          +-- request-changes --> apply_human_report_revision --> review_report
  |
export_report
  |
COMPLETED
```

任何确定性错误、预算耗尽、证据不足、审校耗尽或导出冲突都进入稳定 `FAILED`。人工拒绝和取消进入独立稳定终态。

## 6. 四类数据边界

### 6.1 可持久化业务状态

- `run_id`、`thread_id`、Schema 和图版本。
- 当前状态、当前节点、原始需求、确认需求。
- 人工确认 revision 和请求哈希。
- 工具 attempt、检索轮次、审校轮次、人工返修次数。
- evidence ID、证据缺口、安全错误码。
- 报告草稿、revision、hash、审校结果和批准绑定。
- `artifact_id`、幂等键、相对文件名、内容哈希和大小。

### 6.2 运行时依赖

- 编译后的 LangGraph。
- SQLite 连接和 checkpointer。
- 工具执行器、证据评估器、写作者、审校器和导出器。
- observer 和 clock。

这些对象由运行环境注入，不属于业务事实。

### 6.3 密钥和敏感响应

- API Key、Cookie、鉴权头和连接字符串。
- 完整供应商请求/响应。
- 未脱敏异常堆栈。

全部禁止进入 checkpoint、日志样例和 Git。

### 6.4 不应序列化的对象

- 文件句柄、socket、线程锁和数据库连接。
- SDK 响应对象、回调和任意可执行对象。

## 7. 技术栈

- Python `3.14.3`：项目运行语言。
- `langgraph==1.2.9`：显式状态图、条件路由、中断和恢复。
- `langgraph-checkpoint-sqlite==3.1.0`：本地 SQLite checkpoint。
- `pydantic==2.13.4`：严格输入、状态、工具、报告和评估合同。
- `pydantic-settings==2.14.2`：固定配置依赖；当前离线夹具没有真实供应商密钥配置。
- `pytest==9.1.1`：离线单元和集成测试。
- Python 标准库：SQLite、哈希、临时目录、文件系统和 SVG 生成。

没有模型 SDK、向量数据库、浏览器框架、Web UI 或多智能体依赖。

## 8. 目录结构

```text
projects/02-agent-research-workflow/
├─ src/agent_research/       # 状态、节点、工具、报告、评估和演示
├─ tests/                    # 普通离线测试
├─ data/synthetic-sources/   # 10 份原创固定资料
├─ evals/                    # 12 案例、gold、基线和运行摘要
├─ scripts/                  # 环境、评估、演示和制品检查入口
├─ demo/                     # 演示说明、固定报告和 SVG
├─ docs/                     # PRD、架构、依赖和评估资料
├─ README.md
├─ RETROSPECTIVE.md
├─ LLH_Study.md
└─ STATUS.md / DECISIONS.md
```

## 9. 核心代码必须理解

### 9.1 `StrictModel`：所有合同的共同基线

位置：[`models.py`](src/agent_research/models.py#L42)

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )
```

含义：

- `extra="forbid"`：未知字段直接失败，防止敏感字段偷偷进入状态。
- `frozen=True`：合同对象不可原地修改，状态变化必须显式产生新值。
- 字符串统一去除首尾空白。

### 9.2 `RuntimeState`：checkpoint 的业务合同

位置：[`runtime_state.py`](src/agent_research/runtime_state.py#L135)

最重要的不是字段多，而是组合约束。例如：

- `NEEDS_HUMAN` 必须停在人工节点，并带 revision/hash。
- `tool_attempts` 不能超过工具预算。
- 报告草稿、revision 和 hash 必须一致。
- `COMPLETED` 必须有可重算的制品记录。
- 密钥形态文本被拒绝。

状态不是普通字典。普通字典只能保存值；`RuntimeState` 还证明这些值组合合法。

### 9.3 `_validated_update`：每个节点增量也要验证

位置：[`workflow.py`](src/agent_research/workflow.py#L66)

```python
merged = state.model_dump(mode="json")
merged.update(updates)
validated = RuntimeState.model_validate(merged)
```

节点只返回自己负责的字段，但返回前先把增量合并成完整状态验证。这样错误不会等到下一个 checkpoint 才暴露。

### 9.4 第一个人工暂停点

位置：

- [`confirm_requirements`](src/agent_research/workflow.py#L117)
- [`await_human_requirements`](src/agent_research/workflow.py#L145)

`confirm_requirements` 先写入：

- `NEEDS_HUMAN`。
- 新的确认 revision。
- 当前请求的规范哈希。

然后 `await_human_requirements` 才调用 `interrupt()`。恢复时决定必须匹配：

```text
run_id
thread_id
expected_revision
expected_request_hash
```

若人工编辑需求，流程回到 `validate_request`，旧确认哈希清空。

### 9.5 工具执行与重试

位置：

- [`ToolCall / ToolResult`](src/agent_research/tool_contracts.py#L152)
- [`DeterministicFakeToolExecutor.execute`](src/agent_research/fake_tools.py#L164)
- [`execute_tools`](src/agent_research/workflow.py#L327)

执行顺序：

1. 必须已有 confirmed requirements。
2. 参数候选、维度、来源和章节必须在人工批准范围。
3. attempt 从持久化 `tool_attempts + 1` 计算。
4. 成功结果只保存标准化 evidence ID。
5. 瞬时错误有预算才进 `retry_tool`。
6. 确定性错误或预算耗尽进入 `FAILED`。

假执行器按 attempt 选择脚本结果，不依赖内存游标。关闭进程再恢复也不会跳过步骤。

### 9.6 证据门

位置：[`DeterministicEvidenceAssessor.assess`](src/agent_research/evidence_assessment.py#L161)

每个 requirement 有一个或多个可接受 evidence ID 集合。只要一个完整集合被当前证据覆盖，该 requirement 才满足。

```python
if not gaps:
    status = SUFFICIENT
elif retrieval_round < max_retrieval_rounds:
    status = NEEDS_MORE_EVIDENCE
else:
    status = INSUFFICIENT
```

关键点：相似证据、常识和模型推断都不能代替冻结集合。最多两轮。

### 9.7 草稿和程序绑定引用

位置：

- [`EvidenceCitationBinder.bind`](src/agent_research/report_drafting.py#L239)
- [`hash_report_draft`](src/agent_research/report_drafting.py#L311)

写作者只提交声明和 evidence ID。Binder 检查：

- 推荐候选属于人工批准范围和允许集合。
- 声明精确匹配当前 gold 夹具。
- 候选、维度和 evidence ID 属于本次任务。
- evidence ID 已实际收集。

然后程序从 `VerifiedSource` 绑定 source ID、section ID、标题、版本和 SHA-256。写作者不能提供这些可信元数据。

`report_hash` 排除 revision。相同内容不同 revision 有相同内容哈希；人工决定另外绑定 revision。

### 9.8 审校与有限修改

位置：

- [`DeterministicReportReviewer.review`](src/agent_research/report_review.py#L144)
- [`review_report`](src/agent_research/workflow.py#L567)
- [`revise_report`](src/agent_research/workflow.py#L653)

审校检查：

- 声明 evidence ID 与绑定引用集合一致。
- 必需候选是否覆盖。
- 必需评价维度是否覆盖。
- 是否包含固定禁止断言。

`review_rounds` 表示“成功生成的新 revision 数”，不是 reviewer 调用次数。最多修改 2 次，因此最多审校 3 次。

### 9.9 第二个人工暂停点

位置：

- [`await_human_report`](src/agent_research/workflow.py#L748)
- [`apply_human_report_revision`](src/agent_research/workflow.py#L839)

人工决定绑定：

```text
run_id
thread_id
report_confirmation_revision
report_revision
report_hash
```

动作：

- `approve`：进入导出边界。
- `request-changes`：生成新报告 revision，旧批准失效，重新审校。
- `reject`：稳定拒绝终态。
- `cancel`：稳定取消终态。

人工返修最多 2 次。每次人工返修后自动审校轮次重置，但人工循环和自动循环各自仍有硬上限。

### 9.10 安全幂等导出

位置：

- [`compute_artifact_id`](src/agent_research/report_export.py#L111)
- [`SafeMarkdownExporter`](src/agent_research/report_export.py#L246)
- [`export_report`](src/agent_research/workflow.py#L899)

`artifact_id` 绑定：

```text
run_id
approved_report_revision
approved_report_hash
固定 markdown 格式
```

导出器不接受模型路径。最终文件名固定为 `<artifact_id>.md`。

发布流程：

1. 校验绝对、规范化 allowlist 根目录。
2. 拒绝符号链接、junction/reparse point 和非普通文件。
3. 在同目录写临时文件并 `fsync`。
4. 用 `os.link(temp_path, target)` 执行“不存在才成功”的发布。
5. 最终字节一致才返回成功。
6. 清理临时文件。

### 9.11 运行时可观测性

位置：

- [`RunObserver.observe`](src/agent_research/observability.py#L267)
- [`build_run_summary`](src/agent_research/observability.py#L401)

observer 只记录：

- 节点、顺序和状态变化。
- monotonic 相对时间与主动执行耗时。
- 人工动作、工具结果类别和稳定错误码。

不记录 Prompt、节点载荷、证据正文、报告正文、路径、完整异常或响应。

`GraphInterrupt` 记为 `INTERRUPTED`，不是失败。observer 不进入 checkpoint，业务恢复不依赖它。

### 9.12 统一评估运行器

位置：[`run_workflow_evaluation`](src/agent_research/evaluation_runner.py#L944)

运行器逐案：

1. 读取冻结输入和假工具脚本。
2. 创建临时 SQLite 和导出目录。
3. 执行真实 LangGraph。
4. 用预设人工动作恢复两个暂停点。
5. 完成后才比较 expected path、终态、证据和尝试上限。
6. 汇总可重算分子、分母和 basis points。

`expected` 不能驱动图执行。否则评估是在复制答案。

## 10. 关键路径怎么讲

### 10.1 完整成功

```text
validate
confirm requirements
人工批准
plan
tool success
evidence sufficient
draft
review pass
confirm report
人工批准
export
COMPLETED
```

### 10.2 缺候选或缺维度

流程仍进入人工暂停，但批准不完整需求会被拒绝。系统不会补猜候选或维度。

### 10.3 瞬时工具错误恢复

第一次返回 transient error，状态保存 attempt；`retry_tool` 回到同一逻辑调用；第二次成功。参数和逻辑调用键不变。

### 10.4 证据不足

第一轮有缺口，允许第二轮；第二轮仍缺失，写入 `evidence-insufficient` 并失败。写作者调用次数为 0。

### 10.5 人工返修

人工对已审校报告选择 `request-changes`；新草稿增加 report revision，清除旧审校结果，重新审校和暂停。旧 revision/hash 的 approve 被拒绝。

### 10.6 崩溃窗口恢复

测试先发布文件，但故意不让 checkpoint 记录成功；重开 SQLite 后重放 `export_report`。导出器读到同 ID、同字节文件，返回 `UNCHANGED`，目录仍只有一个制品。

## 11. 循环和停止条件

| 循环 | 上限 | 到达上限后的行为 |
|---|---:|---|
| 工具尝试 | 3 次 | `tool-retry-exhausted` |
| 检索轮次 | 2 轮 | `evidence-insufficient` |
| 自动审校修改 | 2 次 | `review-limit-exhausted` |
| 人工报告返修 | 2 次 | `human-revision-limit-exhausted` |

未知字段、权限越界、确定性参数错误、401/403 类权限问题和内容冲突不应自动重试。

## 12. checkpoint、恢复和重放

### 为什么暂停必须写 checkpoint

人可能几分钟、几小时后才回复。进程、内存对象和数据库连接可能已经消失。checkpoint 保存恢复决策所需业务事实，人工回来后用同一 `thread_id` 找到状态。

### 为什么节点必须可重放

`interrupt()` 恢复时从节点开头重新执行。暂停节点前不能放不可重复副作用。真正写文件的 `export_report` 也必须幂等。

### `run_id` 和 `thread_id` 区别

- `run_id`：业务任务身份。
- `thread_id`：LangGraph checkpoint 查找身份。

当前实现要求两者都匹配人工决定，防止把另一个线程的批准用于当前任务。

## 13. 测试与评估区别

### 自动测试

验证局部和集成行为：

- Pydantic 合同。
- 状态组合和计数边界。
- 每条条件路由。
- 重试、暂停、恢复和导出。
- 路径穿越、符号链接和敏感信息排除。

普通测试由 `tests/conftest.py` 自动拦截 socket。假工具、假写作者和临时 SQLite 保证无网络、无费用。

### 固定评估

验证整个工作流在 12 个冻结业务案例上的行为。分类：

- 成功：4。
- 需求不完整：2。
- 证据不足：2。
- 工具失败：2。
- 人工返修：1。
- 恢复幂等：1。

测试回答“代码规则有没有被破坏”；评估回答“完整业务案例是否走对路径并满足指标”。

## 14. 如何解释量化结果

### `12/12` 案例通过

表示 12 个冻结案例的实际路径、终态、证据、尝试上限、推荐和制品数量都匹配预期。

不表示真实模型任务成功率 100%。

### `10/10` 引用绑定

实际生成报告里的 10 个引用全部属于已验证来源，并与声明 evidence ID 一致。没有报告的失败案例不进入分母。

### `0/10` 无证据声明

10 条实际报告声明全部精确匹配 gold 并绑定证据。这里只证明固定夹具边界，不证明开放语言事实正确性。

### `1/1` checkpoint 恢复

唯一恢复案例在重开 SQLite 后状态一致，并以 `UNCHANGED` 重放导出。

### token 和费用为 0

因为没有模型调用。它证明普通基线无费用，不是未来真实成本估算。

## 15. 安全设计

### 外部内容

来源正文全部视为不可信数据。提示注入文本不能改变工具 allowlist、路径或权限。

### 工具参数

Schema 合法不等于已授权。必须再检查本次人工批准范围。

### 路径

来源加载和导出都检查规范路径、真实父目录、符号链接和 Windows junction/reparse point。

### 写操作

只有最终 `export_report` 可以写文件；它不是模型工具，且必须已有当前 revision/hash 的人工批准。

### 敏感数据

密钥、鉴权头、Cookie、完整响应、原始异常和运行时路径不进入 checkpoint、基线或提交演示。

## 16. 关键取舍

### 单工作流，不用多智能体

状态、权限、成本和恢复更容易解释。只有同一评估集证明多智能体有质量或成本净收益时才增加。

### 原创固定资料，不用真实网页

先隔离状态机和安全边界。代价是不能代表现实产品状态。

### 精确 gold，不用模型裁判

结果确定、无费用、可审计。代价是不能评价任意语义表达和可读性。

### 安全失败，不降级完成

证据不足、路径不安全、硬链接不支持或制品冲突时停止。保守，但不会用猜测和覆盖制造成功。

### observer 不进 checkpoint

业务状态更小，敏感面更低。代价是崩溃前未外送事件不能恢复。

## 17. 已知限制和改进方向

### 当前限制

- 无真实模型、Embedding、检索器或官方资料。
- 假写作者和审校器不代表真实语义质量。
- PRD 中“系统提出候选/维度”尚未实现；当前直接暂停。
- 未执行人工报告质量量表，不能声称平均 `4/5`。
- 无真实 token、费用和性能基准。
- 未验证 Linux、macOS、多进程竞争或高并发 SQLite。
- 无 Web UI、公开部署、账号权限和生产监控。
- 硬链接发布依赖文件系统能力。

### 真实模型接入前

1. 批准供应商、模型 ID、调用次数、token 和人民币预算。
2. 冻结真实官方资料 URL、版本、许可和 SHA-256。
3. 记录新增依赖的版本、兼容性、许可和磁盘影响。
4. 模型只能输出版本化提案合同。
5. 保留两个 Human-in-the-loop 门、循环上限和不可覆盖导出。
6. 新建评估版本，不覆盖 `workflow-v1`。
7. 先通过全部离线回归，再报告真实语义质量和费用。

## 18. 高频面试问题与参考回答

### Q1：为什么使用 LangGraph？

任务需要多阶段状态、条件分支、有限循环、人工暂停和恢复。普通函数链可以实现，但 LangGraph 能把节点、路由和 checkpoint 明确表达并测试。

### Q2：为什么不用一次大模型调用？

一次调用无法可靠表达人工边界、重试上限、恢复身份和外部副作用幂等，也不容易定位失败发生在哪一步。

### Q3：为什么不用普通 RAG？

普通 RAG 常是一次检索加一次回答。P2 还需要需求确认、研究计划、证据充分性、审校、人工返修和安全导出。

### Q4：状态与普通函数参数有什么区别？

参数通常只服务一次调用；状态跨节点、跨暂停和跨进程恢复，还决定后续路由，所以必须版本化、可序列化并验证组合一致性。

### Q5：为什么等待人工不是失败？

它是业务流程中的正常状态。`NEEDS_HUMAN` 表示系统安全地缺少授权或信息，失败则表示无法继续满足合同。

### Q6：为什么暂停前先写等待状态？

`interrupt()` 恢复会从节点开头重放。先写 revision/hash 和等待节点，进程重启后仍知道人正在批准哪个版本。

### Q7：为什么批准要绑定 revision 和 hash？

revision 区分第几版或第几次展示，hash 证明内容未被篡改。只用其中一个都不够。

### Q8：Schema 校验后为什么还要业务校验？

Schema 只能证明字段和类型合法，不能证明候选、来源、章节和权重属于当前人工批准范围。

### Q9：哪些错误重试？

只重试明确瞬时错误，例如 timeout、连接中断、429 和部分 5xx。非法参数、权限、未知来源、哈希冲突和预算不足不重试。

### Q10：为什么不能无限重试？

会造成无限循环、隐藏费用、长时间占用和难以解释的行为。所有循环必须有硬上限。

### Q11：如何防止模型伪造引用？

模型或假写作者只提交 evidence ID。程序验证它属于本次收集结果，再从可信来源目录绑定标题、章节、版本和哈希。

### Q12：证据不足时怎么办？

最多补检索一次；第二轮仍不足就 `FAILED`，不生成报告，不用常识补齐。

### Q13：`review_rounds=2` 是审校两次吗？

不是。它表示成功生成两个自动修改 revision。初始草稿也会审校，因此最多审校三次。

### Q14：怎样保证恢复后重试顺序一致？

attempt 和 round 保存进 checkpoint。假执行器按持久化数字选择脚本结果，不依赖内存游标。

### Q15：为什么批准和导出分成两个节点？

批准是业务决定，导出是外部副作用。分离后可单独测试未批准不写文件、批准过期拒绝和导出重放。

### Q16：如何实现幂等导出？

`artifact_id` 绑定运行、批准 revision/hash 和格式；文件名由程序派生。相同字节返回 `UNCHANGED`，不同字节冲突，不覆盖。

### Q17：为什么用硬链接，不用 replace？

replace 可能覆盖竞争窗口中后来出现的文件。硬链接只在目标不存在时建立，符合“永不覆盖”边界。

### Q18：checkpoint 保存什么？

只保存恢复决策所需业务事实。连接、执行器、客户端、observer、密钥和完整响应不保存。

### Q19：observer 为什么不进入 checkpoint？

观测不是业务恢复依据。分离能减小状态和敏感数据面；代价是崩溃前未外送事件会丢失。

### Q20：怎样避免评估偷看答案？

先只用案例输入、工具脚本和人工动作执行实际图，结束后才比较 `expected`。测试还会故意修改 expected，确认实际执行不变。

### Q21：`12/12` 说明什么？

说明冻结离线案例的工作流行为全部匹配预期，不说明真实模型准确率或现实资料正确率。

### Q22：为什么不用多智能体？

单图已经覆盖核心需求。多智能体会增加状态、调用、成本和调试复杂度；没有同集净收益证据前不加入。

### Q23：项目最大难点是什么？

不是生成 Markdown，而是保证暂停恢复后批准仍绑定正确内容，以及文件已发布但 checkpoint 未提交时重放不产生第二个制品。

### Q24：真实模型接入最先做什么？

先批准模型、预算和数据边界，再用版本化适配器替换假对象，保留现有合同和离线回归。

### Q25：生产化还缺什么？

真实资料与模型评估、供应商错误处理、成本预算、并发控制、跨平台验证、身份权限、生产观测和部署方案。

## 19. 面试中容易说错的话

错误：“这个项目有 144 个测试函数。”

正确：“最近一次 pytest 结果是 `144 passed`；部分测试使用参数化，源码中的 `def test_` 数量不是 144。”

错误：“12/12 说明模型准确率 100%。”

正确：“12/12 是确定性离线工作流案例通过率。”

错误：“系统会自动搜索互联网。”

正确：“当前只使用原创固定快照和确定性假工具。”

错误：“Human-in-the-loop 就是最后看一眼报告。”

正确：“需求范围和最终报告有两个持久化暂停点，决定绑定身份、revision 和 hash。”

错误：“用了 Schema，所以工具调用安全。”

正确：“Schema 后还有业务作用域、allowlist、预算和结果证据范围校验。”

错误：“checkpoint 保存了整个应用。”

正确：“只保存版本化业务状态；运行时对象重新注入。”

错误：“内容哈希相同就能直接复用旧批准。”

正确：“人工决定同时绑定报告确认 revision、报告 revision 和内容哈希。”

## 20. STAR 项目故事

### Situation

AI 技术选型资料分散，一次聊天报告难以复现，结论和引用也可能缺少可信绑定。

### Task

实现一个能暂停、恢复、限制权限、验证证据、人工确认并安全导出的 LangGraph 研究工作流。

### Action

- 先冻结 PRD、架构、10 份原创资料、12 个案例和金标准。
- 定义严格 `runtime-state-v1` 和两个 Human-in-the-loop 门。
- 增加 Tool Calling Schema、业务作用域和有限重试。
- 实现两轮证据门、结构化草稿、程序绑定引用和有限审校。
- 实现 revision/hash 批准、内容寻址和不可覆盖导出。
- 用真实图运行 12 个案例，并保存可重算指标和脱敏运行摘要。

### Result

12 个案例全部通过；路径、重试/停止、引用和恢复达到当前目标；无证据声明、未批准导出和权限扩大为 0；普通离线测试 `144 passed`。

### Reflection

结果只证明固定夹具下的工作流可靠性。下一步应先验证学习者能独立讲解，再做完成审计；真实模型需要独立预算和新评估版本。

## 21. 自测题

1. 为什么 P2 选择单工作流而不是多智能体？
2. `RuntimeState` 至少保存哪五类业务事实？
3. 哪些对象绝不能进入 checkpoint？
4. `_validated_update` 解决什么问题？
5. `run_id` 和 `thread_id` 分别做什么？
6. 为什么 `interrupt()` 节点必须考虑重放？
7. 需求批准绑定哪些字段？
8. 报告批准为什么比需求批准多绑定字段？
9. Schema 合法为什么仍可能越权？
10. 工具 attempt 为什么必须持久化？
11. 哪些错误可以重试，哪些不能？
12. 证据集合为空代表什么？
13. 为什么证据不足路径不能调用写作者？
14. 引用中哪些字段由程序绑定？
15. `report_hash` 为什么排除 revision？
16. `review_rounds=2` 最多会调用 reviewer 几次？
17. 人工返修后哪些批准和审校数据需要失效？
18. `artifact_id` 绑定哪些内容？
19. 如何测试“文件已发布、checkpoint 未提交”？
20. 为什么 observer 事件不进入 checkpoint？
21. 测试与固定评估有什么区别？
22. 为什么 `expected` 不能驱动评估执行？
23. 如何解释 `10/10` 引用绑定？
24. 当前 token 和费用为什么是 0？
25. 真实模型接入前必须获得哪些批准？

### 答案关键词

1. 无净收益证据；单图更易控状态、成本和恢复。
2. 身份、路由、需求、计数、证据、报告、错误、制品。
3. 连接、客户端、执行器、observer、clock、密钥、完整响应、文件句柄。
4. 节点增量合并后立即验证完整状态组合。
5. 业务任务身份；LangGraph checkpoint 身份。
6. 恢复从节点开头执行，可能重复副作用。
7. run、thread、确认 revision、请求 hash。
8. 还要报告确认 revision、报告 revision 和报告 hash。
9. 类型合法不等于属于本次批准范围。
10. 重启后仍按正确脚本步骤和预算执行。
11. 瞬时错误可有限重试；参数、权限、哈希和冲突不重试。
12. 固定快照没有任何组合能证明该要求。
13. 防止把缺证据任务伪装成报告成功。
14. source ID、section、标题、版本和 SHA-256。
15. 内容身份与展示/修改次数是不同事实。
16. 最多 3 次。
17. 清批准 revision/hash、旧审校结果；重新审校和暂停。
18. run、批准 revision/hash、格式。
19. 先手动发布文件，不提交成功状态；重开 SQLite 后重放。
20. 观测不是业务恢复依据，减少敏感面。
21. 局部/集成规则；完整业务案例指标。
22. 防止把预期答案复制成实际结果。
23. 实际报告中的 10 个引用全部绑定已验证来源。
24. 没有真实模型调用，不是生产成本估算。
25. 模型、调用/token/人民币预算、资料来源/许可/版本、依赖和数据安全边界。

## 22. 实操自测

### 第一关：能运行

在 P2 目录：

```powershell
$env:LANGGRAPH_STRICT_MSGPACK="true"
$env:LANGSMITH_TRACING="false"
.\.venv\Scripts\python.exe scripts\verify_environment.py
.\.venv\Scripts\python.exe -m pytest -q
```

### 第二关：能复核评估

```powershell
.\.venv\Scripts\python.exe scripts\run_workflow_evaluation.py --check
.\.venv\Scripts\python.exe scripts\run_observability_demo.py --check
```

### 第三关：能演示

```powershell
.\.venv\Scripts\python.exe scripts\run_demo.py
.\.venv\Scripts\python.exe scripts\check_demo_assets.py --check
```

### 第四关：能定位代码

脱离本文，找到并解释：

- `RuntimeState`。
- 两个 `interrupt()`。
- `execute_tools`。
- `EvidenceCitationBinder`。
- `SafeMarkdownExporter`。
- `run_workflow_evaluation`。

### 第五关：能修改

练习但不要直接改冻结基线：

1. 在临时分支新增一个确定性工具失败案例。
2. 先写 expected path，再实现假工具脚本。
3. 运行全部离线测试。
4. 解释为什么不能静默修改 `workflow-v1`。

## 23. 个人参与范围

本项目在 Codex 指导和协作下分阶段完成。学习者参与：

- 场景、目标和边界确认。
- 依赖、安装、API费用和数据范围审批。
- 关键设计取舍和阶段推进。
- 运行结果、演示和交付确认。

Codex 协助：

- 合同、工作流、测试和评估实现。
- 问题诊断、安全检查和文档整理。

求职时建议表述：

> 我在 AI 编码助手协作下完成项目，能解释架构、运行测试、复核评估，并正在通过自测验证独立修改能力。

在不能脱离参考重建关键路径前，不表述为完全独立实现。

## 24. 复习路线

### 第一轮：能说

记住一句话、30 秒介绍、两个 Human-in-the-loop 门和 12/12 的正确含义。

### 第二轮：能解释

回答状态、checkpoint、revision/hash、Tool Calling、证据门和幂等导出。

### 第三轮：能定位

在五分钟内找到六个核心代码入口和对应测试。

### 第四轮：能应对追问

重点练：

- 为什么 Schema 不等于授权。
- 为什么 checkpoint 不保存运行时对象。
- 为什么 `interrupt()` 会重放。
- 为什么硬链接优于覆盖式 replace。
- 为什么确定性基线不等于真实模型质量。

### 第五轮：能现场演示

运行三路径演示，指出暂停、成功导出和证据不足停止，再展示工作流 SVG 和量化基线。

## 25. 最终记忆卡

```text
问题：一次聊天研究不可恢复、不可审计、权限和证据难控
方案：显式 LangGraph + 严格状态 + 两个人工门
工具：3 个只读/纯计算工具，Schema 后再做业务授权
证据：最多 2 轮，不足就失败
审校：最多 2 次自动修改
人工：需求确认 + 报告 revision/hash 批准
恢复：SQLite checkpoint，只存业务状态
导出：内容寻址、硬链接、永不覆盖、重放 UNCHANGED
评估：12 个冻结案例真实执行，expected 只做事后比较
结果：12/12；引用 10/10；恢复 1/1；未批准导出 0
边界：无真实模型、真实资料、真实费用和公开部署
```

能脱离本文讲清这张卡、定位核心代码、运行演示并正确解释限制，才算真正掌握 P2。
