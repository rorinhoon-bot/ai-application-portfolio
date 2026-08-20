# AI Application Portfolio

面向 AI 应用开发实习与初级岗位的本地作品集。四个项目均有代码、自动测试、固定评估、架构文档与学习复盘；部分项目使用真实模型或模型资产时有明确的成本、数据和运行边界。

> 公开范围：P0～P3 的源码、测试、固定评估、架构说明和演示材料。项目均为学习与作品展示，不声称生产部署能力。

## 作品导航

| 项目 | 解决的问题 | 核心技术 | 可核验证据 |
|---|---|---|---|
| [P0：结构化内容生成器](projects/00-structured-content-generator/) | 将不稳定模型文本变成可校验学习笔记 JSON | Python、Pydantic、JSON Schema、HTTPX、Prompt 评估 | 90 测试通过；10 例固定评估；Schema 100%；人工事实支持率 97.3% |
| [P1：带引用知识库问答](projects/01-cited-rag/) | 基于固定 Python 官方文档回答，并给出程序绑定引用 | 本地 BGE、Qdrant、MiMo、Streamlit | `Recall@5` 86.7%；引用绑定 100%；拒答准确率 100%；人工忠实度 4/4 |
| [P2：LangGraph 研究报告工作流](projects/02-agent-research-workflow/) | 将技术选型研究做成可暂停、恢复、人工批准的工作流 | LangGraph、SQLite checkpoint、Tool Calling、幂等导出 | 144 测试通过；12/12 固定案例；4.8/5 人工报告评分；SVG 演示 |
| [P3：本地 MCP 安全工具服务](projects/03-mcp-tool-server/) | 受限笔记检索与人工确认任务创建 | MCP、SQLite、Windows HANDLE、状态机 | 240 测试；C 评估 11/11；D-6 评估 40/40；stdio 演示 8/8 |

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

