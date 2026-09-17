# AI 工作流框架选型简报

## 研究问题
Compare graph-plan and chain-plan for an AI evidence research application with tool calling, human approval and recovery.

## 证据范围
本报告的 `supported`/`contradicted` 只基于本次运行实际读取且列出的证据。`unknown` 只表示本次已读证据未覆盖该单元，不表示整个冻结快照、框架或其文档不具备该能力。

## 执行摘要
已检查 2 个候选和 3 个维度；发现 6/6 个单元格有支持证据。

## 决策状态
`conditional`

## 证据矩阵

| 候选 | 维度 | 状态 | 结论 | 证据 |
|---|---|---|---|---|
| graph-plan | tool-calling | supported | The graph-plan synthetic design routes tool calling through an explicit allowlist and validates arguments before dispatch. This is a proposed design, not measured performance. | graph-plan-tool-calling#tool-calling |
| graph-plan | human-approval | supported | The graph-plan synthetic design requires human approval of the request and report hash before exporting a final artifact. | graph-plan-human-approval#human-approval |
| graph-plan | recovery | supported | The graph-plan synthetic design records checkpoint recovery at node boundaries and uses idempotent export. Exactly-once behavior still requires fault tests. | graph-plan-recovery#recovery |
| chain-plan | tool-calling | supported | The chain-plan synthetic design wraps tool calling in a read-only adapter. The adapter checks input contracts and binds evidence identifiers. | chain-plan-tool-calling#tool-calling |
| chain-plan | human-approval | supported | The chain-plan synthetic design places human approval in a separate host before publishing the report. Model output cannot grant approval. | chain-plan-human-approval#human-approval |
| chain-plan | recovery | supported | The chain-plan synthetic design proposes recovery from a saved request. It does not yet establish node-level checkpoint recovery or fault-injection performance. | chain-plan-recovery#recovery |

## 限制

- 结果仅反映已批准来源快照，不证明实际性能。
- 未知证据未被当作否定结论。

## 候选选择
graph-plan

## 每格限制与来源定位

快照：snapshot-integration-64e1e18351f5b7aeecdc

- graph-plan/tool-calling：依据来源快照，仍需验证实际项目表现。
- graph-plan/human-approval：依据来源快照，仍需验证实际项目表现。
- graph-plan/recovery：依据来源快照，仍需验证实际项目表现。
- chain-plan/tool-calling：依据来源快照，仍需验证实际项目表现。
- chain-plan/human-approval：依据来源快照，仍需验证实际项目表现。
- chain-plan/recovery：依据来源快照，仍需验证实际项目表现。

### 本次已读引用

- chain-plan-human-approval#human-approval：chain-plan.html#human-approval；章节 SHA256：68febeff89b75c2c2519174e239e70e68a03e4cb616a4ede1c254e8aa7c12aa1
- chain-plan-recovery#recovery：chain-plan.html#recovery；章节 SHA256：dcaedb64a3dd009ee4bb5c241dd43edcaa663734076947977c98765dc11b9737
- chain-plan-tool-calling#tool-calling：chain-plan.html#tool-calling；章节 SHA256：4dca7b5b6614263d16bff7082daef6d87abc392a6e5a2575fe450d0fdbf2aec3
- graph-plan-human-approval#human-approval：graph-plan.html#human-approval；章节 SHA256：39d339801f352a120fa5c51880830db1f0130d73409ff7eb66b78c6679873fae
- graph-plan-recovery#recovery：graph-plan.html#recovery；章节 SHA256：f92eb0820ebfc9c1b1a5a6eed9643769c09a9c858fe6f2ab7829138c10062ec2
- graph-plan-tool-calling#tool-calling：graph-plan.html#tool-calling；章节 SHA256：682ec1d9d063aa51ea7d34d666c7e39d1f2c32aaf561d7bf27249b5dee22fc2a

导出格式：markdown-v2.1
