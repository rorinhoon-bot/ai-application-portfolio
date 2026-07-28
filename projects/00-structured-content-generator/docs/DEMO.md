# P0 五分钟演示

本演示使用已保存评估结果，不再次调用真实模型 API，不产生费用。

## 1. 问题（30 秒）

普通大模型可能返回非法 JSON，也可能把自身知识补进用户材料。P0 目标是把学习材料转换成可校验、可测试、可评估的结构化笔记。

## 2. 方案（60 秒）

展示 `README.md` 中的架构图，并说明：

- Pydantic 在网络调用前校验输入。
- `ModelClient` 把业务逻辑和 MiMo HTTP 细节分开。
- Prompt、用户材料和 JSON Schema 分开传递。
- 模型响应必须经过 JSON 解析和 Pydantic 输出校验。
- 暂时性传输错误最多重试 2 次，内容错误不重试。

## 3. 自动测试（45 秒）

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

预期：

```text
90 passed
```

全部测试使用假客户端，不访问真实 API。

## 4. 查看最终评估（60 秒）

```powershell
$result = Get-Content -Raw -Encoding UTF8 `
  .\evals\results\20260728T072321Z-improved_v2-automatic.json |
  ConvertFrom-Json

$result.metrics | ConvertTo-Json
$result.failures | ConvertTo-Json
```

预期重点：

```text
schema_pass_rate = 1.0
failures = []
generated_example_label_rate = null
```

示例指标为 `null`，因为 `improved_v2` 没有生成非 `null` 示例；按 PRD 应解释为 `N/A`，不能说成 `100%`。

## 5. 展示 Prompt 优化证据（60 秒）

打开：

- `evals/results/20260728-comparison-report.md`
- `evals/results/20260728-manual-review.md`
- `evals/results/20260728-improved-v2-manual-review.md`

讲解：

- `improved_v1` Schema 通过率为 `100%`，但事实支持率只有 `52.2%`。
- 原因是模型加入材料外定义、机制、命令、数字和示例。
- `improved_v2` 增加逐项证据检查，默认 `example=null`。
- 相同模型和固定评估集复测后，事实支持率提高到 `97.3%`。

## 6. 限制与下一步（45 秒）

- Schema 正确不等于事实正确，仍需人工评分。
- `improved_v2` 还有 3 个缺失信息遗漏和 1 个覆盖遗漏。
- 默认不生成示例提高安全性，但降低教学丰富度。
- P1 将进入带引用的 RAG，不把 P0 扩展成复杂系统。

## 演示完成标准

- 五分钟内说明问题、架构、测试、评估、改进和限制。
- 不展示 `.env`、API Key、鉴权头或供应商控制台敏感信息。
- 不重新运行真实评估；展示已保存结果即可。
