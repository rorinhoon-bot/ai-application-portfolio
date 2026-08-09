# P2：LangGraph 研究报告工作流

作品集旗舰项目。

## 解决什么问题

当团队需要在多个 AI 应用技术方案之间做选择时，资料分散、比较口径不一致、结论缺少证据，人工研究又难以复现。本项目把“确认需求—规划—检索—写作—审校—人工确认—安全导出”做成可暂停、可恢复、可评估的显式工作流。

首版场景：**AI 应用技术选型研究报告**。例如，输入“为中文技术文档问答选择工作流框架，比较 2～4 个候选方案，并考虑成本、可观测性和 Human-in-the-loop”，输出带证据、限制和建议的 Markdown 报告。

## 用户、输入、输出与边界

- 目标用户：需要比较 AI 应用技术方案的工程师、技术负责人和产品负责人。
- 输入：研究问题、报告读者、业务约束、2～4 个候选方案、3～8 个评价维度及固定来源策略。候选或评价维度缺失时暂停等待人工，不自行猜测。
- 输出：人工批准后的内容寻址 Markdown 报告，以及可机器校验的运行摘要。
- 不处理：真实或实时技术选型、任意网页搜索、代码/依赖/云资源修改、高风险医疗/法律/金融研究、公开部署。

## 与普通聊天机器人、普通 RAG 的区别

- 普通聊天机器人通常直接生成一段回答；本项目保存显式状态，按节点执行，有条件路由、重试上限、停止条件和人工暂停。
- 普通 RAG 通常是“检索一次，再回答一次”；本项目会先确认需求和研究计划，再多轮检索、检查证据是否充足、写作、审校和修改。
- 模型不能直接执行任意工具、访问任意 URL、决定输出路径或完成最终导出。程序校验 Tool Calling 参数；人工批准后才产生最终报告文件。

## 工作流概览

![LangGraph 研究报告工作流](demo/assets/workflow-overview.svg)

## GitHub 展示与演示

- **真实证据**：`144 passed`；固定工作流案例 `12/12`；引用绑定 `10/10`；checkpoint 恢复 `1/1`；人工报告评分 `4.8/5`。
- **已有制品**：本 README 已嵌入工作流 SVG；下方“离线演示”嵌入真实终端 SVG。
- **面试学习**：状态图、人工暂停、恢复、幂等导出和面试问答见 [LLH_Study.md](LLH_Study.md)。
- **可选补图**：可按仓库根目录 [截图清单](../../docs/GITHUB_PUBLISHING_CHECKLIST.md#4-截图与演示清单) 补一张真实运行摘要；不需要伪造 Web UI。

> 公开说明边界：当前资料和工具均为原创虚构/确定性夹具，不能作为真实技术选型结论或真实模型质量证明。

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
- 最终普通测试：`144 passed`；测试默认阻断网络。
- v2 报告真实人工质量评分：`4.8/5`，通过 `4.0/5` 门槛；记录见 `evals/results/workflow-v2-human-report-review.md`。
- 需求见 `docs/PRD.md`，状态图和安全边界见 `docs/ARCHITECTURE.md`。
- 精确依赖提案见 `docs/DEPENDENCIES.md`；首批原创离线评估资料见 `docs/EVALUATION_DATA.md`。

当前仍只使用原创虚构资料、确定性假工具和假写作者。未下载真实研究语料，未调用模型 API，未产生费用，也未公开部署。

## 新环境安装

要求：Windows、CPython `3.14.x`。在仓库根目录打开 PowerShell：

```powershell
Set-Location projects\02-agent-research-workflow
& 'C:\Path\To\Python314\python.exe' --version
& 'C:\Path\To\Python314\python.exe' -m venv .venv
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
```

把示例 Python 路径替换为本机 CPython 3.14 可执行文件。`requirements-dev.txt` 已固定生产、传递和测试依赖版本。当前离线演示不需要 API Key；所需环境变量完整列在 `.env.example`，运行命令会显式设置它们。

## 离线演示

![P2 离线演示终端截图](demo/assets/offline-demo-terminal.svg)

运行暂停、成功、失败和观测四段终端简报：

```powershell
$env:LANGGRAPH_STRICT_MSGPACK="true"
$env:LANGSMITH_TRACING="false"
.\.venv\Scripts\python.exe scripts\run_demo.py
```

使用 `--json` 输出机器可读 manifest；使用 `--check` 重跑真实图并逐字节检查提交的 manifest、Markdown 报告与运行摘要。脚本不接受任意案例 ID 或输出路径。完整说明与提交制品见 `demo/README.md`。

逐字节重建并检查两张 SVG：

```powershell
.\.venv\Scripts\python.exe scripts\check_demo_assets.py --check
```

五分钟讲解提纲见 `demo/FIVE_MINUTE_TALK.md`。

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

## 开发复盘

离线首版的开发过程、失败根因、关键取舍、限制和真实模型接入条件见 [`RETROSPECTIVE.md`](RETROSPECTIVE.md)。P2 已完成最终验收；真实模型、真实资料和部署仍需另立版本。

## 学习与面试讲义

30 秒、2 分钟和 5 分钟介绍、核心代码、面试问答、自测题及诚实参与范围见 [`LLH_Study.md`](LLH_Study.md)。P2 已通过最终验收；讲义不代表真实模型或真实资料能力。

## 完成审计

逐项 `PROJECT_STANDARDS.md` 证据见 [`docs/COMPLETION_AUDIT.md`](docs/COMPLETION_AUDIT.md)。真实人工报告质量评分为 `4.8/5`，记录见 [`evals/results/workflow-v2-human-report-review.md`](evals/results/workflow-v2-human-report-review.md)；AI 自评未代替人工验收。
