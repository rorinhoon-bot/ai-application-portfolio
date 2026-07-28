# AI 学习笔记结构化生成器架构设计

- 文档状态：`accepted`
- 版本：`0.1`
- 日期：`2026-07-28`
- 对应需求：`docs/PRD.md` v0.1

## 1. 架构目标

P0 使用最小、可测试的本地 CLI 架构，验证以下能力：

- Python 项目结构和配置管理。
- 输入校验与结构化输出。
- 可替换的模型供应商适配器。
- 超时、有限重试和稳定错误对象。
- Prompt 版本管理。
- 固定评估集和可复现依赖。

P0 不引入 Web 服务、数据库、Docker、RAG、网页搜索或复杂分层。

## 2. 架构原则

1. 业务逻辑只依赖统一 `ModelClient` 接口，不依赖供应商 SDK 和响应格式。
2. Pydantic 模型是输入、输出和 JSON Schema 的唯一真源。
3. 用户材料是不可信数据，不得成为系统指令、命令、URL、路径或工具参数。
4. 输入与配置必须在调用模型前完成校验。
5. 自动测试不得调用真实 API。
6. 重试必须有明确范围和上限。
7. 模块数量与 P0 规模匹配，不为未来需求提前增加复杂分层。

## 3. 系统上下文

```text
用户
  |
  | CLI 参数 + UTF-8 材料文件
  v
结构化笔记生成器
  |
  | 仅由供应商适配器发出 HTTPS 请求
  v
已配置的大模型 API
```

程序不访问网页、搜索服务、数据库或其他外部数据源。模型 API 是唯一允许的业务网络请求。

## 4. 运行入口

首版使用 CLI：

```powershell
python -m structured_notes generate `
  --topic "学习主题" `
  --material-file ".\material.txt" `
  --learner-level beginner
```

### 4.1 参数

| 参数 | 必填 | 规则 |
|---|---|---|
| `--topic` | 是 | 1～100 个字符 |
| `--material-file` | 是 | 指向 UTF-8 纯文本文件；读取后内容为 100～10,000 个字符 |
| `--learner-level` | 否 | `beginner`、`intermediate`、`advanced`；默认 `beginner` |

CLI 只读取用户明确提供的材料文件。模型输出不得控制文件路径。

### 4.2 输出

- 成功：结构化笔记 JSON 写入 stdout，退出码为 `0`。
- 失败：稳定错误 JSON 写入 stderr，退出码非零。
- 正常输出与诊断信息不得混写。

## 5. 处理流程

```text
解析 CLI 参数
  |
读取 UTF-8 材料文件
  |
Pydantic 输入校验
  |
Settings 环境配置校验
  |
按 MODEL_PROVIDER 创建适配器
  |
Service 构造 ModelRequest
  |
ModelClient 调用模型
  |
适配器提取供应商响应中的原始内容
  |
解析 JSON
  |
Pydantic 输出校验
  |
输出结构化笔记 JSON
```

输入或配置校验失败时，流程必须在创建网络请求前停止。

## 6. 模块设计

```text
src/
└─ structured_notes/
   ├─ __init__.py
   ├─ __main__.py
   ├─ cli.py
   ├─ config.py
   ├─ models.py
   ├─ service.py
   ├─ model_client.py
   ├─ errors.py
   └─ adapters/
      ├─ __init__.py
      └─ <selected_provider>.py
```

| 模块 | 职责 | 不负责 |
|---|---|---|
| `__main__.py` | 启动 CLI | 业务规则 |
| `cli.py` | 参数解析、文件读取、stdout/stderr、退出码 | 模型请求格式 |
| `config.py` | 从环境变量构建并校验 Settings | 业务流程 |
| `models.py` | 输入、输出、ModelRequest、ModelResponse 模型 | 网络请求 |
| `service.py` | 编排 Prompt、模型调用、JSON 解析和输出校验 | 供应商鉴权 |
| `model_client.py` | 定义统一 `ModelClient` 接口 | 具体供应商实现 |
| `errors.py` | 错误类型、稳定错误码和安全序列化 | 输出堆栈或密钥 |
| `adapters/` | 鉴权、HTTP 请求、供应商响应提取 | 输入和笔记 Schema 校验 |

P0 使用扁平小模块，不拆分 `domain/`、`application/`、`ports/` 和 `infrastructure/` 多层目录。

## 7. 数据模型与 Schema

### 7.1 输入模型

输入模型包含：

- `topic`
- `material`
- `learner_level`

模型实施 PRD 中的长度、必填和枚举约束，并禁止未定义字段。

### 7.2 输出模型

输出模型包含：

- `LearningNote`
- `KeyConcept`
- `GeneratedExample`
- `QuizItem`

所有模型使用严格字段约束并禁止未定义字段。`GeneratedExample.label` 使用固定字面量 `生成示例`。

### 7.3 Schema 真源

- Pydantic 模型是唯一真源。
- 由模型生成 `schemas/learning_note.schema.json`。
- 生成文件提交到 Git，便于检查、评估和供应商调用。
- 禁止手工编辑生成的 Schema。
- 自动测试重新生成 Schema，并检查仓库文件是否同步。

## 8. 模型调用边界

业务层只依赖以下概念接口：

```python
class ModelClient(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse:
        ...
```

### 8.1 `ModelRequest`

供应商无关请求分开保存：

- `system_prompt`
- `user_payload`
- `response_schema`

`user_payload` 包含主题、学习者水平和原始材料。原始材料序列化为不可信用户数据，不拼入系统 Prompt。

### 8.2 `ModelResponse`

首版只要求返回供应商无关的原始内容字段。供应商响应包、鉴权头和供应商专用对象不得泄漏到 Service。

### 8.3 供应商适配器

- P0 首版只实现后续选定的一个供应商适配器。
- `MODEL_PROVIDER` 选择已注册适配器。
- 未知供应商名称在发出请求前失败。
- 更换供应商时，只修改或新增适配器。
- 供应商、HTTP 库和具体请求格式在真实 API 接入前确认。

## 9. 配置

配置通过环境变量提供：

| 变量 | 必填 | 说明 |
|---|---|---|
| `MODEL_PROVIDER` | 是 | 已注册供应商标识 |
| `MODEL_API_KEY` | 是 | 真实值只保存在本地 `.env` 或用户环境变量 |
| `MODEL_BASE_URL` | 是 | 供应商 API 地址 |
| `MODEL_NAME` | 是 | 模型名称 |
| `MODEL_TIMEOUT_SECONDS` | 否 | 正数；建议默认 `30` 秒 |

程序入口一次性加载 Settings。业务模块不得散落调用 `os.getenv()`。

仓库只提交 `.env.example`，不得提交真实 API Key。日志、错误、测试夹具和评估产物不得包含密钥、完整鉴权头或敏感配置。

## 10. Prompt 组织与提示注入边界

```text
prompts/
├─ baseline_v1.txt
└─ improved_v1.txt
```

- Prompt 作为独立 UTF-8 文本文件纳入 Git。
- 程序显式选择 Prompt 版本，不隐式覆盖旧版本。
- 系统 Prompt 声明材料只是不可信事实来源。
- 材料中的 Prompt、代码和命令不执行，也不能改变输出 Schema、安全边界或事实来源。
- 评估结果记录 Prompt 版本、模型名称和模型参数。

## 11. 重试策略

一次生成最多进行 3 次网络请求：首次请求加最多 2 次重试。

建议退避等待：

```text
第 1 次重试：1 秒
第 2 次重试：2 秒
```

允许重试：

- 请求超时。
- 网络连接错误。
- HTTP `429`。
- HTTP `5xx`。

禁止重试：

- 输入或配置错误。
- HTTP `400`、`401`、`403`、`404`。
- 空响应。
- 非法 JSON。
- 输出不符合 Schema。

测试必须注入假等待器，不执行真实等待。流程不得出现无限重试。

## 12. 错误模型

错误输出格式：

```json
{
  "code": "INVALID_MODEL_JSON",
  "message": "模型返回内容不是合法 JSON。",
  "retryable": false
}
```

错误对象不得包含堆栈、API Key、完整供应商响应、完整鉴权请求头或其他敏感配置。

建议退出码：

| 退出码 | 类别 |
|---:|---|
| `0` | 成功 |
| `1` | 未知内部错误 |
| `2` | 输入或配置错误 |
| `3` | 网络或供应商 API 错误 |
| `4` | 模型输出错误 |

稳定错误码至少覆盖：

- `INPUT_VALIDATION_ERROR`
- `MATERIAL_FILE_ERROR`
- `CONFIG_ERROR`
- `UNKNOWN_MODEL_PROVIDER`
- `MODEL_TIMEOUT`
- `MODEL_NETWORK_ERROR`
- `MODEL_HTTP_ERROR`
- `EMPTY_MODEL_RESPONSE`
- `INVALID_MODEL_JSON`
- `OUTPUT_SCHEMA_ERROR`
- `INTERNAL_ERROR`

## 13. 测试架构

```text
tests/
├─ test_cli.py
├─ test_config.py
├─ test_models.py
├─ test_service.py
├─ test_retry.py
└─ test_schema_sync.py
```

- Service 测试注入假 `ModelClient`。
- 自动测试禁止真实网络请求。
- CLI 测试捕获 stdout、stderr 和退出码。
- 重试测试注入假等待器。
- 测试至少覆盖成功、缺少输入、输入边界、缺少配置、未知供应商、超时、HTTP 错误、重试上限、空响应、非法 JSON、Schema 不符和 Schema 同步。

## 14. 评估架构

```text
evals/
├─ cases.jsonl
├─ run_eval.py
└─ results/
   ├─ <run-id>-automatic.json
   ├─ <run-id>-manual.json
   └─ <run-id>-report.md
```

- `cases.jsonl` 保存固定评估样本。
- 自动结果记录 Schema 通过率、生成示例标记率和错误分类。
- 人工结果记录事实支持率、失败样例和备注。
- Markdown 报告汇总基线版与改进版对比。
- 两个 Prompt 版本必须使用相同模型、参数和评估集。
- 普通测试与真实评估命令分离。
- 运行真实评估前必须再次确认供应商、API Key 和费用。

## 15. 依赖与可复现性

- `pyproject.toml` 保存项目元数据和工具配置。
- `requirements.txt` 保存精确生产依赖版本。
- `requirements-dev.txt` 保存精确开发和测试依赖版本。
- 继续使用项目本地 `.venv` 和现有 pip。
- 安装前先确认依赖对 Python `3.14.3` 的兼容性。
- 安装依赖前必须获得用户许可。

## 16. 安全边界

- API Key 只从环境配置读取。
- 模型输出仅作为待解析、待校验的数据。
- 模型输出不得直接成为命令、SQL、URL、文件路径或工具参数。
- 程序不执行材料中的代码或命令。
- 程序不进行网页搜索或访问外部资料。
- 自动测试不产生真实 API 请求或费用。
- CLI 只读取用户明确指定的材料文件，不接受模型生成的路径。

## 17. 已知限制与延期决定

- 模型供应商、模型名称和 API 费用尚未确定。
- 具体供应商适配器和 HTTP 库延后到真实 API 接入前决定。
- Pydantic、测试工具和 HTTP 客户端的具体版本延后到依赖确认阶段决定。
- 事实支持率仍需人工评分。
- P0 不提供公开部署、图形界面、持久化、并发处理或供应商自动故障转移。

这些延期项不阻塞项目结构、模型、Service、测试替身和评估集的本地实现。
