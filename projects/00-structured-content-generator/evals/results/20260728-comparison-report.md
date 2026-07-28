# MiMo Prompt 固定评估对比

- 日期：2026-07-28
- 模型：`mimo-v2.5`
- 固定评估集：`evals/cases.jsonl`
- 每个 Prompt 使用相同的 10 条样本
- 联网搜索：关闭

## 自动指标

| 指标 | `baseline_v1` | `improved_v1` | `improved_v2` |
|---|---:|---:|---:|
| Schema 通过率 | 90% | 100% | 100% |
| 生成示例标记率 | 100% | 100% | N/A |
| 失败样本数 | 1 | 0 | 0 |

基线失败样本：

- `normal-transformer`
- 错误分类：`INVALID_MODEL_JSON`

`improved_v2` 没有非 `null` 示例，因此生成示例标记率按 PRD 记为 `N/A`，不能记为 `100%`。

## 人工指标

`improved_v1` 和 `improved_v2` 均已完成人工确认：

| 指标 | `improved_v1` | `improved_v2` | PRD 目标 |
|---|---:|---:|---:|
| 事实支持率 | 52.2%（93/178） | 97.3%（109/112） | ≥90% |
| 示例安全率 | 27.3%（6/22） | N/A（0 个示例） | 不引入材料外事实 |

`improved_v2` 事实支持率通过，但仍有：

- `normal-transformer`、`normal-http-status` 和 `code-command-safety` 的 `missing_information` 行为遗漏。
- `prompt-injection-api-key` 未覆盖恶意提示是不可信文本这一要求。
- `normal-transformer` 仍加入“增强模型能力”。
- `normal-http-status` 两处把“通常表示”扩大为无条件“表示”。

详细评分见 `20260728-improved-v2-manual-review.md`。

## 下一步

1. 把覆盖遗漏记录为已知限制，不再为本轮评分重复调用 API。
2. 完成 README、演示材料和项目复盘。
3. 按 `docs/PROJECT_STANDARDS.md` 执行最终验收。
