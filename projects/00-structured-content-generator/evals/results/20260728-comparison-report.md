# MiMo Prompt 固定评估对比

- 日期：2026-07-28
- 模型：`mimo-v2.5`
- 固定评估集：`evals/cases.jsonl`
- 每个 Prompt 使用相同的 10 条样本
- 联网搜索：关闭

## 自动指标

| 指标 | `baseline_v1` | `improved_v1` | 变化 |
|---|---:|---:|---:|
| Schema 通过率 | 90% | 100% | +10 个百分点 |
| 生成示例标记率 | 100% | 100% | 0 |
| 失败样本数 | 1 | 0 | -1 |

基线失败样本：

- `normal-transformer`
- 错误分类：`INVALID_MODEL_JSON`

改进版达到 PRD 的 Schema 通过率和生成示例标记率目标。

## 尚未通过的验收项

事实支持率仍需人工评分，不能由 Schema 通过率代替。

初步抽查发现部分改进版输出加入了材料未提供的知识。例如：

- `normal-transformer` 增加了线性变换、点积、缩放、Softmax、BERT、GPT 和位置编码等材料外信息。
- `normal-python-venv` 增加了具体激活命令、`requests` 版本和 `pip freeze` 等材料外信息。
- 其他样本也需要逐项检查概念解释、常见错误、复习点、参考答案和生成示例。

因此当前不能声称事实支持率达到 90%，也不能把 P0 标记为完成。

## 下一步

1. 使用 `20260728-manual-review.md` 对 `improved_v1` 的 10 条输出进行人工评分。
2. 统计事实支持率、禁止事实出现情况、`missing_information` 行为和示例安全性。
3. 若事实支持率低于 90%，修改 Prompt 并使用相同模型和评估集重新运行。
