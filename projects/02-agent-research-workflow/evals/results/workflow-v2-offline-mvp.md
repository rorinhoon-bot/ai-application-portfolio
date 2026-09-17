# P2 V2 离线 MVP 验证记录

- 日期：2026-09-14
- Git 基线：`codex/p2-langgraph-v2` / `dcb164e95059b060ffd6aebbaa093a7626177614`（分支仅本地改名）
- 模式：offline；脚本模型 `scripted-v2`；工作流来源快照：`demo/v2/manifest.json`（合成开发夹具）；D2 真实快照：`data/real-sources/snapshot-1855a50c906058faffe87039/manifest.json`
- 真实模型：未运行；DeepSeek 适配器只完成可替换接口和默认关闭的 HTTPS 客户端
- 外部副作用：无网络请求、无收费、无云资源、无发布

## 已验证

| 项目 | 结果 | 证据 |
|---|---:|---|
| P2 全量测试 | `178 passed` | `.venv\Scripts\python.exe -m pytest -q`，显式关闭 LangSmith tracing |
| V1 固定工作流基线 | `12/12`，逐字节通过 | `scripts\run_workflow_evaluation.py --check` |
| V2 需求人工门 | 通过 | `tests/test_v2_graph.py`、`test_v2_cli.py` |
| V2 报告人工门 | 通过 | `tests/test_v2_graph.py`、`test_v2_cli.py` |
| V2 证据矩阵 | 2 候选 × 3 维度，6 单元格 | `test_full_v2_offline_flow_has_two_human_gates_and_one_artifact` |
| V2 调用账本 | 规划/草稿/审校 3 条成功记录可重放 | `tests/test_v2_ledger.py`、端到端图测试 |
| UNKNOWN 模型请求 | 进入 `RECOVERY_REVIEW`，不继续工具，不自动重发 | `test_model_transport_unknown_pauses_without_follow_on_tool_execution` |
| 导出幂等 | 同一运行只产生 1 个内容寻址 Markdown | 图测试、CLI smoke test |
| D2 机器清单检查 | 冻结清单 6 页通过离线校验；未冻结计划仍拒绝 collect | `scripts/collect_sources_v2.py check`；`SOURCE_PLAN_NOT_FROZEN` 闸门测试 |
| D2 采集器安全边界 | HTTP mock、默认 DNS 私网目标拒绝、固定快照采集通过 | `tests/test_v2_source_collector.py`；实际请求仅发往 allowlist raw GitHub |
| D2 固定官方快照 | 6 个 commit 固定原始文件，`163080` bytes；真实章节 search/read 通过 | `data/real-sources/snapshot-1855a50c906058faffe87039/manifest.json`；本轮无收费 |

D2 覆盖审查见 [`docs/v2/09-SOURCE-COVERAGE.md`](../../docs/v2/09-SOURCE-COVERAGE.md)：两个候选×三个维度的六个单元均有可读取章节。该结果只证明来源定位与快照完整性，不计入内容质量分数。

## 尚未证明

- 合成 `demo/v2/` 只证明状态、引用身份、失败停止和导出边界；不证明 LangGraph/PydanticAI 的现实能力、版本事实或报告语义正确性。
- 没有真实 API 请求，因此没有 DeepSeek token、费用、延迟、限流或响应质量证据。
- 已有正式官方资料快照，但尚未运行真实模型；因此 V2 内容质量评估、引用语义支持率和推荐完成率仍为 `N/A`，不能沿用 V1 的 `4.8/5`。
- 当前 `RECOVERY_REVIEW` 只安全停机；D4 才实现带账本查对后的人工继续/取消路径和跨进程故障注入。

## 复现实验

```powershell
Set-Location -LiteralPath '.\projects\02-agent-research-workflow'
$env:LANGGRAPH_STRICT_MSGPACK = 'true'
$env:LANGSMITH_TRACING = 'false'
$env:LANGCHAIN_TRACING_V2 = 'false'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_workflow_evaluation.py --check
```

CLI 最小演示：

```powershell
$r = Join-Path $env:TEMP ('p2-v2-' + [guid]::NewGuid().ToString('N'))
$s = .\.venv\Scripts\python.exe scripts\run_research_v2.py --runtime-root $r start | ConvertFrom-Json
\.venv\Scripts\python.exe scripts\run_research_v2.py --runtime-root $r resume --thread-id $s.thread_id --action approve
\.venv\Scripts\python.exe scripts\run_research_v2.py --runtime-root $r resume --thread-id $s.thread_id --action approve
```
