# D2 官方资料精确清单与采集记录

- 版本：`p2-v2-source-plan-0.1`；2026-09-14
- 状态：`frozen`
- 机器清单：[`source-plan-v1.json`](source-plan-v1.json)；`scripts/collect_sources_v2.py check` 只读校验，`collect` 要求冻结状态和 plan id 确认。
- 采集结果：`data/real-sources/snapshot-1855a50c906058faffe87039/manifest.json`；6 文件、`163080` bytes。
- 采集上限：首批 6 页；扩展上限 12 页；所有原始文件合计不超过 5 MiB。
- 采集方式：仅执行清单中的 HTTPS GET；保存原始字节、规范化文本、访问时间、页面版本/commit、许可证据和 SHA-256。
- 已冻结 commit：LangChain docs `671c0929a2840feb951f69532366d5227306cc3f`；PydanticAI `5cbacfc8f86d653baa0ca2e31970cbf4f0fcec95`。许可证证据均为对应仓库同一 commit 的 MIT `LICENSE` 文件。

## 推荐首批 6 页

| 编号 | 候选 | 维度 | 官方页面 | 采集前核对 |
|---|---|---|---|---|
| LG-01 | LangGraph | state-model | <https://raw.githubusercontent.com/langchain-ai/docs/671c0929a2840feb951f69532366d5227306cc3f/src/oss/langgraph/overview.mdx> | `langchain-ai/docs` 固定 commit；MIT LICENSE |
| LG-02 | LangGraph | human-approval | <https://raw.githubusercontent.com/langchain-ai/docs/671c0929a2840feb951f69532366d5227306cc3f/src/oss/langgraph/interrupts.mdx> | `interrupt`/`Command` 示例；MIT LICENSE |
| LG-03 | LangGraph | recovery | <https://raw.githubusercontent.com/langchain-ai/docs/671c0929a2840feb951f69532366d5227306cc3f/src/oss/langgraph/persistence.mdx> | checkpointer、thread、恢复语义；MIT LICENSE |
| PA-01 | PydanticAI | state-model | <https://raw.githubusercontent.com/pydantic/pydantic-ai/5cbacfc8f86d653baa0ca2e31970cbf4f0fcec95/docs/output.md> | `pydantic-ai` 固定 commit；MIT LICENSE |
| PA-02 | PydanticAI | human-approval | <https://raw.githubusercontent.com/pydantic/pydantic-ai/5cbacfc8f86d653baa0ca2e31970cbf4f0fcec95/docs/deferred-tools.md> | deferred tool 审批语义，不扩写为完整恢复保证；MIT LICENSE |
| PA-03 | PydanticAI | recovery | <https://raw.githubusercontent.com/pydantic/pydantic-ai/5cbacfc8f86d653baa0ca2e31970cbf4f0fcec95/docs/durable_execution/overview.md> | 后端/集成前提；MIT LICENSE |

这些原始文件覆盖 V2 首个闭环的三个比较维度。页面内容按固定 commit 采集；Mdx 中的组件导入只作为原文保留，不把未采集的 snippet 当作证据。

## 冻结与采集检查表

1. 已冻结 6 个原始文件；每个文件保留候选、维度和预期证据关系。
2. 已记录最终 URL、目标主机、仓库路径、commit、MIT LICENSE URL 和可再分发依据。
3. 估算原始字节与规范化字节，确保首批 ≤6 页且总量 ≤5 MiB；扩展前重新确认。
4. 采集器只允许冻结主机和路径；拒绝凭据 URL、非 HTTPS、非标准端口、私网/回环目标和未登记重定向。
5. 采集后人工查看每个候选×维度至少一个章节。无支持证据保留 `unknown`，不使用常识或另一候选资料补齐。

## 暂不采集

- GitHub README、源码和 LICENSE：除非页面许可覆盖范围已核对，或用户明确把它们加入清单。
- 价格、性能基准、社区活跃度、实时版本排名和第三方博客。
- 任意搜索结果、动态站点、私有资料、需登录页面、PDF/图片和候选框架安装包。

采集完成后，来源快照进入 `SourceStore` 前必须通过大小、哈希、UTF-8、路径和章节检查；若页面没有目标章节，保留缺口，不用常识补齐。
