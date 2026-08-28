# P1 学习总结：带引用的知识库问答

## 1. 项目介绍

### 30秒

这是一个版本感知的 Python 官方文档 RAG 服务。它导入固定的3.13/3.14简体中文 HTML，用本地 BGE、中文/代码Sparse和Qdrant检索，再让MiMo只依据证据回答。模型只能选择本次检索Chunk ID，URL、版本和章节由程序绑定；CLI、Streamlit和只读FastAPI复用同一核心。Qdrant既保留离线Local适配器，也完成Docker Server、读写权限、重启和snapshot恢复实测。全新发布集Recall@5为95%，candidate Recall@20为100%，拒答准确率100%，引用绑定100%，共372项离线测试。

### 2分钟

项目解决“模型回答看似正确但引用不可核验”的问题。语料使用Python官方文档固定快照；导入阶段保存版本、URL、许可、章节anchor、位置和哈希。HTML清洗保留标题、段落、列表和代码，删除导航与脚本。Chunk和索引身份确定性生成。

问答时，本地 `BAAI/bge-small-zh-v1.5` 生成查询向量，Qdrant返回Top-5。对显式3.13/3.14比较，程序分别按版本检索再平衡合并。MiMo只输出状态、正文和Chunk ID；程序验证ID属于本次结果，再绑定真实引用。证据不足时拒答。

固定检索集从稠密基线66.7%提升到86.7%。单一 cosine 阈值在新锁定集只有70%/70%，因此没有进入生产链。最终模型集达到可回答召回80%、拒答准确率100%、引用绑定100%；显式版本比较人工复核3/3。

V2把向量存储从单进程Local模式扩展为独立Qdrant Server：固定镜像摘要、Linux named volume、回环端口、admin/read-only密钥隔离。固定资产离线重建1359 points；restart、down/up后身份不漂移；snapshot下载校验并恢复到临时collection后全量验证，再删除临时collection。FastAPI `/readyz`用read-only key实测200且不调用MiMo。

检索生产路径进一步升级为确定性Hybrid：Dense启用exact search，Sparse使用固定中文双字gram与代码标识符BM25；两路闭合第20名同分边界，再用zero-based `RRF(k=2)`和`Fraction`在客户端融合。新20题中，旧生产Recall@5为80%，Hybrid为95%；14项发布门全部通过。

### 5分钟

按 `docs/DEMO.md` 演示：先说明问题和用户，再展示完整数据链路、CLI真实结果、安全边界、基线与优化、失败报告和下一步。

## 2. 一句话原理

先从本地官方文档检索证据，再让 MiMo 只基于证据回答；引用元数据由程序绑定，不能由模型编造。

## 3. 用户、输入输出与价值

- 用户：查阅Python 3.13/3.14官方中文文档的学习者和开发者。
- 输入：问题，以及可选单一Python版本。
- 输出：JSON状态、答案、官方URL、版本、章节、摘录、索引与构建ID。
- 价值：减少手工翻页时间；回答可回查；无证据时不编造。
- 非目标：任意网页、第三方库、工具执行、实时搜索、写操作和公开部署。

## 4. 技术栈

- Python 3.14、Pydantic、Pydantic Settings
- Beautiful Soup：解析官方 HTML
- FastEmbed + `BAAI/bge-small-zh-v1.5`：本地中文向量
- Qdrant Client + Qdrant Server 1.19：离线Local适配器、回环服务化存储
- Docker Desktop/Compose：非root容器、named volume、权限与恢复验收
- HTTPX + MiMo `mimo-v2.5`：结构化回答
- Streamlit：本地求职展示页
- FastAPI + Uvicorn：只读 HTTP 服务、健康与就绪探针
- pytest：离线自动测试

## 5. 数据链路

`SourceManifestEntry` 保存人工确认来源；`DocumentSnapshot` 绑定真实 HTML 哈希；`ContentBlock` 保存结构和清洗文本；`DocumentChunk` 保存检索单元与引用位置。

来源 URL、Python 版本、许可和预期哈希来自人工清单；页面标题、章节和 anchor 来自 HTML；ID、顺序、清洗文本和哈希由程序确定性生成。模型不能生成或修改这些字段。

## 6. 核心实现

### HTML 导入

解析器只接收 HTML 字符串。导入服务负责安全路径、文件读取、哈希、canonical URL 和标题校验。正文结构使用 allowlist；脚本、样式、导航、页脚和搜索控件删除。缺少主内容、标题、真实 anchor 或出现未知正文结构时整页失败。

### Chunk

先按结构 Block 切分，再按固定 token 上限合并或拆分。代码保留空格和缩进。Chunk ID 使用 UUIDv5，绑定来源、快照、配置、位置和文本哈希；相同输入产生相同结果。

### Embedding 与索引

模型 revision、文件 allowlist、大小和 SHA-256 固定。构建前审计 token，禁止静默截断。Qdrant payload 保存完整引用字段。活动索引指针只在新索引完整构建并校验后替换。

### 检索

基线是稠密 Top-5。优化后增加用户原文 ASCII 代码标识符通道，再用稠密结果补满，不生成或改写查询。固定集从10/15提升到13/15。

显式同时出现3.13和3.14时，程序删除已由过滤器表达的版本词，分别执行精确版本过滤检索，再按2+2+1合并为5条证据。单版本路径不变。

当前Server生产模式为`hybrid-client-rrf-v1`。Dense与Sparse先各取确定性Top-20：从limit 64开始，如果第20名与窗口末项同分，就按64、128、256继续扩大，最多到Manifest point count。每路按分数降序、point ID升序稳定排序。

融合使用zero-based rank：每个点累加`1/(2+r)`。内部用`Fraction`精确比较，避免浮点同分漂移；最终再按point ID破同分。融合Top-20后才批量读取payload并验证ID、Chunk schema、版本和引用字段，Top-5必须是候选前缀。

### 回答与引用

MiMo 输出 `answered/refused/conflict`、正文和 Chunk ID。Pydantic 校验状态组合；引用 ID 必须属于本次检索结果。程序从对应 payload 绑定 URL、版本、章节和摘录。未知 ID 直接失败。

拒答允许模型省略空正文和空引用；程序补固定拒答文案。这个默认值不包含事实。`answered/conflict` 仍必须有正文和有效引用；`conflict` 必须覆盖至少两个 Python 版本。

显式版本比较证据足够时使用 `answered`，正文分别标版本。只有矛盾无法安全化解时才使用 `conflict`；其引用必须覆盖至少两个版本。

### Streamlit 展示层

`streamlit_app.py` 只组装现有应用；`cited_rag.ui` 只负责显示。页面首次打开不加载 BGE 或索引，提交问题后才初始化并缓存应用。引用按钮读取程序已验证的 `AnswerCitation`，不让模型生成 URL。AppTest 使用假应用，因此普通 UI 测试仍然离线。

### FastAPI 服务边界

`api_models.py` 只定义 HTTP 请求、响应和 Problem Details；业务回答继续使用 `AnswerResult`。`api.py` 的应用工厂接收可注入假服务，模块导入和 `/healthz` 都不创建重资源。`/readyz` 验证配置、模型资产和活动索引，但不生成向量、不调用 MiMo。

问题校验、领域错误、模型错误和未知异常分别映射为稳定 422、503、502、504 或脱敏 500。请求 ID 由服务端生成，客户端不能借此伪造日志关联。同步核心由 FastAPI 线程池调用，不复制一套异步 RAG。

### Qdrant Server 服务化存储

`qdrant_connection.py`把Local与Server连接封装为两个工厂。在线进程只读`.env.qdrant-read`；构建与备份命令单独读admin配置。Server URL必须精确为`http://127.0.0.1:6333`，HTTP请求不能覆盖URL、Key、collection或timeout。

Compose固定unprivileged镜像摘要，使用UID/GID 1000:1000、只读rootfs、capabilities清空、no-new-privileges和资源上限。活数据只放Linux named volume，不把Windows本地索引目录直接挂给Server；迁移使用固定语料、模型和Chunk合同离线重建。

最初使用`internal: true`时，容器内部健康但Windows宿主机无法访问published port。B1的API仍在宿主机，因此最终经批准改为项目专用普通bridge；端口映射和bridge默认绑定地址都锁定127.0.0.1，6334/6335不发布。等API也容器化后，才能重新考虑纯internal服务网络。

权限不是靠配置阅读推断：read key实际count/scroll/query均200，create/upsert/delete均403。持久化脚本实际执行restart和无`-v`的down/up；恢复脚本固定snapshot SHA-256，上传到唯一临时collection并验证1359个ID、payload、过滤和self-query，最后只删除临时collection。

## 7. 评估

- 检索：固定15题，`Recall@5=86.7%`。
- 单一相似度拒答阈值：锁定集仅70%/70%，正式拒绝采用。
- 最终回答集：可回答召回80%，拒答准确率100%，引用绑定100%。
- 人工忠实度：4/4。
- 初始版本比较集：0/3，暴露单路检索缺陷，报告保留。
- 双版本平衡检索后：3题回答人工复核3/3，引用绑定3/3。
- V2-C2服务端RRF：development 29/30，但唯一locked运行排名漂移，发布失败并保留证据。
- V2-C2.1旧50题：只做稳定性，50/50题各3次一致，不使用旧质量标签发布。
- V2-C2.1新20题：Dense/旧生产/Hybrid Recall@5为75%/80%/95%；Hybrid MRR 0.7100、nDCG 0.7705、candidate Recall@20 100%。
- Hybrid相对旧生产新增失败0，P95为8.011秒；14项门禁全部通过并激活。

失败报告和旧评估集保留；看过结果后不回调旧集分数。

## 8. 关键取舍

- 不用 LangChain/LlamaIndex：首版直接实现数据边界，便于解释。
- 本地 Embedding：语料不外发，运行成本稳定；代价是模型资产较大。
- Qdrant Local继续承担普通离线测试和回退；Server提供真实进程/网络/权限/持久化证据，代价是Docker与运维复杂度。
- Server活数据使用named volume并由固定资产重建，不直接迁移Windows Local目录；多一次构建，换来POSIX存储边界和可复现身份。
- B1使用回环HTTP而非TLS：只适合单机；任何局域网或公网使用前必须加TLS/反向代理并重新审批。
- 模型不生成引用元数据：少一点灵活性，换来可验证来源。
- 不用单一分数阈值拒答：实验简单，但跨问题不稳定。
- 无自动 API 重试：避免重复费用和隐藏失败；网络错误直接暴露。
- Streamlit 只做本地展示：复用核心服务、改动小；代价是还没有公开部署和账号体系。
- FastAPI 先只读、回环访问：先稳定跨项目合同；代价是尚无公网认证、限流、配额和遥测。
- 客户端RRF而非服务端RRF：多两次召回请求和一次payload读取，换来候选边界、算术与同分规则可测试、可复现。
- V3无development拆分：算法常量先冻结，再只打开一次发布集；代价是不能用V3继续调参，后续Reranker必须另建数据集。

## 9. 个人参与范围

本项目在 Codex 指导下完成。学习者参与需求与架构确认、语料/依赖/API费用审批、关键语义选择和阶段验收；Codex协助设计、实现、测试、诊断和文档整理。求职介绍时应说“在AI编码助手协作下完成并能解释、运行、修改”，不要表述为完全独立手写。

## 10. 常见面试问题

**为什么引用不能直接让大模型生成？**

模型可能编造 URL、章节或引用不存在的 Chunk。让模型只选本次检索 ID，程序再绑定可信 payload，可验证且可测试。

**怎样防止路径穿越？**

先做相对 POSIX 路径词法校验，再对真实文件 `resolve(strict=True)` 并检查仍位于允许根目录；同时拒绝符号链接和 Windows junction 逃逸。

**为什么相同文档要保存原始文本和清洗文本？**

原始 HTML 用于审计；清洗文本用于引用和检索。两者通过快照哈希、Block 位置和内容哈希关联，能证明清洗没有经过模型改写。

**Recall@5 是什么？**

固定问题的预期证据是否出现在前5条结果。13/15表示15题中13题至少命中一个预期 Chunk。

**为什么版本冲突集失败？**

初始问题只做一次全库Top-5，相关结果会被一个版本或相似页面占满。后来改为分别过滤3.13和3.14并平衡合并，新集人工复核3/3。旧0/3报告没有覆盖。

**怎样避免评估污染？**

固定数据和索引 fingerprint；优化前后保存报告；已查看的问题不再充当新锁定成绩；网络失败和结构错误不伪装成拒答。

**为什么 `/healthz` 与 `/readyz` 要分开？**

`/healthz` 只证明进程活着，必须快速且无重资源副作用。`/readyz` 判断配置、模型资产和索引能否服务；失败返回503，避免流量进入坏实例。

**为什么 HTTP 层不重新定义回答和引用逻辑？**

CLI、Streamlit、P2 和 P3 应共享同一个 `CitedRagService`。HTTP 层只做校验、封装和异常翻译，避免不同入口出现引用或拒答语义漂移。

**为什么不把Qdrant Local目录直接挂到Server？**

Local和Server的存储运行边界不同，Windows/WSL bind mount也不具备完整POSIX语义。项目从固定语料、Chunk配置和模型revision重建同一逻辑index ID，让Server写自己的Linux named volume；V1 Local目录保持只读回退。

**为什么internal网络最后改成普通bridge？**

B1的FastAPI在Windows宿主机，必须通过published port访问容器。实测`internal: true`使容器健康却没有宿主机接口连接。专用普通bridge恢复宿主机访问，再用`127.0.0.1`端口映射和driver绑定双重限制；这不等于允许公网。

**怎样证明read-only key真的只读？**

用它对活动collection执行count、scroll和self-query，预期200；再实际发create、幂等upsert和delete请求，三者必须403。测试结束用admin确认唯一探针collection不存在，报告不保存Key。

**怎样证明重启后数据没有静默损坏？**

restart和down/up前后都加载同一活动Manifest，检查index/build/collection身份、512维Cosine、1359 point、全部payload与唯一ID、版本过滤和self-query。每阶段`embedded_count=0`，证明不是偷偷重建掩盖丢失。

**snapshot恢复为什么不用活动collection原地覆盖？**

原地恢复失败可能破坏当前服务。先上传到唯一临时collection，完整验证后再决定是否切换；本次只做灾备演练，不切换活动指针，并在验证后精确删除临时collection。

**为什么服务端RRF失败后改成客户端RRF？**

服务端返回的同分集合和第20名边界可能漂移，客户端只能稳定已经返回的点。新方案对Dense/Sparse分别扩大窗口直到同分组闭合，再用`Fraction`精确融合，因此输入集合、rank、算术和最终同分规则都能离线测试。

**为什么旧50题不能继续当发布locked？**

旧集已经参与开发并暴露过locked失败，继续读取质量标签会造成评估污染。它只用于稳定性回归；新V3在任何查询前人工冻结，且问题和相关Chunk都不与V2重复，然后三模式各运行一次。

**为什么没有继续上Reranker？**

新集candidate Recall@20只比Recall@5高0.05，且只有1题的相关证据位于6～20名，不满足0.10和至少2题的双门。召回后的可修复排序空间不足以证明下载1.13 GiB模型合理。

## 11. 自测题

1. 哪些元数据来自 HTML，哪些由程序生成？
2. 为什么 Chunk ID 要绑定配置和文本哈希？
3. `answered` 引用未知 Chunk ID 时应怎样处理？
4. 为什么普通测试不能访问网络？
5. 单一 cosine 阈值为何在锁定集失败？
6. 语料 ZIP 恢复前要校验哪些内容？
7. 怎样向面试官解释13/15检索结果和两个失败样例？
8. 显式版本比较为什么使用 `answered`，何时才使用 `conflict`？
9. Streamlit 页面为什么要延迟初始化应用，并使用可注入工厂测试？
10. `/healthz`、`/readyz` 和 `/v1/answers` 各自允许哪些副作用？
11. 为什么客户端提供的 `X-Request-ID` 不能直接信任？
12. Local适配器与Server适配器分别解决什么问题？
13. 为什么B1不能同时使用internal网络和Windows宿主机API？
14. read-only权限测试为什么必须包含真实写请求？
15. `docker compose down`与`down -v`的风险差别是什么？
16. snapshot恢复后要验证哪些字段，为什么不能只看point count？
17. 同分边界为什么必须闭合，64/128/256窗口何时停止？
18. zero-based `RRF(k=2)`怎样计算，为什么内部使用`Fraction`？
19. V2与V3怎样隔离开发、稳定性和发布质量证据？

能脱离代码回答以上问题，并现场运行CLI、Streamlit、FastAPI或Qdrant验收脚本，指出引用绑定、权限与恢复代码和失败报告，才算真正掌握。
