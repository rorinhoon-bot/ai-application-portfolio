# P1 V2-D3 有限重试设计

- 文档状态：`accepted；implemented；fake-verified；runtime-verified`
- 版本：`0.2`
- 日期：`2026-08-27`
- 前置基线：V2-D1 运行已激活，V2-D2 `workflow-ready`
- 适用范围：MiMo 回答生成 HTTP 调用；不改变检索、Embedding、Qdrant 或索引发布

## 1. 目标

MiMo 适配器已按本设计实现有界重试。D3 只处理可证明的短暂上游故障，同时把重复调用、潜在重复计费和总时延锁在小范围内：

1. 一个 `AnsweringService.answer()` 仍是一个逻辑请求。
2. 同一逻辑请求最多产生两次物理 `POST`，最多一次重试。
3. 重试使用完全相同的模型、Prompt、证据和请求体；不重新检索、不改写问题、不降低引用合同。
4. 最终错误继续使用现有 `MODEL_TIMEOUT`、`MODEL_NETWORK_ERROR` 或 `MODEL_HTTP_ERROR`，API 状态映射不变。
5. 普通测试和 CI 继续完全离线，不调用真实 MiMo。

## 2. 当前事实与风险

- `MiMoClient.generate()` 默认发一次 `/chat/completions`；只有命中固定白名单才允许第二次。
- 当前固定 `mimo-v2.5`、HTTPS、30 秒单次超时、800 completion tokens、`temperature=0`、非流式、最多一次自动重试。
- `ModelHttpError` 只保留状态码，不保存供应商响应体；`ModelTimeoutError` 和 `ModelNetworkError` 不泄露异常正文。
- 已有真实评估报告把 `automatic_retries` 记录为 `0`；没有可核实的当前 MiMo 单价，不能用 Token 反推费用。
- 网络断开或读取超时可能发生在供应商已接受请求之后。因此“没有收到响应”不等于“没有计费”。D3 不承诺 exactly-once 或费用可逆。

## 3. 不变合同与明确不做

- 不重试 `InvalidModelJsonError`、`ModelOutputError`、`InvalidCitationIdError`。HTTP 200 后的空响应、非法 JSON、Schema 错误和引用错误属于确定性合同失败。
- 不重试 HTTP `400`、`401`、`403`、`404`、`409`、`413`、`422` 或未列入白名单的状态；这些错误需要修正请求、凭据或配置。
- 不对 Embedding、Qdrant、检索、索引写入、快照、API 路由或用户请求做重试。
- 不新增依赖，不下载模型，不写入或删除 Qdrant，不修改 Docker 网络、卷或系统设置。
- 不把 `Retry-After`、上游正文、Key、问题、证据、回答或绝对路径返回给客户端或写入遥测。

## 4. 尝试次数合同

- `MAX_ATTEMPTS = 2`，表示一次初始尝试和一次重试；值是代码固定常量，不由请求参数或环境变量调大。
- 重试预算按一次逻辑 `generate()` 计算，不按进程全局共享。并发请求互不借用预算。
- 非重试错误立即结束。重试错误在第二次失败后立即结束，不再递归或排队。
- 第一次成功后不再发送请求；第二次成功只返回第二次响应。

## 5. 可重试故障白名单

### 5.1 HTTP 响应

仅允许重试：`408`、`429`、`500`、`502`、`503`、`504`。

`ModelHttpError` 仍只保存整数状态码。适配器内部可读取响应头，但只能抽取安全的 `Retry-After` 秒数，不能保存原始 headers 或响应体。

### 5.2 传输异常

只把已确认尚未收到应用响应的连接阶段故障标为可重试：

- `httpx.ConnectError`：可重试。
- `httpx.ConnectTimeout`、`httpx.PoolTimeout`：可重试。
- `httpx.ReadTimeout`、`httpx.WriteTimeout`、`httpx.ReadError`、`httpx.WriteError`：默认不重试，因请求可能已到达供应商或已产生部分响应。
- 取消、`KeyboardInterrupt`、`BaseException` 不捕获、不重试。

实现需要在内部保留 timeout/network 阶段信息，但对外稳定错误代码和安全错误文本保持不变。无法判定阶段时按不可重试处理。

## 6. 等待与总时限

- 默认退避基线为 `250 ms`；D3 只有一次重试，因此不执行第二个退避周期。
- 有效的 `Retry-After` 优先于基线，但只接受非负十进制秒数；HTTP-date、负数、非数字和超长值忽略。
- 等待时间统一裁剪到 `0～2 s`，不使用随机 jitter，保证合同测试可重复。
- 逻辑请求总预算为 `model_timeout_seconds + 2 s`。每次 HTTP 调用使用“配置单次超时”和“剩余总预算”较小值。
- 若剩余总预算不足以完成等待，直接抛出最近一次重试错误；不得为了重试突破总预算。
- 等待期间收到进程取消或线程中断时立即停止，不发送第二次请求。

## 7. 幂等、计费与结果语义

- 重试是 at-least-once 发送，不是 exactly-once。当前供应商对 `Idempotency-Key` 支持未得到核实，D3 不伪造该 header。
- 两次请求的 JSON 请求体必须字节等价；不能因为重试改变 temperature、Prompt、证据顺序或引用 ID。
- 最终成功响应的 Token usage照常写入 `AnswerResult`。之前无响应尝试的 usage 不伪造为 `0`，并标记为 `usage_unknown`/`billing_uncertain`。
- 没有可信价格来源时仍只记录 Token 和尝试数，报告保持 `cost_available=false`；不得声称“重试没有费用”。
- 第二次失败时抛出最近一次错误；若第一次错误为 429、第二次为 503，最终对外仍是现有 `MODEL_HTTP_ERROR` 与 `502 model_upstream_failed`。

## 8. 可观测性扩展

现有信号保持低基数和隐私边界：

- `rag.model.calls` 计数物理 HTTP 尝试，不再把一次逻辑请求误写成一次调用；允许的 `attempt` 值只有 `1`、`2`。
- 新增 `rag.model.retries` Counter，标签只允许 `reason=rate_limit|server_error|connect_error|connect_timeout|pool_timeout`。
- 新增事件 `rag.model.attempt`，允许字段：`attempt`、`max_attempts`、`retry_reason`、`retry_delay_ms`、`billing_uncertain`、`outcome`。
- 最终 `rag.model.completed` 继续记录最终 outcome 和已知 Token；不把缺失 usage 补成零。
- `request_id` 关联同一逻辑请求的两次尝试；不把问题、证据、回答、供应商响应、Key、URL query 或绝对路径加入日志、span 或 label。
- 评估/运行报告至少区分 `logical_request_count`、`physical_attempt_count`、`retry_count`、`usage_complete` 和 `billing_uncertain_attempts`。

## 9. 测试与发布门

实现阶段必须新增离线 fake-provider 合同，不发真实请求：

1. 每个白名单 HTTP 状态最多重试一次；第二次失败不再调用。
2. 非白名单状态、非法 JSON、Schema 错误和引用错误零重试。
3. `ConnectError`、`ConnectTimeout`、`PoolTimeout` 重试；`ReadTimeout`、`WriteTimeout`、取消不重试。
4. `Retry-After` 合法值优先、非法/HTTP-date忽略、超过 2 秒裁剪；基线退避为 250 ms。
5. 注入时钟、sleep 和 POST 序列，验证总预算、请求体字节一致和无真实等待。
6. 失败时错误代码、HTTP 状态、脱敏 Problem Details 和 request ID合同不变。
7. metrics 物理尝试数、retry 数、Token 缺失语义和 `billing_uncertain` 与 fake 序列一致。
8. 敏感夹具在日志、trace attribute、metric label 和异常文本中出现次数为 0。
9. 全量既有离线测试零删除；`compileall`、`pip check`、CI smoke、Git边界和 `git diff --check` 通过。

发布前不运行真实 MiMo。若以后要做真实烟雾或评估，必须另行给出价格来源、最大总预算、调用次数和批准语句。

## 10. 实施、回滚与批准边界

### 10.1 建议实施范围

另行批准后，才允许：

1. 修改 `adapters/mimo.py`、模型错误内部阶段元数据、可观测性计数与相关离线测试。
2. 只使用 Python 标准库和现有 `httpx`，不安装新包。
3. 生成新的代码/测试/文档提交和本地 fake-provider 报告；不改活动索引、Qdrant collection、named volume 或 Docker 配置。
4. 以独立镜像/代码版本运行本地回滚验收；失败时恢复 `cited-rag-api:v2-d1`，不删除旧镜像或运行数据。

### 10.2 不在本批准内

- 真实 MiMo API、任何新增费用、真实用户数据、远程 GitHub Actions、公开部署或云资源。
- 修改 `MODEL_TIMEOUT_SECONDS` 上限、暴露客户端重试参数、加入全局限流或熔断。
- 把潜在重复计费写成确定成本，或把重试成功写成 exactly-once。

建议批准语句：

`批准按 RETRY_DESIGN.md 第10.1节执行 V2-D3`

## 11. 实施与验收结果

- `MiMoClient`已固定`MAX_ATTEMPTS=2`，使用同一请求体、250毫秒默认退避、安全`Retry-After`解析、2秒等待上限和`model_timeout_seconds + 2 s`总预算。
- HTTP仅重试`408/429/500/502/503/504`；传输层仅重试`ConnectError`、`ConnectTimeout`、`PoolTimeout`。读取/写入阶段异常仍单次失败，并保留阶段与费用不确定语义。
- `rag.model.calls`改为物理尝试计数；新增`rag.model.retries`和`rag.model.attempt`。最终Token只记录供应商明确返回值，不补零。
- `data/retry-smoke-report.json`固定五类fake-provider序列；不联网、不真实等待、不调用MiMo、不写Qdrant。CI已加入该smoke。
- 独立镜像`cited-rag-api:v2-d3`完成回环验收：health 200、ready 200、非法answer 422；临时容器随后移除，活动`v2-d1`未切流量。
- Qdrant容器身份、启动时间、活动指针、Manifest哈希和named volume均未变化；完整机器证据见`data/retry-runtime-release-report.json`。
- 未安装新依赖，未发送合法真实问题，真实MiMo调用为0，远程GitHub Actions仍未运行。
