# DECISIONS

## D-001：先做工程热身

- 状态：accepted
- 决定：正式 RAG 作品前先完成结构化内容生成器。
- 原因：概念覆盖较广，但 Python、API、测试和 Git 实践尚未验证。

## D-002：P0 选择 AI 学习笔记场景

- 状态：accepted
- 决定：P0 实现“AI 学习笔记结构化生成器”。
- 原因：场景贴合学习者需求，能在有限范围内验证 Prompt、结构化输出、事实约束、评估和错误处理。

## D-003：每个作品使用项目本地虚拟环境

- 状态：accepted
- 决定：P0 虚拟环境放在 `projects/00-structured-content-generator/.venv`。
- 原因：隔离不同作品的依赖；依赖文件放在 H 盘项目目录；避免污染全局 Python。
- 验证：已创建 `.venv`，Python `3.14.3` 和 pip `25.3` 可用，隔离状态正常。

## D-004：复用现有 Python 3.14.3

- 状态：accepted
- 决定：复用当前用户目录中的 Python `3.14.3`，不重复安装，不修改系统级 `PATH`。
- 原因：`python`、`py` 和 pip 已可用，且已成功创建 P0 虚拟环境；当前没有重装必要。
- 复查条件：后续必需依赖明确不支持 Python `3.14` 时，再评估其他版本。

## D-005：模型供应商保持可配置

- 状态：accepted
- 决定：P0 不绑定 DeepSeek、MiMo 或 OpenAI；模型名称、API 地址、API Key 和超时通过配置提供。
- 原因：供应商和预算尚未确定；业务逻辑需要与供应商调用细节分离。

## D-006：P0 不使用 Docker

- 状态：accepted
- 决定：P0 本地运行，不安装、不使用 Docker。
- 原因：P0 目标是验证 Python、API、Schema 和测试；容器化不会增加当前核心证据。

## D-007：首版使用本地 CLI 和扁平模块

- 状态：accepted
- 决定：使用 CLI 接收主题、UTF-8 材料文件和学习者水平；代码采用 `cli.py`、`config.py`、`models.py`、`service.py`、`model_client.py`、`errors.py` 和 `adapters/` 的扁平结构。
- 原因：长材料使用文件输入可避免命令行转义问题；扁平模块符合 P0 规模，同时保留清晰职责边界。

## D-008：Pydantic 模型作为 Schema 唯一真源

- 状态：accepted
- 决定：输入和输出由 Pydantic 模型定义；JSON Schema 由模型生成并保存为 `schemas/learning_note.schema.json`，测试检查两者同步。
- 原因：避免 Python 模型和手写 Schema 出现双重真源，提供可执行的校验证据。

## D-009：通过 ModelClient 隔离模型供应商

- 状态：accepted
- 决定：业务逻辑只调用统一 `ModelClient` 接口；P0 首版只实现后续选定的一个供应商适配器。
- 原因：供应商和预算尚未确定；供应商鉴权、请求格式和响应格式不应影响输入校验、生成流程、Schema 校验和评估。

## D-010：采用有限传输重试和结构化错误

- 状态：accepted
- 决定：超时、网络错误、HTTP `429` 和 `5xx` 最多重试 2 次；非法 JSON、Schema 不符和非暂时错误不重试。CLI 使用包含 `code`、`message`、`retryable` 的 JSON 错误对象和分类退出码。
- 原因：有限重试能处理暂时故障，又避免无限请求、重复费用和掩盖模型输出错误。

## D-011：Prompt 文件化并隔离不可信材料

- 状态：accepted
- 决定：基线版和改进版 Prompt 保存为独立版本文件；系统 Prompt、用户数据和响应 Schema 在 `ModelRequest` 中分开传递。
- 原因：支持可复现评估，并阻止材料中的提示、代码或命令改变系统约束。

## D-012：固定评估集使用 JSONL

- 状态：accepted
- 决定：评估样本保存为 `evals/cases.jsonl`；自动指标和人工评分分别保存为 JSON，汇总报告保存为 Markdown。
- 原因：JSONL 易于逐条处理和版本比较，JSON 与 Markdown 同时满足机器处理和求职展示。

## D-013：继续使用 pip 并精确锁定依赖

- 状态：accepted
- 决定：`pyproject.toml` 保存项目配置，`requirements.txt` 和 `requirements-dev.txt` 保存精确版本；不引入新的依赖管理工具。
- 原因：复用已验证环境，降低 P0 工具复杂度，同时保证安装可复现。

## D-014：固定首批核心依赖

- 状态：accepted
- 决定：生产顶层依赖使用 `pydantic==2.13.4` 和 `pydantic-settings==2.14.2`；开发顶层依赖使用 `pytest==9.1.1`；构建后端使用 `setuptools==83.0.0`。生产与开发间接依赖也在 requirements 文件中精确固定。
- 原因：Pydantic 同时承担输入、输出和 JSON Schema 真源；Pydantic Settings 集中处理环境配置和本地 `.env`；pytest 提供最小测试工具链；setuptools 支持既定 `src/` 布局。无需额外引入 `jsonschema`、`tenacity`、CLI 框架或 mock 插件。
- 验证：已在项目本地 `.venv`、CPython `3.14.3`、Windows AMD64 上成功安装；`pydantic-core==2.46.4` 使用 `cp314-win_amd64` wheel；核心导入和 Schema/Settings 冒烟检查通过；`pip check` 返回 `No broken requirements found.`。
- 延期：不安装 HTTP 客户端和供应商 SDK；选择模型供应商并准备真实 API 接入前另行确认。

## D-015：输出字段必填，列表允许为空

- 状态：accepted
- 决定：`LearningNote`、`KeyConcept`、`GeneratedExample` 和 `QuizItem` 的 Schema 字段全部必填；`example` 必填但允许为 `null`；列表字段允许为空，但列表中的文本项不得为空白。
- 原因：成功结果必须始终包含稳定字段；空列表可明确表达“没有对应内容”；`example=null` 区分“无法安全生成示例”和“字段被模型遗漏”。

## D-016：本地流程通过依赖注入隔离真实网络

- 状态：accepted
- 决定：Service 和 CLI 依赖 `ModelClient` 协议，自动测试注入假客户端与假等待器；供应商注册表在供应商确认前保持为空。
- 原因：可以先验证解析、Schema、错误、重试、CLI 和评估逻辑，同时保证自动测试不访问真实 API、不产生费用。

## D-017：固定评估集先验证结构，真实指标后运行

- 状态：accepted
- 决定：首版固定评估集保存 10 条 JSONL 样本，覆盖正常、信息不足、矛盾、提示注入、命令文本和输入边界；自动执行器记录 Schema 通过率、示例标记率和错误分类，事实支持率保留人工评分。
- 原因：数据集和指标代码可以在无供应商阶段完成并测试；真实基线与改进版比较必须等供应商、模型和费用确认后再运行。

## D-018：首个真实供应商选择 MiMo

- 状态：accepted
- 决定：P0 首个供应商使用 Xiaomi MiMo，模型使用 `mimo-v2.5`，按量付费 OpenAI 兼容 API 地址使用 `https://api.xiaomimimo.com/v1`。
- 原因：用户明确选择 MiMo；`mimo-v2.5` 官方支持 Chat Completions JSON 模式，价格适合 P0 小规模验证。
- 费用边界：真实 API 测试总预算上限为人民币 `5` 元；先执行 1 次冒烟调用，再决定是否运行完整固定评估。

## D-019：MiMo 适配器直接使用 HTTPX

- 状态：accepted
- 决定：使用 `httpx==0.28.1` 直接调用 `/chat/completions`，不安装 OpenAI SDK；请求使用 `response_format={"type":"json_object"}`、`thinking={"type":"disabled"}` 和 `max_completion_tokens=4096`。
- 原因：HTTPX 足以完成单一端点、超时和错误映射，依赖更少；MiMo JSON 模式不直接执行项目 JSON Schema，因此适配器把 Schema 放入可信系统消息，Service 继续使用 Pydantic 做最终校验。
- 验证：HTTPX 及其精确依赖已在 CPython `3.14.3`、Windows AMD64 环境安装；导入、假 HTTP 响应测试和 `pip check` 通过。

## D-020：真实评估前先执行单请求冒烟验证

- 状态：accepted
- 决定：使用 `normal-transformer` 样本、`improved_v1` Prompt 和 `mimo-v2.5` 执行 1 次无重试真实请求；响应通过 Schema 后，才允许考虑运行完整评估。
- 原因：先用最低成本验证 API Key、端点、请求格式、JSON 模式和本地输出校验，避免配置错误导致批量失败或重复费用。
- 结果：请求成功，响应通过 `LearningNote` Schema；摘要保存于 `evals/results/20260728-mimo-smoke.json`。本地未保存 API Key、完整供应商响应或完整材料。
