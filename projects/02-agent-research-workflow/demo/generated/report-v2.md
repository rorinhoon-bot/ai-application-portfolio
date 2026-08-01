# AI 应用技术选型研究报告 v2

- 运行 ID（Run ID）：`run-privacy-durable-selection`
- 线程 ID（Thread ID）：`thread-privacy-durable-selection`
- 报告修订版本（Report revision）：`2`
- 报告文件 SHA-256（Report hash）：见同目录 `report-v2.md.sha256`
- 来源快照（Source snapshot）：`0e73ca7de985cdccb9295252fe2e7f3b2725183681a0576db2c7fb0838b44e3c`
- 制品状态：人工评审改写草稿；尚未经过 v2 工作流批准或导出

## 研究问题

三种方案中，哪种适合处理内部资料且必须支持中断恢复？

本次比较三个虚构候选：

1. `atlasflow`：自托管 Python 工作流库；团队自行维护环境、升级和备份。
2. `beaconflow`：单进程本地 Python 库；配置少，适合短任务和教学演示。
3. `cedarflow`：托管工作流服务；供应商负责运行、升级和备份。

## 已确认约束

- 内部研究资料不得发送到第三方托管工作流服务。
- 进程退出后，必须能从最后成功节点恢复。
- 最终报告导出前，必须由人工批准具体 revision 和内容哈希。

## 执行摘要

推荐 `atlasflow`。它在自托管模式下不要求把研究资料发送给框架供应商，并可将节点状态写入本地 SQLite 后按运行 ID 恢复。

`beaconflow` 可在本机运行，但只有内存状态，进程退出后不能恢复。`cedarflow` 支持托管 checkpoint 恢复，但会向托管服务发送运行状态和工具摘要，不满足严格内部资料约束。

本结论基于同一份原创虚构资料快照的事实对比，不是现实产品建议。

## 候选方案对比

| 候选方案 | 部署方式 | 内部资料处理 | 中断恢复 | 隐私证据强度 | 可靠性证据强度 | 本问题结论 |
|---|---|---|---|---|---|---|
| `atlasflow` | 自托管 Python 库 | 支持。框架不要求向供应商发送资料；外部模型适配器仍需单独控制数据外发。 | 支持。本地 SQLite 保存已完成节点状态，可按运行 ID 恢复。 | 事实（`factual`） | 事实（`factual`） | 满足两项硬约束，推荐。 |
| `beaconflow` | 单进程本地 Python 库 | 有条件支持。框架本身不联网，但应用工具仍可能联网，且框架不审计目标地址。 | 不支持。首版只保留内存状态，进程退出后状态丢失。 | 事实（`factual`） | 事实（`factual`） | 不满足中断恢复硬约束，不推荐用于本问题。 |
| `cedarflow` | 托管工作流服务 | 不支持严格本地资料约束。运行状态和工具摘要会发送到托管服务。 | 支持。托管数据库保存 checkpoint，可从最后成功节点恢复。 | 事实（`factual`） | 事实（`factual`） | 不满足严格隐私硬约束，不推荐用于本问题。 |

## 逐项证据

### `atlasflow`：隐私

- 候选方案：`atlasflow`
- 评价维度：`privacy`
- 证据强度：事实（`factual`）
- 结论：自托管模式不要求把研究资料发送给框架供应商；外部模型适配器的数据边界仍需应用单独控制。
- 证据来源：`atlasflow-security-cost-v1#data-boundary`

### `atlasflow`：可靠性

- 候选方案：`atlasflow`
- 评价维度：`reliability`
- 证据强度：事实（`factual`）
- 结论：可将已完成节点状态写入本地 SQLite；进程退出后可按运行 ID 读取最后成功 checkpoint 并继续。
- 证据来源：`atlasflow-reliability-v1#checkpointing`

### `beaconflow`：隐私

- 候选方案：`beaconflow`
- 评价维度：`privacy`
- 证据强度：事实（`factual`）
- 结论：框架本身不联网，资料可留在本机；但应用工具仍可能联网，且框架不审计目标地址。
- 证据来源：`beaconflow-security-cost-v1#data-boundary`

### `beaconflow`：可靠性

- 候选方案：`beaconflow`
- 评价维度：`reliability`
- 证据强度：事实（`factual`）
- 结论：首版只保存内存中的当前步骤和结果；进程退出后状态丢失，没有内置磁盘 checkpoint。
- 证据来源：`beaconflow-reliability-v1#checkpointing`

### `cedarflow`：隐私

- 候选方案：`cedarflow`
- 评价维度：`privacy`
- 证据强度：事实（`factual`）
- 结论：运行状态和工具摘要会发送到托管服务；离线或禁止第三方存储的项目不满足此部署模式。
- 证据来源：`cedarflow-security-cost-v1#data-boundary`

### `cedarflow`：可靠性

- 候选方案：`cedarflow`
- 评价维度：`reliability`
- 证据强度：事实（`factual`）
- 结论：托管数据库保存节点 checkpoint；任务进程重启后可从最后成功节点恢复。
- 证据来源：`cedarflow-reliability-v1#checkpointing`

## 推荐结论

- 推荐方案：`atlasflow`
- 推荐强度：推断（`inferred`）
- 推断依据：`atlasflow` 同时满足“资料不离开本地环境”和“进程重启后恢复”两项硬约束；`beaconflow` 缺少持久化恢复；`cedarflow` 不满足严格本地资料约束。

### 适用条件

选择 `atlasflow`，当内部资料、状态和草稿必须留在本地控制环境，长任务必须在进程退出后恢复，且团队能承担环境、备份、审计日志和人工确认界面的维护。

考虑 `beaconflow`，当任务短、单进程完成、不要求进程退出后的自动恢复，且优先低启动成本和少量配置。

考虑 `cedarflow`，当可以接受托管服务、外部网络与供应商账号依赖，更重视托管运行、升级、备份和可视化审批，且已单独批准运行与日志费用。

## 下一步动作

1. 搭建 `atlasflow` 自托管运行环境，明确本地资料目录、备份责任和升级责任。当前资料不能证明需要 Docker，因此 Docker 不是本报告前置条件。
2. 配置本地 SQLite checkpoint，使用稳定 `run_id` 验证“进程退出后从最后成功节点恢复”。
3. 为最终报告导出设置人工批准门；批准必须绑定报告 revision 与内容哈希。
4. 运行项目离线验证：`pytest -q`、`scripts/run_workflow_evaluation.py --check`、`scripts/run_demo.py --check`。

## 前置依赖与风险

- `atlasflow` 不提供托管运维；团队必须维护运行环境、升级、备份、checkpoint、审计日志和人工确认界面。
- 外部模型适配器可能导致资料外发；必须单独限制模型提供方、数据范围和权限。
- 已持久化状态与新图版本不兼容时，不能自动迁移业务字段；应拒绝恢复或执行显式迁移。
- 本报告未证明 Docker、真实部署、真实模型调用、真实成本、并发负载或跨平台兼容性。

## 限制

- 三种候选均基于同一套原创虚构合成资料快照评估。
- 本报告不使用真实产品文档、真实模型、网络搜索或付费资料。
- 证据只覆盖本报告列出的隐私与可靠性事实；未覆盖所有功能、成本、性能或生态差异。
- `atlasflow` 推荐只适用于“内部资料必须留在本地，且必须中断恢复”的约束组合。
- 本报告为作品集离线演示用途，不构成现实技术选型、采购、部署或安全建议。

## 引用

| 证据 ID | 来源（Source） | 章节（Section） | 标题（Title） | 版本（Version） | SHA-256 |
|---|---|---|---|---|---|
| `atlasflow-overview-v1#deployment-model` | `atlasflow-overview-v1` | `deployment-model` | AtlasFlow 产品概览 | `1.0.0` | `1f7006f5a315f7e2ad18af3333114299b4b5e692568bb0d4b4f8c21b2fba6ee6` |
| `atlasflow-security-cost-v1#data-boundary` | `atlasflow-security-cost-v1` | `data-boundary` | AtlasFlow 安全与成本说明 | `1.0.0` | `9236be3492ccc092918016dff8c5e74ffaa4aa984b08a2f682fb4a6df2bbfc4d` |
| `atlasflow-reliability-v1#checkpointing` | `atlasflow-reliability-v1` | `checkpointing` | AtlasFlow 可靠性说明 | `1.0.0` | `f6d86ccbda90c5c1ebd159be58bcb52027e8380dfe2c5784e64db105ac6aeab1` |
| `beaconflow-overview-v1#deployment-model` | `beaconflow-overview-v1` | `deployment-model` | BeaconFlow 产品概览 | `1.0.0` | `ab39f2c55336e0c1fcaaa47b04b275451a70d256e7129a5d6e97be9467ea86f4` |
| `beaconflow-security-cost-v1#data-boundary` | `beaconflow-security-cost-v1` | `data-boundary` | BeaconFlow 安全与成本说明 | `1.0.0` | `822e98e41a6d5d7e7a3e9ed6a772e4ed3e33c10f7d46494b1d326d206918f043` |
| `beaconflow-reliability-v1#checkpointing` | `beaconflow-reliability-v1` | `checkpointing` | BeaconFlow 可靠性说明 | `1.0.0` | `60cbd36a63bc2f43e485c291b6535a0910a50e947bd2124203ed9c364e22c0a3` |
| `cedarflow-overview-v1#deployment-model` | `cedarflow-overview-v1` | `deployment-model` | CedarFlow 产品概览 | `1.0.0` | `64540a9bf7c09909b1700952deef81b9b64daed2a40382a711d246d2bd6e580c` |
| `cedarflow-security-cost-v1#data-boundary` | `cedarflow-security-cost-v1` | `data-boundary` | CedarFlow 安全与成本说明 | `1.0.0` | `b14176ef9f7abc43edc3af8453f3e443a2f5473b5e3dcd787eca0e2fbc707f42` |
| `cedarflow-reliability-v1#checkpointing` | `cedarflow-reliability-v1` | `checkpointing` | CedarFlow 可靠性说明 | `1.0.0` | `e01c79a174a401128b5e54f601cfaef37c5a135b7c5662ed716f5c5c28f22b19` |
| `procurement-constraints-v1#privacy-policy` | `procurement-constraints-v1` | `privacy-policy` | 采购约束 | `1.0.0` | `a127485f0e7c23d9ed635e1114a5aa6f8e41c9d0c2d0c930e818c5f054386a1c` |
| `procurement-constraints-v1#recovery-requirement` | `procurement-constraints-v1` | `recovery-requirement` | 采购约束 | `1.0.0` | `a127485f0e7c23d9ed635e1114a5aa6f8e41c9d0c2d0c930e818c5f054386a1c` |
