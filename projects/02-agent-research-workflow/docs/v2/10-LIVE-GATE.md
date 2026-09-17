# D3-live 外部闸门

- 状态：`D3-live-completed; D5-evaluation-not-approved`
- 日期：2026-09-14
- 当前模型：`deepseek-flash`（V4.1 Flash）
- 当前结论：早期三次 smoke 的恢复审查已完成；用户随后确认累计 5 元上限并采用当前模型 ID。一份真实工作流已审校、人工审批模拟并导出；详细结果见 [`v2-live-followup-2026-09-14.md`](../../evals/results/v2-live-followup-2026-09-14.md)。D5 批量内容评估仍未授权。

## 已核对的公开信息

- [Models & Pricing](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) 当前列出 `deepseek-flash`（V4.1 Flash），OpenAI 兼容 base URL 为 `https://api.deepseek.com`，并列出 JSON Output、Tool Calls；旧 `deepseek-v4-flash` 已下线并路由到当前 Flash。
- [Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/) 的 usage 至少记录 `prompt_tokens`、`completion_tokens`；reasoning 明细若返回则记录。
- 当前高峰价格为每 1M token：缓存命中输入 ¥0.04、缓存未命中输入 ¥2、输出 ¥8；价格可变，价格卡仍只做保守预算边界。

## 已冻结的本轮设置

1. 价格卡：缓存未命中输入 440 分/1M、输出 1320 分/1M；以价格页 2026-09-14 的高峰 USD 价格和 `10 CNY/USD` 安全上限换算。所有输入按未命中计费；reasoning token 包含在 completion token。
2. 预算：`500` 分、最多 3 次、累计输入 `48000`、输出 `9000`；最坏 token 上限估算 33 分。
3. `.env`：已用无网络 `live-preflight` 确认存在 key；不记录 key。
4. 资料：使用 D2 固定快照 `snapshot-1855a50c906058faffe87039`，不是 `demo/v2/` 合成资料。

## 本轮结果

| run | 脱敏结果 | 后续行为 |
|---|---|---|
| run-001 | 传输/供应商状态不可判定 | 进入 `RECOVERY_REVIEW`；不重试 |
| run-002 | `MODEL_RESULT_CONTRACT_INVALID` | 进入 `RECOVERY_REVIEW`；不执行工具 |
| run-003 | `MODEL_RESULT_CONTRACT_INVALID_response-id` | 定位旧 response-ID 合同不允许数字开头 |

三次均不保存原始响应，均未执行工具、草稿、审校或导出。第三次之后已修正 response-ID 合同，并让合同失败时持久保存已返回的 usage；该修正仅有离线验证。历史 run-001/002 没有 usage，不能反向推断实际费用。

用下列命令生成请求所需的非秘密配置 hash；endpoint 或输出上限变化后必须重新生成并重新批准：

```powershell
.\.venv\Scripts\python.exe scripts\run_research_v2.py --mode live model-config
```

## Smoke 顺序

每次运行都用独立本地 runtime 目录和账本：

1. `start` 只校验需求和预算，不发送模型请求。
2. 第一次人工批准后，执行一次计划/工具/草稿/审校链；所有工具仍只读 D2 快照。
3. 第二次人工批准后才生成内容寻址制品；再次执行相同批准版本必须命中账本/导出幂等边界。
4. 记录脱敏的 response ID、usage、cost status、错误码、主动耗时和报告 hash；原始响应和密钥不入 Git。
5. 任何 usage/费用不完整、请求超时或供应商能力不符合合同，都停止在 `RECOVERY_REVIEW`，不自动追加请求。

## 放行命令模板

下面只是批准后的执行模板；没有批次预算、共享总额预算、价格卡或环境变量时不会运行。总额预算必须填写供应商账单对账后的剩余额度，不能重新写为完整 ¥5：

```powershell
$env:DEEPSEEK_API_KEY = '<set outside Git and chat>'
.\.venv\Scripts\python.exe scripts\run_research_v2.py `
  --mode live `
  --runtime-root "$env:TEMP\\p2-v2-live-<unique>" `
  --sources-root 'data\\real-sources\\snapshot-1855a50c906058faffe87039' `
  --manifest 'data\\real-sources\\snapshot-1855a50c906058faffe87039\\manifest.json' `
  --budget-file '<approved-budget-json>' `
  --total-budget-file '<approved-remaining-p2-total-budget-json>' `
  --total-budget-ledger "$env:TEMP\\p2-v2-total-budget.sqlite3" `
  --price-card-file '<reviewed-price-card-json>' `
  start --request '<request-bound-to-real-snapshot.json>'
```

实际执行前必须先用 `status`/人工门确认；命令模板本身不构成授权。本轮真实调用已冻结。下一次真实调用前，先在供应商控制台核对当前费用，并以对账后的剩余额度创建共享总额预算；D5 内容验收仍需独立人工评分。
