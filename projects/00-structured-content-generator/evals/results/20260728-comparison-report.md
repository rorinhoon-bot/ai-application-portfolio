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

## 人工指标

`improved_v1` 已完成逐项人工确认：

| 指标 | 结果 | PRD 目标 | 是否通过 |
|---|---:|---:|---|
| 事实支持率 | 52.2%（93/178） | ≥90% | 否 |
| 示例安全率 | 27.3%（6/22） | 不引入材料外事实 | 否 |

主要失败：

- `normal-transformer` 增加线性变换、点积、缩放、Softmax、BERT、GPT 和位置编码等材料外信息。
- `normal-python-venv` 增加激活命令、`requests` 版本和 `pip freeze` 等材料外信息。
- 4 个禁止生成示例的样本仍生成共 6 个示例。
- 其他样本加入状态码、LoRA 机制、API Key 后果、UTF-8 等材料外知识。

Schema 通过不代表事实正确。`improved_v1` 未通过 AC-03 和 AC-04，P0 不能标记完成。

## 下一步

1. 使用确认后的失败模式编写 `improved_v2`。
2. 本地测试 Prompt 注册和关键事实约束。
3. 获得新的费用许可后，使用相同 `mimo-v2.5`、参数和固定评估集运行 `improved_v2`。
4. 对新结果执行相同人工评分，再与 `improved_v1` 比较。
