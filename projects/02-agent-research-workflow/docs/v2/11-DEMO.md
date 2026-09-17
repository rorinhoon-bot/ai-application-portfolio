# P2 V2 本地演示

本演示区分三种证据：离线可复现工作流、真实模型单样本闭环、已执行但有验收限制的批量内容评估。

## 路径一：离线双人工门

```powershell
Set-Location '.\projects\02-agent-research-workflow'
$demoRuntime = Join-Path $env:TEMP ('p2-v2-demo-' + [guid]::NewGuid().ToString('N'))
$run = .\.venv\Scripts\python.exe scripts\run_research_v2.py --env-file (Join-Path $demoRuntime 'absent.env') --runtime-root $demoRuntime start | ConvertFrom-Json
.\.venv\Scripts\python.exe scripts\run_research_v2.py --env-file (Join-Path $demoRuntime 'absent.env') --runtime-root $demoRuntime resume --thread-id $run.thread_id --action approve
.\.venv\Scripts\python.exe scripts\run_research_v2.py --env-file (Join-Path $demoRuntime 'absent.env') --runtime-root $demoRuntime resume --thread-id $run.thread_id --action approve
```

预期：第一次停在 `NEEDS_HUMAN`，第二次停在 `REPORT_NEEDS_HUMAN`，最后为 `COMPLETED` 且 artifacts 目录只有一份 Markdown。它使用合成资料和脚本模型，不产生费用。

## 路径二：真实闭环证据

不重放真实调用。阅读 [D3-live 后续记录](../../evals/results/v2-live-followup-2026-09-14.md)：

1. 结构不合格的推荐被确定性代码拒绝；
2. 引用与证据片段不匹配时，模型审校留下 findings 并进入返修门；
3. 审校为空的报告，才由操作者模拟人工批准并导出内容寻址制品。

最终报告没有在版本库保存：它属于本地 runtime，且带有供应商调用产物。版本库仅保留脱敏结果、hash、usage 分类和限制。

## 路径三：恢复与预算边界

```powershell
$env:LANGGRAPH_STRICT_MSGPACK = 'true'
$env:LANGSMITH_TRACING = 'false'
$env:LANGCHAIN_TRACING_V2 = 'false'
.\.venv\Scripts\python.exe -m pytest -q tests\test_v2_graph.py tests\test_v2_budget_reservations.py
```

断言包括：发送后 UNKNOWN 不重发、同一账本的多连接无法突破调用/token/费用上限、崩溃后的预算预留不自动释放、审校 findings 需要人工返修、审批前不能导出。

## 讲解顺序

先展示输入绑定的 snapshot、模型配置 hash 和预算授权；再展示需求门、只读 search、报告门；最后展示失败记录。不要把单样本通过说成整体质量达标。D5 已完成冻结题运行及助手复核；独立人工评分未完成。最新数量与内容限制见 [交付审计](13-DELIVERY-AUDIT.md)。


## 2026-09-15 实测记录

![离线CLI实测记录可视化](../../demo/v2/cli-record.svg)

数据源为`demo/v2/cli-transcript-2026-09-15-v21.json`。脚本模型、无API；依次NEEDS_HUMAN、REPORT_NEEDS_HUMAN、COMPLETED。再次批准返回NO_HUMAN_GATE:COMPLETED，制品仍只有一份。该图为执行记录的可视化，非截图。

## 当前真实样例

`demo/v2/live-conditional-report-20260915.md`来自D5k真实模型，原文件hash见同名JSON，助手在用户委托下复核批准。必须同时阅读 `evals/results/v2-d5k-assistant-approval.json` 的审校分歧及限制。它有前置条件和拟议实验，未执行30次实验，不代表整批内容验收。不要把历史V1合成样例与此结果混写。
