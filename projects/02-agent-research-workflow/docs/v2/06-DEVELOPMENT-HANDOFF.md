# P2 V2 开发交接

> 2026-09-16最终增量：248项测试通过，六题均完成生成与复核，2份带备注批准、4份拒绝，内容验收未通过。续期已同意并应用，不再等待；有效占用441/500分、100条调用预留已用满。以[18号结论](18-VALIDATION-CLOSEOUT.md)为准，下方阶段数字为历史。


> 2026-09-15 接手更新：优先读取 [13-DELIVERY-AUDIT.md](13-DELIVERY-AUDIT.md)。本文件保留历史设计和命令；旧预算、测试数量及阶段描述不再代表当前状态。

> 最新复核：P2全量219项测试通过。共享500分总额已计入150分历史占用，可新增预留350分；历史7份导出中4份仍带范围finding，不能视为审校通过。详见 [预算与审批交接](12-BUDGET-AND-APPROVAL-HANDOFF.md)。

恢复复核与 D3-live（2026-09-14）：早期三份 live 账本与失败记录一致；后续使用 `deepseek-flash` 完成一份真实闭环，另保留合同失败和引用审校返修样本。CLI 测试隔离真实环境与运行目录；最新完整回归为 196 passed，V1 固定基线通过。详见 D-061/D-062 与 `evals/results/v2-live-followup-2026-09-14.md`。

- 版本：`p2-v2-handoff-0.7`；2026-09-14；当前停点：`D4-reliability-and-content-guard`。
- 最新用户确认：场景与 CLI 优先已接受；资料先6页、上限12页/5MiB；模型为 `deepseek-flash`（V4.1 Flash）；P2 累计人民币上限保持 5 元。实际模型/usage 已由单一真实闭环验证；D5 的30元评估预算未批准。真实单样本不代表内容质量达标。
- 本轮完成 D1 合同、D2 固定官方快照/章节覆盖审查、D3 离线 MVP 与一份真实端到端报告；`demo/v2/` 仍是显式合成夹具。

## 0. 已完成实现入口（开发阶段更新）

```text
V2 合同/状态       .\projects\02-agent-research-workflow\src\agent_research\v2\contracts.py
V2 图              .\projects\02-agent-research-workflow\src\agent_research\v2\graph.py
模型适配器         .\projects\02-agent-research-workflow\src\agent_research\v2\model_client.py
资料快照读取       .\projects\02-agent-research-workflow\src\agent_research\v2\source_store.py
资料安全采集器     .\projects\02-agent-research-workflow\src\agent_research\v2\source_collector.py
资料清单 CLI        .\projects\02-agent-research-workflow\scripts\collect_sources_v2.py
调用账本           .\projects\02-agent-research-workflow\src\agent_research\v2\ledger.py
幂等导出           .\projects\02-agent-research-workflow\src\agent_research\v2\exporter.py
CLI                .\projects\02-agent-research-workflow\scripts\run_research_v2.py
离线夹具           .\projects\02-agent-research-workflow\demo\v2\
V2 行为测试        .\projects\02-agent-research-workflow\tests\test_v2_*.py
模型配置 hash       `scripts/run_research_v2.py --mode live model-config`（不联网；默认加载 .env，不输出 key）
```

当前证据：P2 全量测试 `198 passed`；V1 `workflow-v1` 基线仍逐字节通过。V2 已实测需求门 → plan → 受控 search → draft → review → 报告门 → 单制品导出；未知请求停在 `RECOVERY_REVIEW`，超出 token 预算或快照/预算绑定不匹配会停止。D2 已完成 6 页固定 commit 原文快照，`snapshot-1855a50c906058faffe87039` 共 `163080` bytes，并通过真实章节 search/read；两个候选×三个维度覆盖审查记录在 `docs/v2/09-SOURCE-COVERAGE.md`。真实闭环和失败样本见 `evals/results/v2-live-followup-2026-09-14.md`。D5 的 12 份真实报告完成了助手单人复核但内容验收未通过：详见 `evals/results/v2-content-assistant-review-2026-09-14.md`。

最新兼容修复：执行器不再让模型的自由关键词决定资料覆盖，而是对请求的每个 candidate×dimension 做候选过滤的稳定只读查询。维度 `recovery` 受控映射到 persistence/durable execution/checkpoint，避免通用名称漏掉 durable 页面。`tests/test_v2_source_store.py` 固定验证 PydanticAI recovery 命中 `pa-03#durable-execution`；`tests/test_v2_graph.py` 验证 2×3 图内覆盖且 draft payload 实际包含该证据。定向测试 `34 passed`；尚未重新 live 评估。

另有审校前范围门：报告文本出现整冻结快照缺证据的显式模式，图以 `REPORT_SCOPE_CLAIM_INVALID` 停在报告人工门，账本不创建审校调用。`tests/test_v2_graph.py` 覆盖这条路径。当前 V2 测试分片共 `65 passed`，并通过 `compileall`、`pip check` 与 `git diff --check`。它只拦截已知措辞，不是事实核验替代品；完整复测仍需要新预算。

2026-09-14 D5e 范围复测已启动 3 个案例：`dev-baseline` 与 `dev-structured-output` 完成，`dev-recovery-scope` 的 draft 返回违反 `decision-status-note` 合同；用量已知但没有可重放的合格结果，因此按不可重发规则停在 `RECOVERY_REVIEW`。账本预留 39 分、已知价格卡 usage 11 分。后续真实调用已停止。为避免手动非连续选择绕开批次停机，评估脚本新增 `--case-ids`，按冻结顺序执行并在首个恢复审查停止；离线测试覆盖该选择路径。

D5f 使用更新后的结构 Prompt 独立重测 `dev-recovery-scope` 与四个 holdout 案例，5/5 完成、13 次操作均成功。D5d、D5e 的两个有效制品和 D5f 合计为 8 份范围修复回归报告；助手单人复核记录 40 个有引用矩阵单元、8 个正确限定范围的 unknown。D5 仍没有独立人工验收。随后只读预留汇总发现各独立运行目录合计 553 分，超过 P2 ¥5 风险线；所有 live 调用已冻结。live CLI 已实现共享 P2 总额账本并通过第三次发送前拦截测试，但旧目录不能自动回填。下一步仅可在刷新供应商账单后，以对账得出的剩余额度创建总额授权；不能重新使用完整 ¥5。

## 1. 绝对路径

```text
仓库 .
P2   .\projects\02-agent-research-workflow
设计 .\projects\02-agent-research-workflow\docs\v2\README.md
来源清单与采集记录 .\projects\02-agent-research-workflow\docs\v2\08-SOURCE-PLAN.md
证据覆盖审查 .\projects\02-agent-research-workflow\docs\v2\09-SOURCE-COVERAGE.md
机器清单     .\projects\02-agent-research-workflow\docs\v2\source-plan-v1.json
解释器 .\projects\02-agent-research-workflow\.venv\Scripts\python.exe
状态 .\projects\02-agent-research-workflow\STATUS.md
决策 .\projects\02-agent-research-workflow\DECISIONS.md
```

## 2. Git 基线与保护

- 分支 `codex/p2-langgraph-v2`（由历史遗留的 `codex/p3-local-mcp-tool-service` 本地改名）；HEAD `dcb164e95059b060ffd6aebbaa093a7626177614`。
- 本轮未创建新分支；仅将历史遗留 P3 分支在本地改名为 P2 名称，没有 commit、stage、push。设计文件和 V2 实现仍在工作树中，尚无新的提交 SHA。
- 设计阶段后工作树已有 P2 设计文档、V2 实现和仓库其他用户未提交/未跟踪资料；清单见审查文档。不能执行 `git add .`、清理或重置工作树。
- 本轮新增 `src/agent_research/v2/`、`scripts/run_research_v2.py`、`scripts/collect_sources_v2.py`、`docs/v2/source-plan-v1.json`、`tests/test_v2_*.py`、`demo/v2/`、D2 采集器 HTTP mock/机器清单闸门测试、V2 离线评估记录和 P2 `.gitignore`，并更新 P2 入口文档；没有修改 V1 评估数据、依赖锁文件或 P1/P3 文件。
- 开发阶段仍以当前 status/HEAD 为基线；若后续基线变化，先比较 P2 diff。未暂存、提交或 push；不要用 `git add .` 清理用户已有工作。
- 用户未要求本轮提交，因此不自动提交。交接使用工作树中可定位的文件和验证命令，不把未提交代码描述为已发布版本。

保护文件 SHA-256（本轮写文档前）：

```text
根 README.md
95BD18AAC22B8280B758DC0BC40A985F6B02C0F22583580D575E32E2E8407B66
docs/PORTFOLIO_PLAN.md
BF73B7F0A7519B3527C4C880A1DB4F482672545488969A54C1CD61E007FD2EE4
P2/requirements.txt
5761EFD80248F314BD44A2813FFB692B308C8F69EA9A4020833A96043EFAD099
P2/evals/results/workflow-v1-baseline.json
C00A8E906E9BFC4C6D99DDEECF9E91D55DF85A7D9D4D287385DC25A31BF72C87
```

## 3. 接手必读与第一步

先读用户的全局规则、根 AGENTS、学习交接四份文件、作品集计划、P2 STATUS/DECISIONS，再读 [设计入口](README.md)。历史 PRD/架构及 `report-v2.md` 属 V1；本目录才是产品升级 V2。

任务顺序：D0 设计确认（完成）；D1 合同/最小账本（完成）；D2 真实资料（完成）；D3 CLI 与单样本真实闭环（完成）；D4 故障与内容增强（当前）；D5 独立质量评估（预算未批准）；D6 演示与学习验收。详见 [实施计划](05-IMPLEMENTATION-PLAN.md)。

第一个学习者任务：写「我实际要做的应用、两个候选、三个必须比较的维度、一个硬约束」。助手审查后再进入一小步实现，不能直接生成全部 V2。

## 4. 当前可运行验证命令

PowerShell，均为已有入口。本轮没有运行会自动加载 `.env` 的一键脚本，不读取密钥。

```powershell
Set-Location -LiteralPath '.'
git branch --show-current
git rev-parse HEAD
git status --short
git diff --cached --name-only
git diff --check

Set-Location -LiteralPath '.\projects\02-agent-research-workflow'
$env:LANGGRAPH_STRICT_MSGPACK = 'true'
$env:LANGSMITH_TRACING = 'false'
$env:LANGCHAIN_TRACING_V2 = 'false'
.\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'P2_TESTS_FAILED' }
.\.venv\Scripts\python.exe scripts\run_workflow_evaluation.py --check
if ($LASTEXITCODE -ne 0) { throw 'P2_BASELINE_FAILED' }
.\.venv\Scripts\python.exe scripts\verify_environment.py
if ($LASTEXITCODE -ne 0) { throw 'P2_ENVIRONMENT_FAILED' }
.\.venv\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw 'P2_DEPENDENCIES_FAILED' }
```

V2 离线 CLI（默认使用合成 `demo/v2` 快照，运行目录建议放临时目录）：

```powershell
$r = Join-Path $env:TEMP ('p2-v2-' + [guid]::NewGuid().ToString('N'))
$s = .\.venv\Scripts\python.exe scripts\run_research_v2.py --runtime-root $r start | ConvertFrom-Json
.\.venv\Scripts\python.exe scripts\run_research_v2.py --runtime-root $r status --thread-id $s.thread_id
.\.venv\Scripts\python.exe scripts\run_research_v2.py --runtime-root $r resume --thread-id $s.thread_id --action approve
.\.venv\Scripts\python.exe scripts\run_research_v2.py --runtime-root $r resume --thread-id $s.thread_id --action approve
```

上述命令依次得到 `NEEDS_HUMAN`、`REPORT_NEEDS_HUMAN` 和 `COMPLETED`；最后一个状态包含 `artifact_id`。`--mode live` 需另提供 `DEEPSEEK_API_KEY` 和已批准的 `BudgetAuthorization` JSON，本轮没有执行。

D2 来源清单只读检查：

```powershell
.\.venv\Scripts\python.exe scripts\collect_sources_v2.py check
```

当前输出 `status=frozen`、`source_count=6`；已执行一次受限采集，快照通过 hash/UTF-8/路径和章节检查。后续仍需按 `docs/v2/10-LIVE-GATE.md` 单独确认 DeepSeek live smoke 与预算。

设计阶段历史实测：V1 `144 passed`（27.83 秒）、workflow-v1 逐字节基线通过、环境/SQLite 重开恢复通过、pip check 无依赖冲突。D1/D3 开发阶段新增回归见本交接第 0 节；全部仅用 P2 和测试临时存储，未操作 P1/P3 运行资源。

演示已有入口 `scripts/run_demo.py --check`、`scripts/run_observability_demo.py --check`、`scripts/check_demo_assets.py --check`；本轮普通测试已包含相关制品回归，没有额外声称新运行了独立演示命令。

## 5. CLI 合同（D3 离线已实现；live 仍受关口控制）

`scripts/run_research_v2.py` 通过以下子命令提供本机操作：

```text
start --request <JSON> --mode offline|live
status --thread-id <id>
resume --thread-id <id> --action approve|edit|request-changes|reject|cancel
cancel --thread-id <id>
```

最终报告批准后图内自动导出，不给模型或命令行任意输出路径。offline 使用 `demo/v2/` 合成快照与脚本模型，明确标注非真实质量结果；live 必须同时有 DeepSeek key、预算 JSON 和人工批准，不允许启动时隐式发请求。`status` 可跨进程读取 SQLite checkpoint。

离线可靠性目前由 `tests/test_v2_*.py` 和 CLI smoke test 覆盖；D2 机器清单、采集和真实快照读取已完成；独立内容评估入口和 D3-live 批处理入口尚未实现，不能把 V1 `run_workflow_evaluation.py` 当成 V2 内容质量评估。

## 6. 待决事项与默认推荐

| 事项 | 推荐 | 确认时点 |
|---|---|---|
| 真实产品方向 | 学生/小团队框架选型；先 LangGraph/PydanticAI、CLI | 设计评审 |
| 第一条真实用户需求 | 学习者给实际项目问题；不编造用户访谈 | D0 |
| 来源采集范围 | 官方公开文档，6 页起步，上限12页/5MiB；路径/commit/许可冻结 | D1 提案完成后、采集前 |
| 模型供应商/ID | 单一可用托管模型，工具调用+结构化输出+usage | 适配器 live 实现前 |
| 预算 | smoke ≤5元；全量评估另批≤30元；价格核验后按硬上限执行 | 每次收费批次前 |
| 依赖补丁/SDK | 本地基线保留；必要变更单独说明 | 安装前 |
| 真人复核人 | 学习者主评；同学抽评3份 | D5 前 |
| 部署/UI | 后置，当前没有授权与云资源需求 | 将来另立版本 |

目前无需密钥正文。任何后续模型配置通过 P2 环境变量设置；不要让用户把 key 写进聊天、报告或 Git。

## 7. 设计与开发阶段退出检查

- 已交付审查、PRD、架构、评估、实施计划、开发交接和调研记录。
- STATUS 已标 V2 D1/D3 离线开发中，V1 历史完成结论保留；V2 不标记整体完成。
- 新增决策区分「本轮范围已确认」与「产品/实施提案待确认」。
- 已完成离线实现与测试；仍不安装新依赖、不收费调用、不采集未冻结资料、不建云资源、不发布、不 push。

本轮收尾检查：P2 全量 pytest `196 passed`；V1 基线逐字节通过；环境/SQLite 恢复、`compileall`、`pip check` 和 `git diff --check` 通过。没有安装新依赖、创建云资源或发布；D2 仅执行已冻结的 6 页公开 raw GitHub GET，P1/P3 运行资源未修改。D3-live 已完成一份真实报告；D5 批量评估仍须另行授权。


## 最新修正：消费口径与评估批准

最新用户截图与本地新增19次/83698 tokens完全吻合，显示消费0.80元。历史553分预留不是实际费用；无需再索取同一账单。共享总额仍需固定身份和历史结算检查。评估脚本已禁止对非空或缺失 review_findings 自动批准，6项行为测试通过。历史已导出报告不等于审校通过。详见 P2 `evals/results/v2-billing-and-evaluation-correction.md`；本轮无API调用，内容验收未通过。
