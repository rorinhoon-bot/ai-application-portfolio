# P2 V2 独立内容复核包

状态：待独立评审。此包不更改模型输出、gold、账本或既有助手判定。评审者不应是生成或此前复核这些报告的人。

## 评审材料

| 题目 | 原稿/制品 | 已知助手结论 | 必查点 |
|---|---|---|---|
| `completion-structured-output-defaults` | `.runtime/p2-v2/d5m-completion-verification/approved-01.json` | 有限批准 | 是否准确保留：未指定`output_type`或包含`str`时允许普通文本；不含`str`时才强制结构化。 |
| `completion-interrupt-restart-boundary` | `.runtime/p2-v2/d5m-completion-verification/rejected-02.json` | 拒绝 | 实验是否分别观察节点从头重跑、外部副作用次数、最终业务完成；是否错误写成从暂停行继续。 |
| `completion-exactly-once-boundary` | `.runtime/p2-v2/d5m-completion-verification/approved-03.json` | 有限批准 | 是否把0、1、超过1次副作用分开；是否把单个故障点样本错误扩大为通用exactly-once保证。 |

每份状态JSON包含`report`、`evidence`、`review_findings`和report/artifact hash。固定资料位于`data/real-sources/snapshot-1855a50c906058faffe87039/`；不访问网络，不调用模型，不修改文件。

## 评分步骤

1. 逐句阅读摘要、每个矩阵claim/caveat和限制。可核验事实都进入分母。
2. 对照对应`evidence_id`的摘录，而非只看引用是否存在。
3. 对实验建议单独检查：观察项、通过/失败标准、它不能证明什么。
4. 填写下表。严重错误指改变推荐、把未知写成否定、颠倒原文条件、或把不足实验当作保证。

| 题目 | 支持事实数 / 全部事实数 | 严重错误数 | 清晰度 1–5 | 证据使用 1–5 | 可执行性 1–5 | 限制说明 1–5 | 结论 | 复核者与日期 | 备注 |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| completion-structured-output-defaults |  |  |  |  |  |  |  |  |  |
| completion-interrupt-restart-boundary |  |  |  |  |  |  |  |  |  |
| completion-exactly-once-boundary |  |  |  |  |  |  |  |  |  |

## 签发规则

本包只产生独立复核证据，不自动覆盖既有失败。若所有题无严重错误、每份事实支持率达到90%、平均质量至少4/5且每维均值至少3/5，才可将其作为“人工复核通过”的一项证据。它仍不能改写第一批六题的失败；整体P2是否完成还需重新审查全部完成定义。

不要把评审者姓名、联系方式或私人资料写入Git；使用化名或角色即可。
