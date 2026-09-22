# G4 离线人工评分工具交接

2026-09-22。工具已实现并用助手编造的两条主张测试；**尚无授权真实语料、独立评审者评分或教师正式条款**。工具仅生成空白评分表、校验和汇总人工输入，绝不替评审者决定支持程度，也不宣布报告质量合格。

## 资料与预注册

在评分前确定问题集、冻结报告和来源版本。逐条拆出可核验主张；每条记录 `claim_id`、`claim`、`evidence`（一个或多个含稳定 `source_id` 和对应原文 `text` 的对象）、`limitations`。不要把报告是否获工作流批准当成评分依据。只放获授权内容；资料取得条件与教师要求另按 [G4计划](G4-REAL-DATA-AND-COURSE-PLAN.md) 登记。

示例清单合同（内容仅供格式说明）：

```json
{"schema_version":"g4-claims-v1","claims":[{"claim_id":"case-01","claim":"示例工具支持离线读取。","evidence":[{"source_id":"example-p1","text":"示例工具读取本机原创资料。"}],"limitations":"未经真实场景评估"}]}
```

保存为本机私有 `manifest.json`，冻结后分别生成两个空白表。`manifest_sha256` 是规范 JSON 内容摘要，资料变化后旧表拒绝计分；它不是内容真伪或授权证明。

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/score_content.py --manifest <manifest.json> --reviewer-id rater-a --output <rater-a.json>
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/score_content.py --manifest <manifest.json> --reviewer-id rater-b --output <rater-b.json>
```

两位评审者各自在私有表中给每条 `label` 填 `supported`、`partially_supported`、`unsupported` 或 `unclear`，`severity` 填 `none`、`minor`、`major` 或 `critical`；非完全支持须填写 `note` 说明缺口。评分前不得交换答案或让报告生成模型代评分。仅能找到一位时保留 `single_reviewer` 限制。

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/score_content.py --manifest <manifest.json> --ratings <rater-a.json> <rater-b.json> --output <summary.json>
```

脚本拒绝缺项、重复/未知主张、未填标签、重复评审者和资料摘要不匹配；输出各人标签计数、完全一致率及分歧主张编号。**一致率不是正确率**。分歧需人工仲裁并保留原始标签；报告事实支持率、关键遗漏、冲突处理与拒答表现还需单独评价。当前输出固定 `content_quality: not_accepted` 和 `judgment: requires_independent_adjudication`，不由脚本设置最终验收阈值。

应用行为测试：`-m unittest discover -s apps/course-platform/tests -p test_content_scoring.py -v`。测试数据完全原创合成，模拟两位评审者只是核验计算与拒绝路径，不是独立内容验收。助手编写工具和本文件，不代表学生独立完成或讲解。
