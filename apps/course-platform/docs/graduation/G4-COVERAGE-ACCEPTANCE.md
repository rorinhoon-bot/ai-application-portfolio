# G4 报告整体覆盖复核验收

2026-09-23。分支 `codex/course-platform-ui`，阶段开始 HEAD `d7b0393ee9d44a816d2f695285e7fcd352532ba8`，状态干净。只新增课设应用私有覆盖复核表、离线行为测试和文档；不访问 P1/P2/P3 既有数据库、容器、服务或 P2 真实模型账本。

真实离线应用行为测试从原创合成资料建立项目，走 P1 分词、P2 状态图/人工修订审批、P3 只读 MCP 与审计，取得经独立验证的交付 ZIP。复核表精确复制批准报告的摘要、推荐、决定状态、限制、全部证据矩阵单元与已读证据定位，并列出已读但未在矩阵引用的证据。篡改摘要、遗漏 ZIP 或损坏包被拒绝；未填表不能汇总。模拟填写一项 `concern` 后只报告状态计数和该项编号，保持 `content_quality: not_accepted` 且不声称评审身份真实。CLI 生成和汇总均经真实 ZIP 测试。

完整应用离线命令：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate.py --output apps/course-platform/.runtime/g4-coverage-tests.json
```

**63/63通过、0失败/0错误/0跳过，208.744秒**，结果见 [g4-coverage-tests.json](../results/g4-coverage-tests.json)。未重跑三个原项目各自完整测试；新增依赖、资料下载、收费 API 和真实模型调用均为0。

本复核表只把矩阵外的报告部分列入人工复核，不能自动判断语义支持、遗漏、冲突或资料外推断。答案是助手合成行为测试，不是真人独立评分。正式资料使用权、教师当届细则、评审者身份/独立性和学生独立讲解均未验证。浏览器接口仍报 `Browsers: Error: nodeRepl.fetch request failed`；原生 Edge 是用户无关页面，未操作。干净检出三角色 UI 与操作系统下载目录仍未复演。原开发工作树 668 条既有状态路径保留，课设工作树提交前复查。
