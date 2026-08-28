# P1 依赖方案

- 文档状态：`accepted`
- 日期：`2026-07-28`
- V2更新：`2026-08-24`（FastAPI、Qdrant Server与API容器已验证）
- Python：CPython `3.14.3`
- 平台：Windows x86-64
- 解析工具：pip `25.3`

## 1. 权限状态

用户已明确批准创建独立环境、依赖文件、安装固定依赖和运行本地验证。

- 已创建 `pyproject.toml`、`requirements.txt`、`requirements-dev.txt`。
- 已创建 P1 独立 `.venv`。
- 已安装固定生产与开发依赖。
- 已批准并安装 Streamlit 求职展示页的固定依赖。
- 已经单独批准并下载固定revision的 `BAAI/bge-small-zh-v1.5` 必需资产；资产本体位于Git忽略目录，逐文件哈希见 `data/model-assets.json`。
- 已在人民币5元授权上限内调用真实 MiMo API；调用次数和tokens见回答、版本比较评估报告。普通测试仍不调用API。

## 2. 兼容性验证方法

使用 P0 已有 CPython `3.14.3` 执行：

```powershell
python -m pip install `
  --dry-run `
  --ignore-installed `
  --only-binary=:all: `
  --no-cache-dir `
  --report <temporary-report> `
  beautifulsoup4==4.15.0 `
  fastembed==0.8.0 `
  qdrant-client==1.18.0 `
  httpx==0.28.1 `
  pydantic==2.13.4 `
  pydantic-settings==2.14.2 `
  pytest==9.1.1 `
  setuptools==83.0.0
```

结果：

- 依赖解析成功。
- 无版本冲突。
- 核心栈首轮所有 50 个包均有当前平台可用的二进制 wheel 或通用 Python wheel。
- dry-run 本身未安装任何包；获得批准后才执行实际安装。
- pip 提示有新版本，但 P1 不升级全局或 P0 pip。

## 3. 顶层生产依赖

| 依赖 | 精确版本 | 必需 | 用途 |
|---|---:|---|---|
| `beautifulsoup4` | `4.15.0` | 是 | 解析 Python 官方 Sphinx HTML，保留章节与正文结构 |
| `fastembed` | `0.8.0` | 是 | 通过 ONNX Runtime 在本地生成中文 Embedding |
| `qdrant-client` | `1.18.0` | 是 | 本地持久化向量存储、余弦检索和元数据过滤 |
| `httpx` | `0.28.1` | 是 | 调用 MiMo HTTPS API，并处理超时与 HTTP 错误 |
| `pydantic` | `2.13.4` | 是 | 输入、元数据、回答、引用和错误模型 |
| `pydantic-settings` | `2.14.2` | 是 | 集中读取环境变量和本地 `.env` |
| `streamlit` | `1.60.0` | 是 | 本地求职展示页与可注入 AppTest |

未加入：

- LangChain：首版无需框架编排。
- LlamaIndex：首版直接实现导入、检索和引用边界。
- `lxml`：Beautiful Soup 配合标准库 `html.parser` 已满足首批 HTML。
- GPU 版 FastEmbed：首版使用 CPU，避免 CUDA 依赖。

Streamlit 扩展验证：

- 官方安装文档声明支持 Python 3.10—3.14。
- PyPI 元数据确认 `streamlit==1.60.0`、Python `>=3.10`、Apache-2.0 和通用 wheel。
- 对完整 `requirements-dev.txt + streamlit==1.60.0` 执行 `--dry-run --only-binary=:all:`，解析为 79 个固定版本，无冲突。
- 实际安装后 `pip check` 通过，核心导入输出 `1.60.0`。
- 参考：<https://docs.streamlit.io/get-started/installation/command-line>、<https://pypi.org/project/streamlit/>。

## 4. 顶层开发与构建依赖

| 依赖 | 精确版本 | 必需 | 用途 |
|---|---:|---|---|
| `pytest` | `9.1.1` | 是 | 自动测试 |
| `setuptools` | `83.0.0` | 是 | `src/` 布局、editable 安装和构建后端 |

暂不加入：

- `pytest-cov`：首阶段先验证测试行为，不以覆盖率数字代替测试质量。
- Ruff、Black、mypy：可在代码结构稳定后单独提案，避免一次引入过多工具。

## 5. 完整精确解析结果

以下版本来自 CPython `3.14.3`、Windows x86-64、`--only-binary=:all:` dry-run。

### 5.1 顶层包

```text
beautifulsoup4==4.15.0
fastembed==0.8.0
httpx==0.28.1
pydantic==2.13.4
pydantic-settings==2.14.2
qdrant-client==1.18.0
pytest==9.1.1
setuptools==83.0.0
```

### 5.2 间接包

```text
annotated-types==0.8.0
anyio==4.14.2
certifi==2026.7.22
charset-normalizer==3.4.9
click==8.4.2
colorama==0.4.6
filelock==3.32.0
flatbuffers==25.12.19
fsspec==2026.6.0
grpcio==1.83.0
h11==0.16.0
h2==4.4.0
hf-xet==1.5.2
hpack==4.2.0
httpcore==1.0.9
huggingface-hub==1.25.1
hyperframe==6.1.0
idna==3.18
iniconfig==2.3.0
loguru==0.7.3
mmh3==5.2.1
numpy==2.5.1
onnxruntime==1.28.0
packaging==26.2
pillow==12.3.0
pluggy==1.6.0
portalocker==3.2.0
protobuf==7.35.1
py-rust-stemmers==0.1.8
pydantic-core==2.46.4
Pygments==2.20.0
python-dotenv==1.2.2
pywin32==312
PyYAML==6.0.3
requests==2.34.2
soupsieve==2.9.1
tokenizers==0.23.1
tqdm==4.70.0
typing-extensions==4.16.0
typing-inspection==0.4.2
urllib3==2.7.0
win32-setctime==1.2.0
```

### 5.3 Streamlit 新增间接包

```text
altair==6.2.2
attrs==26.1.0
blinker==1.9.0
gitdb==4.0.12
GitPython==3.1.57
httptools==0.8.0
itsdangerous==2.2.0
Jinja2==3.1.6
jsonschema==4.26.0
jsonschema-specifications==2025.9.1
MarkupSafe==3.0.3
narwhals==2.24.0
pandas==3.0.5
pyarrow==24.0.0
pydeck==0.9.3
python-dateutil==2.9.0.post0
python-multipart==0.0.32
referencing==0.37.0
rpds-py==2026.6.3
six==1.17.0
smmap==5.0.3
starlette==1.3.1
tenacity==9.1.4
toml==0.10.2
tzdata==2026.3
uvicorn==0.51.0
watchdog==6.0.0
websockets==16.1.1
```

## 6. 关键二进制兼容证据

dry-run 为 CPython `3.14`、Windows x86-64 选择：

- `numpy-2.5.1-cp314-cp314-win_amd64.whl`
- `onnxruntime-1.28.0-cp314-cp314-win_amd64.whl`
- `grpcio-1.83.0-cp314-cp314-win_amd64.whl`
- `mmh3-5.2.1-cp314-cp314-win_amd64.whl`
- `pillow-12.3.0-cp314-cp314-win_amd64.whl`
- `pydantic_core-2.46.4-cp314-cp314-win_amd64.whl`
- `py_rust_stemmers-0.1.8-cp314-cp314-win_amd64.whl`
- `pywin32-312-cp314-cp314-win_amd64.whl`
- `pyyaml-6.0.3-cp314-cp314-win_amd64.whl`

`tokenizers==0.23.1` 和 `hf-xet==1.5.2` 使用兼容 CPython 3.14 的稳定 ABI wheel。

## 7. 模型下载

建议模型：

```text
BAAI/bge-small-zh-v1.5
```

已知信息：

- 中文检索模型。
- FastEmbed 支持。
- 向量维度 `512`。
- 最大长度 `512`。
- FastEmbed 模型大小约 `0.090 GB`。
- MIT License。

模型文件不进入 Git。首次真实加载模型前，需要单独获得下载批准，并固定模型 revision、文件哈希和本地缓存目录。

## 8. 安装后验证结果

2026-07-28 已完成：

1. 创建 `projects/01-cited-rag/.venv`。
2. 创建项目元数据和精确 requirements 文件。
3. 安装固定生产与开发依赖。
4. 确认 Python 为 `3.14.3`，且 `sys.prefix != sys.base_prefix`。
5. 成功导入 Beautiful Soup、FastEmbed、Qdrant Client、HTTPX、Pydantic、Pydantic Settings 和 pytest。
6. 使用 Qdrant `:memory:` 建立 3 维余弦距离 collection，写入假向量并成功检索到预期 point。
7. `pip check` 输出 `No broken requirements found.`。
8. Streamlit 扩展后，生产与开发 requirements 中 79 个固定版本与实际安装版本完全一致。
9. `.venv` 已被仓库根目录 `.gitignore` 的 `.venv/` 规则忽略。

该阶段没有实例化 FastEmbed 模型，没有下载真实 Embedding 模型，没有下载知识库语料，也没有调用 MiMo API。

## 9. V2-A FastAPI 依赖（已批准并安装）

- 提案日期：`2026-08-23`
- 权限状态：`accepted and installed`
- 核验环境：CPython `3.14.3`、Windows x86-64、pip `25.3`

### 9.1 顶层变更

| 依赖 | 精确版本 | 变更 | 用途 | 选择原因 |
|---|---:|---|---|---|
| `fastapi` | `0.141.1` | 新增直接依赖 | 严格 HTTP 合同、依赖注入、OpenAPI 与异常处理 | 与现有 Pydantic v2 模型直接集成；适合应用工厂和离线 ASGI 合同测试 |
| `uvicorn` | `0.51.0` | 从间接依赖提升为直接依赖 | 本地 ASGI 运行器 | 已由 `streamlit==1.60.0` 锁定、安装并通过 `pip check`；提升为直接依赖避免运行入口依赖偶然的传递关系 |

新增间接锁定包：

```text
annotated-doc==0.0.5
```

不选择 `uvicorn[standard]`：本切片只需本地确定性运行；现有锁文件已含兼容的 `httptools` 和 `websockets`，不再扩大可选依赖。

### 9.2 兼容性证据

已执行只读 dry-run，未安装包：

```powershell
python -m pip install `
  --dry-run `
  --ignore-installed `
  --only-binary=:all: `
  -r requirements-dev.txt `
  fastapi==0.141.1 `
  annotated-doc==0.0.5
```

结果：

- 完整现有生产/开发锁与 `fastapi==0.141.1` 解析成功，无版本冲突。
- 保留现有 `pydantic==2.13.4`、`starlette==1.3.1`、`anyio==4.14.2`、`httpx==0.28.1` 和 `uvicorn==0.51.0`。
- 新增包为通用 Python wheel，不引入新的平台二进制依赖。
- 另核验当日可用最新版本为 FastAPI `0.141.1`、Uvicorn `0.52.4`；为减少无关升级，本提案不把已验证的 Uvicorn 从 `0.51.0` 升到 `0.52.4`。

### 9.3 批准后的精确动作

1. 在 V2 独立工作树的 `projects/01-cited-rag/.venv` 创建 CPython `3.14.3` 虚拟环境。
2. `pyproject.toml` 新增 `fastapi==0.141.1` 和直接声明 `uvicorn==0.51.0`。
3. `requirements.txt` 新增 `annotated-doc==0.0.5`、`fastapi==0.141.1`；现有 `uvicorn==0.51.0` 不变。
4. 安装 `requirements-dev.txt`，随后执行 `pip check`、版本导入检查和全部离线回归测试。
5. 不下载模型、不启动 Qdrant Server、不调用 MiMo、不打开公网监听。

### 9.4 安装与验证结果

2026-08-23 获得学习者明确批准后完成：

1. 在 V2 独立工作树创建 `.venv`，确认 CPython `3.14.3`。
2. 安装完整 `requirements-dev.txt` 精确锁；实际安装 `fastapi==0.141.1`、`annotated-doc==0.0.5`、`uvicorn==0.51.0`。
3. `pip check` 输出 `No broken requirements found.`。
4. 新 `.venv` 命中仓库 `.gitignore` 的 `.venv/` 规则。
5. FastAPI 自带 TestClient 在当前 Starlette 中提示迁移到未批准的 `httpx2`；实现没有追加依赖，而是使用既有 `httpx==0.28.1` 的 `ASGITransport` 完成离线合同测试。
6. 全部 252 项测试通过；本地 Uvicorn 在 `127.0.0.1` 冒烟通过。

安装阶段只下载已批准的 Python wheel。未下载模型、未恢复语料或索引、未调用 MiMo、未启动 Docker、未修改系统设置。

## 10. V2-B1 Docker/Qdrant（已批准并验证）

学习者批准精确副作用后，实际安装与验证如下：

| 制品 | 固定/实际值 | 已核实网络大小 |
| --- | --- | ---: |
| Docker Desktop | `4.87.0`，Windows x86-64 build `236836` | `659,189,680` bytes |
| Docker installer SHA-256 | `9ac03d4e900c0fdee981d4bde083a55fdfb28ffba2cae77726eff2a437254822` | — |
| Qdrant image | `qdrant/qdrant:v1.19.0-unprivileged` | `70,706,168` bytes（amd64压缩层） |
| Qdrant index digest | `sha256:a0e04fe623cb064502cd869cefc1dc7ce359d8edd481063b5bd351c0a0a2c91e` | — |
| Python Client | 继续使用 `qdrant-client==1.18.0` | 已安装 |
| Docker CLI / Engine | `29.7.2` / `29.7.2` | 随Desktop安装 |
| Docker Compose | `5.4.0` | 随Desktop安装 |

Docker Desktop以per-user/WSL 2模式安装；安装命令没有使用`--accept-license`。程序目录和WSL数据根使用本机配置路径。Qdrant活数据使用Linux named volume，没有把Windows bind mount用作storage。

V2-B1没有新增Python包、没有下载新模型、没有调用MiMo。固定镜像实际为linux/amd64，Config.User为`1000:1000`；Client 1.18与Server 1.19的真实兼容性检查通过。Compose使用专用非internal bridge，但只向`127.0.0.1:6333`发布REST端口。完整运行、权限、持久化和snapshot恢复证据见`docs/QDRANT_SERVER_DESIGN.md` v0.2。

## 11. V2-B2 Linux API 容器（已批准并验证）

- 审计日期：`2026-08-24`
- 实施方式：先只读审计，再按学习者明确批准拉取固定镜像、下载带哈希wheel、构建并运行验收。
- 目标：CPython 3.14、Linux amd64、Debian bookworm glibc 2.36、binary wheel only。

基础镜像候选已固定为`python:3.14.7-slim-bookworm@sha256:23c59390fc717bf09f9336908199a0ae75d9c4264bf296123f94ad772fea3b52`。linux/amd64 manifest为`sha256:ff4ceef5258b9303b40c004af0bd31ac82c6248a6b951f9d9b329bf456f1f4b7`，4个压缩层合计`44,791,060` bytes。

对现有76个生产锁包检查兼容wheel：75个通过；唯一失败为Windows专用`pywin32==312`。初始元数据递归遗漏 `qdrant-client` 经 `httpx[http2]` 引入的三个包，首次 `--require-hashes` 构建安全失败。补入现有锁中的 `h2==4.4.0`、`hpack==4.2.0`、`hyperframe==6.1.0` 后，正确Linux运行闭包为44个包，所选wheel合计`65,250,778` bytes。

独立`requirements-api.txt`固定每个所选wheel的版本、文件名与SHA-256；构建使用`--require-hashes --only-binary=:all:`，容器内44个版本精确匹配且`pip check`通过。Streamlit、Pandas、PyArrow、PyDeck、GitPython、`pywin32`和开发工具不进入API镜像。完整包清单、失败修正和验收见`docs/API_CONTAINER_DESIGN.md` v0.2及`data/api-container-report.json`。

## 12. V2-C Hybrid/Rerank只读能力审计

- 审计日期：`2026-08-24`
- 新安装：无。
- `qdrant-client==1.18.0`与Qdrant Server `1.19.0`已提供named Sparse、`Modifier.IDF`、Prefetch和RRF，无需为Hybrid增加Python包。
- `fastembed==0.8.0`的 `Qdrant/bm25` 不支持中文language，SimpleTokenizer按空白切分；本项目不采用，避免虚假中文BM25。计划用现有`mmh3==5.2.1`实现可审计Han bigram与代码词元。
- FastEmbed现有Cross-Encoder支持 `BAAI/bge-reranker-base`。只读Hugging Face元数据确认候选revision `2cfc18c9415c912f9d8155881c133215df768a70`、MIT、Chinese/English；FastEmbed所需5文件合计 `1,129,559,216` bytes。
- 当前没有下载Reranker。只有Hybrid评估证明候选排序空间并获得明确批准后，才执行固定文件下载与资产哈希。

完整审计与批准边界见`docs/HYBRID_RERANK_DESIGN.md` v0.1及`data/hybrid-rerank-capability-audit.json`。
