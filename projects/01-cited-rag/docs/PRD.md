# 带引用的 Python 官方文档知识库问答 PRD

- 文档状态：`draft`
- 版本：`0.16-draft`
- 日期：`2026-08-28`
- 项目性质：P1，第一个求职级主作品
- 版本说明：第 1～20 节保留已验收 V1 基线；第 21 节定义 V2 生产化升级，冲突处以第 21 节为准。V2-B见专项设计；V2-C精确范围见`docs/HYBRID_RERANK_DESIGN.md`与`docs/DETERMINISTIC_FUSION_DESIGN.md`；V2-D见`docs/OBSERVABILITY_CI_DESIGN.md`；P1-F / V2-E见`docs/RESTRICTED_DEPLOYMENT_DESIGN.md`。

## 1. 背景

Python 官方文档内容多、章节深，并且不同 Python 版本可能给出不同结论。普通关键词搜索需要用户自己打开多个页面核对；普通大模型回答又可能混入训练知识，引用也可能无法定位到真实原文。

本项目构建本地知识库问答系统：导入已确认来源与许可的 Python 官方简体中文文档，保存真实版本和章节元数据，通过 Embedding 与向量检索找到证据，再生成带可核验引用的回答。没有足够证据时拒绝编造。

## 2. 目标用户

- 需要查询 Python `3.14` 官方文档的中文开发者和学习者。
- 需要区分 Python `3.13` 与 `3.14` 行为差异的开发者。
- 希望核验答案来源，而不是只接受模型结论的用户。

## 3. 用户问题

系统准备解决：

- 官方文档分散，定位相关章节耗时。
- 同一主题可能涉及多个文档。
- 不同版本材料可能冲突。
- 普通模型可能回答知识库中没有的内容。
- 普通模型可能生成看似合理但不存在的引用。

## 4. MVP 目标

用户通过本地 CLI 导入固定文档快照并提问。系统必须：

1. 导入、清洗并切分文档。
2. 保存文件名、文档版本、章节路径、段落或 Chunk 标识、来源 URL、许可和内容哈希。
3. 使用本地 Embedding 建立可持久化向量索引。
4. 检索与问题相关的文档片段。
5. 使用 `mimo-v2.5`，只根据检索证据生成回答。
6. 引用由程序从真实检索结果绑定，不能由模型自由编写。
7. 证据不足时明确拒答。
8. 材料冲突时说明冲突，标明各自版本并分别引用。
9. 使用至少 20 条固定评估问题保存基线与优化结果。

## 5. 已确认语料方向

主语料：

- Python `3.14` 官方简体中文文档子集。

对照语料：

- 少量 Python `3.13` 官方简体中文对应文档。
- 只用于版本差异、冲突材料和版本限定问题。

来源原则：

- 只使用 Python 官方文档站提供的材料。
- 入库前固定文档版本和下载日期，不在问答时实时抓取网页。
- 每个来源写入清单：原始 URL、Python 版本、文档标题、下载日期、内容哈希、许可说明。
- 不使用个人隐私、公司资料、未知来源文件或许可不明材料。
- Python 软件和文档采用 Python Software Foundation License Version 2；分发语料时保留版权、许可和必要署名。

首批范围：

- Python `3.14`：教程、`venv`、`pathlib`、`json`、`argparse` 和“Python 3.14 有什么新变化”。
- Python `3.13`：“Python 3.13 有什么新变化”，以及版本冲突评估所需的少量对应页面。
- 首批导入格式使用官方 HTML，保留标题层级和章节标识。
- 具体文件、URL、快照日期和内容哈希在语料清单中固定。

## 6. 核心使用流程

### 6.1 建库

1. 用户把已批准的官方文档快照放入允许的语料目录。
2. CLI 校验路径、文件类型、版本清单和必要元数据。
3. 程序解析文档，去除导航、页脚等噪声。
4. 程序按章节和段落切分，保留来源关系。
5. 本地 Embedding 生成向量。
6. 本地向量存储保存向量、文本和元数据。
7. 程序输出导入数量、跳过数量、错误和索引版本。

### 6.2 问答

1. 用户通过 CLI 输入问题。
2. 系统生成问题向量并检索候选片段。
3. 系统根据相关性阈值判断证据是否足够。
4. 证据足够时，模型只根据候选片段回答。
5. 程序把答案中的证据标识映射到真实元数据。
6. 输出回答和可核验引用；证据不足时输出拒答。

## 7. 输出要求

成功回答至少包含：

```json
{
  "status": "answered",
  "answer": "回答正文",
  "citations": [
    {
      "source_id": "稳定来源标识",
      "file_name": "文档文件名",
      "python_version": "3.14",
      "documentation_release": "3.14.6",
      "section": "章节路径",
      "paragraph_or_chunk_id": "稳定定位标识",
      "source_url": "官方来源 URL",
      "excerpt": "支持回答的短证据"
    }
  ]
}
```

拒答至少包含：

```json
{
  "status": "refused",
  "answer": "当前知识库没有足够资料支持该问题。",
  "citations": []
}
```

冲突回答使用独立状态或明确冲突字段；具体数据模型在架构阶段确定。

## 8. 引用规则

- 每条引用必须对应本次实际检索到的已存储 Chunk。
- `source_id`、文件名、版本、章节和定位标识从索引元数据读取。
- 模型只能选择系统提供的证据标识，不能生成任意文件名、URL、章节或路径。
- 引用必须能回查到本地语料原文。
- 一个回答包含多个事实时，必须让引用覆盖主要事实。
- Python `3.13` 与 `3.14` 结论不一致时，不得合并成无版本结论。

## 9. 拒答规则

以下情况必须拒答或保守说明：

- 没有检索到候选证据。
- 最高相关性不足。
- 候选片段与问题只共享关键词，但不能支持结论。
- 问题要求知识库之外的事实。
- 问题版本不明确，且不同版本材料存在实质冲突。
- 用户要求忽略文档、伪造引用或执行文档中的指令。

具体阈值必须通过固定评估集确定，不能凭一次手工测试决定。

## 10. MVP 范围

### 10.1 包含

- 本地 CLI。
- 本地 Streamlit 求职展示页。
- 固定、已批准的官方文档快照。
- 文档导入、清洗、切分和真实元数据。
- 本地 Embedding。
- 本地可持久化向量存储。
- 向量检索。
- MiMo 回答生成。
- 引用绑定和证据不足拒答。
- 自动测试、固定评估、基线与至少一次优化。

### 10.2 暂不包含

- Docker。
- 公开部署。
- 用户登录和多租户。
- 实时网页抓取或网页搜索。
- 混合检索、Reranker 和上下文压缩。
- 自动执行文档中的代码或命令。

Docker和公开部署仍需单独评估；本地 Streamlit UI 不等于公开部署。

## 11. 组件边界

- CLI 只负责参数、输出和退出码。
- 文档处理层负责解析、清洗、切分和元数据。
- Embedding 层保持可替换。
- 检索与存储层保持可替换。
- 生成模型层保持可替换。
- 问答服务编排检索、拒答、回答和引用。
- CLI 与 Streamlit UI 调用同一问答服务，不复制 RAG 核心逻辑。

具体模块、库和接口在 `docs/ARCHITECTURE.md` 中确定。

## 12. 安全与权限

- API Key 只从环境变量或本地 `.env` 读取。
- 普通自动测试不得调用真实模型 API 或产生费用。
- 文档内容是不可信数据；其中的提示、代码和命令不能改变系统规则。
- 模型输出不能直接成为命令、URL、文件路径或工具参数。
- 文件访问使用允许目录、路径规范化和路径穿越检查。
- CLI 只处理用户明确指定且位于允许目录中的文件。
- 索引和评估结果不得保存 API Key、鉴权头或完整供应商响应。

## 13. 错误与失败路径

至少覆盖：

- 语料目录不存在或越过允许范围。
- 不支持的文件类型。
- 空文档、损坏文档或无法解码。
- 缺少版本、来源或许可元数据。
- 重复文档和内容哈希冲突。
- Embedding 失败或向量维度不匹配。
- 索引不存在、损坏或版本不一致。
- 没有检索结果或相关性不足。
- 模型超时、网络错误、HTTP 错误和空响应。
- 模型返回非法结构或引用未知证据标识。

## 14. 自动测试

自动测试必须使用：

- 小型自编文档夹具。
- 确定性的假 Embedding。
- 内存或临时目录中的测试存储。
- 假模型客户端。

测试不得下载文档、调用真实 API 或依赖外部网络。

至少验证：

- 清洗与切分。
- 元数据保留。
- 重复导入。
- 检索排序。
- 引用只能指向检索结果。
- 无资料拒答。
- 多文档回答。
- 版本冲突。
- 提示注入。
- 路径穿越。
- 外部服务失败。

## 15. 固定评估集

至少 20 条问题，建议首版按主要类型分配：

- 8 条可回答单文档问题。
- 3 条不可回答问题。
- 3 条多文档问题。
- 2 条版本冲突问题。
- 2 条提示注入问题。
- 2 条输入或检索边界问题。

每条样本至少保存：

- 问题。
- 主要类型。
- 适用 Python 版本。
- 预期相关来源或 Chunk。
- 必须覆盖的事实。
- 禁止出现的事实。
- 是否应拒答。
- 人工评分记录。

## 16. 指标

至少记录：

- `Recall@k`：预期证据是否进入前 `k` 个检索结果。
- 检索相关性：返回片段是否与问题相关。
- 引用有效率：引用是否真实存在并来自本次检索结果。
- 忠实度：回答事实是否能由引用证据支持。
- 拒答准确性：应该拒答和应该回答的行为是否正确。

PRD v0.1 已确认目标：

- 引用有效率：`100%`。
- `Recall@5`：不低于 `80%`。
- 忠实度：不低于 `90%`。
- 拒答准确性：不低于 `80%`。

## 17. 基线与优化

基线：

- 单一向量检索。
- 固定 Chunk 策略。
- 固定 `top_k`。
- 不使用混合检索、Reranker 或上下文压缩。

优化至少执行一次，可以选择：

- 调整 Chunk 大小或重叠。
- 调整元数据与标题拼接策略。
- 调整 `top_k` 或拒答阈值。
- 在基线证据不足时再评估混合检索或 Reranker。

比较要求：

- 使用相同语料快照、评估集、生成模型、Embedding 模型和生成参数。
- 保存每次配置、结果、失败案例和错误分类。
- 至少一个选定指标改善，且引用有效率不得退化。

## 18. 验收标准

### AC-01：语料

- 语料来源、版本、下载日期、哈希和许可可追踪。
- 不包含私密或许可不明数据。

### AC-02：导入

- 文档可重复导入。
- 清洗、切分和元数据保留有自动测试。
- 重复文件和失败文件有清晰结果。

### AC-03：检索

- 使用 Embedding 与向量检索。
- 固定评估集保存 `Recall@k` 和相关性结果。

### AC-04：引用

- 每条引用可回查到真实语料。
- 引用只能来自本次检索结果。
- 引用有效率达到确认后的目标。

### AC-05：回答与拒答

- 回答只使用检索证据。
- 无资料、版本不明冲突和提示注入场景行为正确。
- 忠实度与拒答准确性达到确认后的目标。

### AC-06：测试与评估

- 普通自动测试不访问网络。
- 固定评估问题不少于 20 条。
- 保存基线与至少一次同条件优化结果。

### AC-07：工程交付

- 新环境能按 README 启动。
- CLI 与本地 Streamlit 页面都能按 README 启动。
- 页面展示回答、拒答/冲突状态、程序绑定引用和安全错误提示。
- `.env.example` 不含真实密钥。
- README、架构、演示、限制和开发复盘完整。
- 项目完成后创建 `LLH_Study.md`。
- 达到项目验收清单后才能标记 `completed`。

## 19. 已确认技术边界

- 生成模型：P1 首版使用 MiMo `mimo-v2.5`，但未经再次批准不调用真实 API。
- Embedding：本地运行；具体模型和库待 Python `3.14.3` 兼容性核验。
- 向量存储：本地持久化；具体实现待架构评审。
- 入口：本地 CLI 与本地 Streamlit 页面。
- 后续：Docker和公开部署后置。
- 安装任何依赖前，必须提交生产与开发依赖的精确版本、用途、必要性和兼容性证据，并获得明确批准。

## 20. 待架构阶段确认

1. Python `3.13` 冲突评估使用的具体对应页面。
2. HTML 清洗规则与 Chunk 边界。
3. 本地 Embedding 候选。
4. 本地向量存储候选。
5. 检索、拒答和引用接口。

## 21. V2 生产化升级需求

### 21.1 升级背景

V1 已证明本地端到端 RAG、真实引用、拒答、固定评估和 Streamlit 展示可以运行，但对外仍是单机 Demo：没有稳定服务合同、独立向量数据库、部署边界、持续集成和运行可观测性，也缺少 Dense、Hybrid 与 Rerank 的同条件对比证据。

V2 不重做 V1。它保留已验收核心和历史报告，把项目升级为可被 P2 Agent 与 P3 MCP 复用的生产化知识服务。

### 21.2 V2 目标用户与调用方

- 求职面试官：可查看架构、测试、评估、故障路径和部署证据。
- Python 文档查询用户：获得带版本、章节和官方 URL 的可验证回答。
- P2 Agent：通过稳定 HTTP API 调用 P1，而非导入内部实现。
- P3 MCP 服务：把 P1 能力暴露为受约束工具，并保留错误与引用语义。
- 运维者：能检查健康、就绪、请求追踪、延迟和失败分类。

### 21.3 V2 范围

按顺序交付：

1. **V2-A，服务边界**：FastAPI 只读 API、健康/就绪端点、Problem Details、请求 ID、离线 API 测试。
2. **V2-B，存储与运行环境**：Qdrant Server 适配器、Docker/Compose、本地确定性启动与数据恢复。
3. **V2-C，检索质量**：关键词召回、Dense+Sparse 融合、可选 Reranker 消融；使用同一语料、同一评估集和同一指标比较。
4. **V2-D，可观测与持续集成**：结构化日志、OpenTelemetry 链路/指标、GitHub Actions 离线测试与评估门禁。
5. **V2-E，受控部署与展示**：先提供不含密钥、模型调用和任意输入的公开静态证据页；实时问答只有在身份、持久配额、费用断路器、密钥和恢复边界另行获批后才部署。

### 21.4 明确不做

- 任意网页抓取、开放式文件上传、用户指定本地路径。
- 把模型输出直接用作命令、SQL、路径或工具参数。
- 多租户 SaaS、完整账号系统、Kubernetes 和自动扩缩容。
- 无认证的公网写接口或索引管理接口。
- 为了指标删除失败样本、覆盖旧报告或更换题目后仍声称同条件提升。

### 21.5 功能需求

#### FR-V2-01：稳定问答 API

- 提供 `GET /healthz`、`GET /readyz` 和 `POST /v1/answers`。
- API 复用现有 `CitedRagService` 和 `AnswerResult`，不复制回答逻辑。
- 请求不得控制模型名、温度、Prompt、索引路径、来源 URL 或密钥。
- 详细合同见 `docs/API_CONTRACT_V2.md`。

#### FR-V2-02：服务化向量存储

- 保留本地模式作为离线测试适配器。
- 新增 Qdrant Server 适配器，并验证集合、过滤、健康检查和发布一致性。
- 索引构建与在线问答隔离；写操作不得由公开问答端点触发。

#### FR-V2-03：可比较的检索流水线

- 至少保留 Dense 基线，并实现一种 Sparse/BM25 召回与可解释融合策略。
- Reranker 作为可开关阶段；必须记录模型、revision、Top-K、延迟和资源成本。
- Dense、Hybrid、Hybrid+Rerank 使用固定语料快照和固定问题集比较。
- 当前 `dense-plus-identifiers` 单独作为生产现状对照，不能命名为BM25或Sparse。
- 中文Sparse必须证明tokenizer适配中文与代码词元；不接受把仅按空白切分的英文BM25直接用于连续中文。

#### FR-V2-04：异步摄取边界

- 摄取任务作为后续受保护管理能力，不与首个只读 API 同时开放。
- 任务必须有稳定 ID、状态、失败原因、幂等边界和可恢复记录。
- 任何真实写接口都必须先补鉴权、权限检查和审计记录。

#### FR-V2-05：可观测性

- 每个请求生成并传播请求 ID。
- 记录检索、重排、生成和总耗时，以及候选数量、状态和错误类别。
- 不记录密钥、完整文档、完整回答和用户原始问题。
- OpenTelemetry 接入不能改变业务结果，也不能让离线测试依赖外部采集器。

#### FR-V2-06：持续集成

- 每次提交运行格式/静态检查、离线单元测试和 API 合同测试。
- 固定快速评估集作为质量门禁；完整真实模型评估单独手动触发并受费用控制。
- CI 不包含真实 API Key，不自动调用付费模型。

#### FR-V2-07：受限求职展示

- 公开首发使用固定录制证据，并显著标注“非实时推理”；每项指标和案例都能回指已追踪报告及SHA-256。
- 静态页不接受任意问题，不连接FastAPI、Qdrant或MiMo，不包含运行密钥、第三方脚本、分析或追踪。
- 公开页面与实时问答是两条独立发布路径；静态页完成不得表述为公网RAG API上线。
- 实时路径必须先验证独立身份、持久配额、全局费用断路器、请求体总大小、可信代理、Secret管理、资源上限和snapshot恢复。

### 21.6 非功能需求

- 新环境按 README 可恢复固定语料、安装锁定依赖并启动只读 API。
- 默认只监听回环地址，默认关闭 CORS。
- 服务未就绪时快速失败，错误体不泄露堆栈、绝对路径或上游原文。
- 普通测试不访问网络、不加载真实大模型、不要求 Docker 守护进程。
- 先测量本机 P50/P95 延迟、吞吐、错误率、Token 和估算成本，再设性能门槛；不得虚构 SLA。

### 21.7 V2 验收标准

#### AC-V2-01：API 切片

- 三个首发端点符合 `API_CONTRACT_V2.md`。
- 假服务测试覆盖 answered、refused、conflict、校验错误、未就绪、上游超时和未知异常。
- 成功与失败响应都有合法请求 ID。
- 首屏存活检查不加载 BGE、Qdrant 或 MiMo。

#### AC-V2-02：检索与评估

- V1 指标和报告原样保留。
- 固定检索评估集扩展到不少于 50 条，并按问题类型分层。
- 提交 Dense、Hybrid、Hybrid+Rerank 的同条件表格，至少包含 Recall@5、MRR、nDCG、P50/P95 延迟和资源说明。
- 引用程序绑定有效率保持 `100%`；生成质量和拒答继续使用固定集验证。
- 新评估集固定development与locked-test拆分；所有参数只能用development选择，locked-test在配置冻结后运行。
- Reranker前必须报告候选Recall@20；候选没有相关证据时，不得把排序模型描述为可修复召回。

#### AC-V2-03：工程运行

- Qdrant Server 和 API 可通过受控本地运行方案启动，重启后数据行为可验证。
- CI 的普通路径完全离线并通过。
- 日志与链路能把一个请求关联到检索、生成和错误分类，且不含敏感内容。
- Docker/部署材料、架构图、演示、限制和复盘完整。

#### AC-V2-04：安全与公开部署

- 未经批准不公开部署、不创建付费资源、不发送真实用户数据。
- 若进入公网，必须先验证认证、限流、配额、超时、CORS、密钥注入和只读权限。
- `.env.example` 只含占位符；Git 安全检查覆盖密钥、私密数据、模型资产和运行数据。
- 公开静态证据必须标注录制/非实时状态，不接受任意输入或发出后端请求；实际URL、远程CI和在线可用性只能在真实发布后声明。
- 平台预算告警、最大实例数或内存计数器不得冒充硬费用上限；长期实时公网必须有跨重启持久配额与停止机制。

### 21.8 首个实现切片

V2-A 已完成：

1. 独立 API 请求/响应模型。
2. 应用工厂和依赖注入。
3. `/healthz`、`/readyz`、`/v1/answers`。
4. 领域异常到安全 HTTP 错误的显式映射。
5. 完全离线的 API 测试。

FastAPI/Uvicorn、独立虚拟环境、Qdrant Server、API镜像、Hybrid发布、可观测性、CI本地合同和有限重试均已按各自批准完成。真实MiMo调用、远程CI、创建云资源和公开部署仍属于暂停点，须先提交精确方案并获得批准。

### 21.9 V2-A 阶段验收结果

V2-A 于 2026-08-23 通过阶段验收：

- 三个首发端点及 OpenAPI 与 `docs/API_CONTRACT_V2.md` v0.2 一致。
- `CitedRagService`、`AnswerResult`、引用和拒答语义原样复用。
- 29 项 HTTP 合同测试覆盖三种业务状态、严格输入、服务未就绪、模型失败/超时、未知异常、404、OpenAPI、请求 ID 和 CORS 关闭。
- 3 项底层测试证明就绪检查只验证检索依赖，不生成查询向量、不调用回答模型。
- 全部 252 项普通测试离线通过；V1 测试零删除。
- 真实本地 Uvicorn 冒烟得到 health 200、缺资产 readiness 503、非法请求 422 和 OpenAPI 200。
- 未调用真实 MiMo、未启动 Docker/Qdrant Server、未创建云资源、未公开部署。

本结果只完成 AC-V2-01。AC-V2-02～04 仍属于后续 V2-B～V2-E，不能标记为已完成。

### 21.10 V2-B1 服务化存储切片

V2-B 先交付“宿主机 FastAPI + Docker Qdrant Server”，再单独交付 API 容器：

1. 保留本地 Qdrant 适配器和 V1 `data/indexes/`，普通测试不依赖 Docker。
2. 新增只从受控环境配置创建的 Server 适配器；在线 API 使用 read-only key，迁移命令使用 admin key。
3. Qdrant 只发布 `127.0.0.1:6333`；不发布 gRPC/集群端口，不开放写 API。
4. Windows/WSL 活数据使用 Docker named volume，不把 Windows 目录 bind mount 到 `/qdrant/storage`。
5. 用固定语料、Chunk、模型 revision 和资产哈希重建 1359-point Server collection；验证通过后才写独立活动指针。
6. 验证权限拒绝、失败发布、restart、down/up、snapshot 和临时恢复 collection。
7. 不加入 PostgreSQL；任务持久化等到摄取 worker 有真实需求时再设计。

详细设计、批准边界与实际证据见 `docs/QDRANT_SERVER_DESIGN.md` v0.2。该切片状态为`implemented`；API容器仍属于V2-B2。

### 21.11 V2-B1 阶段验收结果

V2-B1于2026-08-23通过阶段验收：

- Docker Desktop 4.87.0/Engine 29.7.2和固定摘要的Qdrant 1.19.0-unprivileged运行成功；活数据与snapshot使用两个Linux named volume。
- 专用普通bridge只发布`127.0.0.1:6333`；6334/6335未发布。初始internal网络阻断宿主机访问，经学习者单独批准后修正，并保留全部容器加固项。
- 固定语料和5个本地模型文件离线重建1359 points；512维Cosine、payload、唯一ID、Python 3.13过滤和self-query全部通过。
- read-only key的count/scroll/query为200；create/upsert/delete为403。在线FastAPI不持有admin key。
- restart和不带`-v`的down/up后活动index/build/collection身份不变，向量重建数为0，两个named volume保留。
- 9,922,560-byte snapshot的SHA-256固定并与Qdrant checksum匹配；上传恢复到唯一临时collection后全量验证通过，临时collection已删除，活动collection不变。
- P1真实`/healthz`与`/readyz`均返回200，readiness未发送MiMo请求。
- 最终300项普通测试离线通过；V1/V2-A测试零删除，普通测试仍不需要Docker。

本结果完成FR-V2-02和AC-V2-03中的Qdrant本地运行/持久化部分；CI、结构化日志/链路、API镜像和部署材料仍由V2-B2/V2-D继续完成。不能据此声称公网生产、高可用或多节点。

### 21.12 V2-C1检索评估结果

AC-V2-02的评估先行部分于2026-08-24完成：

- `retrieval-v2`固定50题，按12个语义改写、12个精确标识符、10个混合问题、8个版本问题和8个已知难例分层；拆分为30 development与20 locked-test。
- 50个唯一相关Chunk已在1359-point活动Server collection中只读回查；point/payload ID和版本均一致。
- Dense为42/50、Recall@5 84.0%、MRR@5 0.6313、nDCG@5 0.6840。
- 当前`dense-plus-identifiers`为45/50、Recall@5 90.0%、MRR@5 0.7217、nDCG@5 0.7673。
- 两条路径各执行5次warm-up和150个顺序计时样本；P95分别为5.304秒与5.802秒。
- 当前路径净增3个命中，但`t-string`版本题出现1个真实退化；失败和退化均保留。
- 旧15题与两份V1报告字节哈希不变；评估没有Qdrant写入、MiMo调用、模型下载、依赖安装或容器重启。

该时点AC-V2-02尚未全部完成；后续C2结果见21.13。C3仍只在候选召回证明存在排序空间后审批。

### 21.13 V2-C2门禁结果

V2-C2已实现并验证1359-point Dense+Sparse候选索引、确定性中文/代码BM25词表、RRF候选层和旧schema回退。development为29/30，Recall@5与candidate Recall@20均为96.67%。

唯一一次locked运行在指标生成前检测到重复排名漂移。按AC-V2-02的可复现要求与冻结合同安全失败：不重跑锁定集、不激活Hybrid、不重建或重启API。当前生产路径继续使用`dense-plus-identifiers`；Reranker前置证据不足，V2-C3不启动。

### 21.14 V2-C2.1确定性融合结果

本切片不修改索引或Sparse权重：Dense使用exact search；Dense/Sparse在第20名同分触边时扩大返回窗口；客户端用精确分数与point ID闭合同分组，再用`Fraction`按固定`RRF(k=2)`融合。

旧`retrieval-v2`仅作为稳定性回归，50/50题各3次一致。查询前冻结的新20题`retrieval-v3`与V2问题/相关Chunk无重合；Dense、旧生产与确定性Hybrid Recall@5分别为0.75、0.80、0.95，Hybrid candidate Recall@20为1.00。

发布门14/14通过，活动指针已切到Hybrid build`740d893f-20e4-4677-8e7c-74a4d45de92e`，API升级为`cited-rag-api:v2-c2-1`。C3前置门未通过，不下载Reranker。具体合同与证据见`docs/DETERMINISTIC_FUSION_DESIGN.md` v0.2和`data/deterministic-fusion-release-gate.json`。

### 21.15 V2-D可观测性与CI设计

V2-D拆为D1可观测性、D2 CI和后置D3有限重试。D1使用隐私安全JSON日志、手工OpenTelemetry trace/metrics与本地Collector；遥测默认可关闭，Collector不可达不得改变问答、health或ready。D2使用最小`GITHUB_TOKEN`权限和完整commit SHA固定官方Action；普通测试不加载真实模型、不访问Qdrant Server、不调用MiMo。

运行时metrics保存低基数请求、阶段耗时、错误、候选数、回答状态和Token。问题、证据、回答、密钥、供应商响应和绝对路径禁止进入日志、trace或metrics。当前无可信MiMo定价依据，费用保持不可用，不用Token估算虚假金额。

详细依赖、Collector摘要、测试、回滚和批准边界见`docs/OBSERVABILITY_CI_DESIGN.md` v0.3。设计完成不等于实现完成；远程GitHub Actions首次成功前不能声称CI通过。

### 21.16 V2-D1代码实施结果

D1已实现字段allowlist JSON日志、request ID/trace关联、八阶段手工span、八类低基数metrics、OTLP/HTTP导出与有界关闭。离线内存导出测试覆盖父子链路、422错误、Token、候选数、敏感值零泄漏和遥测故障隔离；完整384项测试通过。

Collector Compose与`cited-rag-api:v2-d1`已完成运行激活。Docker Engine由学习者手工启动，既有Qdrant按restart策略发生一次受控重启；Qdrant容器身份、活动Hybrid索引、Manifest、snapshot和named volume保持不变。Collector固定digest启动，API只重建为`v2-d1`；端点、`rag_*`指标、debug trace、Collector故障隔离、隐私扫描和回滚均通过。运行证据见`data/observability-runtime-release-report.json`。D2本地workflow已达到`workflow-ready`，远程CI仍未运行；D3有限重试已按21.18节完成。

### 21.17 V2-D2 CI实施结果

新增`.github/workflows/p1-ci.yml`，固定Windows CPython 3.14.3离线合同job与Ubuntu API镜像合同job；官方Action使用完整commit SHA，workflow最小权限为`contents: read`，不使用secret、不push、不启动Qdrant。固定fake Embedding/Qdrant/Model smoke输出经Pydantic重验的机器JSON；Git边界检查拒绝`.env`、私钥、模型与生成索引。当前本地等价命令通过，状态为`workflow-ready`，远程GitHub Actions尚未运行，不能声称`remote-passed`。

### 21.18 V2-D3有限重试实施结果

D3已按冻结设计实现。一次逻辑MiMo请求最多两次物理尝试，仅允许`408/429/500/502/503/504`和已确认连接阶段故障重试；读取/写入超时、模型JSON/Schema/引用错误不重试。`Retry-After`只接受安全秒数并裁剪到2秒，默认退避250毫秒，逻辑总时限不超过`model_timeout_seconds + 2 s`。请求体保持相同；读取/写入失败和可能重复发送均保留`billing_uncertain`语义，没有可信单价时继续保持`cost_available=false`。

离线fake-provider smoke固定五类序列并加入CI；独立`cited-rag-api:v2-d3`镜像通过health 200、ready 200、非法answer 422验收后已移除临时容器。活动`v2-d1`未切流量，Qdrant身份、活动索引证据和named volume零变化。未调用真实MiMo、未安装依赖、未触发远程CI。详细设计与证据见`docs/RETRY_DESIGN.md`、`data/retry-smoke-report.json`和`data/retry-runtime-release-report.json`。

### 21.19 P1-F / V2-E受限部署设计

公开展示冻结为两条隔离路径。E1/E2使用GitHub Pages纯静态证据页，展示固定指标、录制问答、失败发布、架构、运行报告与诚实限制；页面不接受任意问题、不连接API/Qdrant/MiMo、不持有密钥，并显著标注“录制证据，非实时推理”。

E3受控实时问答只保留为条件候选：Cloud Run只读API与Qdrant Cloud必须在资源实测、独立身份、跨重启持久配额、全局费用断路器、请求大小、可信代理、Secret管理和snapshot恢复全部通过后另行审批。预算告警和最大实例都不作为硬费用封顶证据。

本设计未创建账户或云资源，未更改GitHub Pages设置，未push、未触发远程Actions、未调用MiMo、未产生费用。精确合同、官方来源、实施切片和批准边界见`docs/RESTRICTED_DEPLOYMENT_DESIGN.md` v0.1与`data/deployment-capability-audit.json`。

### 21.20 V2-E1本地静态证据实施结果

`portfolio-site/p1/`已实现纯静态、无后端的求职证据页。固定页面覆盖同一V3新20题的三模式检索对比、10题回答质量、3个录制案例、失败关闭与恢复证据、容器/可观测性证据和已知限制，并显著标注“非实时推理”。

确定性导出器固定读取已追踪报告与截图，生成输入/输出SHA-256 manifest；离线合同锁定数值、来源、无网络运行调用、无任意输入、无密钥和小屏/键盘可用性。CI本地合同加入`--check`，但远程Actions仍为`remote-unrun`。

本地HTTP 200预览已通过。没有安装依赖、调用MiMo、写Qdrant、修改Docker、push、启用Pages、创建公开URL或云资源；V2-E2仍需独立设计与批准。

### 21.21 V2-E2发布设计结果

E2发布进一步拆为E2A本地发布就绪与E2B公开激活。E2A只允许在工作树创建Pages workflow、标准库artifact验证器与离线合同；E2B才允许push、PR、合并、Pages Source设置、远程Actions和公开URL。

发布artifact只含`portfolio-site/p1/`。workflow顶层权限为空；verify job只有`contents: read`，deploy job只有`pages: write`和`id-token: write`。PR及非`main`手工运行不部署；所有官方Action固定完整commit SHA，不使用PAT、repository secret、第三方Action或运行后端。

预期项目站URL只记录形状，首次真实deployment与HTTP/hash验收前保持未验证。设计阶段外部副作用为0；详细合同见`docs/PAGES_RELEASE_DESIGN.md`。

### 21.22 V2-E2A本地发布就绪结果

已实现独立Pages workflow和标准库artifact验证器。发布门先重算固定证据，再校验9文件精确清单、SHA-256、扩展名、文件与字节上限、CSP、无远程运行资源、无表单/iframe、无本机路径与secret；机器证据见`data/pages-release-readiness-report.json`。

workflow顶层权限为空；verify仅`contents: read`，deploy仅`pages: write/id-token: write`，且PR与非main手工运行不能部署。E2A完整离线验收通过，但没有push、PR、远程run、Pages设置、deployment或公开URL。E2B仍需独立批准。
