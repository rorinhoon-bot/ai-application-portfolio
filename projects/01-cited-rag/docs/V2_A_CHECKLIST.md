# P1 V2-A 只读 API 阶段验收

- 日期：`2026-08-23`
- 状态：`passed`
- 范围：FastAPI 服务边界，不含 Docker、Qdrant Server、真实模型调用或公网部署

## 合同

- [x] `GET /healthz` 无业务应用初始化。
- [x] `GET /readyz` 检查本地配置与检索依赖，不调用 MiMo。
- [x] `POST /v1/answers` 复用 `CitedRagService` 和 `AnswerResult`。
- [x] 请求拒绝未知字段、非法版本、首尾空白和超长问题。
- [x] answered、refused、conflict 保持原业务语义。
- [x] 全部错误使用脱敏 `application/problem+json`。
- [x] 服务端请求 ID 同时进入响应头和问答/错误体。

## 安全

- [x] 客户端不能传模型、Prompt、温度、API Key、URL、路径或索引参数。
- [x] 客户端提供的 `X-Request-ID` 不受信任、不复用。
- [x] 未知异常不回显密钥形状字符串、堆栈或领域 reason。
- [x] CORS 默认关闭。
- [x] 启动文档固定监听 `127.0.0.1`。
- [x] 根目录 `start-p1-api.cmd` 固定回环地址并检查独立 `.venv`。
- [x] `start-p1-api.cmd` 已实际启动；health 与最终 OpenAPI 合同通过，随后正常关闭。
- [x] 没有写端点、上传、抓取或索引管理端点。

## 自动验证

- [x] 29 项 API 合同测试通过。
- [x] 3 项服务/检索就绪测试通过。
- [x] 全部 252 项 pytest 离线通过；V1 测试零删除。
- [x] `compileall` 通过。
- [x] `pip check` 通过。
- [x] `git diff --check` 通过。
- [x] `.venv`、`.env`、模型、展开语料和索引仍被 Git 忽略。

## 真实本地 HTTP 冒烟

启动命令：

```powershell
.\.venv\Scripts\python.exe -m uvicorn cited_rag.api:app `
  --app-dir src `
  --host 127.0.0.1 `
  --port 8765 `
  --no-access-log
```

结果：

| 请求 | 状态 | 关键结果 |
| --- | ---: | --- |
| `GET /healthz` | 200 | `application/json`，合法 `X-Request-ID` |
| `GET /readyz` | 503 | 独立工作树缺少 Git 忽略资产，返回脱敏 `service_not_ready` |
| 空问题 `POST /v1/answers` | 422 | 脱敏 `request_validation_failed` |
| `GET /openapi.json` | 200 | 业务路径仅 health、ready、answers |
| 跨域预检 | 405 | 无 `Access-Control-Allow-Origin` |

服务已在验证后正常关闭。该冒烟没有调用 MiMo，没有恢复或下载模型，没有启动 Docker，没有对公网监听。

## 阶段结论

V2-A 达到 `docs/PRD.md` 的 AC-V2-01。项目已从只能本机界面调用，升级为具有稳定 HTTP 合同、运行探针、错误语义和跨项目复用边界的本地知识服务。

下一阶段 V2-B 需要先设计 Qdrant Server、Docker/Compose、持久卷、构建发布和失败回滚；安装或启动前再次审批。
