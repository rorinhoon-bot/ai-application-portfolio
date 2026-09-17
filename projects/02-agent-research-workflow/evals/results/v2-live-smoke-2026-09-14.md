# V2 D3-live smoke 恢复审查

- 日期：2026-09-14
- 授权：最多 3 次 `deepseek-v4-flash` 请求，人民币上限 5 元。
- 输入：冻结官方快照 `snapshot-1855a50c906058faffe87039`；两个候选、三个维度；不使用 V1 合成金标准。
- 非秘密配置：价格卡 hash `2508a5062ef5b8299766d8d86bbe8eb23499ef2c933502e4be57e072e8fab86a`，模型配置 hash `0c2b25749f01789c2cfb18770c9bce9353f8546256bb1f04037e3c36d0c8eb68`。

## 结果

| 本地 run | 计划节点账本状态 | 脱敏错误码 | 工具/报告/导出 |
|---|---|---|---|
| `run-d3-live-001` | `unknown` | `MODEL_CALL_UNKNOWN` | 0 / 无 / 无 |
| `run-d3-live-002` | `unknown` | `MODEL_RESULT_CONTRACT_INVALID` | 0 / 无 / 无 |
| `run-d3-live-003` | `unknown` | `MODEL_RESULT_CONTRACT_INVALID_response-id` | 0 / 无 / 无 |

第三次确认供应商响应达到适配器，但 response ID 以数字开头，旧合同拒绝了它。之后已把 response ID 改为受限供应商字符集，并让“响应已到达但合同失败”的账本保存已解析 usage；该修正只通过离线 HTTP double 和工作流恢复测试，未再次调用 API。

原始响应、请求鉴权、API key、完整 payload 和 checkpoint 均不进入本文件。run-001/002 发生在 usage 持久化修正前，因此没有可验证 usage；不能从价格卡的 33 分最坏估算推出实际账单，也不能声称本轮实际费用低于 5 元。需要在 DeepSeek 控制台核对本轮三次请求后，才能获得费用证据。

## 结论

本轮只证明了：key 加载不泄露、价格卡/预算绑定、UNKNOWN 停止和账本恢复审查路径工作。它**没有**证明真实计划 JSON、受控工具、报告内容质量、二次人工门或幂等导出成功。下次请求必须获得独立的新预算授权。
