# AI 工作流框架选型简报

## 研究问题
Our student team already uses Pydantic models. The decisive need is validated structured output. We do not need a graph or persistent workflow today. Compare both candidates and make a conditional choice only if the supplied evidence supports these requirements; state prerequisites and a concrete validation experiment.

## 证据范围
本报告的 `supported`/`contradicted` 只基于本次运行实际读取且列出的证据。`unknown` 只表示本次已读证据未覆盖该单元，不表示整个冻结快照、框架或其文档不具备该能力。

## 执行摘要
在本次提供的冻结证据范围内，两个候选在三个维度上均有官方文档支持。LangGraph 的证据覆盖图状态建模（StateGraph/MessagesState）、基于 interrupt 的人工审批暂停与恢复、以及基于 checkpointer 的状态持久化与恢复。PydanticAI 的证据覆盖基于 Pydantic 模型的结构化输出与校验、基于 requires_approval/ApprovalRequired 的工具审批边界、以及依赖外部引擎（Temporal、DBOS、Prefect、Restate、AWS Lambda）的持久执行。用户团队已使用 Pydantic 模型，且当前不需要图或持久工作流，因此结构化输出校验是决定性需求；PydanticAI 的 output_type 直接以 Pydantic 构建 schema 并校验返回值，与现有技术栈契合度更高。但证据未覆盖性能、定价、生产就绪度或团队学习成本，故只能给出附前置条件的条件性选择。

## 决策状态
`conditional`

## 证据矩阵

| 候选 | 维度 | 状态 | 结论 | 证据 |
|---|---|---|---|---|
| langgraph | state-model | supported | 官方文档展示了基于 StateGraph 与 MessagesState 的状态建模：定义节点函数接收状态并返回状态更新，通过 add_node/add_edge 构建图并 compile 后调用。 | lg-01#icon-icon-download-size-20-install |
| langgraph | human-approval | supported | 官方文档描述了 interrupt 函数作为人工审批边界：在节点内调用 interrupt 会暂停图执行、保存当前状态并等待恢复，恢复时通过 Command(resume=...) 将值传回节点；使用需 checkpointer 与 thread_id。 | lg-02#pause-using-interrupt |
| langgraph | recovery | supported | 官方文档描述了持久化与恢复机制：Checkpointer 按线程持久化图状态快照，用于对话连续性、human-in-the-loop、时间旅行与容错；并说明 MemorySaver 重启后丢失、生产应使用 PostgresSaver/SqliteSaver 等持久化 checkpointer。 | lg-03#checkpointer-vs-store, lg-03#troubleshooting-common-issues |
| pydantic-ai | state-model | supported | 官方文档描述了结构化输出建模：Agent 构造函数的 output_type 支持标量、list/dict、TypedDict、dataclass 与 Pydantic 模型及类型联合；默认利用模型工具调用返回结构化数据，并使用 Pydantic 构建 JSON schema 并校验模型返回的数据。 | pa-01#structured-output-data-structured-output |
| pydantic-ai | human-approval | supported | 官方文档描述了工具审批边界：可通过 requires_approval=True 或抛出 ApprovalRequired 要求人工审批，RunContext.tool_call_approved 可判断是否已获批。 | pa-02#human-in-the-loop-tool-approval |
| pydantic-ai | recovery | supported | 官方文档描述了持久执行能力：可构建在瞬时 API 失败、应用错误或重启后保留进度的 durable agents，并官方支持 Temporal、DBOS、Prefect、Restate、AWS Lambda durable functions 等五种持久执行方案。 | pa-03#durable-execution |

## 限制

- 前置条件：团队接受以 PydanticAI 的 Agent(output_type=...) 作为结构化输出入口，并确认当前不需要 LangGraph 式的图编排与内置 checkpointer 持久化；若后续需要持久工作流，需另行评估 PydanticAI 的外部持久执行引擎集成（Temporal/DBOS/Prefect/Restate/AWS Lambda）或重新考虑 LangGraph。
- 前置条件：人工审批场景中，若通过 UI 适配器暴露端点，必须按文档警告在工具函数内实现鉴权，不能仅依赖审批标志作为授权边界。
- 本次证据未覆盖性能、定价、生产就绪度、团队学习成本与迁移成本，这些均属未知，不能据此推断任一候选更优。
- 两个候选的 recovery 维度证据均指向不同实现路径（LangGraph 内置 checkpointer 对比 PydanticAI 外部持久执行引擎），本次证据未提供两者在故障恢复语义上的直接可比数据。
- 下一步验证：搭建一个最小对照实验，用同一组 Pydantic 模型分别定义 PydanticAI 的 output_type 与 LangGraph 的图状态输出，对同一批含边界/非法字段的模型响应各运行至少 30 次，记录结构化校验通过率与失败原因分布；判定标准为：若 PydanticAI 在满足团队可接受通过率（例如 ≥95%）且无需引入图编排的前提下稳定通过，则维持 pydantic-ai 的条件性选择，否则重新评估。

## 候选选择
pydantic-ai

## 每格限制与来源定位

快照：snapshot-1855a50c906058faffe87039

- langgraph/state-model：该证据描述的是图状态（messages）建模，未直接说明对 Pydantic 模型作为结构化输出的校验能力。
- langgraph/human-approval：文档要求生产环境使用持久化 checkpointer，且 interrupt 载荷需可 JSON 序列化。
- langgraph/recovery：文档同时提示 checkpoint 可能无限增长，需要定期清理或设置保留策略。
- pydantic-ai/state-model：文档提到静态类型检查器在函数或多类型联合场景下可能无法正确推断输出类型。
- pydantic-ai/human-approval：文档明确警告审批不是针对不可信客户端的授权边界，仍需在工具函数内做鉴权。
- pydantic-ai/recovery：该能力依赖外部持久执行引擎集成，文档未说明无需外部引擎的内置持久化。

### 本次已读引用

- lg-01#icon-icon-download-size-20-install：langgraph/overview.mdx#[icon-icon-download-size-20-install]；章节 SHA256：046929f9b3142edd6b96c3ac8ef19df8ec9456d31feeadf9a2db7e347fbf3924
- lg-02#pause-using-interrupt：langgraph/interrupts.mdx#[pause-using-interrupt]；章节 SHA256：6eba37f5fe86a3a18070e79fba58d36da1b3230531742507723856f7b3eb5ff5
- lg-03#checkpointer-vs-store：langgraph/persistence.mdx#[checkpointer-vs-store]；章节 SHA256：96c7ea7b460f49fb059ac3df4d95fdd25c235faa7a21f29b3901c1f2b822d6ae
- lg-03#troubleshooting-common-issues：langgraph/persistence.mdx#[troubleshooting-common-issues]；章节 SHA256：578b585374bf089ac7d935c79512f4d6a1183cbdef7ec0b949d53cf359c6febb
- pa-01#structured-output-data-structured-output：pydantic-ai/output.md#[structured-output-data-structured-output]；章节 SHA256：7201ccc41133d4b38e39ccded9b01926e01936d9b8562817a8b85463abc23f9c
- pa-02#human-in-the-loop-tool-approval：pydantic-ai/deferred-tools.md#[human-in-the-loop-tool-approval]；章节 SHA256：78e2787f7981ec4eca65bff327177be33f555d46a3eed2410c86d124dfbc0f6c
- pa-03#durable-execution：pydantic-ai/durable-execution.md#[durable-execution]；章节 SHA256：c4913424da89e5341eea3a3bb8c4ca39f0ae095ba475ddb5c964dfc057cd67cd

导出格式：markdown-v2.1
