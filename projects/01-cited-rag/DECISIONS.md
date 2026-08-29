# DECISIONS

## D-001：P1 使用版本化官方中文技术文档

- 状态：accepted
- 决定：P1 知识库内容选择版本化官方技术文档，主要语种为简体中文。
- 原因：来源权威、版本可追踪、章节结构清楚，适合验证真实引用和版本冲突。

## D-002：语料选择 Python 3.14，并使用少量 3.13 对照

- 状态：accepted
- 决定：主语料使用 Python `3.14` 官方简体中文文档子集；少量 Python `3.13` 对应文档用于版本差异和冲突场景。
- 原因：与当前 Python `3.14.3` 工程环境和求职方向相关；官方文档能提供真实来源、许可、版本和章节元数据。
- 边界：首批具体章节、文件格式和快照日期仍需确认。

## D-003：CLI 作为 MVP 入口

- 状态：accepted
- 决定：首版使用本地 CLI；RAG 核心服务与入口分离，后续 UI 复用同一服务。
- 原因：CLI 更适合先验证导入、检索、引用、拒答、自动测试和批量评估，避免同时引入前端问题。

## D-004：UI、Docker和公开部署分阶段加入

- 状态：accepted
- 决定：核心 RAG 和固定评估达标后优先增加本地 UI；Docker和公开部署再单独评估与审批。
- 原因：UI 有求职展示价值；Docker和部署会增加许可、隐私、密钥、费用和平台问题，不应阻塞核心能力验证。

## D-005：首版生成、Embedding与存储边界

- 状态：accepted
- 决定：生成模型使用 MiMo `mimo-v2.5`；Embedding 本地运行；向量存储本地持久化。
- 原因：复用 P0 已验证的生成模型适配经验，同时控制 Embedding 费用和语料外发范围。
- 边界：未经批准不调用真实 API；Embedding 模型、库和向量存储具体实现必须先核验 Python `3.14.3` 兼容性，再提交依赖方案审批。

## D-006：首批使用官方 HTML 与确认后的质量目标

- 状态：accepted
- 决定：Python `3.14` 首批导入教程、`venv`、`pathlib`、`json`、`argparse` 和 3.14 新变化；Python `3.13` 导入新变化及少量冲突对照页面。首批格式为官方 HTML。
- 原因：HTML 能保留标题层级和章节标识，便于清洗、切分和真实引用；纯文本会丢失部分结构。
- 质量目标：引用有效率 `100%`、`Recall@5 ≥ 80%`、忠实度 `≥ 90%`、拒答准确性 `≥ 80%`。

## D-007：选择轻量、可替换的首版 RAG 技术栈

- 状态：accepted
- 决定：HTML 使用 Beautiful Soup；Embedding 使用 FastEmbed 和 `BAAI/bge-small-zh-v1.5`；向量存储使用 Qdrant Client 本地持久化模式；生成模型使用 MiMo `mimo-v2.5`。
- 原因：该组合支持中文、本地 CPU Embedding、真实向量存储和后续服务化，同时不要求首版安装 Docker 或引入 LangChain、LlamaIndex。
- 兼容性：CPython `3.14.3` 的 pip dry-run 已解析全部 50 个二进制或通用 wheel，无版本冲突。
- 边界：技术栈确认不等于安装许可；模型下载和真实 API 调用仍需单独批准。

## D-008：P1 使用独立虚拟环境和完整精确版本清单

- 状态：accepted
- 决定：使用 `projects/01-cited-rag/.venv`；生产依赖写入 `requirements.txt`，开发依赖通过 `requirements-dev.txt` 叠加；50 个直接与间接依赖全部固定精确版本。
- 原因：P1 与 P0 环境隔离；完整固定间接依赖可复现本次 Python `3.14.3`、Windows x86-64 解析结果。
- 验证：清单与实际安装版本完全一致；核心导入、Qdrant 内存检索和 `pip check` 均通过。
- 边界：安装 Python 包不代表获准下载 `BAAI/bge-small-zh-v1.5`、下载知识库语料或调用真实 MiMo API。

## D-009：导入数据使用四层真实元数据合同

- 状态：accepted
- 决定：导入数据分为 `SourceManifestEntry`、`DocumentSnapshot`、`ContentBlock` 和 `DocumentChunk` 四层。
- 来源边界：来源 ID、逻辑文档键、Python 版本、来源 URL、安全相对路径、获取时间、预期标题、许可和预期哈希来自人工确认的 manifest；页面标题、章节层级、anchor 和正文来自真实 HTML；哈希、顺序、ID、清洗文本和 Chunk 边界由程序确定性生成。
- 模型边界：模型不得生成或修改来源、版本、URL、路径、许可、标题、anchor、哈希、ID 或内容位置。
- 原因：分离人工声明、真实 HTML 和程序派生数据，才能让每条引用回查到确定文件、快照、章节和内容范围。

## D-010：引用使用有限清洗文本并保留原始快照

- 状态：accepted
- 决定：原始 HTML 文件保持不变；正文块同时保留 `raw_text` 和 `clean_text`；`DocumentChunk.text` 由 `clean_text` 确定性拼接并作为引用文本；`embedding_text` 只用于检索。
- 清洗边界：普通文本只规范换行、非断行空格和连续空白；代码块不折叠空格、不改缩进、不增加或删除代码。
- 追踪：保存原始 HTML、清洗后内容和 Chunk 文本哈希。
- 原因：引用文本需要易读，同时必须能证明没有被模型摘要或改写。

## D-011：导入采用单活动快照和整批原子更新

- 状态：accepted
- 决定：MVP 中每个 `(document_key, python_version)` 只允许一个活动快照；相同来源和哈希重复导入时幂等跳过；同一 `source_id` 对应不同哈希时失败。
- 原子性：一个 manifest 中任一文档发生致命错误，整批导入失败，现有索引保持不变；新索引完整构建并校验后才能替换活动索引。
- 版本边界：3.13 和 3.14 可以共享 `document_key`；即使内容哈希相同，也不得跨版本合并。
- 原因：防止部分成功造成知识库静默缺页，避免重复 Chunk，并保留版本冲突所需的独立证据。

## D-012：HTML 清洗使用结构 allowlist 和严格失败边界

- 状态：accepted
- 决定：只处理唯一主内容区域；保留标题、anchor、段落、嵌套列表、代码、定义列表、提示块、引用块和必要表格；删除脚本、样式、导航、页脚、搜索控件和 Sphinx UI 噪声。
- 失败边界：主内容或 `h1` 缺失、标题不符、正文为空、引用章节缺少真实 anchor、anchor 重复、canonical URL 不符或出现可能静默丢失的未知正文结构时，整份文档失败。
- 路径边界：manifest 只接受允许数据根目录内的普通 `.html` 相对路径；拒绝绝对路径、驱动器路径、UNC、`..`、符号链接和 Windows junction 逃逸。
- 测试：先使用五个自编 HTML 夹具验证，不下载真实官方语料。

## D-013：路径安全分成词法校验和文件系统校验

- 状态：accepted
- 决定：Pydantic 数据模型只执行不访问文件系统的词法校验，拒绝绝对路径、驱动器或 URI scheme、反斜杠、空路径段、`.`、`..` 和非 `.html` 后缀；导入服务再使用允许根目录、`resolve(strict=True)` 和包含关系检查处理符号链接与 Windows junction 逃逸。
- 原因：纯数据模型不能可靠判断真实文件指向；把两层校验混在一起会让 Schema 验证依赖机器目录状态，也容易产生已经完成路径安全检查的假象。
- 测试边界：模型测试覆盖词法规则；后续导入服务测试必须使用临时目录覆盖真实路径、符号链接和 junction 边界。

## D-014：固定 HTML 元素到内容 Block 的映射

- 状态：accepted
- 决定：标题只维护章节路径；普通段落、列表项、代码、定义项、admonition、表格行、blockquote 和图片 alt 分别生成确定类型的 Block。
- 去重规则：列表项只提取自身直接内容，嵌套列表项单独生成；admonition 和 blockquote 聚合为单个 Block；聚合容器的已消费后代不再次生成。
- 文本规则：admonition 标题与正文使用换行连接；表格单元格使用 ` | ` 连接；代码内容和缩进不变。
- 位置规则：`block_order` 排列全部输出 Block；`paragraph_order` 只排列最终输出的 `paragraph` Block。
- 证据：两个有效自编 Sphinx 形状 HTML 及其固定 JSON 期望覆盖上述映射；三个异常夹具固定解析失败边界。
- 原因：先固定期望再写解析器，可防止实现过程按测试结果反向修改规则，也避免父容器和子元素被重复索引。

## D-015：HTML 解析器保持纯字符串输入和中间结果边界

- 状态：accepted
- 决定：`PythonDocsHtmlParser.parse()` 只接受 HTML 字符串并返回 `ParsedDocument`；解析器不接受路径或 URL，也不访问文件系统或网络。
- 中间模型：`ParsedDocument` 和 `ParsedContentBlock` 不包含来源 ID、快照 ID 或 Block ID，不能直接写入向量存储。
- 绑定边界：只有导入服务完成 manifest、允许根目录、实际哈希、预期标题和 canonical URL 校验后，才能生成持久化 `DocumentSnapshot` 和 `ContentBlock`。
- 错误边界：结构失败统一抛出 `DocumentParseError`，错误码固定为 `DOCUMENT_PARSE_ERROR`，reason 保留最短可测试原因。
- 原因：把 HTML 结构解析与文件权限、来源真实性和持久化身份分开，便于离线测试，也防止解析器因页面中的路径或链接产生外部读取。

## D-016：快照与内容块使用可复现的 UUIDv5 身份

- 状态：accepted
- 决定：Snapshot ID 绑定 `source_id` 与实际原始 HTML SHA-256；Block ID 再绑定 Snapshot ID、解析器 schema、顺序、类型、真实 anchor 和清洗文本 SHA-256。固定项目命名空间，使用 UUIDv5 生成。
- 内容哈希：清洗后文档哈希只覆盖页面标题与按顺序排列的结构化 Block，不包含获取时间或本地导入时间。
- 原因：相同输入必须得到相同持久化身份，方便幂等导入、差异检查和引用回查；内容、解析器或位置改变时，相关身份必须改变。
- 边界：模型不参与 ID、哈希或规范化输入生成。

## D-017：Manifest 批量导入先完整预检，重复导入仍校验真实文件

- 状态：accepted
- 决定：批量导入先在内存中安全读取、校验和解析全部来源；任一来源失败则整批失败，预检阶段不写索引。manifest 规范哈希按 `source_id` 排序，语料身份同时绑定解析器 schema。
- 重复规则：活动 manifest 完全一致时返回 `UNCHANGED`，但仍重新读取文件并验证哈希、标题和 canonical URL，不能仅凭旧语料 ID 跳过。
- 冲突规则：同一 `source_id` 出现不同 `raw_sha256` 时失败；内容更新必须使用新的 `source_id`，且每个 `(document_key, python_version)` 仍只有一个活动来源。
- 原因：避免本地文件被替换后继续信任旧状态，也避免部分成功、输入顺序变化或来源 ID 复用造成不可追踪语料。

## D-018：系列版本与精确文档发布版分开记录

- 状态：accepted
- 决定：`python_version` 保存检索和冲突比较使用的系列版本 `3.14` 或 `3.13`；新增必填 `documentation_release` 保存获取时页面显示的精确发布版，本批为 `3.14.6` 和 `3.13.14`。
- 传播：`SourceManifestEntry` 和后续 `DocumentChunk` 都保存精确发布版；字段必须符合补丁版本格式并属于对应系列。
- 原因：`docs.python.org/zh-cn/3.14/` 等系列 URL 会随补丁发布更新。只记录系列版本无法准确说明本地快照来自哪次文档发布。

## D-019：简体中文来源允许严格对应的官方语言无关 canonical

- 状态：accepted
- 观察：本批25个 Python 官方简体中文页面都把 canonical 指向 `https://docs.python.org/3/...`，而下载来源是 `https://docs.python.org/zh-cn/{series}/...`。
- 决定：继续保存简体中文 `source_url` 和 HTML 的真实 canonical。canonical 可与来源完全相等，或为同一 `docs.python.org` HTTPS 主机下、文档后缀完全一致的 `/3/` 地址。
- 拒绝：不同主机、HTTP、凭据、非默认端口、查询、片段或不同文档路径全部失败。
- 原因：接受官方真实结构，同时不把校验放宽成“同域名即可”。

## D-020：首批真实语料使用精确 allowlist，本地原始快照暂不提交 Git

- 状态：accepted
- 更新：D-036批准提交确定性压缩快照；展开后的原始HTML目录仍不提交Git。
- 范围：Python `3.14.6` 简体中文22页、Python `3.13.14` 简体中文3页，另保存1个官方许可页面作为非索引证据。
- 获取边界：只访问批准的 `docs.python.org` HTTPS URL；不递归、不下载资源文件；越域重定向、非 HTML、单页超过10 MiB或覆盖已有文件时失败。
- 保存：原始 HTML 位于 `data/sources/html/`，许可证据位于 `data/sources/license/`，两者暂不提交 Git；精确 URL 清单、获取报告、Manifest和许可说明进入 Git。
- 结果：26个下载均通过边界检查，总计3,581,318字节；25份正文离线导入成功，生成5003个内容 Block。

## D-021：Chunk 使用字符上限、块内偏移和完整 Block 重叠

- 状态：accepted
- 数值更新：本决定的切分、偏移和重叠语义继续有效；`800/120/400` 初始数值已由 D-028 的 `520/80/260` 取代。
- 基线：`max_characters=800`、`overlap_characters=120`、`minimum_split_characters=400`，长度按 Python `len(str)` 计算，固定 `\n\n` 分隔符计入上限。
- 边界：Chunk 不跨真实 `section_anchor`；普通超长文本按换行、句末、空白、硬边界依次拆分；代码优先按完整行拆分，单行过长才硬切。
- 追踪：`DocumentChunk` 新增 `block_start_offset`、`block_end_offset`、`chunking_schema_version` 和 `chunk_config_sha256`，精确表示 Block 内0-based半开区间。
- 重叠：只复用同章节内完整、未拆分且总长度不超过120字符的 Block 后缀；不强行截取部分 Block，不允许只有重叠没有新内容。
- 文本：引用 `text` 只含按范围提取的 `clean_text`；`embedding_text` 使用真实 `section_path` 前缀，不调用模型。
- 身份：Chunk ID 绑定 Snapshot、chunker schema、配置哈希、顺序、精确范围和内容哈希。
- 证据：真实语料5003个 Block 中13个超过800字符，最大代码块8705字符，因此块内偏移是必要字段。

## D-022：同一 Block 分段连续拼接，不插入 Block 分隔符

- 状态：accepted
- 决定：不同 ContentBlock 之间使用固定 `\n\n`；同一超长 Block 的相邻分段若被合并到同一 Chunk，则直接连续拼接。
- 原因：块内分段只是字符范围切割。插入 `\n\n` 会改写原文，破坏偏移重建和代码保真。
- 验证：固定长文本、长代码、超长单行夹具覆盖完整重建；真实5003个 Block 全量分段无丢字。

## D-023：Chunk 基线真实输出固定为974个可追踪单元

- 状态：superseded_by_D-028
- 配置：`chunker-v1`，800字符上限、120字符完整 Block 重叠、400字符最小文本拆分位置。
- 结果：25份文档生成974个 Chunk；长度中位580、P99 799、最大800；286个 Chunk 使用重叠；Chunk ID 无重复。
- 失败修正：真实8705字符代码块暴露换行搜索上界多取一位的问题，已使用半开区间修正并加入回归测试。
- 边界：此结果只证明确定性切分和追踪正确，不证明检索效果最优；后续必须用固定评估集比较。

## D-024：Embedding 固定模型资产身份并禁止静默截断

- 状态：accepted
- 决定：`BAAI/bge-small-zh-v1.5` 使用固定的 `Qdrant/bge-small-zh-v1.5` Hugging Face完整 commit SHA；对实际加载的 ONNX、tokenizer、配置和词表生成规范资产哈希。普通运行只允许本地资产，不自动联网或回退下载。
- Token边界：真实模型到位后，使用同一 tokenizer 关闭截断逐条审计 `embedding_text`；任一输入超过512 tokens时，在推理和索引写入前失败并回到 Chunk 配置调整。
- 原因：FastEmbed `0.8.0` 默认启用512 tokens静默截断。仅记录公开模型名或只校验字符数，无法证明向量实际覆盖完整检索文本。
- 边界：模型下载仍需另行明确批准；现有974个字符 Chunk只是待 tokenizer 审计的基线。

## D-025：Embedding 输出与索引身份使用严格确定性合同

- 状态：accepted
- 决定：Chunk 按 `(source_id, chunk_order)` 稳定排序，批次基线64；输出数量必须匹配，每个向量转 `float32` 后校验维度、有限值和非零范数，再L2归一化；Qdrant使用 Cosine。
- 索引身份：`IndexSpecification` 绑定语料、解析器、Chunk、Embedding配置哈希、维度、距离和 `payload-v1`；规范哈希生成 fingerprint 与 UUIDv5 `index_id`。
- Payload：point ID使用 `chunk_id`；只复制引用和来源追踪字段，不保存 `embedding_text`、原始HTML、绝对路径或模型生成元数据。
- 原因：防止向量错位、坏数值、模型或 tokenizer 漂移，以及不同语料或配置被误当成同一索引。

## D-026：本地索引通过不可变构建和原子指针激活

- 状态：accepted
- 决定：每次物理构建使用新 `build_id` 和新 collection；完整写入并验收后，才写不可变 `IndexManifest`，最后用同目录临时文件加 `os.replace()` 替换 `active-index.json`。
- 失败边界：最终替换前任何失败都不修改旧活动指针；旧 collection 不在成功路径中自动删除；Manifest、指针或物理状态不一致时拒绝查询。
- 原因：Qdrant本地 alias实现会逐条修改再保存，不能依赖它提供失败回滚。项目自己的小型原子指针更容易固定和测试。
- 验证：临时目录测试证明最终替换失败时旧指针字节不变；Qdrant `:memory:` 测试证明3维 Fake向量、Python版本过滤和引用payload可工作。

## D-027：固定 BGE 实际资产并用真实 tokenizer 阻断超限输入

- 状态：accepted
- 模型资产：经学习者单独批准，从 Hugging Face `Qdrant/bge-small-zh-v1.5` 固定完整 revision `46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59`，下载5个必需文件共95,221,432字节；模型卡许可为MIT。
- 资产身份：逐文件SHA-256及规范资产SHA-256 `dea3d1b18367c7734c34cdcdc01d4cc78ccf8f591fceb7e74d6e272e8f8e4133` 写入可追踪报告；资产本体保存在Git忽略目录。
- 审计：使用同一 tokenizer 关闭截断和padding，对974个当前 `embedding_text` 逐条计数；94个超过512 tokens，最大694。
- 结果：严格停止真实Embedding和索引写入，没有接受FastEmbed静默截断。后续Chunk配置调整必须另行确认。

## D-028：生产 Chunk 基线调整为 tokenizer 安全的520/80/260

- 状态：accepted
- 决定：生产唯一默认配置改为 `max_characters=520`、`overlap_characters=80`、`minimum_split_characters=260`；分隔符和章节前缀规则不变。旧 `800/120/400` 作为失败基线保留，不再用于后续索引。
- 选择依据：固定 BGE tokenizer关闭截断后的候选比较中，`520/80/260` 对全部真实输入零超限，最大460 tokens，保留52 tokens余量；参数比例接近原设计，并比 `500/80/250` 少36个Chunk。
- 真实结果：5003个Block生成5082个片段和1359个Chunk；字符中位416、P99 519、最大520；349个Chunk使用完整Block重叠；Chunk ID无重复。
- Token结果：中位241、P90 346、P95 369、P99 407、最大460，超过512为0。
- 身份：新配置哈希为 `ff8d07e2916a175093ce9c06920013dda95e6ce61036ece84ac34e614c9b28b4`；配置变化按原合同生成新的Chunk ID和后续索引身份。
- 边界：本决定只批准Chunk配置调整和无截断复验，不等于批准生成真实向量、写持久化Qdrant索引或调用MiMo。

## D-029：真实本地索引使用固定资产、全量新建和原子激活

- 状态：accepted
- 决定：经学习者明确批准，使用固定模型revision与资产哈希、`HF_HUB_OFFLINE=1`、CPU和64条批次，为1359个新Chunk生成512维归一化向量；写入新Qdrant collection，物理验收后才写Manifest和原子活动指针。
- 身份：Index ID为 `614f6c23-7c35-5832-8086-c29651d60866`，fingerprint为 `ea641fef238f3e74d6f64fa923feb53f9a7f36d88b082f14cafdcaabb541c4cd`。
- 结果：39.052秒完成；1359个point、payload和唯一ID一致；self-query约1.0；Python 3.13过滤通过。相同规格复验返回 `UNCHANGED` 且 `embedded_count=0`。
- 失败证据：首次真实构建发现代码Chunk尾换行被payload trim校验误拒绝；失败发生在point写入和激活前，留下0 point非活动collection。正文payload改为只拒绝空白文本、不裁剪字符，并新增回归测试。
- 保存：约10.9 MB索引本体和活动Manifest位于Git忽略的 `data/indexes/`；可提交证据为 `data/index-build-report.json`。失败collection不在成功路径自动删除。
- 边界：本决定不批准MiMo调用、回答生成、公开部署或自动删除旧/失败collection。

## D-030：检索请求和结果绑定活动索引与真实 payload

- 状态：accepted
- 输入：问题必须非空、无首尾空白且不超过500字符；版本只允许 `3.13`、`3.14` 或未指定；首版固定 `top_k=5`。
- 索引边界：查询前校验活动指针、不可变Manifest、collection存在性、Cosine向量配置、维度和point数；查询向量维度必须与活动索引一致。
- 结果：每条结果保存连续rank、真实Cosine分数、完整 `payload-v1`、检索原因和程序组合的 `source_url#section_anchor`；point ID必须等于payload中的Chunk ID。
- 版本：问题指定版本时使用Qdrant精确元数据过滤；结果合同再次检查所有返回项版本一致。
- 错误：非法输入使用 `RETRIEVAL_INPUT_ERROR`；查询执行失败使用 `RETRIEVAL_ERROR`；索引或payload漂移使用 `INDEX_CONSISTENCY_ERROR`。
- 模型边界：模型不参与问题规范化、版本过滤、排名、来源元数据、Chunk ID或引用URL生成。

## D-031：保留稠密失败基线，采用透明标识符通道达到 Recall@5 目标

- 状态：accepted
- 固定集：15个从已验证语料人工选证据的中文问题，绑定活动索引fingerprint和一个或多个真实Chunk ID；覆盖教程、标准库、Python 3.13与3.14精确过滤。
- 稠密基线：相同语料、Chunk、模型、索引、问题集和 `top_k=5` 下命中10题，`Recall@5=66.7%`，未达到80%目标。BGE中文查询指令无收益；移除已被版本过滤覆盖的冗余版本词后为11题、73.3%。
- 优化：仅从用户原问题中提取明确出现的ASCII代码标识符；最多保留2条经payload文本匹配且仍按同一查询向量分数排序的结果，再用稠密结果补满5条。指定版本时，同时从向量文本移除冗余版本词。
- 结果：命中13题，`Recall@5=86.7%`，比稠密基线提高20个百分点并达到目标。每条结果记录 `dense` 或 `identifier` 原因。
- 安全：程序不猜测答案、不生成同义词、不使用模型改写查询；标识符必须直接来自用户文本。无标识符时退化为规范化后的稠密检索。
- 已知失败：询问模块名称属性但问题未出现 `__name__`，以及 `zip(*matrix)` 证据仍未进入前5。两题保留为真实失败，不修改答案或放宽相关证据迁就实现。
- 边界：这是PRD允许的“基线不足后评估混合检索”优化，不等于加入BM25、Reranker或生成式查询扩展；拒答阈值仍未确定。

## D-032：拒绝把单一 Cosine 阈值作为生产证据充分性规则

- 状态：rejected
- 校准实验：独立24题校准集上，阈值 `0.6187245534246643` 得到可回答召回100%、拒答准确率91.7%、平衡准确率95.8%。
- 锁定评估：不再调阈值后，使用全新20题评估集只得到可回答召回70%、拒答准确率70%、平衡准确率70%，两类均未达到80%。
- 失败原因：相似度分数有明显重叠。`range(5)`、`venv --upgrade-deps` 和Python 3.13 `Path.walk` 等语料内问题分数低于阈值；缺少完整API文档的 `logging.basicConfig`、`sqlite3.autocommit` 和 `typing.Protocol` 问题却与新变化页面获得高相似度。
- 决定：不把该阈值设为默认策略，不进入问答生产链路。实验常量命名为 `EXPERIMENTAL_SCORE_ONLY_POLICY`，`assess_evidence()` 必须显式传入策略。
- 保留证据：校准集、校准报告、锁定评估集和失败报告全部保留，不能通过回调阈值、删除难题或放宽“可回答”定义掩盖失败。
- 下一分叉：需要选择扩充语料范围、增加专门相关性/Reranker能力，或在MiMo阶段让模型基于证据执行结构化“可回答/拒答”判断并用独立集验证。以上均改变当前架构或外部调用边界，需要学习者决定。

## D-033：采用 MiMo 结构化证据判断，并由程序绑定全部引用元数据

- 状态：accepted
- 授权：学习者选择方向C，批准使用 `mimo-v2.5`，真实API费用上限为人民币5元；密钥只保存在Git忽略的P1 `.env`。
- 模型边界：MiMo只返回 `answered/refused/conflict`、回答正文和本次检索结果中的Chunk ID。URL、版本、文档发布版、章节、anchor、摘录和本地路径均不得由模型生成。
- 程序边界：Pydantic严格校验模型JSON；未知Chunk ID使用 `INVALID_CITATION_ID` 安全失败；`answered` 必须有引用，`refused` 不得有引用，`conflict` 必须引用至少两个不同Python版本。
- 调用边界：固定 `mimo-v2.5`、HTTPS、30秒超时、最多800 completion tokens、禁用thinking、非流式、无自动重试；记录供应商返回的prompt/completion/total token，不记录Key或原始供应商报文。
- 烟雾结果：1次真实调用成功，输入1830 tokens、输出143 tokens、总计1973 tokens；回答状态为 `answered`，两个引用均属于本次检索并由程序绑定到Python 3.14官方文档。
- 锁定集：新建 `answering-v1` 共10题，5题应回答、5题应拒答，绑定活动索引fingerprint；不使用已查看的单分数阈值锁定集调参。
- 当前结果：第一批5个应回答题全部正确；评估调用共9493 input tokens、662 output tokens。连同烟雾测试，已知累计6次调用、12128 tokens。
- 费用阻塞：官方公开页面未提供可核实的当前按量单价，只读控制台又被账户安全策略阻止；第二批5次调用因此暂停，不能在无法证明累计费用低于5元时继续。

## D-034：拒答允许程序补固定空值，v3锁定评估达到目标

- 状态：accepted
- 诊断：v1的3个 `MODEL_OUTPUT_ERROR` 中，复查1题稳定得到 `answer:string_too_short`；模型已输出拒答状态，但拒答正文为空。v2另发现模型省略固定 `schema_version`，以及1次独立网络失败。
- 决定：`refused` 可省略或返回空 `answer`、`citation_ids` 和固定schema版本；程序补 `schema_version="1"`、固定拒答文案和空引用。`answered/conflict` 仍必须提供非空正文和合法引用ID。
- 安全：默认值不包含事实、URL、路径、章节或模型生成来源；不能把 `answered` 降级成默认引用，也不能把结构错误伪装成回答。
- 稳定性：MiMo请求增加 `temperature=0`；最多800 completion tokens、无自动重试和严格引用子集校验不变。
- 科学边界：v1与v2失败结果原样保留；每次修正后使用全新问题集，不覆盖或重跑旧锁定成绩。
- v3结果：10题中可回答召回80%、拒答准确率100%、引用绑定有效率100%，三项达到PRD目标；17144 input tokens、624 output tokens，usage覆盖10/10调用。
- 人工复核：4个实际回答均由绑定原文直接支持，首版人工忠实度4/4。详细记录见 `docs/ANSWERING_EVALUATION.md`。

## D-035：首版CLI只开放 ask，并固定本地资产路径

- 状态：accepted
- 命令：`python -m cited_rag ask --question "..." [--python-version 3.13|3.14]`。
- 输入：问题继续由 `RetrievalQuery` 校验；版本只允许3.13、3.14或省略；CLI不接受任意索引路径、模型路径、URL或API参数。
- 组装：入口只加载P1 `.env`、已验证本地BGE资产和固定 `data/indexes` 活动索引；运行时设置 `HF_HUB_OFFLINE=1`，禁止模型下载。
- 输出：验证后的 `AnswerResult` JSON写stdout；稳定领域错误JSON写stderr。配置错误和意外错误不输出异常详情、Key或供应商响应。
- 边界：首版不在统一CLI开放下载、导入或索引写入；这些高副作用操作继续使用受控脚本。普通CLI测试注入假应用，不访问网络。
- 验证：真实CLI问答成功，返回 `ensure_ascii=False`、1个Python 3.14官方引用和1956 total tokens。

## D-036：提交确定性压缩语料快照，恢复后继续忽略原始HTML

- 状态：accepted
- 选择：学习者批准方案A；提交单个压缩HTML快照和严格恢复脚本，不直接提交展开后的26个HTML文件。
- 内容：25个Python官方简体中文正文页面和1个官方许可证据页；未压缩共3,581,318字节，ZIP为580,230字节。
- 身份：ZIP SHA-256为 `c1d3fb0a04968f8810fe71efede103c04d28bb2499ac53e690f5bbbc27d1c2a0`；清单保存全部26个安全相对路径、字节数和逐文件SHA-256。
- 确定性：成员按路径排序；固定时间戳、权限、压缩算法和级别。相同输入测试生成完全相同ZIP字节。
- 恢复安全：先校验归档整体大小和哈希、完整成员集合、路径、类型、加密标志、逐文件大小和哈希；全部通过后才恢复。拒绝路径穿越、符号链接、缺失/额外成员、篡改和覆盖已有HTML根目录。
- Git边界：压缩制品和清单进入Git；恢复后的 `data/sources/html/`、`license/`、模型资产和Qdrant索引继续忽略。
- 新环境：语料离线恢复；BGE使用固定revision在线恢复并比对已提交模型报告；索引离线重建且保留历史构建证据。

## D-037：保留版本冲突0/3结果，下一版改用双版本平衡检索

- 状态：accepted
- 固定集：`conflict-v1` 含3个Python 3.13/3.14真实 `argparse` 差异问题，绑定活动索引fingerprint；正确条件为 `conflict` 且引用同时覆盖两个版本。
- 结果：0/3；两题拒答，一题仅引用3.14并返回 `answered`；3次调用共4524 input tokens、168 output tokens、4692 total tokens，无重试。
- 根因：当前未指定版本时只做一次全库Top-5检索，不能稳定给出两个版本的直接证据。缺少3.13证据时，模型不得从3.14“新增”说明推断3.13结论。
- 决定：保留固定集和失败报告，不改题、不重跑、不只调Prompt。下一版分别在3.13和3.14过滤范围检索，程序合并平衡证据，再使用全新锁定集验证。
- 产品边界：首版普通单版本问答已达标；跨版本冲突明确列为已知限制，不把P1整体成绩误写为全部场景达标。

## D-038：显式版本比较使用 answered，并实现双版本平衡检索

- 状态：accepted
- 选择：学习者批准方案A。用户明确要求比较Python 3.13与3.14，且证据能分别说明时，状态使用 `answered`，正文必须标明版本；只有证据矛盾且无法安全化解时才使用 `conflict`。
- 原因：版本差异是可回答问题，不等于系统无法处理的冲突。强迫所有比较返回 `conflict` 会把正确答案误计为失败。
- 检索：问题显式同时包含3.13和3.14时，程序分别执行精确版本过滤检索，再以2+2+1合并为5条平衡证据；单版本和普通问题路径不变。
- 证据：`conflict-v1` 原0/3报告保留；`conflict-v2` 原自动规则仍因错误状态预期计0/3，不改写。按批准语义人工复核v2为3/3，引用绑定3/3有效。
- 调用：v2共3次、5890 total tokens；另有2次版本未明确诊断、3831 total tokens；全部无重试。
- 边界：3题人工集规模小；机器可读 `conflict` 仍有严格双版本引用合同和自动测试，但未形成稳定真实模型基线。

## D-039：Streamlit 作为本地求职展示层

- 状态：accepted
- 选择：加入 `streamlit==1.60.0`，保留 CLI；不公开部署、不加入登录、多租户或索引写入。
- 复用：页面调用现有应用工厂和 `CitedRagService`，不复制检索、模型、引用或配置逻辑。
- 启动：首次页面加载不初始化 BGE、Qdrant 或 MiMo；用户提交非空问题后才创建并缓存应用。
- 安全：引用链接、版本、章节和摘录只来自验证后的 `AnswerResult`；领域错误使用稳定文案，隐藏供应商原始响应和意外异常。
- 测试：Streamlit AppTest 注入假应用，验证初始加载无副作用、回答与引用展示、外部错误不泄露；普通测试完全离线。
- 展示：真实浏览器验证桌面和窄屏无横向溢出，示例填充和版本切换正确，官方锚点可回查，控制台无错误；保存真实带引用回答截图，SHA-256为 `6fef657899aa82e46c2c385b11c35f67e0a2ed93e2d65bf50a9f000f60de1eb5`。
- 外部调用：浏览器验收产生1次已授权真实 MiMo 问答；无自动重试，未追加其他付费调用。

## D-040：保留 V1，在独立分支执行 P1 V2 生产化升级

- 状态：accepted
- 选择：从固定提交 `dcb164e95059b060ffd6aebbaa093a7626177614` 创建 `codex/p1-production-rag-v2` 和独立工作树；V1 的代码、指标、失败报告与验收结论不覆盖。
- 原因：升级会跨越 API、存储、检索、运行环境和 CI。独立分支可保持已完成作品可演示，也避免影响主工作树中的用户改动。
- 边界：只有通过新验收的 V2 证据才写入 V2 结论；不得把计划能力写成已实现能力。

## D-041：按 P1→P2→P3 顺序构建统一 AI 研究工作台

- 状态：accepted
- 选择：先把 P1 升级为稳定知识服务；P2 再通过 HTTP 使用它；P3 最后把经过约束的能力暴露为 MCP 工具。
- 原因：P1 是后两个项目的可复用知识底座。先稳定合同和错误语义，可避免 P2/P3 直接耦合本地内部代码。
- 证据要求：每个项目都必须独立可运行、可测试、可评估；三者集成是加分项，不替代各自验收。

## D-042：V2 首个切片只实现只读 FastAPI 边界

- 状态：accepted
- 选择：首发仅含 `/healthz`、`/readyz`、`/v1/answers`；复用 `CitedRagService` 和 `AnswerResult`，HTTP 层只负责严格校验、请求 ID、异常映射和响应包络。
- 默认安全：监听回环地址、关闭 CORS、不接受上传、URL、路径、模型参数、Prompt、密钥或索引控制参数。
- 测试：注入假服务与假就绪探针；普通测试不访问网络、不加载 BGE/Qdrant/MiMo。
- 延后：SSE、反馈、摄取写接口、认证、限流和公网部署。
- 详细合同：`docs/API_CONTRACT_V2.md` v0.2。

## D-043：Qdrant Server、Hybrid/Rerank 和摄取 worker 分阶段加入

- 状态：accepted
- 选择：V2-A 不同时引入所有基础设施。顺序为 API 合同、Qdrant Server/Docker、检索消融、可观测/CI、受控部署。
- 原因：每一步都能单独回归和归因；避免 API、索引、召回和部署同时变化导致失败无法定位。
- 发布语义：远程 Qdrant 初期继续使用项目拥有的活动构建指针；是否改用原生 alias，等待单独验证后决定。
- 进度：API合同与Qdrant Server阶段已按独立批准完成；Hybrid/Rerank、可观测/CI、摄取worker和部署仍未开始。
- 费用与权限：V2-B1已取得并执行精确批准；后续安装新软件、下载模型、调用真实API、创建云资源和公开部署仍需逐项批准。

## D-044：FastAPI 使用懒加载、服务端请求 ID 和脱敏 Problem Details

- 状态：accepted
- 依赖：学习者批准并安装 `fastapi==0.141.1`、`annotated-doc==0.0.5`；已有 `uvicorn==0.51.0` 提升为直接依赖。独立 CPython 3.14.3 `.venv` 的 `pip check` 通过。
- 初始化：模块导入和 `/healthz` 不创建 BGE、Qdrant 或 MiMo 客户端；应用只在 `/readyz` 或首次合法问答时创建，且只缓存成功实例。
- 就绪：`CitedRagService.check_ready()` 只校验本地配置、固定模型资产、活动索引、collection 配置、维度和 point 数；不生成查询向量，不调用 MiMo。
- 请求身份：忽略客户端 `X-Request-ID`，每次由服务端生成 UUID；成功问答、已知错误和未知错误的响应头/错误体保持一致。
- 错误：请求错误映射 422；索引/检索不可用映射 503；模型上游失败映射 502；模型超时映射 504；未知异常映射脱敏 500。领域 reason、原始输入、路径、堆栈和供应商响应不回显。
- 线程模型：HTTP 路由保持同步，由 FastAPI 线程池执行；现有同步核心不改写为第二套异步实现。
- 测试：FastAPI/Starlette TestClient 提示迁移到未批准的 `httpx2`，因此使用既有 `httpx==0.28.1` 的 ASGI transport；29 项 API 合同、3 项就绪底层和全部 252 项离线测试通过。
- 运行：真实 Uvicorn 只绑定 `127.0.0.1` 冒烟；CORS 默认关闭。未调用 MiMo、未启动 Docker、未公开部署。

## D-045：V2-B 先迁移到回环 Qdrant Server，再容器化 API

- 状态：accepted
- 拆分：V2-B1 保持 FastAPI 在 Windows 宿主机，只把 Qdrant 切换为 Docker Server；迁移、权限、重启、快照和恢复通过后，V2-B2 才构建 API 镜像。
- 版本：实际安装 Docker Desktop `4.87.0` per-user/WSL 2；Qdrant 固定 `v1.19.0-unprivileged` 及 index digest；继续使用相邻 minor 的 `qdrant-client==1.18.0`。
- 存储：Docker WSL 数据根使用本机配置路径；Qdrant storage/snapshots 使用 Linux named volume，拒绝 Windows bind mount 活数据。
- 网络：专用非 internal bridge 只发布 `127.0.0.1:6333`；6334/6335不发布。在线 API 使用 read-only key，受控迁移使用 admin key；CORS、telemetry 和远程 snapshot URL recovery 关闭。
- 发布：V1本地索引不修改；Server使用独立活动Manifest/指针。固定语料与本地模型资产已重建1359 points，验证成功后激活。
- 数据库：V2-B1 没有持久任务状态，因此不加入 PostgreSQL；摄取 worker 设计时再评估。
- 验收：read-only count/query为200，create/upsert/delete为403；restart和down/up后身份不变；9,922,560-byte snapshot下载、上传恢复、全量验证和临时collection清理通过；P1 `/readyz` 使用read-only key返回200且未调用MiMo。
- 边界：本决定不批准 API 镜像、TLS、公网、云资源、named volume删除或MiMo调用。完整实测见 `docs/QDRANT_SERVER_DESIGN.md` v0.2。

## D-046：宿主机访问 Qdrant 使用专用普通 bridge 与双重回环约束

- 状态：accepted
- 发现：初始 `internal: true` 网络中容器健康，但 Docker 没有建立宿主机 published endpoint；Windows `127.0.0.1:6333` 连接被拒绝。internal 网络不能同时满足“宿主机 FastAPI访问容器”的B1拓扑。
- 决定：经学习者单独批准，把网络改为项目专用 `bridge` 且 `internal=false`；Compose端口显式为 `127.0.0.1:6333:6333`，bridge driver默认绑定地址也固定为 `127.0.0.1`。
- 限制：普通 bridge 技术上允许容器外连，因此同时关闭telemetry、CORS、cluster和snapshot URL recovery；容器保持非root、只读rootfs、capabilities清空与资源上限。该方案只用于单机回环B1。
- 验证：运行态 `NetworkSettings.Ports` 仅有 `127.0.0.1:6333`，6334/6335未发布，网络 `internal=false`，宿主机 `/readyz=200`。旧空internal网络已删，两个named volume保留。
- 后续：V2-B2把API也容器化后，可重新使用仅服务间可达的internal网络；不得把当前端口改为局域网或公网地址。

## D-047：历史验收报告不可覆盖，新环境用显式 restore 重跑

- 状态：accepted
- 问题：Server索引和snapshot受Git ignore保护，但四份小型验收报告进入Git。若“报告已存在”永远阻止执行，新clone的空volume无法复现构建。
- 决定：构建、权限、持久化和恢复脚本默认拒绝覆盖历史报告；操作员显式传入 `--restore` 时允许重跑真实动作，但保留已提交报告的原始字节。
- 安全：`--restore`不放宽URL、Key、collection、路径或Docker命令边界；持久化脚本仍禁止`down -v`，恢复脚本仍只删除唯一临时recovery collection。
- 结果：README的新环境路径可复现Server数据，又不会把新机器时间、build ID或snapshot哈希冒充原验收结果。

## D-048：API容器使用独立Linux wheel锁与只读运行资产

- 状态：accepted
- 基础镜像：固定Docker Official Image `python:3.14.7-slim-bookworm`及index digest；不使用Alpine，避免FastEmbed二进制栈的musl兼容风险。
- 依赖：API镜像只安装递归闭包中的44个精确运行包；版本与wheel哈希全部锁定，禁止sdist和现场编译。初始元数据审计漏掉 `httpx[http2]` 的 `h2`、`hpack`、`hyperframe`，真实 `--require-hashes` 构建安全失败后补齐，失败没有产生镜像或容器。Streamlit、PyArrow、Pandas、`pywin32`和开发依赖不进入镜像。
- 资产：固定BGE模型与Server Manifest不烘焙进镜像，只从宿主机只读挂载；镜像只包含服务代码和已提交模型资产报告。
- 配置：新增`container` Qdrant profile，只接受`http://qdrant:6333`；宿主机`server` profile继续只接受回环URL。API只接收read-only key，不接收admin key。
- 网络：B2继续使用现有专用非internal bridge。API需要MiMo HTTPS出站，且B1宿主机备份/迁移仍需回环Qdrant；本切片不同时拆分双网络。API和Qdrant分别只发布`127.0.0.1:8000`与`127.0.0.1:6333`。
- 加固：单Uvicorn worker、UID/GID `10001:10001`、只读rootfs、只读资产挂载、tmpfs、capabilities清空、no-new-privileges和资源上限。
- 供应链：Python基础镜像与BuildKit前端均固定digest；44个wheel固定版本、文件名和SHA-256。最终镜像为linux/amd64，大小 `123,768,630` bytes。
- 验收：学习者明确批准`docs/API_CONTAINER_DESIGN.md`第9节后完成。API restart恢复healthy；Qdrant容器ID/启动时间与活动指针/Manifest哈希前后不变；point数1359；全程未发送合法问答、未调用MiMo。机器可读证据为 `data/api-container-report.json`。

## D-049：Hybrid使用中文/代码Sparse与RRF，Reranker后置消融

- 状态：C1 accepted；C2 executed but release-rejected；C3仍为proposed
- 评估先行：先把15题扩为50题，固定五类题型、30题development和20题locked-test；四种模式同集报告Recall@5、MRR@5、nDCG@5、candidate Recall@20、P50/P95与资源。
- Sparse：不使用FastEmbed `Qdrant/bm25`，因为0.8.0没有中文language且SimpleTokenizer按空白切分。采用确定性Han双字gram、ASCII/dotted identifier与数字token；mmh3 index在构建前执行碰撞审计。
- 权重：文档保存BM25 TF与长度归一化，Qdrant named Sparse使用`Modifier.IDF`；Dense/Sparse各取20候选，使用显式等权 `RRF(k=2)`，不直接相加Cosine和BM25原始分数。
- 发布：新Dense+Sparse collection全量构建和验证后才切换Server活动指针；旧Dense-only collection、报告、snapshot和named volume保留。
- Reranker：候选为MIT中英文 `BAAI/bge-reranker-base` 固定revision；只有Hybrid candidate Recall@20证明相关证据已召回但排序不足后才申请下载约1.13 GB资产。当前1 GiB容器上限不先放宽，必须先测量。
- 默认门：locked质量不得退化，Hybrid至少一项主指标绝对提升0.03且P95不超过Dense 2倍；Reranker要求nDCG@5绝对提升0.03、Recall不降且P95不超过Hybrid 3倍。未过门只保留报告。
- 审批：50题评估按D-050完成；C2 Qdrant写入按D-051执行并因D-052门禁失败而未发布。C3模型下载、MiMo调用或资源调整仍未批准；最新结论见`docs/HYBRID_RERANK_DESIGN.md` v0.4。

## D-050：V2-C1冻结50题分层合同并保留简单标识符通道的非单调结果

- 状态：accepted
- 授权：学习者批准`docs/HYBRID_RERANK_DESIGN.md`第10.1节；范围限于Git工作树、现有本地模型和read-only Qdrant，不批准写索引、下载模型、安装依赖、MiMo调用或容器重启。
- 题集：`retrieval-v2`共50题，固定12个语义改写、12个精确标识符、10个语义+标识符、8个版本问题和8个已知难例；30题development、20题locked-test。语义SHA-256为`a3b30c755dc2a4036b9d715a9df2bd891bfb850ce2bc2c369b43447c2a8abd13`。
- 证据：50个唯一相关Chunk从活动1359-point Server collection人工选择并只读回查；point ID等于payload Chunk ID，题目版本与payload版本错配为0。旧15题问题原文纳入V2重新分层，但旧题集与报告原字节不变。
- 合同：V2独立模型计算Recall@5、MRR@5和二元nDCG@5，按题型和split聚合。每模式5次warm-up，50题各重复3次；重复排名或成功/失败状态漂移时安全失败。P50/P95使用nearest-rank。
- Dense结果：42/50，Recall@5 84.0%、MRR@5 0.6313、nDCG@5 0.6840、P50 4.805秒、P95 5.304秒。
- 生产路径结果：45/50，Recall@5 90.0%、MRR@5 0.7217、nDCG@5 0.7673、P50 4.807秒、P95 5.802秒。相对Dense新增4个命中、损失1个命中，净增3题。
- 非单调证据：`template-string-314`被简单标识符通道从命中变为未命中；5个最终失败全部保留。不能把该通道描述为单调安全，也不能删题或修改相关Chunk迁就实现。
- 候选边界：现有检索器只暴露最终Top-5，candidate Recall@20必须为null并带不可用状态。只有C2 Hybrid暴露独立候选层后才能测量Reranker上限。
- 资源：模型资产95,221,432字节，collection 205,628,065字节；两模式各150个warm样本，外部API调用0。cold-start受文件缓存影响，不用于模式优劣结论。
- 下一门：C2必须另行提交Qdrant写入、新collection、活动指针和API容器影响的精确审批。Reranker仍不下载，直到Hybrid candidate Recall@20证明存在排序空间。

## D-051：C2候选先评估后激活，并以当前生产路径作为发布下限

- 状态：accepted；执行后发布门失败
- Sparse身份：固定`unicode-code-bm25-v1`的NFKC、五段Han范围、双字gram、ASCII/dotted identifier、数字版本词元、三类命名空间、mmh3 x86-32 seed 0、`k1=1.2`、`b=0.75`；规范配置SHA-256为`53400f58436e2faf179eb5383aac62e63ca8ab86d161e7c8a05b413ee3b9d8a2`。
- 碰撞边界：构建前审计完整语料词表；查询时用不可变词表拒绝同hash异词伪匹配。词表hash、词元总数、文档数和Sparse配置进入索引身份。
- 构建：新collection从已验证旧collection复制Dense与payload，再加入Sparse，不重新下载或联网生成Dense。未验证的新collection不得激活；失败时只允许清理本次新建且未激活的collection。
- 发布：先跑development并冻结配置，再只运行一次locked-test。门槛通过后才切活动指针和重启API；未过门时现有生产API完全不动。
- 门槛：除相对Dense的原门槛外，locked Recall不得低于当前生产路径0.90，MRR不得低于0.6467，nDCG不得低于0.7074。复杂方案不能以低于当前生产质量的结果替换默认路径。
- 回滚：新代码必须继续读取旧schema v1；激活后验收失败时将指针切回固定旧build `418359df-7c62-4345-9bfe-57459c251dd3`并恢复`dense-plus-identifiers`。旧collection、snapshot和named volume不删除。
- 预检：固定1359 Chunk产生158,321次词元、25,836个唯一词元、118,664个Sparse非零项；空向量0、mmh3碰撞0。Docker Engine当时未运行，预检没有启动它或写Qdrant。
- 审批边界：学习者已批准`docs/HYBRID_RERANK_DESIGN.md` v0.3第10.2节；执行结果见D-052。该批准不含Reranker下载或锁定失败后的算法重设计。

## D-052：Hybrid锁定排名不稳定时失败关闭，不重跑锁定集或激活

- 状态：accepted
- 构建证据：候选collection `cited-rag-c1a14f1add33-740d893f20e4`含1359 points；Dense向量与payload从固定旧build复制，Sparse含118,664个非零项，词表25,836项，碰撞和空向量均为0。候选始终未激活。
- 身份事故：恢复预检曾因规范JSON全局使用`exclude_none=True`，让旧Embedding配置的两个`null`字段消失并短暂生成错误Dense身份。程序立即恢复固定旧指针，删除仅本次误建且未激活的collection/Manifest；随后把旧哈希语义恢复并增加冻结身份回归测试。旧活动数据没有删除或覆盖。
- development：首次运行发现Qdrant对RRF同分不保证返回顺序；加入固定`score desc, point ID asc`的客户端同分规则后，30题各3次稳定，Recall@5和candidate Recall@20均为29/30（96.67%）。此后融合参数冻结。
- locked：按合同只执行一次。评估器在报告和指标生成前检测到三次重复结果签名漂移，抛出`EVALUATION_ERROR: V2 repeated retrieval ranking changed`。没有重跑、窥测指标或用锁定集调参。
- 解释：客户端排序能稳定已返回同分项，但不能约束Qdrant内部Prefetch/RRF的同分名次、RRF分数或第20名候选边界。因此该实现不满足可复现发布合同。
- 发布结论：`data/hybrid-release-gate.json`为`passed=false`；活动指针仍指向Dense build `418359df-7c62-4345-9bfe-57459c251dd3`，API仍运行`cited-rag-api:v2-b2`且未重启。候选与失败证据保留供后续设计复盘。
- C3结论：锁定candidate Recall@20不可用，development的candidate Recall@20又不高于Recall@5，未证明有可被Reranker修复的排序空间。因此不下载1.13 GB Reranker；下一步必须先另行设计并审批确定性融合方案。

## D-053：C2.1使用exact召回、同分边界闭合和客户端Fraction RRF

- 状态：accepted；implemented；release-passed
- 根因边界：V2-C2客户端排序只能处理服务端已返回项，不能保证Prefetch/RRF内部同分名次和第20名集合。新方案不通过忽略candidate元数据或放宽稳定性守卫掩盖问题。
- Dense：固定`SearchParams(exact=True)`；Qdrant官方说明exact绕过HNSW并提供stable deterministic order，适合本项目1359-point小集合。
- Sparse：利用Qdrant Sparse always exact；Dense/Sparse均从limit 64开始，若第20名与窗口末项同分则倍增，最大到Manifest point count，闭合后按score与point ID取20。
- 融合：客户端使用zero-based rank、`k=2`、等权和`Fraction`计算RRF；最终以精确RRF分数和point ID排序。检索配置升级schema v3，索引schema v2不变。
- 评估隔离：旧50题只做稳定性回归，不再作为发布质量locked；另建查询前冻结、证据不重复的新20题`retrieval-v3`，同集一次运行三模式。
- 发布下限：Hybrid不得新增当前生产失败，Recall不得低于Dense/当前生产且至少0.80，MRR/nDCG相对生产最多下降0.02，至少一项指标相对生产提升0.03，P95不超过生产2倍。
- C3边界：只有新集candidate Recall@20比Recall@5高至少0.10且至少2题相关证据落在6～20名，才另行设计Reranker；C3必须再建新locked集。
- 审批边界：学习者已批准`docs/DETERMINISTIC_FUSION_DESIGN.md`第10节；执行未安装依赖、未下载模型、未调用MiMo、未写Qdrant或创建/删除collection。

## D-054：V3门禁通过后发布确定性Hybrid，C3继续关闭

- 状态：accepted
- 稳定性：旧50题仅验证稳定性，50/50各3次一致且不使用质量标签；新V3在查询前冻结，20题与V2问题和相关Chunk均无重合。
- 质量：V3 Hybrid Recall@5/MRR@5/nDCG@5为0.95/0.7100/0.7705，当前生产为0.80/0.6125/0.6608；candidate Recall@20为1.00，新增生产命中失败0，P95为8.011秒。
- 发布：14项门禁全部通过，活动指针切到build`740d893f-20e4-4677-8e7c-74a4d45de92e`，API镜像升级为`cited-rag-api:v2-c2-1`并恢复healthy；旧Dense build和镜像保留供回滚。
- C3：candidate与Top-5差仅0.05且只有1题位于6～20名，不满足0.10与至少2题双门；不下载Reranker。
- 边界：V3已消耗为发布locked，不得用于后续Reranker调参后再次声称locked；后续C3如重新提出，必须另建development与未使用locked集。

## D-055：V2-D先用手工稳定信号实现隐私安全可观测，再加入最小权限CI

- 状态：accepted；D1 code-implemented/runtime-pending；D2 proposed
- 顺序：D1实现JSON结构化日志、手工OpenTelemetry trace/metrics和本地Collector；D2再加入GitHub Actions；有限重试作为D3后置，不在未测量失败类别前扩大MiMo调用。
- 依赖：选择稳定`opentelemetry-api==1.44.0`、`opentelemetry-sdk==1.44.0`和`opentelemetry-exporter-otlp-proto-http==1.44.0`。不选当前pre-release的FastAPI自动埋点，避免隐私、高基数和版本边界失控。
- 隐私：问题、证据、回答、引用摘录、密钥、供应商响应和绝对路径不得进入日志、span或metrics；metrics只允许低基数标签。index/build可进日志和span，不进labels。
- 故障隔离：遥测默认可关闭；Collector不可达不影响health、ready或问答结果。OTLP端口不发布，Prometheus exporter只绑定`127.0.0.1:9464`。
- 供应链：Collector固定官方GHCR 0.159.0 index digest；GitHub官方checkout/setup-python固定完整commit SHA，workflow权限仅`contents: read`。
- 科学边界：没有可核实MiMo定价时只记录Token并标记费用不可用；没有远程Actions运行时只声称workflow-ready，不声称CI passed。
- 审批：学习者已批准第12.1节。三个直接依赖及四个递归依赖已精确安装/锁定；JSON日志、八阶段trace、低基数metrics、隐私与故障隔离测试、Collector/Compose合同已实现，384项离线测试通过。
- 运行边界：Docker Engine当前停止。既有Qdrant为`restart: unless-stopped`，启动Engine可能导致它重启，而第12.1节明确禁止Qdrant重启。因此Collector拉取、`v2-d1`构建和容器激活暂停，不能用“已批准D1”推导出违反同节禁止项的权限。
- 保留边界：尚未改变容器、写Qdrant、调用MiMo、下载模型或创建云资源；D2和D3仍须另行批准。

## D-056：Docker失效运行socket阻塞时失败关闭，不执行factory reset

- 状态：accepted；runtime-blocked
- 授权：学习者允许启动Docker Engine，并允许既有Qdrant因`restart: unless-stopped`发生一次受控重启；仍禁止Qdrant写入、删除、配置和volume变更。
- 失败：Docker Desktop等待180秒未就绪。后台精确错误为`remove .../sailor-ingest.sock: The file cannot be accessed by the system.`，发生在Engine和容器启动前。
- 处理：停止失败Docker进程；确认Ubuntu与docker-desktop WSL均为Stopped；执行`wsl --shutdown`后socket仍不可访问。非提权会话不能重启WslService。
- 决定：不使用Docker Desktop建议的factory reset，不删除run目录其他socket，不修改VHDX或named volume。要求学习者重启Windows释放失效AF_UNIX socket，之后继续同一运行验收。
- 证据：Docker VHDX大小和修改时间不变；活动指针/Manifest哈希不变；Qdrant、Collector和API容器均未启动或改变。机器记录见`data/observability-runtime-preflight.json`。

## D-057：V2-D1运行激活通过，保留Collector与API回滚基线

- 状态：accepted；runtime-activated；D2 proposed
- 运行授权：学习者允许启动Docker Engine，并允许既有Qdrant因`restart: unless-stopped`发生一次受控重启；仍禁止Qdrant写入、删除、配置修改和volume变更。Docker Desktop由学习者手工启动，Engine/Compose版本为29.7.2/5.4.0。
- Qdrant零漂移：容器ID `dab049138856613b941d31bea52846669fa25530a197251b83f398a03ad57d85` 与启动后时间保持不变；固定镜像digest、活动Hybrid collection、1359 points、活动指针SHA-256 `5a905dc41cebc1a9b40d73ef19840629ebd490398a34bfd1639bdb9f0bd54e84`、Manifest SHA-256 `4c8f38c0547fa575a8bef783a4065679153b6c3f5ec5fa86645d83f78f193697`和两个named volume均未改变。
- Collector：官方GHCR 0.159.0固定index digest，Linux/amd64镜像108,615,156 bytes；本次H盘增量503,578,624 bytes，小于512 MiB。运行容器为`10001:10001`、只读rootfs、`cap_drop=ALL`、256 MiB，仅发布`127.0.0.1:9464`，4318不发布。
- API：`cited-rag-api:v2-d1`为Linux/amd64、`10001:10001`、只读rootfs、`cap_drop=ALL`，镜像124,906,372 bytes，本次H盘增量407,826,432 bytes，小于512 MiB；FastAPI/annotated-doc/uvicorn与OTel三项直接依赖精确版本通过，`pip check`通过。
- 运行门：health/ready/OpenAPI/非法422通过；Collector可用时Prometheus `rag_*`与debug trace出现；Collector停止时health/ready/422仍通过且API不重启，恢复后metrics=200；敏感夹具日志/trace/metrics出现0次。
- 回滚：同一Compose API服务实际切回保留的`cited-rag-api:v2-c2-1`并通过health/ready=200，随后恢复`v2-d1`并healthy；Qdrant未重启。失败关闭路径不删除Collector/API镜像、collection或named volume。
- 边界：未发送合法真实问答，MiMo调用0，未下载模型、未写Qdrant、未删除collection/image/volume。D2远程CI、D3有限重试仍需另行批准。完整机器证据见`data/observability-runtime-release-report.json`。

## D-058：V2-D2采用最小权限本地可审计 CI，状态 workflow-ready

- 状态：accepted；workflow-ready；remote-unrun；D3 proposed
- Workflow：新增`.github/workflows/p1-ci.yml`，Windows job固定CPython 3.14.3并执行精确开发依赖、`pip check`、`compileall`、fake smoke、全量pytest和Git边界检查；Ubuntu job只构建固定digest API镜像，不启动Qdrant、不push。
- 安全：只使用官方`actions/checkout` SHA `3d3c42e5aac5ba805825da76410c181273ba90b1`与`actions/setup-python` SHA `5fda3b95a4ea91299a34e894583c3862153e4b97`；`permissions: contents: read`、`persist-credentials: false`、timeout和并发取消固定；不使用repository secret或`pull_request_target`。
- Smoke：`scripts/run_ci_smoke.py`固定fake Embedding、Qdrant和Model，输出经Pydantic二次验证的机器JSON；不读取`.env`、不联网、不下载模型、不调用MiMo。结果见`data/ci-smoke-report.json`。
- Git边界：`scripts/check_git_boundaries.py`拒绝追踪`.env`、私钥、模型文件、原始HTML和生成索引；本地等价命令与387项测试均通过。
- 边界：本次未创建GitHub仓库、未push、未触发远程Actions、未使用外部secret；不能将`workflow-ready`表述为`remote-passed`。D3有限重试仍需另行批准。

## D-059：V2-D3先冻结有限重试合同

- 状态：`accepted；superseded-by-D-060-for-implementation`
- 背景：当前MiMo客户端单次调用。429、部分5xx、连接阶段异常和超时的可重试性、计费与幂等语义不同；未经边界设计直接加重试会扩大费用和总时延。
- 决定：一次逻辑`generate()`最多两次物理POST，最多一次重试；HTTP只允许`408/429/500/502/503/504`，传输层只允许已确认连接/连接池阶段异常。读取/写入超时、取消、非法模型JSON、Schema和引用错误不重试。
- 等待：有效`Retry-After`只解析秒数并裁剪到2秒；缺失时固定250毫秒退避，不使用随机jitter；逻辑总预算为`model_timeout_seconds + 2 s`。
- 幂等/费用：请求体两次必须字节等价，但不伪造供应商`Idempotency-Key`；重试按at-least-once发送处理，潜在重复计费标记`billing_uncertain`，没有可信价格时继续保持`cost_available=false`。
- 观测：`rag.model.calls`按物理尝试计数，新增低基数`rag.model.retries`与`rag.model.attempt`事件；不记录问题、证据、回答、Key、响应体或绝对路径。
- 验证与回滚：实施必须只用fake provider离线测试，覆盖状态白名单、Retry-After、总时限、取消、请求体一致、错误映射和隐私；失败恢复`cited-rag-api:v2-d1`，不改Qdrant或运行卷。
- 边界：设计阶段未改代码运行行为、未安装依赖、未调用真实MiMo、未写Qdrant。实施批准语句为`批准按 RETRY_DESIGN.md 第10.1节执行 V2-D3`。

## D-060：V2-D3实施有界白名单重试并用独立镜像验收

- 状态：`accepted；implemented；fake-verified；runtime-verified`
- 实现：一次逻辑`generate()`固定最多两次物理POST；HTTP只允许`408/429/500/502/503/504`，传输层只允许连接、连接超时和连接池超时。读取/写入阶段异常、非法JSON、Schema和引用错误不重试。
- 预算：同一请求体复用；默认250毫秒，安全`Retry-After`裁剪至2秒，总预算为`model_timeout_seconds + 2 s`。不伪造`Idempotency-Key`。
- 观测：模型响应/错误携带尝试记录；`rag.model.calls`按物理尝试计数，新增`rag.model.retries`和`rag.model.attempt`。连接阶段明确未到应用时不标费用不确定；读取/写入阶段即使不重试也标记不确定。
- 验证：离线fake smoke覆盖五类序列并加入CI；独立`cited-rag-api:v2-d3`通过200/200/422及非root、只读rootfs、`cap_drop=ALL`验收。
- 回滚：临时容器验收后移除，活动`cited-rag-api:v2-d1`从未切流量，健康与身份不变。Qdrant身份、活动指针/Manifest哈希和named volume不变。
- 边界：未安装依赖、未调用真实MiMo、未发送合法真实问题、未写删或配置Qdrant、未改Docker配置、未触发远程CI。证据见`data/retry-smoke-report.json`与`data/retry-runtime-release-report.json`。

## D-061：P1-F先公开静态证据，实时问答保持受控条件项

- 状态：`design-frozen；implementation-pending；external-unexecuted`
- 公开首发：选择GitHub Pages纯静态证据页，展示固定指标、录制问答、架构、失败案例、运行报告和诚实限制；必须标注“非实时推理”，不接受任意问题、不连接FastAPI/Qdrant/MiMo、不持有密钥。
- 真实性：`evidence-manifest.json`后续把每个展示字段绑定到已追踪报告路径和SHA-256；V1、V2-C1与V2-C2.1不同题集不得拼接成单一提升值，`workflow-ready`不得写成远程CI绿色。
- 实时候选：Cloud Run + Qdrant Cloud只进入后续E3预案。资源峰值、身份、跨重启持久配额、全局费用断路器、请求体、可信代理、Secret和snapshot恢复任一未通过时不得公开。
- 平台边界：预算告警和最大实例不是硬费用上限；Qdrant免费集群存在休眠/删除生命周期。免费层与价格执行前必须重新核验。
- 分段审批：E1只在Git工作树生成静态制品；E2才允许Pages公开发布；E3另行批准账户、预算、真实调用和云资源。前一阶段批准不向后继承。
- 未选择：Render Free未证明512 MB/0.1 CPU可承载当前Embedding；Fly.io无免费层；Hugging Face Spaces受账户计划、睡眠与非持久存储假设影响，不作为默认。
- 边界：本设计未创建账户/云资源、未更改Pages设置、未push或触发Actions、未调用MiMo、未产生费用、未修改活动API/Qdrant/Collector。证据见`docs/RESTRICTED_DEPLOYMENT_DESIGN.md`与`data/deployment-capability-audit.json`。

## D-062：V2-E1使用确定性静态证据制品，不把录制结果伪装成实时服务

- 状态：`accepted；implemented；local-verified；public-unexecuted`
- 制品：`portfolio-site/p1/`只含HTML、CSS、JS、固定JSON和两张已追踪截图；页面显著标注“录制证据 · 非实时推理”，不提供表单、任意问题、API代理或第三方运行资源。
- 溯源：标准库导出器固定读取11份机器报告和2张截图，规范化生成页面数据与SHA-256清单；`--check`在离线CI中拒绝源报告与展示制品漂移。
- 真实性：三种检索仅比较同一V3新20题；跨版本案例同时保留原自动判定失败与事后人工复核。`workflow-ready`继续明确为`remote-unrun`，本地HTTP 200不声称公开可用。
- 浏览器边界：CSP设为`default-src 'none'`和`connect-src 'none'`；无fetch/XHR/WebSocket、表单、iframe、分析脚本或动态HTML注入；本地资源同源，外链只作为用户点击导航。
- 验证：新增10项合同覆盖数值、哈希、外部副作用、CSP、键盘操作、小屏响应式、本地路径与密钥泄漏；本地预览仅绑定`127.0.0.1:8765`并返回200。
- 审批边界：未安装依赖、未运行Qdrant/Embedding/MiMo、未改变Docker或活动服务、未push、未触发远程Actions、未启用Pages、未创建公开URL或云资源。V2-E2必须重新冻结并单独批准。

## D-063：V2-E2拆分本地发布就绪与公开激活

- 状态：`accepted-design；implementation-pending；external-unexecuted`
- 切片：E2A只在工作树创建Pages workflow与标准库artifact验证器；E2B才允许push、PR、合并、Pages Source、远程Actions、deployment与公开URL。E2A通过不自动授权E2B。
- 制品：只上传`portfolio-site/p1/`；当前9文件、233,881 bytes。验证器固定扩展名、32文件、1 MiB总量、256 KiB单文件上限，并拒绝符号链接、隐藏文件、路径越界、secret、绝对路径、远程子资源或运行API。
- 供应链：只用GitHub官方`checkout v7.0.1`、`setup-python v7.0.0`、`upload-pages-artifact v5.0.0`与`deploy-pages v5.0.0`，全部固定完整commit SHA；不用第三方Action、floating tag、PAT或secret。
- 权限：workflow顶层`permissions: {}`；verify只有`contents: read`，deploy只有`pages: write`与`id-token: write`。PR与非main手工运行不部署；现有`p1-ci.yml`不增加Pages权限。
- URL：预期项目站形状为`https://rorinhoon-bot.github.io/ai-application-portfolio/`，实际URL在首次部署成功、HTTP 200与hash一致前保持null，不进入简历。
- 回滚：PR失败不合并；部署失败保留run/artifact；内容错误用新提交恢复最后已验证tree，不force-push或删除失败证据。禁用Pages属于外部设置变更，仍需授权。
- 验证：新增7项设计合同；完整`453 passed`，编译、依赖、证据漂移、Git边界和差异检查通过。
- 边界：设计阶段创建workflow 0、push 0、PR 0、remote run 0、Pages设置/deployment/公开URL 0、secret/费用 0；MiMo调用、Qdrant写入、Docker修改均为0。

## D-064：V2-E2A以确定性artifact门和job级最小权限进入本地发布就绪

- 状态：`accepted；implemented；local-verified；external-unexecuted`
- Workflow：新增独立`p1-pages.yml`；顶层权限为空，verify仅`contents: read`，deploy仅`pages: write/id-token: write`。PR和非main手工运行不部署；deploy不checkout源码。
- 供应链：只使用四个已冻结GitHub官方Action完整SHA；checkout不持久化凭据，不使用PAT、repository secret、第三方Action、npm或新增Python依赖。
- 制品门：标准库验证器先检查确定性证据，再冻结根入口、扩展名、32文件/1 MiB/256 KiB上限，并拒绝符号链接、隐藏/非普通/越界文件、远程子资源、运行网络API、表单/iframe、本机路径和疑似secret。
- 机器证据：`pages-release-readiness-report.json`与当前9文件、233,881 bytes及逐文件SHA-256完全绑定；报告默认不可覆盖。
- 验证：新增19项实施合同；完整离线回归`471 passed, 1 skipped`。Windows测试环境不能创建测试symlink而跳过该攻击夹具；生产校验分支与Linux行为未放宽。
- 审批边界：本地提交不授权push、PR、远程run、Pages设置、deployment或公开URL。E2B必须按第11.2节重新批准；E3实时服务、域名、DNS、MiMo和收费云资源仍不在范围。

## D-065：V2-E2B公开激活以远程门禁、内容哈希和静态边界收口

- 状态：`accepted；implemented；public-verified`
- 发布：学习者明确批准`2041a6a`全部144个文件公开；PR #1通过Pages verify、Windows离线合同和Linux API镜像合同后，以squash合并为`0748abfa2f0ec579179ca8095513c0ac3462a2b1`。补充PR #2修正公开状态文案并回填发布证据，通过全部远程门禁后以squash合并为`1faaf45d3752b6277fe1fdab9a0c77d90ad185f0`。
- 跨平台修复：远程CI暴露JSON换行、artifact换行、本地模型资产依赖和冻结评估输入缺失；均以窄范围合同修复，不提交95 MB模型、不改变冻结指标、不绕过失败门。
- Pages：Source固定为GitHub Actions并强制HTTPS；首次run `33173696014`、deployment `6141599225`成功。补充合并后的最终run `33233267570`、deployment `6152214475`成功，URL为`https://rorinhoon-bot.github.io/ai-application-portfolio/`。
- 在线验收：首页、CSS、JS、证据JSON和两张截图均HTTP 200且SHA-256匹配；桌面与360px视觉通过。首次页面暴露旧“Pages尚未启用”文案，后续提交已修正且保留首发报告；最终页面只显示“GitHub Pages 已公开发布”。
- 真实性：公开状态与远程CI结果由`pages-public-release-report.json`绑定；页面继续标注“录制证据 · 非实时推理”，不把静态托管写成实时后端或公网高可用。
- 边界：E2B不包含E3、实时FastAPI/Qdrant/MiMo公网服务、自定义域名、DNS、收费云资源或真实模型调用。
