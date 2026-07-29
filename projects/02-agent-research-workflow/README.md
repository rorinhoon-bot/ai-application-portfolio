# P2：LangGraph 研究报告工作流

作品集旗舰项目。

## 解决什么问题

当团队需要在多个 AI 应用技术方案之间做选择时，资料分散、比较口径不一致、结论缺少证据，人工研究又难以复现。本项目把“确认需求—规划—检索—写作—审校—人工确认—安全导出”做成可暂停、可恢复、可评估的显式工作流。

首版场景：**AI 应用技术选型研究报告**。例如，输入“为中文技术文档问答选择工作流框架，比较 2～4 个候选方案，并考虑成本、可观测性和 Human-in-the-loop”，输出带证据、限制和建议的 Markdown 报告。

## 与普通聊天机器人、普通 RAG 的区别

- 普通聊天机器人通常直接生成一段回答；本项目保存显式状态，按节点执行，有条件路由、重试上限、停止条件和人工暂停。
- 普通 RAG 通常是“检索一次，再回答一次”；本项目会先确认需求和研究计划，再多轮检索、检查证据是否充足、写作、审校和修改。
- 模型不能直接执行任意工具、访问任意 URL、决定输出路径或完成最终导出。程序校验 Tool Calling 参数；人工批准后才产生最终报告文件。

## 当前阶段

- P1 已完成，满足 P2 启动条件。
- P2 独立 `.venv`、固定依赖、PRD 和架构基线已完成。
- 10 份原创资料、40 个稳定证据章节、12 个固定案例和金标准已冻结。
- 显式 LangGraph 已覆盖需求确认、只读工具、两轮证据门、结构化写作、有限审校、最终人工确认和幂等 Markdown 导出。
- 两个人工暂停点、SQLite 恢复、revision/hash 绑定、有限重试和不可覆盖导出均有离线测试。
- 统一 `workflow-v1` 运行器实际执行全部 12 个案例；金标准未因结果修改。
- 可选运行时 observer 已覆盖完整图；生成 `node-event-v1` 和内容哈希绑定的 `run-summary-v1`，不进入 checkpoint。
- `offline-demo-v1` 用三个固定案例展示需求暂停、成功导出和证据不足停止，并关联确定性运行摘要。
- 当前量化基线：案例通过 `12/12`，路径 `12/12`，引用绑定 `10/10`，重试/停止 `12/12`，checkpoint 恢复 `1/1`，无证据声明 `0/10`，未批准导出与权限扩大均为 `0`。
- 当前普通测试：`138 passed`；测试默认阻断网络。
- 需求见 `docs/PRD.md`，状态图和安全边界见 `docs/ARCHITECTURE.md`。
- 精确依赖提案见 `docs/DEPENDENCIES.md`；首批原创离线评估资料见 `docs/EVALUATION_DATA.md`。

当前仍只使用原创虚构资料、确定性假工具和假写作者。未下载真实研究语料，未调用模型 API，未产生费用，也未公开部署。

## 离线演示

运行暂停、成功、失败和观测四段终端简报：

```powershell
$env:LANGGRAPH_STRICT_MSGPACK="true"
$env:LANGSMITH_TRACING="false"
.\.venv\Scripts\python.exe scripts\run_demo.py
```

使用 `--json` 输出机器可读 manifest；使用 `--check` 重跑真实图并逐字节检查提交的 manifest、Markdown 报告与运行摘要。脚本不接受任意案例 ID 或输出路径。完整说明与提交制品见 `demo/README.md`。

## 离线验证

在 P2 目录执行：

```powershell
$env:LANGGRAPH_STRICT_MSGPACK="true"
$env:LANGSMITH_TRACING="false"
.\.venv\Scripts\python.exe scripts\verify_environment.py
.\.venv\Scripts\python.exe -m pytest -q
```

重新执行 12 个固定案例并检查是否与提交基线完全一致：

```powershell
$env:LANGGRAPH_STRICT_MSGPACK="true"
$env:LANGSMITH_TRACING="false"
.\.venv\Scripts\python.exe scripts\run_workflow_evaluation.py --check
```

去掉 `--check` 会把新运行结果打印为 JSON，但不会修改基线文件。提交基线位于 `evals/results/workflow-v1-baseline.json`。

重新生成一个成功案例的确定性运行摘要：

```powershell
$env:LANGGRAPH_STRICT_MSGPACK="true"
$env:LANGSMITH_TRACING="false"
.\.venv\Scripts\python.exe scripts\run_observability_demo.py --check
```

去掉 `--check` 会把 `run-summary-v1` 打印到标准输出。提交样例位于 `evals/results/privacy-durable-run-summary.json`。

## 当前限制

- 基线证明确定性工作流可靠性，不证明真实模型的语义质量。
- 报告内容只来自原创虚构快照，不能用于现实技术选型。
- 当前摘要记录节点主动执行耗时，不包含人工等待时间；进程崩溃前未外送的 observer 事件不会由 checkpoint 恢复。
- 当前没有模型调用，因此 token、模型调用和已知费用字段均为 `0`；不是未来真实模型成本估算。
- 真实模型、真实官方资料和公开部署仍需单独批准。
