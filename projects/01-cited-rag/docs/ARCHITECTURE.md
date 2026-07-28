# 带引用的 Python 官方文档知识库问答架构

- 文档状态：`accepted`
- 版本：`0.1`
- 日期：`2026-07-28`
- 对应需求：`docs/PRD.md` v0.1

## 1. 架构目标

P1 使用本地 CLI 和可替换组件实现最小可运行 RAG，重点验证：

- Python 官方 HTML 的清洗、切分和真实元数据。
- 本地 Embedding 与持久化向量检索。
- 只能引用实际检索结果的回答。
- 无资料拒答和版本冲突处理。
- 自动测试、固定评估、基线与优化对比。

首版不引入 LangChain、LlamaIndex、Web UI、Docker或公开部署。

## 2. 已确认技术栈

| 能力 | 首版实现 |
|---|---|
| 运行入口 | Python `argparse` 本地 CLI |
| 输入输出模型 | Pydantic |
| 配置 | Pydantic Settings |
| HTML 解析 | Beautiful Soup + 标准库 `html.parser` |
| Embedding | FastEmbed |
| Embedding 模型 | `BAAI/bge-small-zh-v1.5` |
| 推理后端 | ONNX Runtime CPU |
| 向量存储 | Qdrant Client 本地持久化模式 |
| 生成模型 | MiMo `mimo-v2.5` |
| HTTP | HTTPX |
| 测试 | pytest |

完整精确依赖与验证记录见 `docs/DEPENDENCIES.md`。依赖已获批准并安装；Embedding 模型下载和真实 MiMo API 调用仍需单独批准。

## 3. 架构原则

1. CLI、问答服务、Embedding、向量存储和生成模型分离。
2. 业务代码依赖项目定义的接口，不直接依赖 FastEmbed、Qdrant 或 MiMo 细节。
3. HTML、问题和模型输出均视为不可信数据。
4. 引用元数据只能来自实际检索结果。
5. 模型只能返回证据标识，不能自由生成文件名、URL、章节或路径。
6. 自动测试不访问网络、不调用真实 API、不加载真实 Embedding 模型。
7. 基线先使用单一向量检索；没有评估证据前不加入混合检索或 Reranker。
8. 项目独立实现，不在运行时依赖 P0 包。

## 4. 系统上下文

```text
已批准的 Python 官方 HTML 快照
              |
              v
         CLI index
              |
              v
HTML 解析 -> 清洗 -> 分段 -> Chunk -> 本地 Embedding
                                      |
                                      v
                            Qdrant 本地持久化索引
                                      |
用户问题 -> CLI ask -> 问题 Embedding -> 向量检索
                                      |
                                      v
                            检索证据 + 真实元数据
                                      |
                                      v
                           拒答判断 / MiMo 生成
                                      |
                                      v
                        引用标识校验与元数据绑定
                                      |
                                      v
                             JSON 回答或拒答
```

问答时不抓取网页。文档下载和快照固定属于独立、需确认的数据准备步骤。

## 5. CLI

建议命令：

```powershell
python -m cited_rag index `
  --manifest ".\data\sources\manifest.json" `
  --source-dir ".\data\sources\html" `
  --index-dir ".\data\index"
```

```powershell
python -m cited_rag ask `
  --index-dir ".\data\index" `
  --question "Python 3.14 如何创建虚拟环境？" `
  --python-version "3.14"
```

### 5.1 `index`

负责：

- 校验 manifest 和允许目录。
- 导入、清洗、切分和建立索引。
- 输出文档数、Chunk 数、跳过数、失败数和索引版本。

不负责：

- 自动下载网页。
- 执行 HTML 中的代码。
- 调用生成模型。

### 5.2 `ask`

负责：

- 校验问题和可选 Python 版本。
- 调用问答服务。
- 成功 JSON 写 stdout。
- 稳定错误 JSON 写 stderr。
- 使用分类退出码。

## 6. 建议目录

```text
01-cited-rag/
├─ README.md
├─ STATUS.md
├─ DECISIONS.md
├─ .env.example
├─ pyproject.toml
├─ requirements.txt
├─ requirements-dev.txt
├─ data/
│  ├─ sources/
│  │  ├─ manifest.json
│  │  └─ html/
│  └─ index/
├─ docs/
│  ├─ PRD.md
│  ├─ ARCHITECTURE.md
│  └─ DEPENDENCIES.md
├─ src/
│  └─ cited_rag/
│     ├─ __init__.py
│     ├─ __main__.py
│     ├─ cli.py
│     ├─ config.py
│     ├─ models.py
│     ├─ errors.py
│     ├─ ingestion.py
│     ├─ chunking.py
│     ├─ retrieval.py
│     ├─ answering.py
│     ├─ embedding.py
│     ├─ vector_store.py
│     └─ adapters/
│        ├─ html_parser.py
│        ├─ fastembed.py
│        ├─ qdrant.py
│        └─ mimo.py
├─ tests/
├─ evals/
└─ demo/
```

`data/index/`、模型缓存和本地 `.env` 不进入 Git。官方语料是否直接提交，需根据仓库大小和许可清单单独决定。

## 7. 数据模型

### 7.1 来源清单

每个来源至少包含：

```text
source_id
file_name
title
python_version
source_url
retrieved_at
sha256
license
```

`source_id` 由项目分配并保持稳定。`sha256` 校验本地文件是否与清单一致。

### 7.2 文档块

每个 Chunk 至少包含：

```text
chunk_id
source_id
text
embedding_text
file_name
title
python_version
section_path
section_anchor
paragraph_start
paragraph_end
source_url
content_sha256
```

`text` 是引用原文。`embedding_text` 可以拼接标题和章节用于检索，但不得替代引用原文。

### 7.3 检索结果

```text
chunk
score
rank
```

### 7.4 模型回答草稿

模型只允许返回：

```json
{
  "status": "answered",
  "answer": "回答正文",
  "citation_ids": ["chunk-id-1"]
}
```

允许状态：

- `answered`
- `refused`
- `conflict`

程序验证 `citation_ids` 是本次检索结果的子集，再绑定完整引用信息。

## 8. HTML 解析与清洗

首批输入为 Python 官方 Sphinx HTML。

解析步骤：

1. 使用 Beautiful Soup 和标准库 `html.parser`。
2. 只读取页面主内容区域。
3. 删除 `script`、`style`、导航、页眉、页脚、目录按钮和无正文控件。
4. 保留 `h1`～`h6` 层级及元素 anchor。
5. 保留正文段落、列表项、提示块、代码块和必要表格文本。
6. 合并连续空白，但不改变代码内容。
7. 给段落分配稳定顺序号。
8. 保存原始 HTML 哈希和清洗后内容哈希。

清洗器不访问 HTML 中的外部链接，不执行脚本，也不根据页面内容读取其他路径。

## 9. Chunk 策略

基线采用章节感知切分：

- 先按标题层级和段落边界分组。
- 单个 Chunk 目标上限为 `800` 个字符。
- 相邻 Chunk 使用最多 `120` 个字符的段落级重叠。
- 单个段落超过上限时，再按句子或安全字符边界切分。
- 标题路径加入 `embedding_text`，引用 `text` 保持原文。
- 代码块尽量整体保留；过长时记录拆分。

这些值是基线参数，不是假定最优。优化阶段使用相同评估集比较 Chunk 大小、重叠和标题拼接策略。

## 10. Embedding 接口

业务层只依赖：

```python
class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...
```

首版适配器：

- FastEmbed `0.8.0`。
- 模型 `BAAI/bge-small-zh-v1.5`。
- ONNX Runtime CPU。
- 向量维度 `512`。
- 模型版本或仓库 revision 必须记录到索引清单和评估结果。

生产流程第一次加载会下载约 90 MB 模型文件；必须另行获得用户批准。自动测试使用确定性假 Embedding。

## 11. 向量存储接口

业务层只依赖：

```python
class VectorStore(Protocol):
    def replace(self, chunks: list[DocumentChunk], vectors: list[list[float]]) -> None:
        ...

    def query(
        self,
        vector: list[float],
        *,
        limit: int,
        python_version: str | None,
    ) -> list[RetrievedChunk]:
        ...
```

首版适配器：

- Qdrant Client `1.18.0`。
- `QdrantClient(path=...)` 本地持久化。
- Cosine 距离。
- collection 向量维度固定为 `512`。
- payload 保存真实元数据。
- 测试可使用 `QdrantClient(":memory:")`。

索引 manifest 保存：

- collection 名称。
- schema 版本。
- Embedding 模型和 revision。
- 向量维度。
- Chunk 参数。
- 语料 manifest 哈希。
- 建库时间。

索引配置不匹配时拒绝查询，要求重建索引。

## 12. 检索

基线：

- 单一稠密向量检索。
- `top_k=5`。
- 问题明确指定 Python 版本时使用元数据过滤。
- 问题未指定版本时允许检索 `3.13` 和 `3.14`，回答层检查版本冲突。

拒答阈值不凭经验写死：

1. 建立独立校准问题，不计入最终固定评估。
2. 观察可回答和不可回答问题的最高分分布。
3. 选择并记录阈值。
4. 固定阈值后运行最终评估。

检索结果顺序、分数、过滤条件和 Chunk ID 写入评估结果。

## 13. 回答与引用

问答服务流程：

1. 校验问题。
2. 生成问题向量。
3. 检索 `top_k` 证据。
4. 根据阈值和证据语义决定拒答候选。
5. 把证据文本和不可伪造的 Chunk ID 传给生成模型。
6. 模型返回回答状态、正文和 `citation_ids`。
7. Pydantic 校验结构。
8. 检查每个 `citation_id` 是否属于本次检索结果。
9. 由程序绑定文件名、版本、章节、URL和短证据。
10. 输出最终回答。

安全失败：

- 未知引用 ID：返回 `INVALID_CITATION_ID`，不展示伪造引用。
- `answered` 但无引用：返回输出错误。
- `refused` 但包含引用：按数据模型规则拒绝。
- 引用无法从存储回查：返回索引一致性错误。

## 14. 版本冲突

冲突条件：

- 检索结果存在不同 Python 版本。
- 相关片段对同一问题给出不兼容结论。
- 用户问题未限定版本，或限定版本与证据不一致。

处理：

- 不静默选择一个版本。
- 输出 `conflict`。
- 分别说明各版本结论。
- 每个版本结论引用对应版本 Chunk。
- 必要时要求用户明确版本。

冲突识别首版由证据约束 Prompt 和结构化输出完成，并通过固定夹具与人工评估验证；不引入额外冲突分类模型。

## 15. 生成模型接口

复用 P0 已验证的设计经验，但 P1 独立实现：

```python
class AnswerModelClient(Protocol):
    def generate(self, request: AnswerModelRequest) -> AnswerModelResponse:
        ...
```

MiMo 适配器负责：

- HTTPS 鉴权和请求。
- 超时、网络和 HTTP 错误映射。
- 提取供应商响应。

问答服务负责：

- Prompt。
- 证据编号。
- JSON 解析。
- 输出 Schema。
- 引用 ID 校验。

自动测试注入假客户端。真实调用必须再次确认预算。

## 16. 配置

建议环境变量：

```text
MODEL_PROVIDER=mimo
MODEL_API_KEY=
MODEL_BASE_URL=https://api.xiaomimimo.com/v1
MODEL_NAME=mimo-v2.5
MODEL_TIMEOUT_SECONDS=30
EMBEDDING_PROVIDER=fastembed
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
RETRIEVAL_TOP_K=5
RETRIEVAL_MIN_SCORE=
ALLOWED_DATA_ROOT=
```

规则：

- `.env.example` 不含真实密钥。
- Base URL 必须使用 HTTPS。
- 允许目录解析为绝对路径后再校验包含关系。
- 模型输出不能修改任何配置。

## 17. 路径安全

路径处理：

1. 从可信配置读取唯一允许的数据根目录。
2. 对用户路径执行规范化和绝对路径解析。
3. 检查解析结果位于允许根目录内。
4. 拒绝 `..`、符号链接逃逸和不支持文件类型。
5. 输出和索引路径同样执行边界检查。

HTML 内的 `href`、`src` 和模型输出永远不能成为本地读取路径。

## 18. 错误模型

稳定错误码至少包含：

- `INPUT_VALIDATION_ERROR`
- `PATH_OUTSIDE_ALLOWED_ROOT`
- `SOURCE_MANIFEST_ERROR`
- `SOURCE_HASH_MISMATCH`
- `UNSUPPORTED_DOCUMENT_TYPE`
- `DOCUMENT_PARSE_ERROR`
- `EMPTY_DOCUMENT`
- `EMBEDDING_ERROR`
- `VECTOR_DIMENSION_MISMATCH`
- `INDEX_NOT_FOUND`
- `INDEX_VERSION_MISMATCH`
- `RETRIEVAL_ERROR`
- `INSUFFICIENT_EVIDENCE`
- `MODEL_TIMEOUT`
- `MODEL_NETWORK_ERROR`
- `MODEL_HTTP_ERROR`
- `INVALID_MODEL_JSON`
- `OUTPUT_SCHEMA_ERROR`
- `INVALID_CITATION_ID`
- `INDEX_CONSISTENCY_ERROR`
- `INTERNAL_ERROR`

错误不得包含 API Key、完整鉴权头、完整供应商响应或私密路径。

## 19. 测试架构

### 单元测试

- HTML 主内容提取。
- 标题路径和段落顺序。
- Chunk 大小、重叠和稳定 ID。
- manifest 与哈希校验。
- 路径穿越和允许根目录。
- 引用 ID 子集校验。
- 拒答和冲突状态规则。

### 组件测试

- 确定性假 Embedding + Qdrant `:memory:` 检索。
- 临时目录中的 Qdrant 持久化。
- 索引配置不一致。
- 假 MiMo HTTP 响应和错误映射。

### 端到端自动测试

- 使用小型自编 HTML 夹具。
- 不下载官方文档。
- 不加载真实 Embedding 模型。
- 不调用真实 API。

## 20. 评估

评估分两层：

### 20.1 检索评估

- 不调用生成模型。
- 记录 `Recall@5`、排名、分数和错误类型。
- 可以重复运行，不产生 API 费用。

### 20.2 回答评估

- 记录引用有效率、忠实度和拒答准确性。
- 自动检查引用完整性和引用 ID。
- 忠实度保留人工评分或经过批准的等价评分方法。
- 真实 MiMo 运行前再次确认预算。

基线与优化必须固定：

- 语料 manifest。
- 评估集。
- Embedding 模型及 revision。
- 生成模型和参数。
- Prompt 版本。

## 21. 后续 UI、Docker和部署

核心评估达标后：

1. 新增本地 UI 入口，复用问答服务。
2. UI 显示答案、版本、章节和可展开证据。
3. 稳定后再创建 Docker 方案。
4. 公开部署前检查许可、上传权限、密钥、费用、限流和隐私。

首版架构不要求 Docker，也不排除以后将 Qdrant 本地模式替换为 Qdrant Server。

## 22. 未决事项

- Python `3.13` 的具体冲突对照页面。
- BGE 查询指令是否加入及其基线效果。
- 拒答阈值校准结果。
- 官方语料是否进入 Git，或只提交下载清单和校验脚本。
- 真实 MiMo 评估预算。
- UI 技术、Docker和部署平台。
