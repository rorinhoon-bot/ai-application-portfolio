# G4 交付包与评分清单绑定验收

2026-09-22。分支 `codex/course-platform-ui`，阶段开始 HEAD `40dc6e04a1d4e09e13d781dc5ab124bcd098aa0b`。本阶段只改课设应用评分/ZIP复核、行为测试与文档；P1/P2/P3 原项目状态和真实模型预算未触碰。

旧 `g4-claims-v1` 虽然用清单哈希拒绝过期评分，却无法证明填入的 `source_id` 和原文来自报告交付包。现由 `score_content.py --prepare-from-bundle --bundle <delivery.zip>` 先用独立复核器验证完整 ZIP，再依次提取批准报告的所有 `evidence_cells`；新 `g4-claims-v2` 固定 ZIP 字节摘要、报告哈希、每格声明、引用的来源段和格内限制。生成评分表、仲裁表或汇总均须再次提供原 ZIP，逐项重建比对。未知格保留零引用；旧 v1 继续支持格式演示，汇总明确标 `source_binding: unverified`。

行为测试使用两份原创合成资料实际走 P1 分词、P2 checkpoint/审批/修订、P3 MCP 审计和 ZIP 交付。有效 ZIP 可生成完整清单；伪造声明、伪造来源段、删除单元、遗漏 ZIP 或损坏包均拒绝。已标合成标签只验证计数，不是独立内容评分。

首次完整回归 **63项中53通过、10错误，197.710秒**，见 [首次失败结果](../results/g4-bundle-binding-first-run.json)：`frozen_bundle.py` 间接导入 `workflow_runtime`，其进程级 `sys.addaudithook` 拒绝后续测试服务器本机绑定，报 `OFFLINE_NETWORK_BLOCKED`。修复为从 `common` 读取 JSON，并在 ZIP CLI 显式设置 P2 合同路径。单独进程导入复核器后本机 loopback bind 行为测试通过。再次运行：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate.py --output apps/course-platform/.runtime/g4-bundle-binding-tests-fixed.json
```

**63/63通过、0失败/0错误/0跳过，205.660秒**，见 [完整结果](../results/g4-bundle-binding-tests.json)。首次失败保留，不算通过。原 P1/P2/P3 各自完整项目回归不在本次范围。

机械绑定只证明本地 ZIP 内数据与评分清单一致，没有外部签名，不证明资料来源授权、来源事实正确、报告遗漏率、评审身份或独立性。`content_quality` 仍固定 `not_accepted`。正式资料、教师要求、独立人评、干净检出浏览器 UI/操作系统下载目录和学生独立讲解仍待验证。无新增依赖、下载、收费 API 或公开部署。
