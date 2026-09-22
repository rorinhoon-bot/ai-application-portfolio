# G4 人工仲裁工具离线验收

2026-09-22。工作树 `codex/course-platform-ui`，阶段开始 HEAD `69f327ad3efba39a4447254654baabd420111617`，状态干净。助手协作实施；不代表学生独立完成、真实人评或教师认可。

复查 `frozen_bundle_cli.py` 的仓库外路径与损坏包行为：既有 `test_frozen.py` 在系统临时目录将有效 ZIP 写盘并通过独立 CLI，改动报告成员后返回拒绝。本轮没有发现需要修改复核器的可复现缺陷，未为凑变更修改交付格式。

G4评分工具新增第三张空白人工仲裁表。只有在两位独立评审者各自完成标签后，仲裁者才能人工填写覆盖每条主张的最终标签、严重程度和理由；工具校验资料摘要、完整性和标签，再把原始标签计数/分歧与仲裁后描述统计一同输出。`adjudicator_id_distinct` 仅比较填报ID，**不证明评审者身份真实或独立**。`supported_claim_rate` 只表示清单内被仲裁为完全支持的主张占比，不衡量遗漏、冲突处理、拒答或报告整体质量；`content_quality` 始终为 `not_accepted`，无自动合格阈值。

测试只用助手虚构的两条主张与模拟评分。新增行为测试覆盖人工仲裁后的分歧保留、计数与ID区别，以及空表、缺项、资料变更拒绝。完整应用命令：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate.py --output apps/course-platform/.runtime/adjudication-tests.json
```

**63/63 通过，0失败/0错误/0跳过，199.404秒**，见 [adjudication-tests.json](../results/adjudication-tests.json)。完整回归结束后，仅将输出字段从可能暗示身份核验的名称改为 `adjudicator_id_distinct`，并重跑评分模块专项 **5/5通过、0.880秒**；没有因此改业务流程。所有测试只用临时数据和现有虚拟环境，新增依赖0、真实模型调用0。原 P1/P2/P3 各自完整项目测试不在本次范围。

浏览器控制接口仍不可用，三角色干净检出 UI 与浏览器 ZIP 下载目录仍未验收。正式资料授权、真实独立人评、人工仲裁、教师当届评分条款及学生本人讲解均未取得；不能把本次合成工具测试写成报告内容质量达标或毕业设计完成。
