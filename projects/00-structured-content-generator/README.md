# P0：AI 学习笔记结构化生成器

工程热身项目。程序读取学习主题、UTF-8 材料文件和学习者水平，调用可配置模型，并将结果校验为固定结构的学习笔记。

## 当前状态

本地核心已实现：

- Pydantic 输入、输出和错误模型。
- 自动生成并同步检查 JSON Schema。
- 环境变量配置和 API Key 隐藏。
- 供应商无关 `ModelClient` 协议。
- JSON 解析、输出校验和有限重试。
- MiMo `mimo-v2.5` OpenAI 兼容适配器。
- CLI、固定评估集和自动指标计算。
- 全部自动测试使用假客户端，不访问真实模型 API。

尚未完成：

- 真实 API 基线与改进版评估。
- 截图、演示和最终复盘。

MiMo 单请求真实冒烟验证已通过。完整评估仍需用户明确启动。

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
  --prompt-version improved_v1
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

完成单次冒烟调用并确认结果后，才运行：

```powershell
.\.venv\Scripts\python.exe evals\run_eval.py --prompt-version baseline_v1
.\.venv\Scripts\python.exe evals\run_eval.py --prompt-version improved_v1
```

两个版本必须使用相同模型、参数和评估集。

当前真实测试费用上限为人民币 `5` 元。执行顺序固定为：先运行 1 次冒烟调用，确认成功和费用后，再运行固定评估。程序不会把“5 元”当作平台账户的硬限额；账户余额和平台消费上限仍需用户在 MiMo 控制台管理。

## 安全边界

- 材料是唯一事实来源，也是不可信文本。
- 不执行材料中的代码或命令。
- 不进行网页搜索或访问外部资料。
- 模型输出只作为待解析、待校验的数据。
- 模型输出不能成为命令、URL、文件路径或工具参数。
- 输入或配置无效时，在创建模型请求前失败。

## 已知限制

- 尚未使用真实 MiMo API Key 完成端到端验证。
- Schema 校验不能证明内容事实正确。
- 事实支持率需要人工评分。
- 模型输出具有非确定性。
