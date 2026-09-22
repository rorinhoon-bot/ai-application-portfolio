# AI Application Portfolio

面向 AI 应用开发实习与初级岗位的本地作品集。四个项目均有代码、自动测试、固定评估、架构文档与学习复盘；部分项目使用真实模型或模型资产时有明确的成本、数据和运行边界。

> 公开范围：P0～P3 的源码、测试、固定评估、架构说明和演示材料。项目均为学习与作品展示，不声称生产部署能力。

## 作品导航

| 项目 | 解决的问题 | 核心技术 | 可核验证据 |
|---|---|---|---|
| [P0：结构化内容生成器](projects/00-structured-content-generator/) | 将不稳定模型文本变成可校验学习笔记 JSON | Python、Pydantic、JSON Schema、HTTPX、Prompt 评估 | 90 测试通过；10 例固定评估；Schema 100%；人工事实支持率 97.3% |
| [P1：带引用知识库问答](projects/01-cited-rag/) · [公开证据页](https://rorinhoon-bot.github.io/ai-application-portfolio/) | 基于固定 Python 官方文档回答，并给出程序绑定引用 | FastAPI、Qdrant、Hybrid RRF、OpenTelemetry、GitHub Actions/Pages | 新20题 `Recall@5` 95%；引用绑定 100%；发布门 14/14；公开静态证据可核验 |
| [P2：LangGraph 研究报告工作流 V2](projects/02-agent-research-workflow/) | 将技术选型研究做成可暂停、恢复、人工批准的工作流 | LangGraph、SQLite checkpoint、模型适配器、预算账本、幂等导出 | 266项离线回归；双审批；真实内容验收未通过，保留失败记录 |
| [P3：MCP 安全工具服务 V2](projects/03-mcp-tool-server/) | 默认只读的受控工具与调用审计 | MCP stdio、严格输入输出、快照哈希、Windows HANDLE | 254通过、9跳过；V2固定评估16/16；V1证据保留 |
| [P1-P2-P3：可信研究与交付平台](integrations/graduation/) | 将可追溯资料、审批、MCP调用与报告交付关联 | 隔离适配器、持久化恢复、双审批、收据复核 | 离线端到端18/18；独立包复核28/28；合成资料与脚本模型 |
| [研据工作台：带 UI 的课设工程](apps/course-platform/) | 在网页管理研究、审批、证据、审计与报告下载 | 原生 Web、严格 JSON API、独立 SQLite、隔离工作进程 | 应用 55 项离线回归通过；本机三角色权限；复用 P1/P2/P3 |

课设 UI 启动：仓库根目录双击 `start-course-platform.cmd`。需求分析、架构、权限与扩展计划见 [课设说明](apps/course-platform/README.md)。当前使用合成资料与脚本模型；学校当届要求、真实内容质量、全新机器依赖安装和公开部署尚未验收。本机三角色权限不等于远程多租户安全。

P1已发布版本保持原样。P2真实模型首批六题为2份有限批准、4份拒绝；修复后三题为2份有限批准、1份拒绝，不能以工作流测试替代内容质量。P2原项目预算永久封顶5元，保守占用417/500分、调用容量109/109；本次整合及发布验证不新增真实调用。

最新交付范围、隐私过滤与版本差异见[发布说明](docs/integration/PUBLICATION.md)。仅发布源码、锁定依赖、必要夹具、测试、脱敏结果和演示；开发工作树全量清单、内部学习档案、密钥、运行数据库和模型资产不进入此次提交。实现包含助手协作，学生独立设计、讲解与人工内容评价仍需单独证据。

## 推荐阅读顺序

1. 先看各项目 `README.md`：问题、运行命令、结果和限制。
2. 再看 `docs/ARCHITECTURE.md`：系统边界和数据流。
3. 最后看 `LLH_Study.md`：面试讲解、代码阅读路线、追问与自测。

| 学习或面试目标 | 优先项目 |
|---|---|
| 模型 API、结构化输出、Prompt 评估 | P0 |
| RAG、引用、检索评估 | P1 |
| Agent 工作流、状态、恢复、人工确认 | P2 |
| MCP、工具权限、文件安全、并发副作用 | P3 |

## 本地验证入口

每个项目有独立环境与命令。完整命令见各自 README；公开前建议至少复跑：

```powershell
# P0
Set-Location projects\00-structured-content-generator
.\.venv\Scripts\python.exe -m pytest -q

# P1
Set-Location ..\01-cited-rag
.\.venv\Scripts\python.exe -m pytest -q

# P2
Set-Location ..\02-agent-research-workflow
.\.venv\Scripts\python.exe -m pytest -q

# P3
Set-Location ..\03-mcp-tool-server
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe evals\run_d6_eval.py
```

