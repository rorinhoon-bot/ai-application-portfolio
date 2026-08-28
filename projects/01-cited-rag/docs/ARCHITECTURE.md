# 带引用的 Python 官方文档知识库问答架构

- 文档状态：`draft`
- 版本：`0.36-draft`
- 日期：`2026-08-28`
- 对应需求：`docs/PRD.md` v0.13-draft
- 版本说明：第 1～22 节保留已验收 V1 架构；第 23 节定义 V2 生产化覆盖层。

## 1. 架构目标

P1 使用本地 CLI、Streamlit 展示页和可替换组件实现可运行 RAG，重点验证：

- Python 官方 HTML 的清洗、切分和真实元数据。
- 本地 Embedding 与持久化向量检索。
- 只能引用实际检索结果的回答。
- 无资料拒答和版本冲突处理。
- 自动测试、固定评估、基线与优化对比。

V1不引入 LangChain、LlamaIndex、Docker或公开部署。V2-B1只用Docker运行Qdrant Server，FastAPI仍在Windows宿主机；Streamlit仍是本地展示层。

问题明确同时包含3.13和3.14时，v0.18沿用已验收的双版本过滤检索，再以2+2+1合并为5条证据。显式版本比较可返回 `answered`；无法安全化解的矛盾才返回 `conflict`。

## 2. 已确认技术栈

| 能力 | 首版实现 |
|---|---|
| 运行入口 | Python `argparse` 本地 CLI + Streamlit + FastAPI/Uvicorn |
| 输入输出模型 | Pydantic |
| 配置 | Pydantic Settings |
| HTML 解析 | Beautiful Soup + 标准库 `html.parser` |
| Embedding | FastEmbed |
| Embedding 模型 | `BAAI/bge-small-zh-v1.5` |
| 推理后端 | ONNX Runtime CPU |
| 向量存储 | Qdrant Client本地适配器 + Qdrant Server `1.19.0`回环适配器 |
| 生成模型 | MiMo `mimo-v2.5` |
| HTTP | HTTPX |
| 本地 Web UI | Streamlit `1.60.0` |
| HTTP API | FastAPI `0.141.1` + Uvicorn `0.51.0` |
| 容器 | Docker Desktop `4.87.0` + Compose `5.4.0`；仅Qdrant |
| 测试 | pytest |

完整精确依赖与验证记录见 `docs/DEPENDENCIES.md`。依赖、固定Embedding资产和预算内真实MiMo评估均已批准并完成。

## 3. 架构原则

1. CLI、Streamlit UI、问答服务、Embedding、向量存储和生成模型分离。
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
用户问题 -> CLI ask / Streamlit UI -> 问题 Embedding -> 向量检索
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
                       JSON / 页面回答或拒答
```

问答时不抓取网页。文档下载和快照固定属于独立、需确认的数据准备步骤。

## 5. CLI

```powershell
python -m cited_rag ask `
  --question "Python 3.14 如何创建虚拟环境？" `
  --python-version "3.14"
```

### 5.1 `index`

首版不在统一CLI开放。下载、导入、token审计和索引构建继续使用受控脚本，避免普通问答入口获得文件写入或网络下载能力。

后续如开放 `index`，必须保持manifest、允许根目录、不可变构建和原子激活规则。

### 5.2 `ask`

负责：

- 校验问题和可选 Python 版本。
- 调用问答服务。
- 成功 JSON 写 stdout。
- 稳定错误 JSON 写 stderr。
- 使用分类退出码。
- 不接受调用方传入任意索引路径、模型路径、URL或生成参数。
- 运行时固定 `HF_HUB_OFFLINE=1`，只读取已验证本地模型和活动索引。

### 5.3 Streamlit 展示页

- `streamlit_app.py` 只处理 `src/` 入口和应用工厂组装。
- `cited_rag.ui.run_ui()` 只负责输入、版本选择、状态、引用卡片和安全错误文案。
- 首次加载页面不初始化 BGE、Qdrant 或 MiMo；仅在提交非空问题时创建并缓存应用。
- UI 不接受模型路径、索引路径、URL、API 参数或写操作。
- 回答正文按普通 Markdown 渲染；引用链接只读取验证后的 `AnswerCitation.citation_url`。
- 领域错误映射为稳定用户文案；供应商响应、异常详情和密钥不进入页面。
- AppTest 注入假应用，普通 UI 测试不访问网络、不加载真实模型。

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
├─ streamlit_app.py
├─ .streamlit/
│  └─ config.toml
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

导入数据分成来源声明、文档快照、内容块和 Chunk 四层。来源声明保存人工确认的信息；其余层保存程序从真实文件验证或确定性生成的信息。

### 7.1 `SourceManifestEntry`

每个来源至少包含：

```text
schema_version
source_id
document_key
python_version
documentation_release
source_url
relative_path
retrieved_at
expected_title
license_name
license_url
raw_sha256
media_type
language
```

- `document_key` 表示跨 Python 版本的同一逻辑文档，例如 `library-venv`。
- `source_id` 表示一个版本化来源，例如 `py3146-library-venv`。
- `python_version` 首批只接受 `3.13` 或 `3.14`。
- `documentation_release` 保存下载时页面显示的精确补丁发布版，例如 `3.14.6`；它必须属于 `python_version` 系列。
- `relative_path` 使用 `/` 分隔，且只能指向允许数据根目录内的普通 `.html` 文件。
- `retrieved_at` 是取得网页快照的时间，必须包含时区；不能用本地导入时间代替。
- `raw_sha256` 是 manifest 声明的原始 HTML 哈希；程序导入时重新计算并比较。
- 来源、版本、URL、路径、许可和预期标题由项目清单提供，不从模型输出推断。

### 7.2 `DocumentSnapshot`

成功验证和解析后的文档快照至少包含：

```text
snapshot_id
source_id
page_title
html_canonical_url
raw_html_sha256
cleaned_content_sha256
parser_schema_version
imported_at
warnings
```

- `snapshot_id` 由 `source_id` 和原始 HTML 哈希确定。
- `page_title` 来自主正文中的真实 `h1`。
- `html_canonical_url` 仅在 HTML 提供 canonical link 时保存，并与 manifest 的 `source_url` 交叉校验。
- `imported_at` 是本地导入时间，不等于 `retrieved_at`。
- 原始 HTML 文件保持不变，作为最终回查依据。

解析器使用两个不持久化的中间模型：

```text
ParsedDocument
ParsedContentBlock
```

它们只保存从 HTML 确定性提取的页面标题、canonical URL、正文 Block 和结构警告，不包含来源 ID、快照 ID 或 Block ID。导入服务完成 manifest、路径、哈希、标题和 canonical URL 校验后，才能把中间结果绑定为 `DocumentSnapshot` 和 `ContentBlock`。

### 7.3 `ContentBlock`

每个保留的正文块至少包含：

```text
block_id
snapshot_id
block_order
paragraph_order
block_type
raw_text
clean_text
section_path
section_anchor
block_anchor
list_level
```

- `block_order` 是所有保留正文块在文档中的 1-based 顺序。
- `paragraph_order` 是原始 `<p>` 在主正文中的 1-based 顺序；非段落块为空。
- `block_type` 首版支持 `paragraph`、`list_item`、`code`、`definition_term`、`table_row` 和 `blockquote` 等确定类型。
- `raw_text` 是从保留 DOM 块提取、尚未规范空白的可见文本。
- `clean_text` 只能通过确定性规则从 `raw_text` 得到，不能由模型改写或摘要。
- `section_path` 保存标题层级；`section_anchor` 和 `block_anchor` 只能来自真实 HTML。

### 7.4 `DocumentChunk`

每个 Chunk 至少包含：

```text
chunk_id
snapshot_id
source_id
document_key
python_version
documentation_release
chunking_schema_version
chunk_config_sha256
chunk_order
block_start
block_start_offset
block_end
block_end_offset
paragraph_start
paragraph_end
text
embedding_text
section_path
section_anchor
source_url
relative_path
content_sha256
```

- `chunk_id` 使用固定项目命名空间和规范化身份字段生成 UUIDv5，可直接作为 Qdrant point ID。
- `chunk_order` 是文档内的 1-based 顺序。
- `block_start` 和 `block_end` 是精确内容范围；`paragraph_start` 和 `paragraph_end` 在 Chunk 不含段落时可以为空。
- `block_start_offset` 和 `block_end_offset` 是首尾 Block `clean_text` 内的0-based半开区间，支持精确回查超长 Block 的分段。
- `chunking_schema_version` 和 `chunk_config_sha256` 固定切分算法与参数来源。
- Chunk 不跨章节边界；过长章节只在章节内部继续切分。
- `text` 按块顺序拼接 `clean_text`，用于引用。
- `embedding_text` 可以拼接页面标题和章节路径用于检索，但不得替代引用文本。
- `content_sha256` 是 `text` 的哈希。

### 7.5 文本关系与字段来源

```text
原始 HTML
  -> raw_text
  -> clean_text
  -> Chunk.text
  -> embedding_text
```

- 普通文本只统一换行、非断行空格和连续空白，不改文字含义。
- 代码块不折叠空格、不改缩进、不增加或删除代码。
- `Chunk.text` 是最终引用文本；`embedding_text` 只用于检索。
- 页面标题、章节层级、anchor 和可见正文来自真实 HTML。
- 安全路径、哈希、顺序、ID、Chunk 边界和导入时间由程序生成。
- 模型不得生成或修改来源、版本、URL、路径、许可、标题、anchor、哈希、ID 或内容位置。

### 7.6 检索结果

```text
chunk
score
rank
```

### 7.7 模型回答草稿

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

### 8.0 可复现语料制品

Git保存确定性 `data/corpus-snapshot.zip` 和严格清单，不保存展开后的HTML目录。归档包含25个正文页面和1个许可证据页；整体与逐文件SHA-256均固定。

恢复流程先完整验证归档身份、成员集合、安全POSIX相对路径、普通文件类型、字节数和哈希，再写入临时目录并移动到原始HTML根。已有 `html/` 或 `license/` 时拒绝覆盖。

模型资产仍不进入Git。`fetch_embedding_model.py --restore` 只恢复固定完整revision和文件allowlist，并与已提交模型报告比较；`build_local_index.py --restore` 使用恢复语料和模型离线重建，保留历史构建报告。

首批输入为 Python 官方 Sphinx HTML。

解析器接口：

```python
class PythonDocsHtmlParser:
    def parse(self, html: str) -> ParsedDocument:
        ...
```

解析器只接收 HTML 字符串，不接收文件路径或 URL，不访问文件系统或网络。结构失败抛出 `DocumentParseError`，稳定错误码为 `DOCUMENT_PARSE_ERROR`。

解析步骤：

1. 使用 Beautiful Soup 和标准库 `html.parser`。
2. 通过版本化选择器 allowlist 定位唯一主内容区域，首批候选为 `main[role="main"]`、`div.body[role="main"]` 和 `div.document div.body`。
3. 只读取唯一主内容区域；找不到或出现多个不等价区域时失败。
4. 删除 `script`、`style`、`noscript`、`template`、导航、页脚、搜索表单、按钮、目录抽屉和无正文控件。
5. 去掉 Sphinx permalink 的显示字符，但先保留真实 anchor。
6. 保留 `h1`～`h6` 层级及元素 anchor。
7. 保留正文段落、嵌套列表、提示块、定义列表、代码块、引用块和必要表格文本。
8. 保留链接的可见文字，但不访问 `href`；图片只保留非空 `alt`，不读取 `src`。
9. 普通文本合并连续空白；代码块保持内容和缩进。
10. 给内容块和段落分别分配稳定的 1-based 顺序号。
11. 保存原始 HTML 哈希和清洗后内容哈希。

清洗器不访问 HTML 中的外部链接，不执行脚本，也不根据页面内容读取其他路径。

以下情况导致整份文档失败，且不生成部分 Chunk：

- 主内容区域缺失或歧义。
- `h1` 缺失、为空或与 `expected_title` 不一致。
- 清洗后没有正文块。
- 需要引用的章节没有真实 anchor。
- anchor 重复，无法唯一定位。
- HTML 提供的 canonical URL 与 manifest 的 `source_url` 不一致。
- 未处理的未知结构仍含正文，可能造成静默内容丢失。
- 文件无法按预期编码读取。

标题层级跳跃只记录结构警告，不单独导致失败。正式导入官方快照前，必须先用已批准语料验证主区域选择器和结构规则。

固定 Block 映射：

- `h1`～`h6` 只更新标题路径和章节 anchor，不单独生成正文 Block。
- 普通 `<p>` 生成 `paragraph`；`paragraph_order` 只统计最终输出的 `paragraph` Block。
- 每个 `<li>` 生成一个 `list_item`，只提取自身直接内容；嵌套 `<li>` 按层级单独生成。
- `<pre>` 生成 `code`，内容和缩进保持不变。
- admonition 容器生成一个 `admonition`，标题与正文使用换行连接；其内部段落不重复生成。
- `<dt>` 生成 `definition_term` 并保留自身 anchor；`<dd>` 中普通段落继续按 `paragraph` 处理。
- 表格每个 `<tr>` 生成一个 `table_row`，单元格使用 ` | ` 确定性连接。
- `<blockquote>` 生成一个 `blockquote`；内部段落不重复生成。
- 有非空 `alt` 的 `<img>` 生成一个 `image_alt`；不读取图片。
- 聚合容器一旦生成 Block，其已消费的后代节点不得再次生成 Block。

### 8.1 单文档安全导入与身份生成

`SingleDocumentIngestor` 负责把一条已验证的 `SourceManifestEntry` 绑定到真实 HTML：

1. 先执行 manifest 的纯词法路径校验。
2. 使用允许根目录和 `resolve(strict=True)` 得到真实路径；真实路径必须仍在根目录内且是普通文件。
3. 按二进制读取并计算 SHA-256；与 `raw_sha256` 不同则整份文档失败。
4. 严格按 UTF-8 解码；不猜测编码。
5. 调用纯 HTML 解析器。
6. 校验页面 `h1` 等于 `expected_title`；HTML 存在 canonical URL 时，它必须等于 `source_url`，或严格对应 Python 官方语言无关 `/3/` 文档路径。
7. 通过固定 UUIDv5 输入生成 Snapshot ID 与 Block ID，再构造不可变结果。

身份和哈希规则：

```text
snapshot_id = UUIDv5(namespace, source_id + raw_html_sha256)
block_id    = UUIDv5(namespace, snapshot_id + parser_schema_version
                    + block_order + block_type + anchors + clean_text_sha256)
```

`cleaned_content_sha256` 对页面标题和清洗后 Block 的规范 JSON 计算。键顺序、列表顺序、UTF-8 编码和分隔符固定，因此相同输入得到相同身份；获取时间和本地导入时间不参与内容身份。

错误对象只暴露稳定错误码、来源标识和最短原因，不包含原始 HTML、正文、密钥或允许根目录外的绝对路径。

Python 官方简体中文页面当前把 canonical 指向同一页面的语言无关地址。例如：

```text
source_url: https://docs.python.org/zh-cn/3.14/library/venv.html
canonical:  https://docs.python.org/3/library/venv.html
```

仅当协议为 HTTPS、主机仍为 `docs.python.org`、无凭据/查询/片段，且去掉 `source_url` 的 `/zh-cn/{python_version}/` 前缀后与 canonical 的 `/3/` 后缀完全一致时才接受。只比较文件名或允许任意同域 URL 都不安全。

### 8.2 Manifest 读取与整批预检

`load_source_manifest()` 只读取允许根目录内的 UTF-8 `.json` 相对路径，随后执行严格 JSON 与 Pydantic 校验。它不访问网络，也不接受 HTML 页面指定其他文件。

`CorpusIngestor` 按以下边界工作：

- 先在内存中验证 manifest 中的全部来源；任一失败则不返回部分语料。
- 预检阶段不写索引、不替换活动语料，也不调用 Embedding 或生成模型。
- manifest 规范哈希按 `source_id` 排序，避免输入数组顺序改变语料身份。
- `corpus_id` 同时绑定 manifest 哈希和解析器 schema 版本。
- 与活动 manifest 完全相同时返回 `UNCHANGED`，但仍重新读取并验证实际文件，防止本地文件被替换后静默跳过。
- 同一 `source_id` 若对应不同 `raw_sha256`，判定来源身份冲突。
- 内容变化必须使用新的 `source_id`；同一 manifest 仍只允许一个活动 `(document_key, python_version)`。

当前批量结果仅表示“全部文档已安全解析并可进入后续阶段”，不等于 Chunk 已切分或索引已持久化。

## 9. Chunk 策略

基线采用章节感知切分：

- 先按标题层级和段落边界分组。
- 单个 Chunk 目标上限为 `520` 个字符。
- 相邻 Chunk 使用最多 `80` 个字符的完整Block重叠。
- 单个段落超过上限时，再按句子或安全字符边界切分。
- 标题路径加入 `embedding_text`，引用 `text` 保持原文。
- 代码块尽量整体保留；过长时记录拆分。

这些值是基线参数，不是假定最优。优化阶段使用相同评估集比较 Chunk 大小、重叠和标题拼接策略。

确定规则：

- 长度按 Python `len(str)` 计算，Block 间 `\n\n` 计入上限。
- Chunk 不跨 `section_anchor`。
- 普通超长文本按换行、句末、空白、硬边界依次拆分。
- 代码优先按完整行拆分，单行过长才硬切。
- 同一 Block 的相邻分段不添加分隔符；不同 Block 使用 `\n\n`。
- 重叠只复用同章节内完整、未拆分且总长度不超过80字符的 Block 后缀。
- `text` 只含清洗后的引用正文；`embedding_text` 使用真实 `section_path` 前缀。
- Chunk ID 绑定 Snapshot、chunker schema、配置哈希、顺序、精确范围和内容哈希。

完整合同、夹具和真实分布见 `docs/CHUNKING_DESIGN.md`。

该配置由固定 BGE tokenizer 的无截断审计确定。旧 `800/120/400` 基线有94/974个输入超过512 tokens；新 `520/80/260` 基线生成1359个 Chunk，最大460 tokens，零超限。

## 10. Embedding 接口

业务层只依赖有序 Provider 与无截断 token 计数器：

```python
class EmbeddingProvider(Protocol):
    def embed_passages(
        self,
        texts: Sequence[str],
        *,
        batch_size: int,
    ) -> Iterable[Sequence[float]]:
        ...

    def embed_query(self, text: str) -> Sequence[float]:
        ...

class TokenCounter(Protocol):
    def count_tokens(self, text: str) -> int:
        ...
```

已固定合同：

- FastEmbed `0.8.0`。
- 模型 `BAAI/bge-small-zh-v1.5`。
- 实际 Hugging Face 来源 `Qdrant/bge-small-zh-v1.5`。
- ONNX Runtime CPU。
- 向量维度 `512`。
- 最大输入 `512 tokens`，批次基线64。
- 模型完整 commit SHA、模型资产规范哈希、MIT许可和缓存安全相对路径进入 `EmbeddingConfig`。
- 普通运行使用 `local_files_only=True`；不自动联网或回退下载。
- 文档使用 `passage_embed()`，问题使用 `query_embed()`；首版不手工添加指令前缀。
- 全部输入先用同一 tokenizer 关闭截断计数；任一超限时不调用 ONNX、不写索引。
- 输出数量必须匹配；每个向量转 `float32` 后检查维度、有限值和非零范数，再L2归一化。

FastEmbed 默认会静默截断，因此不能直接用于项目上限校验。固定模型资产已获批准并完成下载、哈希和本地构建。完整合同见 `docs/EMBEDDING_INDEX_DESIGN.md`。

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

索引身份分两层：

- `IndexSpecification` 保存语料、解析器、Chunk、Embedding、维度、距离和 payload schema；规范哈希生成 fingerprint 与 UUIDv5 `index_id`。
- `IndexManifest` 保存一次物理构建的 `build_id`、collection、时间、point 数和 Qdrant Client 版本。

Qdrant point ID 使用 `chunk_id`。`payload-v1` 保存引用与来源追踪字段，不保存 `embedding_text`、原始 HTML、绝对路径或模型输出。

首版不在活动 collection 上原地更新。新 collection 完整写入并验收后，使用同目录 `active-index.json` 临时文件和 `os.replace()` 激活。旧索引在最终替换前保持不变；清理旧 collection 是独立维护动作。本地 Qdrant alias 不作为唯一活动真相。

索引配置、Manifest、指针或物理 point 不一致时拒绝查询。完整合同见 `docs/EMBEDDING_INDEX_DESIGN.md`。

真实基线已完成：1359个512维point与payload写入活动collection，构建耗时39.052秒；point数、唯一ID、payload、自查询和Python版本过滤全部通过。相同规格复验返回 `UNCHANGED`，没有重新生成向量。索引本体位于Git忽略目录；构建证据保存为 `data/index-build-report.json`。

## 12. 检索

固定输入：

- 问题非空、无首尾空白且最多500字符。
- `top_k=5`。
- Python版本只允许 `3.13`、`3.14` 或未指定。
- 问题明确指定版本时使用Qdrant精确元数据过滤。
- 问题未指定版本时允许检索 `3.13` 和 `3.14`，回答层检查版本冲突。

活动索引必须在查询前通过Manifest、collection、Cosine配置、维度和point数校验。每条结果必须保留rank、Cosine分数、真实 `payload-v1`、检索原因和程序生成引用URL。point ID、payload Chunk ID、Chunk配置或版本不一致时返回索引一致性错误。

固定稠密基线只执行单一向量检索，15题命中10题，`Recall@5=66.7%`。BGE中文查询指令没有改善。按PRD允许的失败后优化路径，首版生产检索使用：

1. 指定版本时，元数据已执行精确过滤，因此从向量查询文本移除冗余 `Python 3.13/3.14` 字样。
2. 只从用户原文提取明确出现的ASCII代码标识符。
3. payload文本匹配结果仍使用同一查询向量按Cosine排序，最多占2个位置。
4. 用稠密结果去重补满5条。
5. 每条结果记录 `identifier` 或 `dense`，便于解释排名来源。

该规则不猜答案、不生成同义词、不调用模型改写查询。优化后15题命中13题，`Recall@5=86.7%`。

拒答阈值不凭经验写死：

1. 建立独立校准问题，不计入最终固定评估。
2. 观察可回答和不可回答问题的最高分分布。
3. 选择并记录阈值。
4. 固定阈值后运行最终评估。

首个分数阈值实验已执行，但没有通过锁定评估。24题校准集上的最佳阈值为 `0.6187245534246643`；全新20题评估集的可回答召回和拒答准确率都只有70%。因此该阈值不进入生产配置，代码中只保留为必须显式传入的实验策略。详细失败见 `docs/EVIDENCE_CALIBRATION.md`。

检索结果顺序、分数、过滤条件、检索原因和Chunk ID写入评估结果。详细合同与报告见 `docs/RETRIEVAL_EVALUATION.md`。

## 13. 回答与引用

问答服务流程：

1. 校验问题。
2. 生成问题向量。
3. 检索 `top_k` 证据。
4. 由MiMo基于受限证据选择回答、拒答或冲突状态。
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

版本处理：

- 用户明确比较3.13和3.14时，分别过滤检索并平衡合并证据。
- 证据足以分别说明时输出 `answered`，正文明确标记各版本。
- 用户未限定版本，且证据不兼容、无法安全给出单一结论时输出 `conflict`。

处理：

- 不静默选择一个版本。
- 分别说明各版本结论。
- 引用必须直接支持版本结论；一条版本变更说明可同时明确新旧行为。
- `conflict` 必须引用至少两个版本的 Chunk。
- 必要时要求用户明确版本。

冲突识别由证据约束 Prompt 和结构化输出完成，不引入额外分类模型。真实显式版本比较人工复核3/3；机器可读 `conflict` 仍只有自动合同测试，没有稳定真实基线。

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

方向C已获批准并实现。模型输出合同固定为：

- `status`：`answered`、`refused` 或 `conflict`。
- `answer`：简体中文回答或拒答说明。
- `citation_ids`：只能复制本次检索结果中的Chunk ID。

程序严格解析单个JSON对象并校验状态组合。`answered` 必须至少选择一个Chunk；`refused` 必须不选择Chunk；`conflict` 必须至少选择两个不同Python版本的Chunk。随后程序从真实 `payload-v1` 绑定版本、精确文档发布版、章节、引用URL和原文摘录。

MiMo适配器固定最多800 completion tokens、禁用thinking、非流式且无自动重试。真实烟雾调用使用1973 total tokens并成功绑定两个官方引用。

后续锁定评估发现，模型可能正确选择 `refused`，但省略固定schema版本或返回空拒答正文。程序允许为拒答补 `schema_version="1"`、固定拒答文案和空引用；这些值不携带事实或来源。`answered/conflict` 仍严格要求正文和真实检索引用。

最终 `answering-v3` 结果：可回答召回80%、拒答准确率100%、引用绑定有效率100%，人工忠实度4/4。详细证据见 `docs/ANSWERING_EVALUATION.md`。

版本比较先暴露单路检索0/3失败，随后加入双版本平衡检索。新3题结果均为明确标版本的 `answered`，人工复核3/3，引用绑定3/3有效；旧失败报告和错误状态判定报告均保留。

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
2. manifest 只接受使用 `/` 分隔的相对路径。
3. 拒绝绝对路径、驱动器路径、UNC 路径、`..` 和空路径段。
4. 相对路径与允许根目录合并后，执行规范化和严格绝对路径解析。
5. 使用解析后的路径检查目标仍位于允许根目录内。
6. 拒绝符号链接或 Windows junction 造成的目录逃逸。
7. 首版只接受普通 `.html` 文件。
8. 输出和索引路径同样执行边界检查。
9. 存储与错误输出只使用安全相对路径，不暴露机器绝对路径。

HTML 内的 `href`、`src` 和模型输出永远不能成为本地读取路径。

### 17.1 重复导入、活动快照和来源追踪

- 同一 `source_id` 和同一原始哈希重复导入时幂等跳过。
- 相同 manifest、清洗器版本和 Chunk 参数重复导入时允许整体 no-op。
- 同一 `source_id` 对应不同原始哈希时失败。
- MVP 中每个 `(document_key, python_version)` 只允许一个活动快照。
- 同一内容出现在不同 Python 版本时允许保留，不能因内容哈希相同而跨版本合并。
- 同一来源 URL 被声明为不同 Python 版本时失败。
- 任一文档发生致命错误时，整批导入失败，现有索引保持不变。
- 新索引应先在临时位置完整构建并校验，再替换活动索引。

来源追踪链固定为：

```text
chunk_id
  -> snapshot_id
  -> source_id
  -> manifest entry
  -> relative_path + raw_sha256
  -> source_url + python_version + retrieved_at + license
```

引用 URL 由程序使用已验证的 `source_url` 和真实 `section_anchor` 组合。不得猜测或生成 anchor。

## 18. 错误模型

稳定错误码至少包含：

- `INPUT_VALIDATION_ERROR`
- `PATH_OUTSIDE_ALLOWED_ROOT`
- `SOURCE_MANIFEST_ERROR`
- `SOURCE_HASH_MISMATCH`
- `UNSUPPORTED_DOCUMENT_TYPE`
- `DOCUMENT_PARSE_ERROR`
- `CHUNKING_ERROR`
- `EMPTY_DOCUMENT`
- `EMBEDDING_ERROR`
- `EMBEDDING_INPUT_TOO_LONG`
- `VECTOR_DIMENSION_MISMATCH`
- `VECTOR_VALUE_INVALID`
- `INDEX_BUILD_ERROR`
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
- 临时目录中的 Manifest 与原子活动指针。
- 后续增加临时目录中的 Qdrant 持久化。
- 索引配置不一致。
- 假 MiMo HTTP 响应和错误映射。

### 端到端自动测试

- 使用小型自编 HTML 夹具。
- 不下载官方文档。
- 不加载真实 Embedding 模型。
- 不调用真实 API。

### 最小固定 HTML 夹具

首批使用五个自编文件：

- `valid_sphinx_page.html`：标题、段落、嵌套列表、代码、定义项、提示块、表格及页面噪声。
- `valid_sphinx_page_313.html`：与首个夹具共享 `document_key`，但使用不同 Python 版本和对照内容。
- `missing_main.html`：主内容区域缺失。
- `missing_title.html`：`h1` 缺失。
- `duplicate_anchor.html`：重复 anchor。

每个 HTML 都包含 `synthetic test fixture` 标记，并配套一个固定 JSON 期望。JSON 保存规范化文本 SHA-256；有效夹具保存页面标题、canonical URL 和完整 Block 列表；异常夹具保存 `DOCUMENT_PARSE_ERROR` 与稳定原因片段。

最低验收样例：

- 清洗后正文块顺序、类型、章节路径和 anchor 与固定期望完全一致。
- 导航、脚本、页脚和控件文字不进入结果。
- 代码内容和缩进保持不变。
- 相同输入重复解析产生相同 Block ID、Chunk ID 和内容哈希。
- 相同来源重复导入不增加 Chunk。
- 同一 `source_id` 换内容后失败。
- 3.13 和 3.14 对照页可同时存在。
- `..`、绝对路径、UNC 路径和链接逃逸均被拒绝。
- 任一文档致命失败时不产生半份新索引。
- 513 tokens 输入在调用 Embedding Provider 前失败。
- Fake Embedding 输出数量、维度、有限值、非零范数和顺序全部验证。
- Qdrant `:memory:` 支持固定排名、版本过滤和引用 URL 重建。
- 活动指针最终替换失败时，旧指针字节不变。

## 20. 评估

评估分两层：

### 20.1 检索评估

- 不调用生成模型。
- 记录 `Recall@5`、排名、分数和错误类型。
- 可以重复运行，不产生 API 费用。
- 固定集绑定活动索引fingerprint；变更语料、Chunk或Embedding后必须建立新版本，不能静默沿用旧Chunk ID。
- 稠密基线报告为 `data/retrieval-evaluation-report.json`；优化报告为 `data/retrieval-evaluation-optimized-report.json`。

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

## 21. UI、Docker和部署

本地 UI 已完成：

1. Streamlit 入口复用问答服务。
2. 页面显示答案、版本、章节、摘录、官方链接和运行追踪。
3. UI 没有索引写入、下载、上传或公开部署能力。

后续如增加 Docker 或公开部署：

1. 先确定模型资产、Qdrant 索引和语料快照的镜像或挂载方案。
2. 公开部署前检查许可、密钥、费用、限流、隐私和访问控制。

当前架构不要求 Docker，也不排除以后将 Qdrant 本地模式替换为 Qdrant Server。

## 22. 后续事项

- 扩大版本比较与机器可读冲突评估集。
- 评估相关性/Reranker组件是否值得加入。
- 决定 Docker和部署平台。

## 23. V2 生产化架构覆盖层

### 23.1 架构原则

1. **保留已验证核心**：`CitedRagService`、严格模型、引用绑定、拒答和索引一致性继续作为单一业务真相。
2. **端口与适配器**：HTTP、Qdrant Server、Embedding、生成模型和遥测是可替换边界；核心不依赖 FastAPI 对象。
3. **读写隔离**：在线问答只读；摄取、构建和发布在受保护的独立执行路径中完成。
4. **先合同后部署**：先用假服务锁定 HTTP 行为，再连接真实本地资源，最后考虑公网。
5. **可比较优化**：Hybrid/Rerank 不覆盖 Dense 基线，所有方案在同一固定集下评估。

### 23.2 分阶段拓扑

```text
Browser / P2 Agent / P3 MCP
             |
             v
      FastAPI read-only API
      health | ready | answer
             |
             v
       CitedRagService
        /           \
       v             v
Retriever ports   ModelClient port
  |       |             |
Dense   Sparse          MiMo
  \       /
   Fusion -> optional Reranker
       |
       v
Qdrant local adapter (tests)
Qdrant Server adapter (runtime)

Protected operator -> ingestion job API -> worker -> build -> validate -> publish
```

V2-A 只实现图中的只读 API，并继续连接现有核心。Qdrant Server、Sparse、Reranker、worker 和遥测在后续独立切片加入。

### 23.3 V2-A 模块

计划新增：

```text
src/cited_rag/
├── api.py          # FastAPI 应用工厂、路由、中间件和异常映射
└── api_models.py   # 仅属于 HTTP 边界的严格请求/响应模型

tests/
└── test_api.py     # 注入假服务和假就绪探针的离线合同测试
```

职责：

- `api_models.py` 不复制 `AnswerResult`；只定义 `AnswerRequest`、成功包络、健康/就绪模型和 Problem Details。
- `api.py` 通过应用工厂接收回答服务与就绪探针，测试不加载真实模型和索引。
- 路由只做校验、调用、异常翻译和响应封装，不包含检索或 Prompt 逻辑。
- `streamlit_app.py` 与 CLI 保持可运行；三种入口都复用同一核心。

### 23.4 请求生命周期

1. 中间件生成 UUID 请求 ID，并放入请求状态和响应头；日志传播留给 V2-D。
2. Pydantic 拒绝未知字段和非法输入。
3. `/v1/answers` 调用注入的同步 `CitedRagService.answer`；框架线程池负责避免阻塞事件循环。
4. 服务返回现有 `AnswerResult`，HTTP 层只增加 `schema_version` 和 `request_id` 包络。
5. 已知领域异常映射到稳定错误码；未知异常返回通用 500，不回传堆栈。安全诊断日志留给 V2-D。

首个切片不实现自动重试。现有模型客户端的重试与超时语义保持不变，避免 HTTP 层与模型层叠加重试。

### 23.5 健康与就绪

- `/healthz` 只证明进程可响应，不能初始化 BGE、Qdrant 或 MiMo。
- `/readyz` 通过独立探针检查配置和只读依赖；不得调用生成模型或产生费用。
- 未就绪返回 503，不让真实问答请求在缺失索引时进入深层调用。
- 探针返回枚举状态；绝对路径、API Key 和供应商原始错误不进入 HTTP 响应。

### 23.6 错误边界

HTTP 层使用 `application/problem+json`：

- 请求校验：422 `request_validation_failed`。
- 配置/索引/检索器未就绪：503 `service_not_ready`。
- 模型上游失败：502 `model_upstream_failed`。
- 模型超时：504 `model_upstream_timeout`。
- 未知异常：500 `internal_error`。

低证据拒答与证据冲突仍是 200 业务结果。详细合同见 `docs/API_CONTRACT_V2.md`。

### 23.7 安全边界

- API 默认监听 `127.0.0.1`，CORS 默认关闭。
- 客户端不能传模型、Prompt、温度、API Key、路径、任意 URL 或索引控制参数。
- 首个切片没有写端点，因此不接受上传和索引变更。
- 日志只记录请求 ID、状态、耗时、计数和安全错误类别；问题正文按默认策略不记录。
- 公网前必须新增身份、限流、配额、代理头信任边界、请求大小限制和密钥管理。
- 公开静态证据页不得复用实时API身份，不接受任意输入，不连接后端，并明确区分录制证据与实时推理。
- 长期公网实时问答还必须使用跨重启持久配额和费用断路器；平台预算告警或最大实例不能替代这两个边界。

### 23.8 Qdrant Server 与发布

V2-B 新增远程适配器，但保留现有本地适配器供离线测试：

- 应用配置只接受受控 URL/集合名，不能由用户请求覆盖。
- 启动时验证集合维度、距离函数、payload schema 和活动构建身份。
- 索引构建写入新构建；验证通过后再发布。继续保留项目拥有的活动构建指针，除非 Qdrant 原生发布语义经过单独验证并记录决定。
- 在线 API 使用只读凭据；worker 使用独立、最小化写权限凭据。
- Docker 数据卷、备份、重启和失败恢复必须有自动测试或可重复运行记录。

### 23.9 Hybrid 与 Reranker

V2-C拆为评估合同、Hybrid索引、可选Reranker三段。先把15题扩为50题，并固定30题development与20题locked-test；旧集合和报告不覆盖。

FastEmbed `0.8.0` 自带BM25没有中文language，且SimpleTokenizer按空白切分，不直接采用。Sparse使用确定性 `unicode-code-bm25-v1`：Han双字gram、ASCII/dotted identifier与数字token；现有mmh3生成32-bit index并在构建前执行全语料碰撞审计。文档保存BM25 TF/长度归一化部分，Qdrant `Modifier.IDF`负责IDF。

新collection使用named vectors：`dense-bge-v1`为512维Cosine，`lexical-bm25-v1`为Sparse+IDF。Dense与Sparse各预取20条，版本Filter相同；Qdrant使用显式等权 `RRF(k=2)`，最终返回5条。配置、tokenizer、平均长度和融合常量进入索引/检索身份。

Reranker候选为FastEmbed已支持、MIT且覆盖中英文的 `BAAI/bge-reranker-base`；固定候选revision `2cfc18c9415c912f9d8155881c133215df768a70`。只处理Hybrid前20，不能扩大来源。只有candidate Recall@20证明存在排序空间后才下载约1.13 GB资产；超长pair使用显式token审计与固定窗口，禁止静默截断。

四种模式输出Recall@5、MRR@5、二元nDCG@5、candidate Recall@20、分层结果、P50/P95、cold-start和资源说明。默认进入门、失败边界、回滚和审批副作用见`docs/HYBRID_RERANK_DESIGN.md` v0.4。没有锁定集收益时不启用新增复杂度。

### 23.10 摄取任务

摄取在 V2-D 之后实现，使用受保护管理面：

- API 只创建任务并返回稳定 job ID。
- worker 执行恢复/导入、清洗、切分、嵌入、写入、验证和发布。
- job 状态至少包含 queued、running、succeeded、failed；保存阶段、时间和安全失败类别。
- 相同语料 manifest 与配置产生可比较构建身份；重复请求必须定义幂等规则。
- 发布前失败不能改变当前活动索引。

### 23.11 可观测性与 CI

- 使用结构化日志传播请求 ID、job ID、index ID 和 build ID。
- OpenTelemetry span 分层为 HTTP、retrieval、rerank、generation；导出器默认可关闭，离线测试不依赖采集器。
- 指标至少覆盖请求数、状态、阶段耗时、候选数、拒答率、错误类别和 Token 计数。
- CI 普通路径运行离线测试、合同测试、静态检查和快速固定评估；真实模型评估只允许手动、有预算地运行。

### 23.12 V2-A 测试矩阵

| 层 | 验证 | 外部依赖 |
| --- | --- | --- |
| API 模型 | 严格字段、长度、枚举、包络 | 无 |
| 健康 | 无初始化、稳定响应 | 无 |
| 就绪 | ready 与安全 503 | 假探针 |
| 回答 | answered/refused/conflict 原样封装 | 假服务 |
| 异常 | 已知映射、未知脱敏、请求 ID | 假服务 |
| 回归 | 现有 220 项普通测试 | 离线 |

### 23.13 当前暂停点

FastAPI/Uvicorn、独立`.venv`、Qdrant Server、API镜像、Hybrid、可观测性、本地CI合同与有限重试均已获批准并完成。以下动作仍需单独批准：

- 触发远程GitHub Actions、修改GitHub Pages设置、push公开站点或声明在线URL。
- 继续修改系统设置、删除镜像、collection、snapshot或named volume。
- 调用真实 MiMo、下载新模型或产生费用。
- 创建云资源、写入真实数据或公开部署。

### 23.14 V2-A 实际实现

实现文件：

```text
src/cited_rag/api_models.py
src/cited_rag/api.py
tests/test_api.py
```

实现细节：

- `create_app()` 接收应用工厂和可选就绪探针；重资源只在 `/readyz` 或首次合法问答时创建，并只缓存成功实例。
- 同步路由由 FastAPI 在线程池执行；核心保持同步，不引入第二套异步业务实现。
- 服务端忽略客户端 `X-Request-ID`，每次生成新 UUID；成功问答和全部错误体与响应头保持一致。
- 请求模型使用严格 Pydantic 配置，拒绝未知字段、缺少 schema 版本、非法版本、首尾空白和超长问题。
- 中间件兜底未知异常，错误体不包含领域 `reason`、原始输入、绝对路径、堆栈或供应商响应。
- `CitedRagService.check_ready()` 委托 `QdrantRetrievalService.check_ready()`；后者检查活动指针、Manifest、Embedding 维度、collection 配置和 point 数，不生成查询向量。
- 默认没有 CORS 中间件；Uvicorn 文档命令固定 `127.0.0.1`。
- 测试使用既有 HTTPX ASGI transport；FastAPI/Starlette 的测试客户端弃用提示没有导致新增未批准依赖。

验证：29 项 API 合同测试、3 项就绪底层测试、全部 252 项离线回归通过。真实 Uvicorn 回环冒烟通过；独立工作树缺少 Git 忽略资产时 `/readyz` 正确返回脱敏 503。

### 23.15 V2-B1 服务化存储实现

V2-B1 只替换运行时向量存储，不同时容器化 API：

```text
Windows FastAPI --read-only key--> 127.0.0.1:6333
                                      |
                                      v
                           Qdrant Server container
                                      |
                                      v
                       Linux named storage/snapshot volumes
                       Docker Desktop WSL disk located on H:
```

- `qdrant_connection.py` 负责本地/Server客户端工厂；Server URL必须精确为`http://127.0.0.1:6333`，保留Client/Server兼容性检查。检索、构建和物理验证继续复用既有业务实现。
- Server URL、Key、timeout 和 profile 只来自操作员环境；HTTP 请求不能覆盖。
- `configure_qdrant_runtime.py`一次性生成`.env.qdrant-server`、`.env.qdrant-admin`和`.env.qdrant-read`；角色密钥不同、至少32字符、文件拒绝覆盖且不打印值。
- 在线进程只接收read-only key；受控构建、权限清理和备份命令单独接收admin key。
- `data/indexes/` 保留 V1 本地回退；Server Manifest 与活动指针写入独立 `data/server-indexes/`。
- 活数据使用 Docker named volume。Windows bind mount 只允许用于只读代码/模型或导出备份，不能承载 Qdrant storage。
- Compose使用专用非internal bridge，并同时把端口映射与bridge默认绑定地址固定为`127.0.0.1`；6334/6335不发布。初始internal网络虽能让容器健康，但会阻断Windows宿主机访问，故经单独批准修正。
- 容器固定unprivileged镜像摘要、UID/GID `1000:1000`、只读根文件系统、capabilities清空、no-new-privileges、1 GiB/2 CPU/512 PIDs与日志轮转；关闭CORS、telemetry、cluster和远程snapshot URL恢复。
- 项目活动指针继续是发布真相；本切片不切换到 alias。失败构建不得改写旧指针。
- 固定语料与BGE资产在`HF_HUB_OFFLINE=1`下重建1359 points；Server使用新build/collection，逻辑`index_id`保持不变。
- 运维验收脚本依次证明read-only权限、restart、无`-v`的down/up、snapshot下载校验与上传恢复；恢复到新的临时collection，不覆盖活动collection，只按精确名称清理临时collection。
- 历史机器可读报告不可覆盖；新环境显式`--restore`重跑真实验证并保留报告字节。
- V2-B1已经稳定通过；V2-B2也已把FastAPI置于只读Linux容器。两个容器通过专用bridge通信，宿主机入口继续只绑定回环。

实际验收：Qdrant `/readyz=200`；read key读操作200、三类写操作403；1359 points的配置、payload、ID、过滤与self-query通过；restart和down/up身份不漂移；9,922,560-byte snapshot恢复通过；P1 `/readyz=200`且不调用MiMo；最终300项离线测试通过。

精确版本、磁盘、迁移、恢复、验收和批准边界见 `docs/QDRANT_SERVER_DESIGN.md` v0.2。

### 23.16 V2-B2 API 容器实现

V2-B2采用固定 `python:3.14.7-slim-bookworm` digest、固定BuildKit前端和API专用44包Linux wheel锁。API镜像不含Streamlit、开发工具、模型、语料、索引或密钥；模型与Server Manifest从宿主机只读挂载。

API新增严格`container` Qdrant profile，只允许Compose DNS地址`http://qdrant:6333`；宿主机`server` profile仍只允许`http://127.0.0.1:6333`。两种边界不能静默互换。

API与Qdrant继续使用专用非internal bridge：API需要向MiMo HTTPS出站，宿主机运维脚本仍需回环访问Qdrant。API只发布`127.0.0.1:8000`，Qdrant回环端口与named volume边界不变。

API固定单worker、非root UID/GID `10001:10001`、只读rootfs、只读资产挂载、tmpfs、capabilities清空、no-new-privileges和资源上限。`/readyz`作为容器healthcheck，会验证本地模型与Qdrant，但不调用MiMo。

最终镜像大小 `123,768,630` bytes。API重启后恢复healthy；Qdrant容器身份和活动索引证据哈希不变，point数保持1359。rootfs及两个资产挂载写入被拒绝；44个运行包与锁完全匹配。精确实施、失败修正、验收与回滚见`docs/API_CONTAINER_DESIGN.md` v0.2和`data/api-container-report.json`。

### 23.17 V2-C1分层评估实现

V2-C1新增独立schema v2，不修改V1评估模型或语义哈希：

- `RetrievalEvaluationSetV2`严格固定50题、五类题型、30/20拆分、Top-5与candidate-20合同。
- `RetrievalEvaluationCaseResultV2`保存最终排名、二元相关性、首个相关排名、倒数排名、nDCG和三次warm延迟。
- `RetrievalEvaluationReportV2`重新验证总体、split、case kind聚合及150个延迟样本；伪造聚合不能通过合同。
- evaluator先执行5次warm-up，再对每题顺序执行3次；同一问题重复排名漂移或成功/失败状态漂移时安全失败。
- 当前`RetrievalResult`只暴露最终Top-5，因此candidate字段为空并带显式不可用状态；C2不得把最终结果冒充候选层。

评估脚本只读取固定本地模型、Server Manifest和Qdrant read-only接口。资源采样只执行`du`、`docker stats --no-stream`和进程线程读取；不调用回答服务。

真实结果：Dense为42/50、Recall 84.0%、MRR 0.6313、nDCG 0.6840、P95 5.304秒；当前生产路径为45/50、Recall 90.0%、MRR 0.7217、nDCG 0.7673、P95 5.802秒。详细证据见`docs/RETRIEVAL_V2_EVALUATION.md`和两份机器可读V2报告。

### 23.18 V2-C2候选索引与失败关闭发布

V2-C2新增schema v2 Hybrid Manifest、不可变Sparse词表、候选构建器和候选层。新collection从固定旧build复制Dense向量和payload，再写入Sparse；完整验证后仍保持inactive。活动指针只接受显式发布脚本，旧schema v1继续可读。

检索器对同一版本Filter分别执行Dense20、Sparse20与Qdrant RRF20，返回最终5条并保存candidate的Dense/Sparse来源排名和RRF分数。客户端对已返回结果执行`score desc, point ID asc`同分规则，但Qdrant内部Prefetch/RRF仍可能在同分名次或候选边界漂移。

development 30题三次重复通过；唯一一次locked运行由评估器检测到重复签名漂移，并在指标/报告生成前失败。发布门缺失locked证据时安全返回`passed=false`；不切活动指针，不构建或重启API。当前生产仍使用旧schema v1的`dense-plus-identifiers`。

### 23.19 V2-C2.1确定性融合提案

新检索模式`hybrid-client-rrf-v1`复用schema v2候选索引。Dense查询启用`SearchParams(exact=True)`；Sparse保持exact。两路从limit 64开始，若第20名与窗口末尾同分则倍增窗口，最大到Manifest point count；同分组完整后按score降序、point ID升序截取Top-20。

客户端使用`Fraction`和zero-based rank计算`sum(1/(2+r))`，再按精确RRF分数降序、point ID升序取融合Top-20。只对最终20个ID批量读取并验证payload。该模式使用RetrievalConfig schema v3；索引Manifest不变。

旧50题只验证重复签名稳定，不再提供发布质量。新20题`retrieval-v3`在任何查询前冻结；同集一次性比较Dense、当前生产路径和确定性Hybrid。门禁通过前活动指针和API不变。完整设计见`docs/DETERMINISTIC_FUSION_DESIGN.md` v0.2。

### 23.20 V2-C2.1确定性融合发布

活动生产检索已切换为`hybrid-client-rrf-v1`。Dense/Sparse各自完成同分边界闭合并稳定取Top-20；客户端以zero-based rank、`k=2`、等权和`Fraction`计算RRF，融合Top-20后才按ID读取payload。最终Top-5严格是candidate前缀。

旧50题只提供50/50三次稳定性证据。新V3在查询前冻结20题并一次运行三模式：Hybrid Recall@5为0.95、candidate Recall@20为1.00，当前生产基线为0.80；14项发布门全部通过。活动build为`740d893f-20e4-4677-8e7c-74a4d45de92e`，API镜像为`cited-rag-api:v2-c2-1`。

旧Dense build、旧API镜像、失败的服务端RRF报告和候选构建证据均保留。若发布后验收失败，指针可原子回到build`418359df-7c62-4345-9bfe-57459c251dd3`。C3门未过，不引入Reranker。

### 23.21 V2-D可观测性与CI实现边界

新增`observability.py`作为跨入口的手工遥测边界：OpenTelemetry API无SDK时为no-op；API启动可选择配置OTLP/HTTP trace与metrics exporter。现有request ID通过`contextvars`传播，并与trace ID写入标准logging JSON。核心业务不依赖FastAPI自动埋点，也不让Collector成为readiness依赖。

span按`HTTP/answer/retrieval/embedding/dense/sparse/fusion/generation`分层。metrics只使用route、method、状态、阶段、outcome、错误码、候选来源和Token类型等低基数标签；index/build只进入日志与span。问题、证据、回答、引用摘录、密钥、上游响应和绝对路径禁止进入全部遥测信号。

Compose可选Collector只在内部4318接收OTLP/HTTP，并将Prometheus exporter绑定到宿主机`127.0.0.1:9464`；4317/4318不发布。Collector停止或导出失败不改变业务结果。详细模块、指标、固定镜像摘要、依赖、测试与批准边界见`docs/OBSERVABILITY_CI_DESIGN.md` v0.2。

当前D1代码已按上述边界实现并通过384项离线测试。Compose中的Collector固定digest、非root、只读rootfs，只发布回环9464；API用`P1_OTEL_ENABLED=true`显式启用导出，默认关闭。运行激活已完成：Collector运行、API使用`v2-d1`且healthy；Collector停止时API health/ready/422不变，恢复后metrics可用；Qdrant容器身份与活动索引证据哈希不变。`v2-c2-1`已实际回滚验证并保留作失败恢复基线。运行证据见`data/observability-runtime-release-report.json`。

CI使用Windows CPython 3.14.3运行完整离线测试、编译、依赖和Git边界检查；固定fake Embedding/Qdrant/Model smoke输出Pydantic验证JSON；Ubuntu只构建固定API镜像且不push。官方Action使用完整commit SHA，workflow只授予`contents: read`，不使用业务secret或`pull_request_target`。D2本地等价命令已通过，状态为`workflow-ready`；仓库未发布前不能声称远程CI绿色。

D3有限重试已实现。MiMo适配器只对固定HTTP/连接阶段白名单做一次重试；每个逻辑请求最多两次物理尝试，读取/写入超时和模型输出合同错误不重试。退避与`Retry-After`均有2秒上限，总时限为单次超时加2秒；同一请求对象复用相同请求体，潜在计费不确定性显式记录。

模型响应和模型错误均携带严格尝试记录；回答服务把物理尝试写入`rag.model.calls`与`rag.model.attempt`，只在确实安排第二次调用时增加`rag.model.retries`，逻辑完成继续由`rag.model.completed`记录。离线fake smoke覆盖HTTP白名单、连接阶段、读取超时、非法JSON、总预算和请求体一致性。独立`v2-d3`镜像完成只读运行验收后移除，活动`v2-d1`保持不变。证据见`docs/RETRY_DESIGN.md`和两份retry报告。

### 23.22 P1-F / V2-E双路径展示架构

公开首发不把FastAPI直接暴露到互联网。E1/E2把已追踪报告确定性导出为`portfolio-site/p1/`纯静态制品：固定录制案例、指标、架构、失败路径、截图与证据manifest全部在构建时生成；浏览器运行时不访问FastAPI、Qdrant、MiMo或第三方脚本。GitHub Pages只承担静态分发，现有`p1-ci.yml`继续保持`contents: read`，Pages发布权限由后续独立workflow限定到部署job。

静态层使用同源本地资产、`connect-src 'none'`、无表单/分析/追踪，并显著标注`recorded_evidence=true`与“非实时推理”。`evidence-manifest.json`把展示字段绑定到输入报告路径和SHA-256。GitHub Pages不能设置项目自定义安全响应头，因此仅靠响应头生效的防点击劫持保护属于已知平台限制，不能虚构已启用。

E3只保留条件拓扑：受控身份进入Cloud Run只读API，API用Secret Manager读取MiMo与Qdrant read-only凭据，Qdrant Cloud从固定snapshot恢复到新collection。认证、`4 KiB`候选请求体上限、可信代理、跨重启持久配额和费用断路器必须在Embedding/Qdrant/MiMo初始化前执行。初始`min=0/max=1/concurrency=1/2 GiB`仅是待资源预检验证的候选值，不是已部署规格。

免费层、价格与生命周期会变化；执行E2/E3前重新核验官方来源。完整平台比较、威胁模型、验收、回滚和批准边界见`docs/RESTRICTED_DEPLOYMENT_DESIGN.md`与`data/deployment-capability-audit.json`。

### 23.23 V2-E1本地静态证据实现

标准库导出器固定读取11份已追踪JSON报告与2张截图，把页面数据规范化写入`portfolio-site/p1/assets/evidence.json`和同源JS，并为全部输入、静态文件和生成输出记录SHA-256。`--check`只重算预期字节并比较，不启动Qdrant、Embedding或MiMo。

浏览器层只用静态HTML/CSS与DOM `textContent`渲染；CSP禁止连接、对象、frame、表单提交和远程默认资源。页面没有任意问题输入、fetch/XHR/WebSocket、iframe、分析脚本或密钥。回答、拒答与跨版本案例均为录制证据，原自动失败和事后人工复核同时保留。

现有Windows离线CI增加站点路径触发和导出一致性检查。E1本地预览绑定`127.0.0.1`并返回200；它不改变活动API/Qdrant/Collector，也不代表GitHub Pages或远程CI已经运行。

### 23.24 V2-E2最小权限发布架构

Pages发布分为`verify`与`deploy` job。`verify`读取仓库、重算证据、执行artifact安全检查并上传唯一`portfolio-site/p1/`制品；`deploy`不checkout源码，只消费已验证artifact并调用Pages部署。顶层权限为空，两个job分别只获得`contents: read`和`pages: write/id-token: write`。

PR和非`main`手工运行不能进入deploy。四个GitHub官方Action固定完整SHA；没有PAT、repository secret、第三方脚本、包安装或后端。项目站使用相对资源URL，artifact根直接映射仓库项目站根。

本地workflow实现与公开激活分开审批。V2-E2A已创建`.github/workflows/p1-pages.yml`和标准库artifact门；`data/pages-release-readiness-report.json`绑定9文件、233,881 bytes与逐文件SHA-256。Pages Source、远程run、deployment、实际URL和线上响应仍无证据。
