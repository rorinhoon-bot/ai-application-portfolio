# workflow-v2 报告改写状态

- 状态：`DRAFT_AWAITING_HUMAN_REVIEW`
- 日期：2026-08-01
- 范围：报告展示与人工评审改写；不是新的 LangGraph 图版本，不替代 `workflow-v1` 可靠性基线。
- 报告：`demo/generated/report-v2.md`
- 完整文件 SHA-256：`4b417eefa5b50f6e16258e8b35b538f441d7e7d3a9733e4009cf3f19e25d8674`；同值见 `demo/generated/report-v2.md.sha256`
- 来源快照：`0e73ca7de985cdccb9295252fe2e7f3b2725183681a0576db2c7fb0838b44e3c`

## v1 到 v2 变更

1. 补齐 `atlasflow`、`beaconflow`、`cedarflow` 三候选，并用相同 `privacy`、`reliability` 维度比较。
2. 补充候选定义、中文执行摘要、统一中文字段标签和一致的证据强度标签。
3. 增加推荐适用条件、其他候选适用场景、四步下一步动作、前置依赖与风险。
4. 增加资料快照、事实覆盖范围和“虚构演示，不构成现实建议”的限制。
5. 保留 `workflow-v1`、金标准、来源快照和原内容寻址制品，不覆盖旧报告。

## v2 新纳入来源

以下 10 份资料早已存在于 `source-manifest-v1`；v2 新纳入报告引用范围，不是新建或下载来源。

| source_id | 相对路径 | SHA-256 |
|---|---|---|
| `atlasflow-overview-v1` | `atlasflow/overview.md` | `1f7006f5a315f7e2ad18af3333114299b4b5e692568bb0d4b4f8c21b2fba6ee6` |
| `atlasflow-reliability-v1` | `atlasflow/reliability.md` | `f6d86ccbda90c5c1ebd159be58bcb52027e8380dfe2c5784e64db105ac6aeab1` |
| `atlasflow-security-cost-v1` | `atlasflow/security-and-cost.md` | `9236be3492ccc092918016dff8c5e74ffaa4aa984b08a2f682fb4a6df2bbfc4d` |
| `beaconflow-overview-v1` | `beaconflow/overview.md` | `ab39f2c55336e0c1fcaaa47b04b275451a70d256e7129a5d6e97be9467ea86f4` |
| `beaconflow-reliability-v1` | `beaconflow/reliability.md` | `60cbd36a63bc2f43e485c291b6535a0910a50e947bd2124203ed9c364e22c0a3` |
| `beaconflow-security-cost-v1` | `beaconflow/security-and-cost.md` | `822e98e41a6d5d7e7a3e9ed6a772e4ed3e33c10f7d46494b1d326d206918f043` |
| `cedarflow-overview-v1` | `cedarflow/overview.md` | `64540a9bf7c09909b1700952deef81b9b64daed2a40382a711d246d2bd6e580c` |
| `cedarflow-reliability-v1` | `cedarflow/reliability.md` | `e01c79a174a401128b5e54f601cfaef37c5a135b7c5662ed716f5c5c28f22b19` |
| `cedarflow-security-cost-v1` | `cedarflow/security-and-cost.md` | `b14176ef9f7abc43edc3af8453f3e443a2f5473b5e3dcd787eca0e2fbc707f42` |
| `procurement-constraints-v1` | `shared/procurement-constraints.md` | `a127485f0e7c23d9ed635e1114a5aa6f8e41c9d0c2d0c930e818c5f054386a1c` |

## 人工验收边界

`workflow-v2-ai-self-review.md` 只是 AI 自评记录，不是人工质量量表结果。真实人工仍须阅读 `report-v2.md`，按 `HUMAN_REPORT_RUBRIC.md` 打分后，才能决定 P2 是否完成。
