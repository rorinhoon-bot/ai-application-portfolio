# 官方资料与开源设计调研

- 核对日期：2026-09-14；范围：LangGraph 官方文档、包元数据、两个研究工作流项目、PydanticAI 官方页面及候选资料入口。
- 设计审查阶段仅浏览公开页面/代码，未 clone、安装或执行外部代码；随后 D2 按已冻结清单完成一次 6 文件原文快照采集。DeepSeek 官方模型列表/价格与 Chat Completions 文档用于核对适配器入口；本轮没有发送模型请求，也不把页面价格当作已批准预算。
- 本文件记录观察与设计推论；main 分支页面可变，不能当作已冻结的生产资料快照。

## 1. 版本与维护核对

| 对象 | 本地/页面版本 | 维护证据 | 许可证 | 对 P2 的决定 |
|---|---|---|---|---|
| LangGraph | 本地 1.2.9；PyPI 最新 1.2.11，2026-08-11 上传，Python >=3.10 | 近期正式包发布与官方 release 页面可读 | MIT | 保留本地基线；开发时单独审查补丁变更，不直接升级 |
| langgraph-checkpoint-sqlite | 本地 3.1.0；PyPI 最新 3.1.1，2026-07-30 上传，Python >=3.10 | 同项目持续发布；本地旧版实测通过 | MIT | 适合本地单执行器；不因此声称支持多用户服务 |
| open_deep_research | main 的 pyproject 为 0.0.16；声明 langgraph>=0.5.4 | 仓库页面明确 2026-08-21 归档、只读 | MIT | 只参考，不引入依赖，不视为持续维护产品模板 |
| local-deep-researcher | main 的 pyproject 为 0.0.1；声明 langgraph>=1.1.0 | 页面未显示归档；存在源码、issue/PR；无法可靠取得最后提交日期 | MIT | 只参考有限研究循环；维护活跃程度不作保证 |

来源：[LangGraph PyPI](https://pypi.org/project/langgraph/)、[1.2.11 release](https://github.com/langchain-ai/langgraph/releases/tag/1.2.11)、[SQLite PyPI](https://pypi.org/project/langgraph-checkpoint-sqlite/)、[LangGraph LICENSE](https://raw.githubusercontent.com/langchain-ai/langgraph/main/LICENSE)。PyPI JSON 元数据本轮另行读取，版本与发布日期一致；没有下载安装包。

DeepSeek 适配器核对入口：[官方模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)、[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)。当前模型按 `deepseek-flash` 接入 `https://api.deepseek.com/chat/completions`；每次新预算仍要重新核对可用能力、usage 字段、价格日期和预算上限。

两个示例的版本是仓库 pyproject 声明，不宣称是 PyPI 最新发布版本。GitHub 未认证 API 返回限流，commit/Atom 页面也未成功取得；因此不编造最新 commit SHA/提交日期。仓库是否归档由本轮主页核实，读取量和 star 数不作为维护质量证明。

## 2. 官方机制与采用方式

- [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)：恢复时从整个节点开头执行；中断前的副作用可能重复。P2 保留「先落等待状态，再独立 interrupt」，批准绑定版本，暂停节点不发模型请求。
- [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)：按 thread 保存状态和恢复；选择持久存储才有重启恢复。P2 保留 SQLite，本轮实测了已有关闭重开恢复；V2 再测真实子进程终止。
- [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)：checkpointer 管运行状态，store 面向跨运行数据。P2 当前无需长期记忆 store，来源快照和操作账本按业务目的单独管理。旧 durable-execution URL 本轮重定向到该页面，不依赖旧路径结构。
- [LangGraph v1](https://docs.langchain.com/oss/python/releases/langgraph-v1)：保留核心图模型；高层 Agent API 变化不能当作重写现有 StateGraph 的理由。

设计推论：LangGraph 保存状态不等于供应商调用具备事务性。V2 要自行处理结果未知、费用预留、结果缓存与幂等导出；这是应用责任，不声称官方框架自动提供 exactly-once 计费。

## 3. 两个 GitHub 项目的取舍

### open_deep_research

已读 [仓库与归档信息](https://github.com/langchain-ai/open_deep_research)、[pyproject](https://raw.githubusercontent.com/langchain-ai/open_deep_research/main/pyproject.toml)、[LICENSE](https://raw.githubusercontent.com/langchain-ai/open_deep_research/main/LICENSE)、[deep_researcher.py](https://raw.githubusercontent.com/langchain-ai/open_deep_research/main/src/open_deep_research/deep_researcher.py)。

可借鉴：先形成 research brief，研究过程和最终报告分开；工具结果整理后再写作；显式限制研究迭代。P2 采用研究简报和证据中间结构。

不采用：supervisor 并行分派、多供应商/搜索/MCP 依赖集合。其工具异常辅助函数会把异常转成文本，P2 继续保留稳定错误码及脱敏边界。归档后无持续维护保证，不能整套复制。

### local-deep-researcher

已读 [仓库](https://github.com/langchain-ai/local-deep-researcher)、[pyproject](https://raw.githubusercontent.com/langchain-ai/local-deep-researcher/main/pyproject.toml)、[LICENSE](https://raw.githubusercontent.com/langchain-ai/local-deep-researcher/main/LICENSE)、[graph.py](https://raw.githubusercontent.com/langchain-ai/local-deep-researcher/main/src/ollama_deep_researcher/graph.py)。

可借鉴：查询、摘要、发现缺口、有限补检索的短循环；`route_research` 按最大轮次停止；来源去重。P2 用缺口驱动一次补检索，保留逐条原文定位，不只保留滚动摘要。

不采用：默认联网搜索、本地模型安装、整份依赖列表。名称中的 local 不代表没有搜索网络副作用。P2 首版用批准快照；用户未授权下载模型，不以「本地免费」跳过硬件和安装确认。

两者 MIT 文件均可读。本轮只提炼设计，没有复制代码；将来复制少量代码需绑定 commit 并保留版权/许可说明，第三方依赖和文档内容另核许可。

## 4. 首批真实语料候选清单（初始提案，已由第5节冻结记录替代）

以下是 D1 采集提案的起点，**不是最终 manifest**。MVP 第一批至多 6 页，必要时扩到 12 页。优先找到相应仓库原始 Markdown，在精确 commit 上读取；不能把 main 页面名写成产品版本。最终冻结清单和实际快照见第5节及 `08-SOURCE-PLAN.md`。

| 候选/维度 | 本轮可访问的官方入口 | 使用时注意 |
|---|---|---|
| LangGraph 总览/工具编排 | [Overview](https://docs.langchain.com/oss/python/langgraph/overview) | 再定位目标版本的具体工具合同，不能只用宣传概览 |
| LangGraph 人工审批 | [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) | 记录恢复时重放、thread 和持久化前提 |
| LangGraph 持久化 | [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers) | 区分本地 SQLite 和部署基础设施 |
| PydanticAI 结构化结果 | [Output](https://pydantic.dev/docs/ai/core-concepts/output/) | 把工具输出、原生结构化输出模式及模型要求分开 |
| PydanticAI 审批 | [Deferred Tools](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/) | 审批机制与崩溃恢复不是同一个能力 |
| PydanticAI 持久化 | [Durable Execution](https://pydantic.dev/docs/ai/capabilities/durable_execution/overview/) | 明确所需后端/集成，不把所有附加服务当作内建零成本 |

PydanticAI 仓库 [LICENSE](https://github.com/pydantic/pydantic-ai/blob/main/LICENSE) 为 MIT；本节当时尚未冻结对应文档 commit，已由第5节的固定 commit 和许可证 URL 补齐。网站 HTML 与仓库文件的授权范围需逐文件复核，许可不明就不收入可分发快照。

## 5. D2 采集结果（2026-09-14）

用户接受按计划推进后，清单冻结为两个公开仓库的固定 commit：`langchain-ai/docs@671c0929a2840feb951f69532366d5227306cc3f` 和 `pydantic/pydantic-ai@5cbacfc8f86d653baa0ca2e31970cbf4f0fcec95`。采集 6 个原始 Mdx/Markdown 文件，快照 `snapshot-1855a50c906058faffe87039`，总计 `163080` bytes；每项记录对应 commit 的 MIT `LICENSE` URL。

采集使用 P2 `source_collector.py`，仅请求机器清单 allowlist。当前 Windows 环境将 `raw.githubusercontent.com` 解析到本机代理的保留地址，因此显式启用 localhost proxy；URL、HTTPS、重定向、大小、路径、UTF-8 和哈希校验仍由采集器执行。快照已由 `SourceStore` 完成真实章节 `search/read` 验证；没有调用 DeepSeek、没有费用。

D2 完成后仍需补：每个候选的版本时效、性能/价格和实际用户问题覆盖；这些不由本次 6 页快照自动推断。若刷新来源，必须新建 snapshot 并重新审查，不覆盖当前快照。

## 6. D3-live 官方能力与价格复核（2026-09-14）

初始只读复核已经过时。2026-09-14 再核对 [DeepSeek Models & Pricing](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)：当前模型 ID 为 `deepseek-flash`（DeepSeek V4.1 Flash），OpenAI 兼容 base URL 为 `https://api.deepseek.com`，支持 JSON Output 与 Tool Calls。官方明确旧 `deepseek-v4-flash` 已下线，旧名会路由到 V4.1 Flash。高峰价为每 1M token：缓存命中输入 ¥0.04、缓存未命中输入 ¥2、输出 ¥8；高峰为北京时间工作日 9:00–12:00 与 14:00–18:00。价格页注明可变，价格卡只适用于经审批的一次预算窗口。

该核对已用于 D3-live 单样本闭环。当前适配器固定 `max_tokens=3000`、禁用 thinking，并在发送前以人民币高峰缓存未命中价格预留调用/token/费用上限；响应 usage 缺失、超时或合同失败仍进入 `RECOVERY_REVIEW`。真实 JSON、usage 与供应商 response ID 已实测；D5 的批量质量与成本验证仍未放行。
