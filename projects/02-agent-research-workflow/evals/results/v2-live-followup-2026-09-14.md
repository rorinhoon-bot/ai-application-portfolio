# V2 D3-live 后续闭环记录

- 日期：2026-09-14；用户确认模型改用 `deepseek-flash`（DeepSeek V4.1 Flash）并保持 P2 累计人民币 5 元上限。
- 输入：冻结官方快照 `snapshot-1855a50c906058faffe87039`；LangGraph 与 PydanticAI；三个已批准维度；没有读取 V1 gold 或把它送入模型。
- 实际模型：`deepseek-flash`。官方价格页说明旧 `deepseek-v4-flash` 已下线，旧名称会转由 V4.1 Flash 提供服务；本轮直接使用当前模型 ID。
- 费用边界：此前控制台截图显示旧三次请求 `3,611 tokens`、`¥0.01`。本轮本地价格卡按高峰、缓存未命中估算并在发送前持久预留；8 次 follow-up 调用累计预留 `64` 分（`¥0.64`）以内。它是保守上限，不是供应商实际账单；本记录不推断当前账户总费用。

## 运行结果

| run | 模型调用 | 结果 | 证据 |
|---|---:|---|---|
| `run-d3-followup-001` | plan + draft | 被确定性检查拒绝 | `recommendation="conditional"` 不是候选 ID；未执行 review/导出 |
| `run-d3-followup-002` | plan + draft + review | 进入人工返修门 | 审校发现 3 条引用片段与 claim 不精确匹配；未导出 |
| `run-d3-followup-003` | plan + draft + review | `COMPLETED` | 审校无 findings；人工审批**模拟**后导出内容寻址 Markdown `b20c2f…825f3f.md` |

最终报告覆盖 2 个候选 × 3 个维度。它对 LangGraph 状态模型、PydanticAI 恢复/持久执行均标为 `unknown`，结论为 `insufficient_evidence`、不做无条件推荐。此行为符合输入约束，但只是一份真实生成样本，不构成内容质量达标或产品可用性证明。

## 实际验证与限制

- 真实 API 证明：环境变量加载、OpenAI 兼容请求、真实 JSON 响应、provider response ID、usage 解析、受控 search、模型草稿、模型审校、两个人工门、SQLite checkpoint 与幂等导出可连通。
- 人工审批由本次演示的操作者模拟，不是独立最终用户验收。
- 不证明：12 题内容质量门槛、跨进程崩溃恢复、并发、多用户、实时资料、性能、生产部署或供应商实际账单精确性。
- 原始 API 请求、完整响应、checkpoint、价格卡内路径与密钥均不纳入版本化结果文件。
