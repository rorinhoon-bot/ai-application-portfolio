# P0：AI 学习笔记结构化生成器

工程热身项目。程序读取学习主题、UTF-8 材料文件和学习者水平，调用可配置模型，并将结果校验为固定结构的学习笔记。

## 问题与用户

- 目标用户：需要把短学习材料整理成固定结构笔记的自学者，以及需要验证 AI 应用工程基础的开发者。
- 输入：学习主题、100～10,000 字符的 UTF-8 材料、学习者水平。
- 输出：通过 Pydantic 和 JSON Schema 校验的学习笔记 JSON。
- 解决问题：把不稳定的模型文本输出变成可校验、可测试、可评估的结构化结果。
- 不处理：网页搜索、RAG、数据库、图形界面、公开部署、文件写入、命令执行和事实外部核验。

## 当前状态

P0 核心目标已实现：

- Pydantic 输入、输出和错误模型。
- 自动生成并同步检查 JSON Schema。
- 环境变量配置和 API Key 隐藏。
- 供应商无关 `ModelClient` 协议。
- JSON 解析、输出校验和有限重试。
- MiMo `mimo-v2.5` OpenAI 兼容适配器。
- CLI、固定评估集和自动指标计算。
- 全部自动测试使用假客户端，不访问真实模型 API。
- MiMo 冒烟、3 个 Prompt 版本的真实固定评估和人工事实评分。
- `improved_v2` Schema 通过率 `100%`，事实支持率 `97.3%`。

## 架构

```text
CLI
 |
 | 主题 + UTF-8 材料 + 学习者水平
 v
Pydantic 输入校验
 |
 v
Service + 版本化 Prompt
 |
 v
ModelClient 协议
 |
 v
MiMo HTTP 适配器
 |
 v
JSON 解析 + Pydantic 输出校验
 |
 v
stdout 学习笔记 JSON
```

职责边界：

- `cli.py`：参数、材料文件读取、stdout、stderr 和退出码。
- `config.py`：集中读取并校验环境变量。
- `service.py`：生成流程、JSON 解析、输出校验和有限重试。
- `model_client.py`：供应商无关接口。
- `adapters/mimo.py`：鉴权、HTTP 请求和供应商响应提取。
- `models.py`：输入、输出和 JSON Schema 唯一真源。

详细设计见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

## 环境要求

- Windows PowerShell
- CPython `3.14.3`
- 项目本地 `.venv`

## 安装

在本目录运行：

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install --no-build-isolation -e .
```

依赖均使用精确版本。项目不需要 Docker。

## 配置

复制 `.env.example` 为 `.env`。保留已确认的 MiMo 配置，只填写本地 API Key：

```text
MODEL_PROVIDER=mimo
MODEL_API_KEY=
MODEL_BASE_URL=https://api.xiaomimimo.com/v1
MODEL_NAME=mimo-v2.5
MODEL_TIMEOUT_SECONDS=30
```

规则：

- `.env` 已被 Git 忽略。
- 不要把真实 API Key 写入源码、测试、日志或截图。
- `MODEL_BASE_URL` 必须使用 HTTPS。
- MiMo API Key 只保存在本地 `.env`，不要通过聊天发送。

## 生成 JSON Schema

```powershell
.\.venv\Scripts\python.exe scripts\generate_schema.py
```

生成文件：

```text
schemas/learning_note.schema.json
```

Pydantic 模型是唯一真源，不手工编辑生成文件。

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

测试覆盖：

- 输入长度、枚举、默认值、空白和额外字段。
- 嵌套输出、固定示例标签和 Schema 同步。
- 缺少配置和 HTTPS 限制。
- Prompt 与不可信材料隔离。
- MiMo 请求地址、请求头、JSON 模式和响应提取。
- 空响应、非法 JSON 和 Schema 不符。
- 超时、网络、HTTP 错误及最多两次重试。
- CLI stdout、stderr、退出码和失败前停止。
- 固定评估集格式、场景分布和指标计算。

测试不产生网络请求或费用。

## CLI

本地配置 MiMo API Key 后使用：

```powershell
.\.venv\Scripts\python.exe -m structured_notes generate `
  --topic "Transformer" `
  --material-file ".\material.txt" `
  --learner-level beginner `
  --prompt-version improved_v2
```

成功时，学习笔记 JSON 写入 stdout，退出码为 `0`。失败时，稳定错误 JSON 写入 stderr，退出码非零。

## 固定评估

评估集位于 `evals/cases.jsonl`，包含：

- 4 条正常材料。
- 2 条信息不足材料。
- 1 条矛盾材料。
- 1 条提示注入材料。
- 1 条代码或命令文本。
- 1 条接近输入下界的材料。

运行真实评估会产生费用，必须先确认供应商、密钥和预算：

```powershell
.\.venv\Scripts\python.exe evals\run_eval.py --prompt-version baseline_v1
.\.venv\Scripts\python.exe evals\run_eval.py --prompt-version improved_v1
.\.venv\Scripts\python.exe evals\run_eval.py --prompt-version improved_v2
```

所有版本必须使用相同模型、参数和评估集。

当前真实测试费用上限为人民币 `5` 元。执行顺序固定为：先运行 1 次冒烟调用，确认成功和费用后，再运行固定评估。程序不会把“5 元”当作平台账户的硬限额；账户余额和平台消费上限仍需用户在 MiMo 控制台管理。

### 已确认结果

| Prompt | Schema 通过率 | 事实支持率 | 示例安全率 |
|---|---:|---:|---:|
| `baseline_v1` | 90% | 未评分 | 未评分 |
| `improved_v1` | 100% | 52.2% | 27.3% |
| `improved_v2` | 100% | 97.3% | N/A（0 个示例） |

`improved_v2` 达到 PRD 的 `≥90%` 事实支持率目标。详细结果见 [`evals/results/20260728-comparison-report.md`](evals/results/20260728-comparison-report.md)。

## 短演示

五分钟演示步骤、讲解稿和无需再次调用 API 的结果查看命令见 [`docs/DEMO.md`](docs/DEMO.md)。

## 面试学习

项目原理、技术栈、核心代码、Prompt 迭代、测试评估、常见面试问题和自测题见 [`LLH_Study.md`](LLH_Study.md)。

## 安全边界

- 材料是唯一事实来源，也是不可信文本。
- 不执行材料中的代码或命令。
- 不进行网页搜索或访问外部资料。
- 模型输出只作为待解析、待校验的数据。
- 模型输出不能成为命令、URL、文件路径或工具参数。
- 输入或配置无效时，在创建模型请求前失败。
- CLI 只读取用户明确传入的本地材料路径；模型输出不能控制文件路径。

## 数据、隐私与许可

- 固定评估集为项目自编的合成学习材料，不含个人数据或第三方数据集。
- 真实生成会把用户提供的材料发送到已配置的 MiMo API；不要输入个人隐私、公司机密或其他敏感内容。
- API 数据处理还受模型供应商条款约束，项目不提供供应商侧的数据保留保证。
- 仓库当前没有单独的开源许可证文件；代码和文档不能被视为已授予公开复用许可。

## 已知限制与复盘

- Schema 校验不能证明内容事实正确。
- 事实支持率需要人工评分。
- 模型输出具有非确定性。
- `improved_v2` 仍有 3 个缺失信息行为遗漏和 1 个必覆盖内容遗漏。
- 默认 `example=null` 提高了事实安全性，但减少了教学示例能力。
- 本地程序无法读取人民币账单或强制 `5` 元费用上限，必须在 MiMo 控制台管理。
- 仅实现 Windows PowerShell 下的复现流程，未验证 macOS 或 Linux。

完整开发复盘见 [`docs/RETROSPECTIVE.md`](docs/RETROSPECTIVE.md)。
