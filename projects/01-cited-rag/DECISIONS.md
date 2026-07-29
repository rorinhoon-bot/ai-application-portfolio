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
