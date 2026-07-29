# P1 依赖方案

- 文档状态：`accepted`
- 日期：`2026-07-28`
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
