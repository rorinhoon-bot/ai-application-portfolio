# 可信 AI 应用方案研究与交付平台：离线交付报告

本报告使用原创合成资料和脚本模型。下列审批仅批准演示流程，不是独立内容质量评分。

运行：`run-41ffe299b92f4dc29943120edcde6ac5`；报告哈希：`8d6e0ea9d71361480f2a2967ce469f7cca084701ad70051848e400670e86aeb4`。

## 边界与未验证项

P2真实内容验收未通过：首批2份有限批准、4份拒绝；修复后2份有限批准、1份拒绝。
P2永久上限5元，保守占用417/500分、调用容量109/109；本轮真实调用0、费用0。
P1只运行HTML解析与夹具关键词适配器，未验证BGE/Qdrant、HTTP、容器或云部署。
本轮由助手实现，学习者独立实现、答辩讲解和独立人工评分尚未验证。

## 审批记录

- REPORT_NEEDS_HUMAN / approve / scripted-test / `8d6e0ea9d71361480f2a2967ce469f7cca084701ad70051848e400670e86aeb4`
- NEEDS_HUMAN / approve / scripted-test / `223d24820b37d5f6588f852d87a99b6696b8dcc03c0b2a6f44044711959c75f7`

## MCP调用审计

每条引用通过P1原始资料哈希与P3读取正文交叉核验；收据位于mcp-audit目录。

- `graph-plan-human-approval#human-approval`：call `0d4c7ae11a7f4192a16b92e00bfec56e`；result `336b147e47cdb23ffec6328e2f010b7b3d0580253b1f4e7943985ede6677dd41`
- `graph-plan-tool-calling#tool-calling`：call `106fc3dfe92841018b6871700ef43127`；result `d0aa3ba36c7a3dbcb579f55290d7ddbdd14fa131abac3dbac58c8309bb24afc6`
- `chain-plan-recovery#recovery`：call `2ec2e771fe324ec8846563455f3de25f`；result `8e76ce40ac4f2e48f9c7a12a16b82bc5bc6ff06882713c29edb00d50059f31c3`
- `chain-plan-tool-calling#tool-calling`：call `3ec1d41eeae84ba1a13e08805d7233e8`；result `6355389dc84865a285a264cd761d62b4ffa727318fe9fa961dc94c2323761887`
- `graph-plan-recovery#recovery`：call `a812b6c176db4352b84b0ab927c59d7c`；result `74757d9adccb7130fdb25aae2cf7848152587038113af1fa9036f5864f7dbb65`
- `chain-plan-human-approval#human-approval`：call `a8dd2153d51c40d8add96e6bbb0c56c8`；result `e17edc29f4132c814c69ca2bc33a64fd40ea7b74344d68142b00f9c5394f1769`
- `graph-plan-human-approval#human-approval`：call `af0aaebb1572433094eb64196a3abe54`；result `67622c18bf8180004e2f4fc737adfcc8bc058e8114f61ceafdf3008625441ab2`
- `chain-plan-human-approval#human-approval`：call `da98ba07debe435089acea30a0b80b6d`；result `a2ad20d19a434443ae910bb9049961fb26ed07d5f88475b097795deb7d236b45`

## P2生成制品（脚本模型）

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

