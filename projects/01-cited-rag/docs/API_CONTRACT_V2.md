# Cited RAG V2 API 合同

- 状态：Accepted
- 版本：0.2
- 日期：2026-08-23
- 适用范围：P1 V2-A，只读问答 API

## 1. 目标

把已验收的 `CitedRagService` 暴露为稳定、可测试的 HTTP 边界，供 Web 前端、P2 Agent 和 P3 MCP 服务复用。

首个切片只提供存活检查、就绪检查和非流式问答。它不改变 V1 的检索、拒答、引用和索引一致性语义。

## 2. 边界

### 2.1 本切片包含

- `GET /healthz`
- `GET /readyz`
- `POST /v1/answers`
- 服务端生成请求 ID
- 统一 Problem Details 错误体
- 基于假服务的 API 自动测试

### 2.2 本切片不包含

- 文件上传、抓取任意 URL、索引写入或删除
- Prompt、模型参数、索引路径或 API Key 的客户端透传
- 流式输出、反馈写入、后台任务
- 用户系统、多租户、计费、公开互联网访问
- 公网 CORS、认证和限流

## 3. 通用约定

- 请求和响应编码：UTF-8 JSON。
- 未声明字段：拒绝，避免静默接受错误参数。
- API 版本：路径中的 `/v1`；响应模型另含 `schema_version`。
- 请求 ID：服务端生成 UUID，写入 `X-Request-ID` 响应头；问答成功体和错误体也返回该值。
- 日志：记录请求 ID、路由、状态码、耗时和安全的统计字段；不记录 API Key、完整文档、完整回答或用户原始问题。
- 默认监听：仅回环地址。公开部署必须先补认证、限流、配额和成本保护。
- 默认 CORS：关闭。

## 4. 端点

### 4.1 `GET /healthz`

用途：进程存活检查。

约束：不得加载嵌入模型、连接 Qdrant 或调用大模型。

成功响应：`200 application/json`

```json
{
  "status": "ok",
  "service": "cited-rag-api"
}
```

### 4.2 `GET /readyz`

用途：判断服务是否具备处理问答请求的必要条件。

检查范围：

- 配置可解析；
- 必需语料、manifest 和索引指针存在且相互一致；
- 已配置的本地检索资源可以初始化；
- 不主动调用 MiMo，不产生模型费用。

就绪响应：`200 application/json`

```json
{
  "status": "ready",
  "service": "cited-rag-api",
  "checks": {
    "configuration": "ok",
    "index": "ok",
    "retriever": "ok"
  }
}
```

未就绪：`503 application/problem+json`，使用第 6 节错误格式。对外只暴露安全原因，不返回密钥、绝对路径或堆栈。

### 4.3 `POST /v1/answers`

用途：基于已发布索引回答一个 Python 官方文档问题，并返回可验证引用。

请求体：

```json
{
  "schema_version": "1",
  "question": "Python 3.14 中 asyncio.TaskGroup 如何处理子任务异常？",
  "python_version": "3.14"
}
```

字段约束：

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | string | 是 | 固定为 `"1"` |
| `question` | string | 是 | 去除首尾空白后 1～500 字符 |
| `python_version` | string/null | 否 | `"3.13"`、`"3.14"` 或 `null` |

成功响应：`200 application/json`

```json
{
  "schema_version": "1",
  "request_id": "8f74e77a-fc10-41c8-880f-0f2dca9d3c8d",
  "result": {
    "schema_version": "1",
    "question": "Python 3.14 中 asyncio.TaskGroup 如何处理子任务异常？",
    "status": "answered",
    "answer": "……",
    "citations": [
      {
        "rank": 1,
        "chunk_id": "a29c79b9-b5bf-4a87-b193-b46849f477bf",
        "python_version": "3.14",
        "documentation_release": "3.14.0",
        "section_path": ["Coroutines and Tasks", "Task Groups"],
        "citation_url": "https://docs.python.org/3.14/library/asyncio-task.html#task-groups",
        "excerpt": "……"
      }
    ],
    "index_id": "a5cf14fb-cdfd-407d-8c0a-0d78e25b974f",
    "build_id": "750e287b-bdd9-45e2-b90a-6dfdfe050482",
    "prompt_tokens": 1234,
    "completion_tokens": 180,
    "total_tokens": 1414
  }
}
```

`result` 直接复用 V1 `AnswerResult` 的业务不变量：

- `answered` 必须有至少一条引用；
- `refused` 不得携带引用；
- `conflict` 必须有至少两条引用；
- 引用最多 5 条，且保留稳定来源 URL、版本和章节路径；
- `index_id` 与 `build_id` 对应本次实际使用的已发布索引。

## 5. HTTP 状态映射

| 状态码 | `code` | 场景 |
| --- | --- | --- |
| 200 | — | 请求成功；业务拒答仍是成功结果，`result.status="refused"` |
| 422 | `request_validation_failed` | JSON 或字段校验失败 |
| 503 | `service_not_ready` | 配置、索引或检索器未就绪 |
| 502 | `model_upstream_failed` | 模型上游返回无效响应或不可恢复错误 |
| 504 | `model_upstream_timeout` | 模型调用超时 |
| 500 | `internal_error` | 未预期服务错误 |

模型拒答、低证据拒答和证据冲突是正常业务结果，不映射为 4xx/5xx。

## 6. 错误格式

所有 API 错误使用 `application/problem+json`：

```json
{
  "type": "https://portfolio.local/problems/service-not-ready",
  "title": "Service is not ready",
  "status": 503,
  "detail": "The retrieval index is unavailable.",
  "code": "service_not_ready",
  "request_id": "8f74e77a-fc10-41c8-880f-0f2dca9d3c8d"
}
```

要求：

- `type` 和 `code` 稳定，可供调用方分支处理；
- `detail` 只提供安全且可操作的信息；
- 堆栈、密钥、绝对路径、原始上游响应不得进入错误体；
- 校验错误可附加字段级 `errors`，但不得回显敏感内容。

## 7. 超时与并发

- HTTP 层不覆盖 V1 的模型超时配置；超时由应用配置统一管理。
- 同步核心通过框架线程池调用，避免阻塞事件循环。
- 第一切片先记录并发基线；确定数据后再设置进程数、线程数和并发上限。
- 不在同一进程中执行索引写操作，避免问答与构建竞争资源。

## 8. 测试验收

首个 API 切片至少覆盖：

1. `/healthz` 不触发重资源初始化。
2. `/readyz` 的 ready 与 503 分支。
3. `/v1/answers` 的 answered、refused、conflict 映射。
4. 未声明字段、空问题、超长问题和非法 Python 版本返回 422。
5. 已知业务异常映射为稳定 Problem Details。
6. 未知异常不泄露内部细节。
7. 成功和失败响应均有合法 `X-Request-ID`。
8. 测试使用注入的假服务，不访问网络、不调用真实模型、不依赖真实 Qdrant。

## 9. 后续兼容扩展

以下端点只预留，不属于当前实现：

- `POST /v1/answers/stream`：SSE 流式事件。
- `POST /v1/feedback`：显式反馈与问题追踪。
- `/v1/admin/ingestion-jobs`：受保护的异步摄取任务。

增加这些端点前，必须分别补充鉴权、限流、幂等、持久化和失败恢复设计。

## 10. V2-A 实现与验证结果

- `src/cited_rag/api_models.py`：严格请求、成功包络、健康/就绪和 Problem Details 模型。
- `src/cited_rag/api.py`：应用工厂、懒加载、服务端请求 ID、中间件、路由与脱敏异常映射。
- `CitedRagService.check_ready()` 只调用检索就绪检查；Qdrant 检查不执行 Embedding，也不调用 MiMo。
- API 测试使用现有 `httpx.ASGITransport` 和假服务，不安装额外测试客户端，不访问外部网络。
- 29 项 API 合同测试通过；3 项服务/检索就绪测试通过；项目完整 252 项离线测试通过。

真实本地 Uvicorn 冒烟：

| 请求 | 结果 | 说明 |
| --- | --- | --- |
| `GET /healthz` | 200 | 未初始化业务应用 |
| `GET /readyz` | 503 | V2 独立工作树未复制 Git 忽略的 `.env`、模型和索引，正确安全失败 |
| 非法 `POST /v1/answers` | 422 | 返回 `application/problem+json` 与服务端请求 ID |
| `GET /openapi.json` | 200 | 只列出三个业务端点 |
| 跨域预检 | 405 | 无 `Access-Control-Allow-Origin`，CORS 默认关闭 |

该冒烟没有调用 MiMo、没有加载远程资源、没有启动 Docker，也没有公开监听。
