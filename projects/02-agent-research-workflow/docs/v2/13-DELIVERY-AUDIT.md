# P2 V2 交付审计与剩余任务

更新：2026-09-16。此文件为最新接手入口，优先于历史阶段记录。状态：`in_progress / content-acceptance-not-passed`。工程核心可运行，尚不满足完整作品验收；不发布、不push、不操作P1/P3资源。

## 基线与路径

- 仓库：`.`
- P2：`.\projects\02-agent-research-workflow`
- 分支：`codex/p2-langgraph-v2`；HEAD：`dcb164e95059b060ffd6aebbaa093a7626177614`。
- 已有大量未提交文件及其他项目工作，均保留；没有暂存、commit、push或切换分支。
- 设计入口：`docs/v2/README.md`；PRD/架构/评估/计划分别为02、03、04、05号文档。

进程恢复增量：[14-PROCESS-RECOVERY.md](14-PROCESS-RECOVERY.md)，新增recover入口、三个真实子进程退出窗口、旧async兼容及双人工门保护验证；未宣称完整故障矩阵。

## 当前最终结论

本轮全部工程交付与六题验证已完成，**内容验收未通过，P2整体不能标completed**。最新逐项结论、费用和后续方向见[18号结论](18-VALIDATION-CLOSEOUT.md)，完整机器证据为 `evals/results/v2-final-regression-complete-20260916.json`。此前部分结果与旧制品均保留。

- 全量248项测试通过；V1基线、compileall、pip check、新镜像独立venv复现及最新增量测试通过。
- 显式状态图、双审批、真实模型/固定资料、工具边界、UNKNOWN、同步checkpoint、真实子进程恢复、预算预留/核销/续期、幂等导出、CLI与学习/演示材料均已交付。
- D5l六题均生成并复核，18次成功API；2份助手带备注批准、4份拒绝。41/41引用链有效、6/6有下一步条目，仍存在事实颠倒、引用遗漏和错误实验判据。条件建议交付1/3，未达80%门槛。
- 助手按用户委托复核，不算独立人类评分；模型审校本身的误报/漏报保留，不宣称已证明其收益。

## 当前预算与授权

用户在方案说明后同意继续剩余任务，已备份并追加截至2026-09-16 23:59的续期，只完成剩余两题/最多6次。原授权文件及历史费用、调用计数未改。无需再询问同一续期。

固定授权 `.runtime/p2-budget/authorization.json`；总库 `.runtime/p2-budget/total.sqlite3`。最新用户实际1.44元/156次在D5l之前；D5l其后18次估算40分，实际供应商增量未知。总账本有效占用441/500分；100条调用预留已用满（含历史占位），停止新增收费调用，不擅自改上限或清零。价格卡估算、保守预留与实际账单分别披露。

## 后续接手边界

本轮没有剩余待跑题目。未来质量改进应先处理事实/推断/建议的分层、caveat引用与审校结构，再设计小批次验证；不是继续原样付费重试。18号文档列出未实现的候选改进，不伪装为已完成。原gold不改，已参与调试的题只能作回归；独立评价与学生解释仍需真实证据。

用户已授权的产品、CLI、资料、Flash和累计5元继续有效；公开发布、push、云资源、扩大来源未授权。不能为了把状态改completed而降低质量门槛、回填固定答案或隐去失败。

## 验证命令

在P2目录运行，普通测试默认断网：

```powershell
$env:LANGGRAPH_STRICT_MSGPACK='true'
$env:LANGSMITH_TRACING='false'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_workflow_evaluation.py --check
.\.venv\Scripts\python.exe -m compileall -q src scripts
.\.venv\Scripts\python.exe -m pip check
```

离线演示命令见 `11-DEMO.md`，本次真实执行摘要在 `demo/v2/cli-transcript-2026-09-15-v21.json`。两次批准完成，第三次重复批准返回 `NO_HUMAN_GATE:COMPLETED`，仍只有一个制品。密钥位置仍是P2根目录`.env`的`DEEPSEEK_API_KEY`；不要打印内容，默认环境变量优先。

## 学习参与

本次实现与复核由助手完成。可独立练习：解释为什么“引用存在”不等于“结论正确”；找出checkpoint与外部调用之间可能重复计费的窗口；解释为什么审批不是登录鉴权；给一份有限简报写下一步核验建议。答案与独立讲解尚未验证。

最新剩余执行准备见 [16-NEXT-CONTENT-GATE.md](16-NEXT-CONTENT-GATE.md)：33条回执只读核对已完成，等待后台金额/次数核对，未启动下一收费批次。
