# P1 只读最终验收与集成契约草案

2026-09-16；依据当前工作树，不据历史说明扩张结论。助手审查，不是独立人工质量评估。

## 证据与结论

当前存在 `projects/01-cited-rag/src/cited_rag/` 中的 HTML 解析、切分、严格 Pydantic 合同、Qdrant 检索、回答引用绑定、应用服务、CLI 与 Streamlit 展示；README、PRD、架构、DECISIONS D-001～D-039、测试、评估说明、FINAL_CHECKLIST、DEMO 和两张截图可定位。根及 P1/P2/P3 未发现其他 AGENTS.md。

历史证据：`docs/FINAL_CHECKLIST.md` 记录 220 项测试；`docs/RETRIEVAL_EVALUATION.md` 记录 13/15 Recall@5=86.7%；`docs/ANSWERING_EVALUATION.md` 记录小样本可回答召回80%、拒答100%、引用绑定100%、忠实度4/4；版本比较3题人工复核。以上均为历史记录，本轮没有重跑真实模型、真实向量检索或人工语义评分。

本次命令（P1 目录）：项目 `.venv/Scripts/python.exe` 启动 pytest，进程 audit hook 拦截 `socket.connect/socket.getaddrinfo/socket.bind`；`-q -p no:cacheprovider tests/test_models.py tests/test_html_parser.py tests/test_chunking.py tests/test_answering.py tests/test_service.py tests/test_answer_evaluation.py`。结果 **74 passed in 7.88s**。设置 `PYTHONDONTWRITEBYTECODE=1`；只执行内存/合成夹具路径，未操作 P1 数据库、服务、容器和 `.env`。这不是完整220项重跑。

当前树未找到 P1 HTTP API、Dockerfile、compose、容器验收或隔离容器启动材料。`CitedRagService` 是 Python 应用服务，不足以证明 HTTP 服务化或容器交付。用户所述这些能力可能位于其他未带入目录；当前验收列为**未核实**，不抹去历史可能存在的证据。不切换其他分支查找，不据此改 P1。

不能宣称完整云部署完成、已上线、生产可用；不能把小样本质量泛化到任意 AI 应用技术选型。P1 官方语料限 Python 3.13/3.14。

## 可复用契约

- `PythonDocsHtmlParser.parse(html)`：纯字符串解析；`DocumentChunker` 产生绑定章节、版本和哈希的 Chunk。可用于独立离线夹具验证。
- `make_retrieval_query(question, python_version)`：问题最多500字符，版本仅3.13/3.14，固定 top_k=5。
- `QdrantRetrievalService.retrieve(query) -> RetrievalResult`：结果含 index_id/build_id、排名、分数、payload、citation_url/retrieval_reason。真实实现需要本地模型和活动索引，本轮不构造它。
- `CitedRagService.answer(question=..., python_version=...) -> AnswerResult`：输入与回答合同可离线注入替身；正式工厂会读 `.env` 并打开索引，不供此次整合调用。
- `AnswerResult`：answered/refused/conflict、正文、程序绑定 citations、index_id/build_id、运行追踪；引用链保留 chunk_id/source_id/snapshot_id、版本、章节、source_url、正文哈希。
- CLI 历史启动：P1 `.venv/Scripts/python.exe -m cited_rag ask --question ...`，`PYTHONPATH=src`；UI：`-m streamlit run streamlit_app.py`。本轮均未执行。
- 整合建议：用项目本地 Python 子进程隔离 P1 3.14 与 P3 3.13；整合层维护固定 JSON 请求/响应。先复用 P1 纯解析/切分与严格合同，在新临时目录处理原创合成资料；不冒充真实BGE/Qdrant检索。P2 以适配器接收可追溯结果，单独标注检索模式和数据来源。

## 未验证与交接

新机器安装、真实检索复跑、HTTP兼容、容器、云部署、跨版本实机冲突、广泛内容质量均未验证。无阻断离线整合的 P1 业务缺陷；P1 零修改。下一阶段由 P3 V2 先完成严格 MCP 合同、审计、只读默认与失败恢复。
> 公开版本补充（2026-09-17）：本审查针对旧开发工作树。最新远端P1已包含API、容器和Pages证据，本次发布保留其文件；版本差异及新的定向验证见[发布说明](PUBLICATION.md)。下文“未找到”不代表新版P1缺少这些文件。
