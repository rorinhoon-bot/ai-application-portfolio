# DECISIONS

## D-001：P1 使用版本化官方中文技术文档

- 状态：accepted
- 决定：P1 知识库内容选择版本化官方技术文档，主要语种为简体中文。
- 原因：来源权威、版本可追踪、章节结构清楚，适合验证真实引用和版本冲突。

## D-002：语料选择 Python 3.14，并使用少量 3.13 对照

- 状态：accepted
- 决定：主语料使用 Python `3.14` 官方简体中文文档子集；少量 Python `3.13` 对应文档用于版本差异和冲突场景。
- 原因：与当前 Python `3.14.3` 工程环境和求职方向相关；官方文档能提供真实来源、许可、版本和章节元数据。
- 边界：首批具体章节、文件格式和快照日期仍需确认。

## D-003：CLI 作为 MVP 入口

- 状态：accepted
- 决定：首版使用本地 CLI；RAG 核心服务与入口分离，后续 UI 复用同一服务。
- 原因：CLI 更适合先验证导入、检索、引用、拒答、自动测试和批量评估，避免同时引入前端问题。

## D-004：UI、Docker和公开部署分阶段加入

- 状态：accepted
- 决定：核心 RAG 和固定评估达标后优先增加本地 UI；Docker和公开部署再单独评估与审批。
- 原因：UI 有求职展示价值；Docker和部署会增加许可、隐私、密钥、费用和平台问题，不应阻塞核心能力验证。

## D-005：首版生成、Embedding与存储边界

- 状态：accepted
- 决定：生成模型使用 MiMo `mimo-v2.5`；Embedding 本地运行；向量存储本地持久化。
- 原因：复用 P0 已验证的生成模型适配经验，同时控制 Embedding 费用和语料外发范围。
- 边界：未经批准不调用真实 API；Embedding 模型、库和向量存储具体实现必须先核验 Python `3.14.3` 兼容性，再提交依赖方案审批。

## D-006：首批使用官方 HTML 与确认后的质量目标

- 状态：accepted
- 决定：Python `3.14` 首批导入教程、`venv`、`pathlib`、`json`、`argparse` 和 3.14 新变化；Python `3.13` 导入新变化及少量冲突对照页面。首批格式为官方 HTML。
- 原因：HTML 能保留标题层级和章节标识，便于清洗、切分和真实引用；纯文本会丢失部分结构。
- 质量目标：引用有效率 `100%`、`Recall@5 ≥ 80%`、忠实度 `≥ 90%`、拒答准确性 `≥ 80%`。

## D-007：选择轻量、可替换的首版 RAG 技术栈

- 状态：accepted
- 决定：HTML 使用 Beautiful Soup；Embedding 使用 FastEmbed 和 `BAAI/bge-small-zh-v1.5`；向量存储使用 Qdrant Client 本地持久化模式；生成模型使用 MiMo `mimo-v2.5`。
- 原因：该组合支持中文、本地 CPU Embedding、真实向量存储和后续服务化，同时不要求首版安装 Docker 或引入 LangChain、LlamaIndex。
- 兼容性：CPython `3.14.3` 的 pip dry-run 已解析全部 50 个二进制或通用 wheel，无版本冲突。
- 边界：技术栈确认不等于安装许可；模型下载和真实 API 调用仍需单独批准。

## D-008：P1 使用独立虚拟环境和完整精确版本清单

- 状态：accepted
- 决定：使用 `projects/01-cited-rag/.venv`；生产依赖写入 `requirements.txt`，开发依赖通过 `requirements-dev.txt` 叠加；50 个直接与间接依赖全部固定精确版本。
- 原因：P1 与 P0 环境隔离；完整固定间接依赖可复现本次 Python `3.14.3`、Windows x86-64 解析结果。
- 验证：清单与实际安装版本完全一致；核心导入、Qdrant 内存检索和 `pip check` 均通过。
- 边界：安装 Python 包不代表获准下载 `BAAI/bge-small-zh-v1.5`、下载知识库语料或调用真实 MiMo API。
