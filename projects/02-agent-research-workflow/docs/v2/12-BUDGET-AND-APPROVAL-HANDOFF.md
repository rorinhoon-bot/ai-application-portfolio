# 预算结算与审批复核交接

> 2026-09-15更新：本文为初始化时记录；新增D5g/D5h后总占用497分，剩余3分。以 [13-DELIVERY-AUDIT.md](13-DELIVERY-AUDIT.md) 为准。

本记录优先于旧交接中的“等待消费截图”“历史预留超过5元即已消费超支”及“8份回归均已通过审校”等表述。旧报告、checkpoint和账本未改写。

## 本轮交付

- `OperationLedger(single_authorization=True)` 将总账本单授权策略持久化。重开时即便未再次传该标志，改变授权ID也会拒绝；原授权限额不变。
- live `resume` 必须使用项目内固定 `.runtime/p2-budget/authorization.json` 和 `total.sqlite3`；其他路径及未初始化账本在发送前拒绝。普通本地用户仍可编辑程序或删除文件，因此不声称这是操作系统级防篡改机制。
- 总预算500分，先记入150分历史占用（已有价格卡143分、早期观测1分及6分余量），可新增预留350分。截图观测80分作为对账证据，不据此自动释放历史记录或重置授权。授权有效期见JSON；到期不能静默延长。
- 评估脚本仅在明确空 findings 时模拟报告批准；未解决finding、缺字段或失败停止批次。模拟批准仍不能称为独立人工验收。
- 范围检测按句段检查，允许“本次提供的冻结证据……”和明确否定范围扩大的说明；直接整快照断言继续拦截。有限模式不是事实核验器。

## 证据与限制

只读检查 D5e/D5f checkpoint：7份导出中4份保留 `REPORT_SCOPE_CLAIM_INVALID`，3份确实执行审校且无finding；另1个运行无合格草稿。机器证据在 `evals/results/v2-checkpoint-approval-audit.json`。新规则离线检查消除3个原误报，仍保留 `holdout-limited-brief` 的告警。这是离线历史响应回归，不是新的live内容通过证据。

全量测试 `219 passed in 48.11s`，V1固定基线、compileall、pip check通过。测试结果为 `.runtime/p2-budget/offline-regression.xml`。本轮未读取密钥正文、未调用API、未安装、未提交或push。

## 接手顺序

1. 检查固定共享总账本中历史150分记录仍存在，授权身份及有效期一致。不要删除总账本，不要另起新授权避开累计额度。
2. 对未通过有效审校的历史报告完成内容核验；需要新生成时使用独立运行ID并保留历史失败分母，不能重新发送UNKNOWN逻辑请求。
3. live命令同时传批次预算、已核对价格卡和固定共享总额路径。遵守500分包含历史占用的总额；调用前重新核对价格变化，不需要重复申请已经授权的5元。
4. 更新内容评分、失败案例、README和学习证据；独立人工评价未发生就继续标注助手单人复核。

验证命令（P2目录）：

```powershell
$env:LANGGRAPH_STRICT_MSGPACK='true'
$env:LANGSMITH_TRACING='false'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_workflow_evaluation.py --check
```

Git仍为 `codex/p2-langgraph-v2`，基线 `dcb164e95059b060ffd6aebbaa093a7626177614`，工作区有既存未提交工作；不覆盖其他项目。
