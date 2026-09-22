# G4 报告整体覆盖复核交接

2026-09-23。分支 `codex/course-platform-ui`，阶段开始 HEAD `d7b0393ee9d44a816d2f695285e7fcd352532ba8`。本工具只准备独立人工复核材料与校验已填写表；不生成评价标签，不判报告质量合格。助手合成材料与填表仅用于行为测试。

此前 `g4-claims-v2` 严格绑定报告证据矩阵每格主张和来源，但不能因此推断摘要、推荐、关键遗漏、证据冲突及限制充分性已被评估。新增 `coverage_review.py`：读取并验证同一 `frozen-delivery-v1` ZIP，输出摘要、推荐、决定状态、限制、每格原文/引用、所有已读证据定位、未在矩阵引用的证据 ID 和五项固定复核问题。未引用证据仅供人工检查，不能自动断定遗漏。资料授权及预注册问题集依 [G4计划](G4-REAL-DATA-AND-COURSE-PLAN.md) 先行确认。

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/coverage_review.py --bundle <delivery.zip> --reviewer-id reviewer-a --output <coverage-reviewer-a.json>
```

评审者在每个 `answers` 项填 `status` 为 `adequate`、`concern` 或 `unclear`。`concern` / `unclear` 必须写具体 `note`；尤其将摘要里的额外主张、关键遗漏、冲突或资料外推断逐句指出。需要两位评审者时分别生成私有表，不能互看答案。完成后提交本机文件复核：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/coverage_review.py --bundle <delivery.zip> --review <coverage-reviewer-a.json> --output <coverage-summary-a.json>
```

每次复核重验 ZIP，重新生成材料并按字节摘要、字段与检查项逐项比对；修改报告摘录、来源、评分问题或换 ZIP 都拒绝。输出只统计状态与列出 `concern_check_ids`，始终是 `content_quality: not_accepted`；`reviewer_identity_verified: false`。填写者 ID、哈希和人工审批都不证明真人身份、资料授权、事实正确或报告整体质量。摘要可能包含多个主张，单个复核项不替代逐主张人工拆分与 [矩阵评分](G4-RATING-HANDOFF.md)。真实独立人评与教师条款仍缺。

行为证据见 [本阶段验收](G4-COVERAGE-ACCEPTANCE.md)。浏览器连接仍失败，本阶段未验干净源码检出三角色 UI、操作系统下载目录，也未碰原 P1/P2/P3 状态和 P2 真实预算。
