# V2-C Hybrid 与 Reranker 设计

- 文档状态：`partially-implemented`
- 版本：`0.5`
- 日期：`2026-08-25`
- 前置：V2-A、V2-B1、V2-B2 已验收
- 实施状态：V2-C1已完成；V2-C2候选已实现但锁定重复排名失败，未发布；V2-C2.1确定性融合已设计待批准；Reranker未实施

## 1. 目标

在固定语料、Chunk、Dense模型和Qdrant Server上，比较四条可复现检索路径：

1. `dense`：V1原始稠密基线。
2. `dense-plus-identifiers`：当前生产检索，用作现状对照，不冒充BM25。
3. `hybrid-rrf`：Dense与中文/代码Sparse并行召回，Qdrant RRF融合。
4. `hybrid-rerank`：只对Hybrid候选做Cross-Encoder重排。

目标不是强行启用更多组件。只有锁定测试集证明质量收益，且延迟、内存、许可和运行复杂度可接受，新增路径才可成为默认值。

本阶段不改变MiMo Prompt、回答合同、引用绑定、语料范围或公开端口。

## 2. 当前证据与缺口

历史 `retrieval-v1` 只有15题：Python 3.14为13题，3.13为2题。Dense命中10/15，`Recall@5=66.7%`；当前 `dense-plus-identifiers` 命中13/15，`Recall@5=86.7%`。

V2-C1已补齐50题分层合同、MRR/nDCG、warm P50/P95、cold-start和资源记录。V2-C2候选检索器已暴露独立candidate层，但锁定运行在指标生成前因重复排名漂移而安全失败：

- development的Hybrid `Recall@5`与candidate `Recall@20`均为29/30；没有显示排序空间。
- locked Hybrid指标不可用，不能补写或推断完整同条件表格。

旧15题和两份报告保持原字节，不覆盖、不改题、不把新结果冒充旧基线。

## 3. 能力审计

### 3.1 Qdrant

固定的Qdrant Server `1.19.0`和Client `1.18.0`已提供：

- named dense vectors与named sparse vectors。
- `SparseVectorParams(modifier=Modifier.IDF)`。
- `Prefetch`、`RrfQuery`和带权RRF参数。
- 单次Query API中分别预取Dense/Sparse候选再融合。

Dense Cosine分数有界，BM25分数无界，不直接做固定alpha原始分数相加。首个Hybrid基线使用排名融合：显式 `RRF(k=2, weights=[1.0, 1.0])`。任何权重或k调优只能使用development拆分，锁定拆分不能参与。

### 3.2 FastEmbed BM25不适合本项目中文语料

已安装FastEmbed `0.8.0`包含 `Qdrant/bm25`，但只列出18种非中文语言。其 `SimpleTokenizer` 先去标点再按空白切分；连续中文通常成为整个长token。即使关闭stemmer，也没有可靠中文词元边界。

因此不选择该现成BM25实现。否则“用了BM25”只是技术名词，不能证明中文关键词召回有效。

### 3.3 Reranker候选

FastEmbed `0.8.0`已支持 `BAAI/bge-reranker-base` Cross-Encoder。官方模型卡标记Chinese/English与MIT；固定revision候选为：

```text
2cfc18c9415c912f9d8155881c133215df768a70
```

FastEmbed加载所需5个文件元数据合计 `1,129,559,216` bytes，其中ONNX为 `1,112,459,588` bytes。当前未下载。模型只能在Hybrid锁定结果证明“候选召回足够但前5排序不足”后进入C3。

审计机器证据：`data/hybrid-rerank-capability-audit.json`。

## 4. C1：50题分层评估合同

新建 `retrieval-v2`，严格绑定现有语料/索引fingerprint。共50题，旧15题可作为已知历史子集，但每题仍须重新标记类型与拆分。

分层数量：

| 类型 | 数量 | 目的 |
| --- | ---: | --- |
| `semantic-paraphrase` | 12 | 不依赖显式代码词，检验Dense语义能力 |
| `exact-identifier` | 12 | API名、属性、参数、命令，检验Sparse精确匹配 |
| `mixed-semantic-identifier` | 10 | 中文意图加代码词，检验融合互补 |
| `version-specific` | 8 | 3.13/3.14过滤、相似页面与版本差异 |
| `known-hard` | 8 | 保留真实难例、近义章节和易混证据 |

拆分固定为30题 `development`、20题 `locked-test`。调tokenizer、RRF参数、候选数或Reranker策略只允许看development；锁定结果只在配置冻结后运行一次。全部四种模式使用同一50题、同一相关Chunk集合。

每题字段：

- 稳定case ID、问题、可选Python版本。
- 单一题型与development/locked-test拆分。
- 一个或多个人工核对的相关Chunk ID。
- 最短rationale，说明相关正文为何直接支持问题。

不从当前检索Top-K反向生成答案。相关Chunk必须从已验证的1359个payload中人工回查。

## 5. 指标与测量

### 5.1 质量

- `Recall@5`：至少一个相关Chunk进入前5的题目比例。
- `MRR@5`：首个相关Chunk倒数排名平均值。
- `nDCG@5`：使用二元相关性；多个相关Chunk按相同gain计算。
- `candidate Recall@20`：融合候选是否含相关Chunk；这是Reranker上限。
- 分层指标：按五种题型和development/locked-test分别输出。
- 引用绑定：返回point ID必须等于payload Chunk ID，URL继续由程序生成，目标100%。

### 5.2 延迟与资源

- 单进程、顺序查询；模型和索引加载不计入warm query延迟，单独记录cold-start。
- 每模式先5次不计分warm-up；50题各运行3次，记录150个样本的P50/P95。
- 同一机器、同一Docker/CPU配置；记录Python、Qdrant、FastEmbed、模型revision、候选数和线程数。
- 记录Qdrant collection字节、模型资产字节；Docker模式用 `docker stats --no-stream` 记录峰值内存快照。
- 评估阶段不调用MiMo，因此无Token/API费用。

### 5.3 V2-C1实际结果

`retrieval-v2`语义SHA-256为`a3b30c755dc2a4036b9d715a9df2bd891bfb850ce2bc2c369b43447c2a8abd13`。50个唯一相关payload均经只读Server回查，ID/版本错配为0。

| 模式 | Recall@5 | MRR@5 | nDCG@5 | P50 | P95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dense | 84.0% | 0.6313 | 0.6840 | 4.805 s | 5.304 s |
| Dense+identifiers | 90.0% | 0.7217 | 0.7673 | 4.807 s | 5.802 s |

生产路径新增4个命中、损失1个命中，净增3/50；质量三项提升，P95增加约9.4%。生产路径仍失败5题，其中`module-name-attribute`与`transpose-with-zip`为V1已知难例。完整分层、运行资源和失败清单见`docs/RETRIEVAL_V2_EVALUATION.md`。

旧15题及两份V1报告SHA-256复验不变。C1全程未写Qdrant、未下载模型、未调用MiMo、未安装依赖、未重启容器。

## 6. C2：中文与代码Sparse设计

### 6.1 词元

新增确定性 `unicode-code-bm25-v1`。完整配置的规范JSON SHA-256固定为`53400f58436e2faf179eb5383aac62e63ca8ab86d161e7c8a05b413ee3b9d8a2`：

- Unicode NFKC规范化，不改payload原文。
- Han范围固定为U+3400～U+4DBF、U+4E00～U+9FFF、U+F900～U+FAFF、U+20000～U+2EBEF和U+30000～U+323AF；连续Han文本生成重叠双字gram，不足2字保留单字。
- ASCII标识符模式固定为`[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*`并转小写；dotted identifier同时产生完整词元与各组件。
- 数字模式固定为`[0-9]+(?:\.[0-9]+)*`，因此`3.14.6`作为一个完整版本词元。
- 三类词元分别加`h:`、`a:`、`n:`命名空间，避免不同词元类别意外等价。
- 不做模型查询扩展、不猜同义词、不读取问题外参数。

词元使用现有 `mmh3` x86-32、seed 0生成unsigned 32-bit index。构建前收集全部唯一词元并审计hash碰撞；任一不同词元碰撞即失败，不写collection。构建同时保存按词元排序的不可变词表及其SHA-256；查询词元若与语料词表发生同hash异词冲突，检索安全失败，不能产生伪匹配。

### 6.2 BM25权重

- `k1=1.2`、`b=0.75`。
- 构建时由全语料计算平均文档词元数；身份保存精确总长度与文档数，不只保存舍入浮点数。
- 文档sparse value固定为`tf*(k1+1)/(tf+k1*(1-b+b*dl/avgdl))`，index升序，值必须有限且大于0。
- 查询使用同一tokenizer；重复词元去重，每个存在词元权重固定为1，index升序。
- IDF由Qdrant `Modifier.IDF`计算。

离线全语料预检结果：1359个Chunk、158321次词元、25836个唯一词元、118664个文档非零项；平均文档长度116.49816041206769、空Sparse向量0、碰撞0。机器证据为`data/hybrid-index-preflight.json`。

tokenizer schema、hash算法、k1、b、词元总数、文档数、词表SHA-256、Sparse名称、配置SHA-256进入新Index Manifest。任何变化产生新索引身份；旧schema v1 Manifest继续可读，以支持回滚。

### 6.3 Collection与查询

新collection同时包含：

```text
dense-bge-v1      512维 Cosine
lexical-bm25-v1   Sparse + IDF
```

旧Dense-only活动collection保留。构建器先完整验证旧活动collection，再逐点复制其已验证Dense向量与payload，同时加入新Sparse向量；不重新下载或联网生成Dense。新collection全量构建、验证1359 points、1359个payload、两种named vector、版本Filter、Sparse自查询与Dense自查询后仍只作为候选，不立即激活。

Hybrid查询：Dense与Sparse各预取20条，版本Filter逐字段完全相同；Qdrant用显式`RRF(k=2, weights=[1.0, 1.0])`融合为20个候选，最终返回5条。development曾出现`0.5`同分交换，因此客户端对Dense、Sparse与Fusion已返回结果固定按score降序、point ID升序。该规则让development三次重复稳定，但locked证明它不能约束Qdrant内部Prefetch/RRF的同分名次、融合分数或候选边界。评估保存Dense/Sparse来源排名、最终融合排名和`rrf_score`；不把RRF分数伪装成Cosine相似度。查询参数不由HTTP请求控制。

先只运行30题development并冻结配置；随后只运行一次20题locked-test。只有第8节发布门通过，才原子切换活动指针、构建`cited-rag-api:v2-c2`并重启API。未过门则保留候选Manifest和报告，不切指针、不重启API。

## 7. C3：可选Cross-Encoder重排

前置门：Hybrid的 `candidate Recall@20` 明显高于 `Recall@5`，说明问题主要是排序而非召回；否则Reranker无法修复缺失候选，不下载模型。

若过门：

- 固定 `BAAI/bge-reranker-base` revision与5文件allowlist，下载后逐文件SHA-256与许可验真。
- 只重排Hybrid前20个已授权Chunk，不扩大来源或绕过版本Filter。
- 输入为原问题与程序从payload构造的章节路径+正文；模型不能修改Chunk ID或引用字段。
- 对query-document pair执行真实tokenizer计数。禁止静默截断；超限时使用固定窗口与重叠，Chunk得分取窗口最大值，并记录窗口数。
- 输出数量、有限分数和Chunk ID集合必须精确匹配；异常时安全失败，不静默退回其他排名。
- 最终取前5；分数命名为 `rerank_score`，不与Cosine、BM25或RRF分数混用。

当前API容器内存限制1 GiB。模型启用前必须实测cold-start、P50/P95和峰值RSS，再决定是否提高限制或把Reranker保持为离线实验；不能先改资源上限再声称满足预算。

## 8. 默认路径进入门

所有阈值在locked-test运行前冻结：

### Hybrid成为默认路径

- 相对Dense locked基线，三项质量指标至少一项绝对提高0.03；`Recall@5`不下降，`MRR@5`与`nDCG@5`均不下降超过0.02。
- 相对当前生产路径`dense-plus-identifiers`，locked `Recall@5`不得低于0.90；`MRR@5`不得低于0.6467；`nDCG@5`不得低于0.7074。
- warm P95不超过Dense的2倍。
- 引用绑定100%，无新增失败案例。

### Hybrid+Rerank相对Hybrid

- locked `Recall@5` 不下降。
- locked `nDCG@5` 至少绝对提高0.03。
- warm P95不超过Hybrid的3倍。
- 内存能在经批准的容器上限内稳定运行；无OOM或静默截断。

未过门：报告保留，组件不进入默认问答路径。当前 `dense-plus-identifiers` 继续可用，不能因新组件更复杂就自动替换。

### 8.1 V2-C2实际门禁结果

- 候选索引验证通过：1359 points、25,836词表项、118,664个Sparse非零项；新增H盘33,865,728 bytes。
- development 30题：Recall@5 `96.67%`，candidate Recall@20 `96.67%`，P50 `7.572 s`，P95 `8.309 s`；配置冻结。
- locked只执行一次；在生成指标前触发重复排名稳定性错误，因此所有locked质量与延迟门均按不可用失败关闭。
- `data/hybrid-release-gate.json`为`passed=false`；活动指针、API镜像和容器启动时间未变。C3前置门未满足。

## 9. 错误、回滚与安全

- Sparse配置、named vector或Manifest不一致：readiness失败。
- tokenizer hash碰撞、词表hash漂移、非有限权重、空Sparse向量或point数量错误：构建失败且不激活。
- Dense/Sparse version Filter必须逐字段相同；否则合同测试失败。
- Reranker资产缺失、hash漂移、输出数量错误、NaN/Inf：模式不可用，不自动下载、不静默降级。
- 回滚只把活动指针切回已验证旧build；新代码必须能读取旧schema v1并恢复`dense-plus-identifiers`。不删除旧collection、snapshot或named volume，不覆盖历史报告。
- 全阶段不让HTTP请求传入模型、权重、candidate K、RRF参数、路径、URL或密钥。

## 10. 分段实施与待批准副作用

### 10.1 V2-C1：评估合同与50题集

计划副作用仅限Git工作树：

1. 新增V2评估模型、MRR/nDCG/延迟统计和离线合同测试。
2. 新建50题 `retrieval-v2`；保留旧15题与报告原字节。
3. 使用现有本地模型和只读Qdrant执行Dense与当前生产路径基线；不写Qdrant。
4. 不安装依赖、不下载模型、不调用MiMo、不重启容器。

### 10.2 V2-C2：Hybrid索引与RRF

C1已完成。C2精确范围如下：

1. 修改Git工作树中的索引schema、Sparse tokenizer/BM25、构建器、Hybrid查询、评估器、测试、文档与Compose API镜像标签；旧schema v1与现有两种Dense模式继续可读、可测。
2. 不安装Python依赖、不下载模型、不访问外部网络、不调用MiMo；使用现有`.venv`、本地BGE资产、Qdrant Client 1.18.0与Server 1.19.0。
3. 启动现有Docker Desktop/Engine和现有Compose服务；不修改Docker安装、许可、WSL位置、端口、网络或资源上限。
4. 使用admin key只创建1个新的Dense+Sparse collection，写入1359 points；Dense从已验证旧collection复制，Sparse由固定语料离线生成。旧活动collection、snapshot和两个named volume禁止删除。
5. 构建前碰撞审计；构建后校验point/payload/named vector/Filter/自查询/身份。若本次新collection未完成验证，允许只删除本次新建且未激活的collection；禁止触及旧活动collection。
6. 先跑development并冻结；再跑一次locked-test与全部50题报告。历史题集和报告禁止覆盖。
7. 只有第8节门槛全部通过才原子替换`data/server-indexes/active-index.json`，离线构建`cited-rag-api:v2-c2`并重启API；随后验证health、ready、非法请求、重复排名稳定性和活动身份。合法问答不发送，故MiMo调用为0。
8. 若门槛未通过，不切换活动指针、不重建或重启API；保留候选Manifest、词表、报告与失败样例。若激活后验收失败，立即切回固定旧build `418359df-7c62-4345-9bfe-57459c251dd3`，新代码按旧schema恢复当前生产检索。
9. 从启动前到完成后的H盘新增硬上限为`1,073,741,824` bytes（1 GiB）；接近上限立即停止。不得执行`docker compose down -v`、volume prune、image prune或删除旧镜像。

待批准语句：

```text
批准按 HYBRID_RERANK_DESIGN.md 第10.2节执行 V2-C2
```

### 10.3 V2-C3：Reranker消融

仅在C2候选召回证明有排序空间后申请。预期网络下载5文件 `1,129,559,216` bytes；Git忽略保存模型；磁盘硬上限建议3 GiB。可能需要调整API容器内存限制，但必须先测量再单独批准。没有证据时不下载。

### 10.4 V2-C2.1：确定性客户端RRF

V2-C2 locked失败后，不重跑旧质量门。新方案使用Dense exact search、Sparse同分边界扩展、`Fraction`客户端RRF和全新20题发布locked集；复用现有候选collection，不写Qdrant。精确算法、评估隔离、发布门、副作用和批准语句见`docs/DETERMINISTIC_FUSION_DESIGN.md` v0.1。

V2-C1批准已执行完成。第10.1节原批准语句保留作审计：

```text
批准按 HYBRID_RERANK_DESIGN.md 第10.1节执行 V2-C1
```

不在C2批准范围：Reranker下载、MiMo调用、新Python依赖、named volume删除、旧collection或snapshot删除、公开端口、云资源、部署、Docker安装/升级或资源上限调整。

## 11. 官方依据

- [Qdrant Hybrid Queries](https://qdrant.tech/documentation/search/hybrid-queries/)
- [Qdrant Search与Exact Search](https://qdrant.tech/documentation/search/)
- [Qdrant Hybrid Search](https://qdrant.tech/documentation/search/text-search/hybrid-search/)
- [FastEmbed](https://github.com/qdrant/fastembed)
- [BAAI/bge-reranker-base](https://huggingface.co/BAAI/bge-reranker-base)
