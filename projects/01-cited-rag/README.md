# P1：带引用的知识库问答

本地导入 Python 官方简体中文文档，使用固定 BGE 模型与 Qdrant 检索，再由 MiMo 只根据检索证据生成回答。引用元数据由程序绑定；证据不足时拒答。

目标用户是需要查阅 Python 3.13/3.14 官方简体中文文档的学习者和开发者。输入为问题及可选版本；输出为 JSON 回答、官方引用、章节、摘录和运行追踪 ID。不处理任意网页、私有文件、第三方库、写操作、工具执行或开放式联网搜索。

## 当前能力

- Python 3.14 文档子集，少量 Python 3.13 对照。
- 官方 HTML 清洗、可追踪 Chunk、固定本地向量索引。
- 稠密检索加用户原文代码标识符通道。
- `mimo-v2.5` 结构化回答、拒答和真实引用。
- 本地 JSON CLI 与 Streamlit 求职展示页。

## GitHub 展示与演示

- **真实证据**：固定检索评估 `Recall@5=86.7%`；引用绑定 `100%`；锁定回答集拒答准确率 `100%`；人工忠实度 `4/4`。
- **演示入口**：下文提供 CLI 和 Streamlit 启动命令；引用必须来自程序绑定的固定官方文档元数据。
- **面试学习**：项目数据流、引用绑定、评估解释和追问见 [LLH_Study.md](LLH_Study.md)。
- **截图状态**：已提交两张真实截图：Streamlit 引用回答与 CLI 结果，见下方“演示”区；截图来自本地运行，不代表在线服务。

> 公开说明边界：语料、模型和本地 Qdrant 索引不全部进入 Git；新机器须按下文恢复。真实问答需要使用者自己的 API Key，绝不提交 `.env`。

## 架构

`固定HTML快照 → 清洗与结构化Block → 可追踪Chunk → 本地BGE向量 → Qdrant Top-5 → MiMo结构化选择Chunk ID → 程序绑定真实引用`

完整设计见 `docs/ARCHITECTURE.md`。

## 本地运行

### 新环境准备

需要 CPython 3.14：

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

恢复固定语料快照，不访问网络：

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe scripts\restore_corpus_snapshot.py
```

恢复固定 BGE 模型需要访问 Hugging Face；脚本只接受已记录仓库、完整revision、5文件allowlist、大小和SHA-256：

```powershell
.\.venv\Scripts\python.exe scripts\fetch_embedding_model.py --restore
```

离线重建本地Qdrant索引：

```powershell
.\.venv\Scripts\python.exe scripts\build_local_index.py --restore
```

恢复命令保留Git中的历史评估报告，不覆盖其时间、build ID或指标。

### API 配置

在本目录创建 `.env`：

```env
MODEL_PROVIDER=mimo
MODEL_API_KEY=你的真实Key
MODEL_BASE_URL=https://api.xiaomimimo.com/v1
MODEL_NAME=mimo-v2.5
MODEL_TIMEOUT_SECONDS=30
```

不要提交 `.env`。当前仓库已忽略该文件。

### 问答

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m cited_rag ask `
  --question "Python 3.14 使用 json.dumps 输出中文时怎样避免 ASCII 转义？" `
  --python-version "3.14"
```

输出是 JSON。成功和正常拒答退出码为0；稳定错误写入 stderr，退出码为1。

### Streamlit 展示页

最省事：双击仓库根目录的 `start-p1-web-ui.cmd`。脚本会自动使用 P1 的 `.venv`、设置 `PYTHONPATH` 并打开浏览器。

也可手动运行：

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

浏览器打开终端显示的本地地址。页面与 CLI 复用同一个 `CitedRagService`：只在提交问题时初始化模型和索引；引用 URL、版本、章节和摘录仍由程序绑定。侧栏默认收起，可用左上角按钮查看评估指标。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

普通测试不访问网络，不调用 MiMo，不下载模型。

## 评估结果

- 检索 `Recall@5`：86.7%。
- 最终回答集：可回答召回80%，拒答准确率100%。
- 引用绑定有效率100%。
- 人工忠实度4/4。
- 双版本比较人工复核3/3；原0/3检索失败报告保留。

详见：

- `docs/RETRIEVAL_EVALUATION.md`
- `docs/EVIDENCE_CALIBRATION.md`
- `docs/ANSWERING_EVALUATION.md`

## 演示

![Streamlit 真实带引用回答](docs/images/streamlit-cited-answer.png)

![CLI 真实结果展示](docs/images/cli-demo.png)

五分钟讲解见 `docs/DEMO.md`；项目原理、核心代码、取舍、面试题和自测题见 `LLH_Study.md`。

## 已知限制

- Git保存580,230字节压缩HTML快照；恢复后的原始HTML仍被忽略。
- 95 MB模型资产和约10.9 MB Qdrant索引不进入Git，需要按上方命令恢复。
- CLI 和 Streamlit 都不开放索引写入；索引构建仍使用受控脚本。
- 锁定回答集仅10题。
- 双版本比较人工集只有3题；机器可读 `conflict` 状态尚未形成稳定真实基线。
- 网络错误直接失败，不自动重试。
