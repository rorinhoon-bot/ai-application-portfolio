# P2 V2 现状审查

- 版本：`p2-v2-audit-0.1`；日期：2026-09-13。
- 方法：阅读本地实现、关键测试断言与评估构造逻辑，使用现存 P2 `.venv` 复核。没有安装、真实模型调用、语料采集或业务代码修改。

## 1. Git 与范围

- 仓库：`.`。
- 项目：`projects/02-agent-research-workflow`。
- 当前分支：`codex/p2-langgraph-v2`；此前因 checkout 复用了 P3 分支，现已在本地改为 P2 专用名称。
- HEAD：`dcb164e95059b060ffd6aebbaa093a7626177614`，`chore: polish portfolio verification workflow`；也是本次读取时最近影响 P2 的提交。
- 开始时 P2 无已跟踪或未跟踪改动；暂存区无改动。
- 仓库已有修改：根 `README.md`、`docs/PORTFOLIO_PLAN.md`。
- 已有未跟踪项：`.tmp/`、`deliverables/`、`output/`、`projects/04-project-learning-tutor/`、`scripts/`、`tmp_hr_docx/`、`tools/`、`面试准备/`、`面试速成手册.md`。不清理、不暂存、不覆盖。
- 未切换分支、未 stash/reset/commit/push。文档停留于当前工作树，开发前再建立独立分支。

适用规则：用户提供的全局规则、根 `AGENTS.md`；仓库文件清单未发现 P2 下更深层 `AGENTS.md`。已阅读四份学习交接、作品集计划、统一验收标准及 P2 文档。旧学习对话未读取。

作品集计划的 P1/P2/P3 勾选只表示历史版本，不代表后续升级完成。P1 最近是保留镜像的本地隔离启动验证，本次未核验云部署，不继承其预算、授权、数据库、容器或服务。

## 2. 已有实现及复用判断

以下路径均相对 P2；行号以本次 Git 基线为准。

| 能力 | 代码与测试证据 | V2 处理 |
|---|---|---|
| 显式完整图 | `src/agent_research/workflow.py:1542` 的 `build_report_export_graph`，并保留各阶段构图函数；`test_report_workflow.py` | 保留节点职责与条件分支，添加 V2 构图入口，不全量重写 |
| 严格状态合同 | `runtime_state.py:135`，节点更新再校验；`test_runtime_state.py` | 延续基础类型、版本和不变量；V2 独立状态合同 |
| 两个人工门 | `workflow.py:117`、`:145`、`:712`、`:748`；需求、报告测试验证 revision/hash 与 SQLite 重开 | 保留「先写等待状态，再 interrupt」；V2 增加资料/预算/配置绑定 |
| 工具边界 | `tool_contracts.py:45` 起的三个合同；`fake_tools.py` 检查候选、来源与权重作用域 | 合同思想可用；执行器需真实检索、读取、计算实现 |
| 有限路由 | `workflow.py:276` 两轮检索、`:327` 工具错误分类；审校及人工返修有硬上限 | 保留上限；新增全运行调用与费用账本 |
| 引用元数据绑定 | `report_drafting.py:298` 从已验证来源构造标题、版本、章节、哈希 | 保留身份绑定，拆除生产金标准内容校验 |
| 安全导出 | `report_export.py:246`，临时文件、fsync、硬链接不覆盖；`test_report_export.py:408` 模拟已发布未 checkpoint 的窗口 | 复用算法；V2 报告格式/身份升级需新增合同与渲染测试 |
| 离线来源校验 | `data_loader.py` 与 `test_source_data.py` 校验成员、大小、UTF-8、哈希、路径 | 提取可复用校验，真实资料采用新 manifest |
| 观测与基线 | `observability.py:244` 内存 observer；`evaluation_runner.py` 实际执行图 | 保留事件字段和分母规则；补持久化事件与真实 usage |

## 3. 假实现与硬编码限制

1. **规划并未理解需求**：`plan_research` 计算计划 ID；完整图的 `plan_evidence_round` 从注入的 `tool_calls` 按轮次取调用。不是模型自主生成检索计划。
2. **工具未做真实业务运算**：`DeterministicFakeToolExecutor` 校验参数后按持久化 attempt 取 `ScriptedToolOutcome`。检索没有相关性排序；读取结果不构成真实网页读取；`calculate_comparison` 校验分值/权重，但没有可交付的真实加权计算结果。
3. **来源合同写死合成模式**：`models.py:104` 为 `synthetic: Literal[True]`，`:149` 来源策略为 `Literal["synthetic-v1"]`；`RuntimeState.source_snapshot_id` 限定 V1 快照。不能换十个 Markdown 就当成真实语料版。
4. **证据门是固定集合判断**：`DeterministicEvidenceAssessor` 判断 evidence ID 组合；运行器 `_evidence_assessor` 根据脚本成功证据构造要求，并给不足类案例加入不可满足要求。不证明现实证据充分性或矛盾识别。
5. **生产式写作链依赖金标准**：`evaluation_runner.py:430` 从 gold 取允许推荐；`:446` 取 gold 声明；`:467` 构造假草稿和 `DraftPolicy`。`report_drafting.py:239` 要求声明集合及整条序列化内容等于允许事实。真实模型即使合理改写也会被拒绝。
6. **审校仅检查固定结构与字符串**：`report_review.py:144` 检查引用集合、候选/维度覆盖、禁止断言子串。运行器需要覆盖的候选来自选出的 gold 声明，不等于输入所有候选的公平比较；不能证明语义蕴含、公平性和事实正确。
7. **恢复不等于真实调用 exactly-once**：现有测试重开 SQLite 并模拟导出崩溃窗口；没有模型请求已发出但结果未知的恢复、账单对账或两个进程同时恢复的合同。
8. **成本为零是因为未调用**：V1 观测的模型/usage 字段固定零；observer 事件只在内存，不保证跨进程连续。现有工具 attempt 上限不替代所有节点共享的持久化费用预算。
9. **演示不是自由输入应用**：`scripts/run_demo.py` 固定三条故事；目前没有真实需求输入、可操作审批/恢复的通用 CLI 或 Web 产品。

## 4. 本轮验证

在 P2 目录显式设置 `LANGGRAPH_STRICT_MSGPACK=true`、`LANGSMITH_TRACING=false`、`LANGCHAIN_TRACING_V2=false`，直接运行脚本；不使用会加载可选 `.env` 的 `run_checks.ps1`，不读取密钥正文。

| 实际命令 | 本轮结果 | 证明范围 |
|---|---|---|
| `.\.venv\Scripts\python.exe -m pytest -q` | `144 passed in 27.83s` | 现有离线回归；网络 socket fixture 默认阻断 |
| `.\.venv\Scripts\python.exe scripts/run_workflow_evaluation.py --check` | `workflow-v1 baseline: passed` | 重跑图与提交 JSON 逐字节一致 |
| `.\.venv\Scripts\python.exe scripts/verify_environment.py` | `status: passed` | 固定直接版本、最小图和临时 SQLite 重开恢复 |
| `.\.venv\Scripts\python.exe -m pip check` | `No broken requirements found.` | 现存环境依赖关系一致 |

环境实际版本：LangGraph 1.2.9、SQLite checkpointer 3.1.0、Pydantic 2.13.4、pydantic-settings 2.14.2、pytest 9.1.1。项目声明 Python `>=3.14,<3.15`。本轮未重建新环境，不能把旧安装记录当成本次新环境验证。

固定集仍为 12 例、10 份合成资料、40 个章节。基线：案例/路径/重试停止各 12/12，引用身份绑定 10/10，恢复案例 1/1，无证据声明 0/10，未批准导出与权限扩大 0。

`test_changed_expectation_does_not_drive_actual_execution` 改坏 expected 路径后实际执行不变且判失败，证明没有把预期路径直接复制成结果；**它不证明 gold 没有参与草稿构造**。

历史人工 4.8/5 仅针对 `demo/generated/report-v2.md`，由 `evals/results/workflow-v2-human-report-review.md` 记录；本轮未重新请人评分。这是 V1 合成演示报告的第二版，不是本次 P2 产品 V2。

尚未证明：真实检索质量、模型工具调用成功率、模型语义/事实质量、真实成本与延迟、跨进程外部调用恢复、多用户并发、跨平台文件安全、真实云部署。socket monkeypatch 也不是操作系统级全进程网络沙箱。

## 5. 文档一致性与优先级

- 旧 `docs/PRD.md` 顶部仍写 final acceptance in progress，后面仍有「人工量表未执行」，与历史最终评分冲突。旧架构的「批准不导出」仅适用于阶段切片，完整导出图会继续。
- 本轮不改写 V1 历史正文；设计入口声明 V1 已完成的范围，V2 新内容以本目录为准。
- P0 优先：解除 gold/合成合同耦合；实现真实资料检索、模型适配、全局预算；形成可交互闭环。
- P1 优先：独立内容评估、故障恢复持久化证据、真实演示。
- 后置：新 UI、向量库、多智能体、P1/P3 接口、云资源。不因求职展示引入无证据收益的技术。
