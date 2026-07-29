# Embedding 与本地索引设计

- 状态：`accepted`
- 版本：`0.2`
- 日期：`2026-07-28`
- 前置输入：已验证、确定性生成的 `DocumentChunk`
- 当前覆盖：接口、元数据、失败规则、固定模型资产、真实本地向量和持久化索引；不调用生成模型或外部API

## 1. 要解决的问题

Chunker 已把25份文档变成1359个token安全、可引用 Chunk。下一步不能只做“文本变向量”：

- FastEmbed 会把过长输入静默截断，可能让索引内容与引用内容不一致。
- 模型名称相同但模型文件或 tokenizer 不同，结果可能不同。
- 向量数量、顺序、维度或数值异常会让 Chunk 与向量错配。
- 索引构建中途失败时，旧索引必须继续可用。
- 检索结果必须能从 Qdrant payload 回查到真实来源和 Chunk。

因此，本阶段先固定 Embedding 与索引之间的数据合同。模型不参与来源元数据、ID、路径、引用或索引版本生成。

## 2. 已核实的本地库行为

当前安装版本：

```text
fastembed == 0.8.0
qdrant-client == 1.18.0
```

已安装 FastEmbed 的本地模型注册信息声明：

```text
公开模型名：BAAI/bge-small-zh-v1.5
实际 Hugging Face 来源：Qdrant/bge-small-zh-v1.5
主模型文件：model_optimized.onnx
维度：512
最大输入：512 tokens
许可：MIT
```

本地源码核验结果：

- `query_embed()` 与 `passage_embed()` 都可用；当前 BGE 实现最终走同一基础 Embedding 路径。
- 当前 BGE 实现会对输出做 L2 归一化。
- tokenizer 默认启用512 tokens 截断，不会自动把“发生截断”作为项目错误返回。
- `local_files_only=True` 和 `specific_model_path` 可用。
- Hugging Face 下载路径可固定 revision；FastEmbed 的 URL 回退来源不提供同等级 revision 身份。
- Qdrant 本地模式支持 collection alias，但本地实现逐条执行 alias 操作后保存，不具备失败后的事务回滚。

这些结论只来自已安装包和静态模型注册信息；没有实例化模型，没有下载模型文件。

## 3. Embedding 配置合同

建议新增严格、不可变的 `EmbeddingConfig`：

```text
schema_version = "1"
provider = "fastembed"
model_name = "BAAI/bge-small-zh-v1.5"
resolved_model_source = "Qdrant/bge-small-zh-v1.5"
model_revision = "<完整 Hugging Face commit SHA>"
model_assets_sha256 = "<本地必需模型资产清单的规范 SHA-256>"
model_license = "mit"
model_cache_relative_path = "data/models/fastembed"
dimension = 512
max_input_tokens = 512
batch_size = 64
distance = "cosine"
normalize = true
query_instruction = null
passage_instruction = null
```

字段来源：

- `model_name`、来源、维度、最大 token 数、许可：来自 FastEmbed 注册信息，并由程序校验。
- `model_revision`：后续经批准获取模型时，从固定 Hugging Face revision 得到；必须是完整 commit SHA。
- `model_assets_sha256`：程序对实际使用的 ONNX、tokenizer、配置和词表文件生成。
- 批次、距离、归一化和指令策略：项目固定配置。
- 模型不得生成或修改任何字段。

`model_assets_sha256` 的输入为：模型目录内实际加载的 `.onnx`、`.json` 和 `.txt` 文件，按安全相对路径排序，逐个记录文件 SHA-256，再对规范 JSON 求 SHA-256。这样 tokenizer 改变也会改变模型身份。

首版不直接依赖 FastEmbed 自动下载。另行批准下载后，先固定 Hugging Face commit，再保存到：

```text
data/models/fastembed/
```

正常索引和测试使用 `local_files_only=True`。如果本地资产不存在或哈希不符，失败；不在普通命令中偷偷联网或回退到 URL 下载。

## 4. Embedding 接口边界

建议接口分成两层：

```text
EmbeddingProvider
  embed_passages(texts) -> vectors
  embed_query(text) -> vector

EmbeddingService
  校验输入
  固定批次
  调用 provider
  校验数量、维度和数值
  绑定 chunk_id 与 vector
```

输入规则：

- 文档输入只使用 `DocumentChunk.embedding_text`。
- 引用仍使用 `DocumentChunk.text`，不使用加了章节前缀的 Embedding 文本。
- Chunk 按 `(source_id, chunk_order)` 稳定排序。
- 空字符串失败。
- 文档使用 `passage_embed()`；问题使用 `query_embed()`。
- 首版不手工添加查询或文档指令。当前注册信息说明前缀“不是很必要”，是否添加必须由后续固定评估证明。

Provider 只接收文本，不接收 URL、路径、许可、Chunk ID 或任意写操作参数。Embedding 模型输出只能作为向量。

## 5. Token 上限：禁止静默截断

当前字符 Chunk 上限是800；这不保证加入章节前缀后的文本少于512 tokens。

真实模型下载后，必须先做离线 tokenizer 审计：

1. 使用同一份已固定 tokenizer。
2. 关闭 tokenizer 截断，仅做计数。
3. 计数包含模型实际使用的特殊 token。
4. 逐个检查全部 `embedding_text`。
5. 任一输入超过512 tokens，返回 `EMBEDDING_INPUT_TOO_LONG`，不调用 ONNX，不写索引。

不能接受以下做法：

- 直接依赖 FastEmbed 的静默截断。
- 用字符数猜 token 数并当作最终校验。
- 截断 `embedding_text`，但继续把完整 `text` 当成已索引证据。

真实首次审计发现超限后，已回到 Chunk 配置阶段降低字符上限，生成新的 `chunk_config_sha256` 和 Chunk ID，再重新审计。旧974个 Chunk保留为失败基线证据。

## 6. 批次与输出校验

生产基线 `batch_size=64`。1359个当前 Chunk 约22批。选择64是保守 CPU 内存基线，不声明性能最优。

每批严格校验：

- 输出数量必须等于输入数量。
- 输出顺序必须保持输入顺序。
- 每个向量必须正好512维。
- 每个元素必须能安全转换为 `float32`。
- 每个元素必须是有限值，拒绝 `NaN`、`+Inf`、`-Inf`。
- 向量 L2 范数必须大于0。
- 统一转换为 `float32` 后再次 L2 归一化；查询与文档执行相同规则。
- 归一化后范数允许浮点误差，但必须接近1。

任何一批失败，整个索引构建失败。已写入的新构建 collection 仍是未激活的孤立构建；旧活动索引不变。

首版不单独保存向量缓存。相同的已完成索引身份直接返回 `UNCHANGED`；失败后重建会重新计算向量。这样先避免缓存键错误导致 Chunk 与旧向量错配。

## 7. 稳定错误码

建议本步增加：

```text
EMBEDDING_ERROR
EMBEDDING_INPUT_TOO_LONG
VECTOR_DIMENSION_MISMATCH
VECTOR_VALUE_INVALID
INDEX_BUILD_ERROR
INDEX_VERSION_MISMATCH
INDEX_CONSISTENCY_ERROR
```

边界：

- Provider 抛出的底层异常映射为 `EMBEDDING_ERROR`，不泄露绝对缓存路径。
- token 超限独立返回 `EMBEDDING_INPUT_TOO_LONG`。
- 数量不一致属于 `EMBEDDING_ERROR`。
- 维度不一致独立返回 `VECTOR_DIMENSION_MISMATCH`。
- 非有限值或零向量返回 `VECTOR_VALUE_INVALID`。
- collection、Manifest、point 数量或 payload 不一致返回索引错误。

错误可包含安全的 `chunk_id`、批次序号和短原因，不输出完整正文或绝对路径。

## 8. 索引身份与 Manifest

索引分为“确定性规格”和“一次物理构建”：

### 8.1 `IndexSpecification`

决定相同输入是否应得到同一逻辑索引：

```text
schema_version
corpus_id
source_manifest_sha256
parser_schema_version
chunking_schema_version
chunk_config_sha256
chunk_count
embedding_config_sha256
embedding_dimension
distance
payload_schema_version
```

```text
index_fingerprint = SHA256(规范化 IndexSpecification JSON)
index_id = UUIDv5(固定项目命名空间, index_fingerprint)
```

任一语料、解析器、Chunk 配置、模型 revision、模型资产、维度、距离或 payload schema 改变，都产生新索引身份。

### 8.2 `IndexManifest`

记录某次完整物理构建：

```text
schema_version
index_id
index_fingerprint
build_id
collection_name
built_at
status = "ready"
specification
point_count
qdrant_client_version
```

- `build_id` 使用程序生成 UUID。
- `collection_name` 使用安全固定前缀加 `index_id` 和 `build_id` 短串。
- `built_at` 是带时区程序时间。
- 只有全部验收通过后才能写出 `status="ready"` Manifest。
- Manifest 不保存向量，不保存绝对机器路径。

## 9. Qdrant point 与 payload

```text
point.id = chunk_id
point.vector = 512维 float32 归一化向量
```

`payload-v1` 建议只保存检索和引用需要的可验证字段：

```text
chunk_id
snapshot_id
source_id
document_key
python_version
documentation_release
chunk_order
block_start
block_start_offset
block_end
block_end_offset
paragraph_start
paragraph_end
text
section_path
section_anchor
source_url
relative_path
content_sha256
chunking_schema_version
chunk_config_sha256
```

不进入 payload：

- 原始 HTML 和 `raw_text`
- 机器绝对路径
- `embedding_text`
- 模型生成内容
- API Key 或配置密钥
- 重复保存的向量

许可、获取时间和原始 HTML 哈希继续通过 `source_id -> SourceManifestEntry` 回查，不在每个 point 重复。

引用地址由程序组合：

```text
source_url + "#" + section_anchor
```

`source_url` 和 anchor 都来自已验证来源，模型不得生成或替换。

## 10. Qdrant collection 配置

生产 collection：

```text
vectors.size = 512
vectors.distance = COSINE
```

首版索引按新 collection 全量构建，不在活动 collection 上原地 upsert。原因：

- 删除过期 point 容易遗漏。
- 中途失败会留下新旧数据混合。
- corpus 或模型变更后，旧向量与新向量不能共存。

可按 payload 建立的首批过滤字段：

```text
python_version
document_key
source_id
```

是否创建 payload index 应以本地 Qdrant 支持和实际查询规模验证；1359个 point 下不是性能前提。

## 11. 原子激活

本地 Qdrant alias 不作为首版活动索引唯一真相。采用项目控制的：

```text
data/indexes/active-index.json
```

构建流程：

1. 计算 `IndexSpecification`、fingerprint 和 `index_id`。
2. 若活动 Manifest 与规格完全一致，重新检查 collection、point 数和配置；全部一致时返回 `UNCHANGED`。
3. 创建带新 `build_id` 的非活动 collection。
4. 分批计算、校验并 upsert；`wait=True`。
5. 验证 collection 向量配置、point 总数、point ID 唯一性和固定检索样例。
6. 写新的 `IndexManifest` 临时文件并同步关闭文件。
7. 使用同目录 `os.replace()` 原子替换 `active-index.json`。
8. 切换成功后，新 collection 才是活动索引。

失败规则：

- 第7步以前失败：旧指针不变。
- 第7步失败：旧指针不变。
- 新失败 collection 可保留为孤立构建，后续显式清理；构建流程不自动删除旧活动 collection。
- 指针指向的 Manifest、collection 或规格不一致时拒绝查询，返回 `INDEX_CONSISTENCY_ERROR`。

`active-index.json` 只保存：

```text
schema_version
index_id
build_id
collection_name
manifest_relative_path
index_fingerprint
```

`manifest_relative_path` 必须是索引根目录内的安全相对 `.json` 路径。

## 12. 重复构建和版本冲突

- 活动索引规格完全相同且校验通过：`UNCHANGED`，不重复 Embedding。
- 相同 `index_id` 但 Manifest 或 collection 内容不一致：`INDEX_CONSISTENCY_ERROR`，不覆盖。
- corpus、Chunk 配置或模型资产不同：生成新 `index_id`，全量构建新 collection。
- collection 中存在未知 point、少 point、重复 Chunk 身份或 payload 哈希不符：构建失败。
- 3.13 与3.14 point 同时保留；查询可按 `python_version` 过滤。
- 不跨版本去重，即使文本和向量相同。
- 旧 collection 的清理是独立维护动作，不属于索引构建成功路径。

## 13. 最小离线验收夹具

确认后实现以下小型自编夹具。生产维度仍为512；测试 Fake 使用3维，便于人工核对。

### 13.1 Fake Embedding

固定输入：

```text
chunk-a -> [1.0, 0.0, 0.0]
chunk-b -> [0.0, 1.0, 0.0]
chunk-c -> [1.0, 1.0, 0.0]
query-a -> [1.0, 0.0, 0.0]
```

验收：

- `batch_size=2` 时三条输入分成2批，输出仍按 a、b、c。
- `chunk-c` 被规范化为约 `[0.7071, 0.7071, 0.0]`。
- 假 Provider 返回少一个向量时，整批失败。
- 2维、含 `NaN`、含 `Inf`、零向量分别失败。
- 假 tokenizer 报513 tokens 时，在调用 Provider 前失败。

### 13.2 Qdrant `:memory:`

写入三个 point：

```text
chunk-a: Python 3.14, vector [1, 0, 0]
chunk-b: Python 3.13, vector [0, 1, 0]
chunk-c: Python 3.14, normalized [1, 1, 0]
```

查询 `[1, 0, 0]`：

- 无过滤时 `chunk-a` 排名第一。
- 过滤 `python_version="3.13"` 时只返回 `chunk-b`。
- 返回 payload 可用 `source_url + section_anchor` 重建固定引用。

### 13.3 Manifest 与原子切换

- 改 corpus、Chunk 配置、模型 revision、模型资产哈希、维度或 payload schema，fingerprint 必须改变。
- 同一规格重复计算，fingerprint 和 `index_id` 必须相同。
- 旧活动指针存在时，模拟 upsert 或验收失败；旧指针字节完全不变。
- 成功时只在最终一步替换指针。
- 活动索引完全一致时返回 `UNCHANGED`，Fake Provider 调用次数为0。
- 指针路径穿越、Manifest 不匹配和 point 数不匹配全部拒绝。

普通测试只使用 Fake、`QdrantClient(":memory:")` 和测试临时目录，不访问网络、不加载 BGE、不写生产索引。

## 14. 短例子

输入：

```text
chunk_id: 123e...
embedding_text: Python 教程 > 控制流

if 语句用于条件分支。
```

Embedding 后：

```text
point.id: 123e...
point.vector: [512维 float32]
payload.text: if 语句用于条件分支。
payload.section_anchor: if
```

引用时：

```text
展示正文：payload.text
打开来源：payload.source_url + "#if"
```

章节前缀只帮助检索，不冒充原文引用。

## 15. 已确认基线

学习者已批准以下最小基线：

1. 使用固定 Hugging Face commit，不允许 FastEmbed 在正常运行时自动联网或回退下载。
2. 真实模型到位后，先做无截断 tokenizer 审计；任一输入超过512 tokens 就回到 Chunk 阶段调整，不接受静默截断。
3. 批次基线为64，向量转 `float32` 后统一 L2 归一化，Qdrant 使用 Cosine。
4. payload 使用 `payload-v1` 最小字段集；许可和获取时间通过来源 Manifest 回查。
5. 使用 `active-index.json + os.replace()` 激活新索引，不把本地 Qdrant alias 当作唯一真相。
6. 先只实现 Fake Embedding、Qdrant `:memory:`、Manifest 与临时指针测试；不下载模型、不写真实索引。

## 16. 离线实现与验证

已实现：

- 严格、不可变的 `EmbeddingConfig`、`IndexSpecification`、`IndexManifest`、`ActiveIndexPointer` 和 `ChunkPayload`。
- Provider 无关的 `EmbeddingService`：全量 token 预检、稳定排序、固定批次、数量检查、512/测试维度检查、`float32` 转换、有限值检查和L2归一化。
- 确定性 Embedding 配置哈希、索引 fingerprint 和 UUIDv5 `index_id`。
- `payload-v1` 从 `DocumentChunk` 逐字段复制；不包含 `embedding_text`、原始 HTML、绝对路径或模型生成元数据。
- 不可变 build Manifest、安全相对路径、Manifest/指针交叉检查及同目录 `os.replace()` 活动指针替换。
- 自编3维 Fake Embedding 固定夹具和 Qdrant `:memory:` 检索。

新增25项离线测试覆盖：

- 两批输出顺序和归一化结果。
- 513 tokens 在 Provider 调用前失败。
- 输出数量、维度、`NaN`、`Inf` 和零向量失败。
- 模型 revision、资产哈希和批次改变配置哈希。
- 语料、Chunk、Embedding 或维度改变索引身份。
- payload 来源追踪和禁入字段。
- Manifest/指针往返、路径穿越和失败替换保留旧指针。
- Qdrant 内存检索排名、Python版本过滤和引用 URL 重建。

此处是接口阶段的离线验收记录；真实适配器与持久化构建结果见第18节。检索服务仍未实现。

## 17. 固定模型资产与真实 tokenizer 审计

学习者另行批准模型网络访问与约90 MB下载后，已完成：

```text
Hugging Face仓库：Qdrant/bge-small-zh-v1.5
完整revision：46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59
许可：MIT
必需文件：5
总字节：95,221,432
模型资产规范SHA-256：
dea3d1b18367c7734c34cdcdc01d4cc78ccf8f591fceb7e74d6e272e8f8e4133
```

模型缓存位于 Git 忽略的 `data/models/fastembed/`。可提交的逐文件大小和 SHA-256 见 `data/model-assets.json`。获取脚本固定仓库、revision、许可、文件 allowlist 和预期大小；不同内容拒绝。

使用 FastEmbed 同一 tokenizer，先确认其配置截断为512，再调用 `no_truncation()` 和 `no_padding()`，对当前974个 `embedding_text` 逐条计数：

```text
中位：329 tokens
P90：507
P95：544
P99：606
最大：694
超过512：94
```

结果为失败，已按合同停止；未加载 ONNX、未生成向量、未写索引。

字符配置离线比较显示：

| 配置 max/overlap/min_split | Chunk数 | 最大tokens | 超限 |
|---|---:|---:|---:|
| 800/120/400 | 974 | 694 | 94 |
| 600/120/400 | 1221 | 526 | 2 |
| 500/120/400 | 1437 | 460 | 0 |
| 520/80/260 | 1359 | 460 | 0 |
| 500/80/250 | 1395 | 453 | 0 |
| 480/80/240 | 1453 | 453 | 0 |

学习者已确认 `520/80/260`。最终真实复验：

- 全部真实输入低于512，最大460，保留52 tokens余量。
- 参数保持约15%重叠和50%最小拆分位置，比例与原基线接近。
- 比 `500/80/250` 少36个 Chunk，减少后续向量计算和索引体积。
- 5003个 Block生成5082个片段和1359个 Chunk；349个 Chunk使用完整Block重叠。
- Chunk字符中位416、P99 519、最大520；token中位241、P99 407、最大460。
- 新配置哈希为 `ff8d07e2916a175093ce9c06920013dda95e6ce61036ece84ac34e614c9b28b4`。

复验报告保存为 `data/embedding-token-audit-v2.json`，状态为 `passed`。本步仍未运行 ONNX、生成真实向量或写索引。

## 18. 真实本地向量与持久化索引

学习者另行批准后，使用固定模型资产和 `HF_HUB_OFFLINE=1` 完成真实构建：

```text
Chunk：1359
Embedding批次：64，约22批
向量：512维 float32，L2归一化
距离：Cosine
构建耗时：39.052秒
Index ID：614f6c23-7c35-5832-8086-c29651d60866
Index fingerprint：
ea641fef238f3e74d6f64fa923feb53f9a7f36d88b082f14cafdcaabb541c4cd
活动collection：cited-rag-614f6c237c35-4facb454cca4
```

物理验收：

- point、payload和唯一ID均为1359。
- collection维度为512，距离为Cosine。
- self-query最高分约1.0。
- Python `3.13` payload过滤只返回3.13 point。
- Manifest与 `active-index.json` 交叉校验通过。
- 相同规格再次运行返回 `UNCHANGED`，`embedded_count=0`，首份报告不覆盖。

真实构建首次暴露：代码Chunk可以因保真而以换行结尾，但早期 `ChunkPayload.text` 错误复用了普通元数据的trim校验。该次构建在Embedding完成、任何point写入和活动指针替换前失败，留下一个0 point非活动collection。合同已修正为“正文必须非空但不裁剪”，并增加代码尾换行回归测试；新 `build_id` 构建成功。

索引本体约10.9 MB，位于Git忽略的 `data/indexes/`。失败collection按既定规则保留，不在成功路径自动删除。可提交构建证据见 `data/index-build-report.json`。

本阶段全程离线；未调用MiMo或其他真实API。
