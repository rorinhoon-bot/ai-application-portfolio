# 五分钟演示

## 90秒静态证据页脚本（V2-E1）

- **0:00—0:15**：指出顶部“录制证据 · 非实时推理”。说明页面不接收任意问题，不连接模型、FastAPI或Qdrant。
- **0:15—0:35**：展示同一V3新20题对比：Dense Recall@5 75%、旧生产80%、确定性Hybrid 95%，candidate Recall@20 100%；不要和旧15题或V2 50题拼接。
- **0:35—0:55**：切换三个录制案例：有依据回答、证据不足拒答、跨版本比较。打开引用；跨版本案例明确展示原自动判定失败与事后人工复核。
- **0:55—1:15**：展示服务端RRF失败、Collector故障隔离和429重试/计费不确定性，强调失败报告没有被删除，发布门14/14后才切活动索引。
- **1:15—1:30**：展示非root只读API、活动build、1359 points与限制。收尾说明：本地制品已验证，GitHub Pages和远程Actions尚未运行。

本地预览：

```powershell
.\.venv\Scripts\python.exe -m http.server 8765 `
  --bind 127.0.0.1 --directory ..\..\portfolio-site\p1
```

浏览器打开`http://127.0.0.1:8765/`。页面数据由`scripts/export_portfolio_evidence.py`从已追踪报告确定性导出；`--check`用于验证没有漂移。

## 0:00—0:40：问题

普通 RAG 容易给出看似合理、却无法回查的回答。P1 面向正在学习或查阅 Python 官方文档的开发者：输入一个 Python 3.13/3.14 问题，输出简体中文答案、官方页面链接、章节和原文摘录；证据不足时拒答。

## 0:40—1:30：方案

1. 从固定官方 HTML 快照读取正文。
2. 清洗导航等噪声，保留标题、段落、列表和代码。
3. 生成可追踪 Chunk；Chunk 绑定版本、URL、章节 anchor、位置和哈希。
4. 使用本地 `BAAI/bge-small-zh-v1.5` 与 Qdrant 检索。
5. MiMo 只返回状态、回答和本次证据中的 Chunk ID。
6. 程序校验 ID，再绑定 URL、版本、章节和摘录。

## 1:30—2:30：运行

先启动求职展示页：

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

展示问题输入、版本范围、回答状态、官方原文按钮和引用摘录：

![Streamlit 真实带引用回答](images/streamlit-cited-answer.png)

CLI 仍适合展示机器可读合同：

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m cited_rag ask `
  --question "Python 3.14 中，使用 venv 创建虚拟环境应运行什么命令？" `
  --python-version "3.14"
```

展示：

![CLI 真实结果展示](images/cli-demo.png)

图片由 `data/mimo-smoke-report.json` 中已保存的真实调用结果确定性重绘，不是伪造的模型输出。可运行 `scripts/render_cli_demo.py` 复现。

如果面试重点是服务化，补充展示只读 API：

```powershell
.\.venv\Scripts\python.exe -m uvicorn cited_rag.api:app `
  --app-dir src --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/docs`，说明 `/healthz` 不初始化资源、`/readyz` 不调用 MiMo、`/v1/answers` 复用同一核心。每个响应带服务端请求 ID；错误统一为脱敏 Problem Details。

Qdrant Server已用固定Compose在`127.0.0.1:6333`运行。现场只做只读检查，不重复执行有副作用的恢复演练：

```powershell
Invoke-RestMethod http://127.0.0.1:6333/readyz
.\.venv\Scripts\python.exe scripts\build_server_index.py --restore
```

第二条命令对活动Manifest、1359 points、全部payload、ID、版本过滤和self-query做复验；`embedded_count=0`说明没有用重建掩盖持久化问题。权限、restart/down-up和snapshot恢复展示机器可读的`data/qdrant-*-report.json`。

## 2:30—3:30：关键安全边界

- `.env`、模型文件、展开语料和 Qdrant 索引不进入 Git。
- 模型不能生成引用 URL、版本、路径或章节。
- 未知 Chunk ID、非法 JSON、冲突状态缺少双版本引用时安全失败。
- 普通测试完全离线；运行时不会自动下载模型。
- 语料恢复先校验 ZIP 和每个文件哈希，并拒绝路径穿越、符号链接和覆盖。
- FastAPI 默认只绑定回环地址并关闭 CORS；没有认证和限流前不公开部署。
- 在线进程只拿Qdrant read-only key；真实权限测试证明三类读操作200、create/upsert/delete均403。
- Qdrant只发布回环REST端口；活数据使用Linux named volume，禁止`docker compose down -v`。

## 3:30—4:20：结果

- 同一V3新20题：Dense `Recall@5=75%`，旧生产路径80%，确定性Hybrid 95%；Hybrid candidate `Recall@20=100%`。
- 最终锁定回答集：可回答召回80%，拒答准确率100%。
- 引用绑定有效率100%。
- 4个实际回答人工忠实度4/4。
- 初始版本比较集0/3，失败报告保留；加入双版本平衡检索后，新集人工复核3/3，引用有效3/3。
- Server离线重建1359 points；restart与down/up后身份不漂移；9,922,560-byte snapshot上传恢复全验通过。
- 最终446项离线测试通过；普通测试不依赖Docker。CI合同为`workflow-ready`，尚无远程Actions通过记录。

## 4:20—5:00：难点与下一步

最难部分不是“调用模型”，而是让每条引用能回查，并诚实处理证据不足与失败发布。显式版本比较使用 `answered`，正文分别标版本；无法安全化解的矛盾才使用 `conflict`。CLI、Streamlit、FastAPI与静态证据页不复制核心RAG逻辑；静态页只展示带哈希的录制结果。下一步先冻结并审批GitHub Pages发布合同，不直接开放匿名实时推理。
