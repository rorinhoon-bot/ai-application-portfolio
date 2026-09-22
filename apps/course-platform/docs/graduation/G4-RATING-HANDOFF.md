# G4 离线人工评分工具交接

2026-09-22。工具已实现并用助手编造的两条主张测试；**尚无授权真实语料、独立评审者评分或教师正式条款**。工具生成空白评分/仲裁表，校验和汇总人工输入；绝不替评审者决定支持程度，也不宣布报告质量合格。

## 资料与预注册

在评分前确定问题集、冻结报告和来源版本。真实评分先取得经独立校验的交付 ZIP，生成 `g4-claims-v2` 清单；它逐格覆盖报告的 `evidence_cells`，严格绑定 ZIP 字节摘要、报告哈希、声明原文、每格引用的来源段和限制。`unknown` 单元允许零条引用。清单不能手改；需补评摘要、未入矩阵的主张、遗漏来源和报告整体质量时，另行登记预注册评分任务。不要把报告是否获工作流批准当成评分依据。只放获授权内容；资料取得条件与教师要求另按 [G4计划](G4-REAL-DATA-AND-COURSE-PLAN.md) 登记。

先从本地 ZIP 制作冻结清单；全程只读 ZIP，不解压、不访问应用数据库或网络：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/score_content.py --prepare-from-bundle --bundle <delivery.zip> --output <manifest.json>
```

旧版示例清单合同仅供格式演示，来源未绑定：

```json
{"schema_version":"g4-claims-v1","claims":[{"claim_id":"case-01","claim":"示例工具支持离线读取。","evidence":[{"source_id":"example-p1","text":"示例工具读取本机原创资料。"}],"limitations":"未经真实场景评估"}]}
```

保存为本机私有 `manifest.json`，冻结后分别生成两个空白表。新合同每次生成评分表、仲裁表和汇总时都须传入**同一个原始 ZIP**；工具重校 ZIP 全部合同，再重新生成清单并逐项比对。主张、来源段、顺序、单元数量或 ZIP 字节变化均拒绝。`manifest_sha256` 是规范 JSON 内容摘要；ZIP 哈希不等于签名或授权证明。

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/score_content.py --manifest <manifest.json> --bundle <delivery.zip> --reviewer-id rater-a --output <rater-a.json>
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/score_content.py --manifest <manifest.json> --bundle <delivery.zip> --reviewer-id rater-b --output <rater-b.json>
```

两位评审者各自在私有表中给每条 `label` 填 `supported`、`partially_supported`、`unsupported` 或 `unclear`，`severity` 填 `none`、`minor`、`major` 或 `critical`；非完全支持须填写 `note` 说明缺口。评分前不得交换答案或让报告生成模型代评分。仅能找到一位时保留 `single_reviewer` 限制。

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/score_content.py --manifest <manifest.json> --bundle <delivery.zip> --ratings <rater-a.json> <rater-b.json> --output <summary.json>
```

脚本拒绝缺项、重复/未知主张、未填标签、重复评审者和资料摘要不匹配；输出各人标签计数、完全一致率及分歧主张编号。`source_binding: verified_bundle` 只表示清单与通过独立校验的本地 ZIP 一致；旧 `g4-claims-v1` 输出 `unverified`。**一致率不是正确率**。分歧需人工仲裁并保留原始标签。

独立评分完成后，可为人工仲裁者生成第三张**空白**表；仲裁者逐条填写最终标签和原因，尤其要说明分歧项。工具不会自动选多数票或覆盖两份原始评分：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/score_content.py --manifest <manifest.json> --bundle <delivery.zip> --adjudicator-id adjudicator-c --output <adjudication.json>
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/score_content.py --manifest <manifest.json> --bundle <delivery.zip> --ratings <rater-a.json> <rater-b.json> --adjudication <adjudication.json> --output <summary.json>
```

仲裁表必须覆盖所有主张，绑定相同资料摘要；输出 `adjudicator_id_distinct` 仅标明其**填报ID**是否与原评审ID不同，不构成真人身份或评分独立性证明。工具计算仲裁后完全支持占比及严重不支持数；这些只是已标主张的**描述统计**，不衡量报告遗漏、冲突处理或拒答，也没有预设合格阈值。无仲裁表时保持 `judgment: requires_independent_adjudication`；有完整仲裁表时为 `adjudicated_descriptive_only`；两种情况均固定 `content_quality: not_accepted`，须结合教师条款、预注册阈值与其他内容维度再人工给结论。

应用行为测试：`-m unittest discover -s apps/course-platform/tests -p test_content_scoring.py -v`。测试数据完全原创合成，模拟两位评审者只是核验计算与拒绝路径，不是独立内容验收。助手编写工具和本文件，不代表学生独立完成或讲解。
