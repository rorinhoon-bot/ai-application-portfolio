# 五分钟演示

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

## 2:30—3:30：关键安全边界

- `.env`、模型文件、展开语料和 Qdrant 索引不进入 Git。
- 模型不能生成引用 URL、版本、路径或章节。
- 未知 Chunk ID、非法 JSON、冲突状态缺少双版本引用时安全失败。
- 普通测试完全离线；运行时不会自动下载模型。
- 语料恢复先校验 ZIP 和每个文件哈希，并拒绝路径穿越、符号链接和覆盖。

## 3:30—4:20：结果

- 检索 `Recall@5`：13/15，86.7%。
- 最终锁定回答集：可回答召回80%，拒答准确率100%。
- 引用绑定有效率100%。
- 4个实际回答人工忠实度4/4。
- 初始版本比较集0/3，失败报告保留；加入双版本平衡检索后，新集人工复核3/3，引用有效3/3。

## 4:20—5:00：难点与下一步

最难部分不是“调用模型”，而是让每条引用能回查，并诚实处理证据不足。显式版本比较使用 `answered`，正文分别标版本；无法安全化解的矛盾才使用 `conflict`。本地 Streamlit 展示层不复制 RAG 逻辑。下一步可扩大版本比较集，再考虑 Reranker 和部署。
