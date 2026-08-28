# V2-C2.1 确定性客户端 RRF 设计

- 文档状态：`implemented`
- 版本：`0.2`
- 日期：`2026-08-25`
- 前置：V2-C2候选索引验证通过，但锁定重复排名门禁失败
- 实施结果：发布门通过，既有Hybrid候选已激活，API已升级为`cited-rag-api:v2-c2-1`

## 1. 问题与目标

V2-C2把Dense20、Sparse20和RRF20交给Qdrant单次Query API。客户端只能稳定排序Qdrant已经返回的点，无法控制服务端Prefetch内部同分名次、RRF分数或第20名候选边界。唯一一次`retrieval-v2` locked运行因此在指标生成前失败：

```text
EVALUATION_ERROR: V2 repeated retrieval ranking changed
```

V2-C2.1目标：复用已验证且未激活的1359-point Dense+Sparse collection，把候选边界闭合和RRF融合移到可测试的确定性客户端代码；使用全新未运行locked集决定是否发布。

本阶段不改变语料、Chunk、Embedding、Sparse tokenizer/BM25、named vector、版本Filter、MiMo Prompt、回答合同或引用绑定。

## 2. 不可变输入与保留证据

- 候选index ID：`c1a14f1a-dd33-59e8-8e4f-26a9f16846f1`。
- 候选build ID：`740d893f-20e4-4677-8e7c-74a4d45de92e`。
- 候选collection：`cited-rag-c1a14f1add33-740d893f20e4`。
- Sparse配置SHA-256：`53400f58436e2faf179eb5383aac62e63ca8ab86d161e7c8a05b413ee3b9d8a2`。
- Dense和Sparse每路最终候选数仍为20；融合候选数20；最终结果5。
- RRF保持`k=2`、两路等权，不做质量调参。
- V2-C2代码、development报告、locked失败记录和失败门禁原字节保留。
- 旧`retrieval-v2`不再提供发布质量证据；不能覆盖、改题或重跑后冒充首次locked结果。

## 3. 确定性召回

### 3.1 Dense

Dense查询增加`SearchParams(exact=True)`，绕过HNSW近似搜索。初始返回上限固定64，`with_payload=False`、`with_vectors=False`。客户端按以下顺序排序：

```text
Cosine score降序，point ID字符串升序
```

### 3.2 Sparse

Qdrant Sparse搜索本身为exact。使用与Dense逐字段相同的版本Filter、相同初始返回上限和相同同分规则。

### 3.3 同分边界闭合

每路目标为前20。初始`limit=64`；排序后满足任一条件即闭合：

1. 返回数量小于请求limit，说明匹配结果已耗尽。
2. 第20名score与最后返回项score不同，说明第20名同分组已完整包含。
3. limit已达到Manifest point count，完整上界已取回。

否则把limit乘2，最大不超过Manifest point count，再执行同一路查询。闭合后才截取20条。若Qdrant返回数量、ID、分数有限性或单调边界违反合同，检索安全失败。

`64`和倍增规则只解决同分完整性与网络开销，不改变最终数学排名；它们进入RetrievalConfig身份，HTTP请求不能覆盖。

## 4. 客户端RRF

对两条已闭合、已稳定排序的Top-20列表，以zero-based rank `r=0..19`计算：

```text
rrf_score(point) = sum(1 / (2 + r))
```

内部使用`fractions.Fraction`累加和比较，避免浮点排序漂移；只在输出严格模型时转换为有限`float`。最终排序固定为：

```text
精确RRF分数降序，point ID字符串升序
```

融合Top-20确定后，再按ID批量读取这20条payload；返回顺序不可信，必须按ID映射并验证point ID、Chunk ID、schema、版本和引用字段。最终Top-5必须是candidate Top-20前缀。

新模式标识固定为`hybrid-client-rrf-v1`，RetrievalConfig升级为schema v3，并保存：

- Dense/Sparse vector名称。
- 每路Top-20、融合20、最终5。
- Dense exact为true。
- 初始limit 64、倍增2、上限来源`manifest-point-count`。
- `k=2`、等权、zero-based rank。
- `fraction-exact`算术与`score-desc-point-id-asc`同分规则。

索引Manifest仍为schema v2；检索算法变化不伪造新索引身份。

## 5. 测试合同

离线测试至少覆盖：

1. Dense必须发送`SearchParams(exact=True)`；Sparse和Dense Filter完全相同。
2. 第20名无同分时只请求64；同分触边时按64、128、256扩展。
3. point数上界1359终止，不能死循环或超过Manifest。
4. 两路返回顺序任意打乱，闭合Top-20和融合结果仍逐字节相同。
5. RRF公式、zero-based rank、单路点、双路点和最终ID同分。
6. 非有限分数、重复ID、返回数超过limit、payload缺失或ID错配安全失败。
7. 旧schema v1继续使用`dense-plus-identifiers`；旧V2-C2 `hybrid-rrf`证据仍可解析，但不能自动激活。
8. `passed=false`、build不匹配或稳定性报告缺失时，激活脚本仍拒绝写指针。

普通测试完全离线，不需要Docker、模型或Qdrant Server。

## 6. 评估隔离

### 6.1 旧50题只做稳定性回归

`retrieval-v2`全部50题可用于新算法的稳定性回归，但不再计算或发布质量指标。每题运行3次，只比较：

- 最终5条ID、rank和RRF分数。
- candidate 20条ID、rank、Dense rank和Sparse rank。
- 扩展轮数及每路闭合limit。

任何漂移立即失败。该报告必须标记`quality_metrics_used_for_release=false`。

### 6.2 新`retrieval-v3`发布locked集

在执行任何V3检索前，新建并冻结20题：五类题型各4题；问题和相关Chunk不得与`retrieval-v2`重复；相关证据从1359个已验证payload人工回查，不能从任何模式Top-K反向生成。固定题集后保存语义SHA-256、来源index fingerprint和证据审计。

`retrieval-v3`没有development拆分。算法常量已由确定性合同冻结，不用V3调参。随后对同一20题依次运行：

1. `dense`。
2. 当前生产`dense-plus-identifiers`。
3. `hybrid-client-rrf-v1`。

每模式5次warm-up；20题各3次；报告不可覆盖。运行开始后，不改题、相关Chunk、算法或门槛。

## 7. 发布门

全部条件同时通过：

- 旧50题稳定性回归无漂移。
- 新20题三个模式重复签名均稳定。
- Hybrid candidate Recall@20可用。
- Hybrid Recall@5不低于同集Dense和当前生产路径，且至少`0.80`。
- Hybrid MRR@5、nDCG@5均不低于当前生产路径超过`0.02`。
- Hybrid三项质量指标至少一项相对当前生产路径绝对提升`0.03`。
- 当前生产路径命中的题，Hybrid不得新增失败。
- Hybrid warm P95不超过同集当前生产路径的2倍。
- 引用payload验证100%，外部API调用0。

任一失败：不切活动指针、不构建或重启API；保留报告和失败样例。

## 8. C3前置门

V2-C2.1通过或失败都不自动下载Reranker。只有新V3报告同时满足以下条件，才允许另写C3设计：

- candidate Recall@20比Recall@5至少高`0.10`。
- 至少2/20题属于“相关Chunk在6～20名，但不在Top-5”。

C3若获准，必须另建新的development与未使用locked集；不能用V3调Reranker后再把V3当发布locked。

## 9. 失败、发布与回滚

- 开发和评估只使用read-only Qdrant key；不需要admin key，不写collection。
- 仅当第7节全部通过，才原子切换活动指针到既有Hybrid build，构建`cited-rag-api:v2-c2-1`并重启API。
- 激活后验证health、ready、非法请求422、CORS关闭、重复排名、活动身份和Qdrant容器身份；不发送合法问答，MiMo调用为0。
- 激活后任一验收失败，立即切回固定Dense build `418359df-7c62-4345-9bfe-57459c251dd3`，恢复`dense-plus-identifiers`并复验ready。
- 不删除旧/候选collection、snapshot、named volume、旧镜像或历史报告。

## 10. 已批准执行范围

批准后允许：

1. 修改检索模型、客户端RRF、评估器、测试、文档和条件性Compose镜像标签。
2. 启动既有Docker Desktop/Engine与现有Compose服务；不修改安装、许可、WSL、端口、网络或资源上限。
3. 使用现有本地BGE、既有Hybrid候选和read-only Qdrant执行旧50题稳定性回归。
4. 人工建立、冻结并审计20题`retrieval-v3`；只运行一次三模式locked评估。
5. 仅在门禁通过后切活动指针、离线构建新API镜像并重启API；失败时按第9节回滚。
6. H盘新增硬上限`1,073,741,824` bytes；接近上限立即停止。

全阶段禁止：安装依赖、联网下载模型、调用MiMo、写Qdrant、创建/删除collection、使用admin key、删除volume/snapshot/旧镜像、公开端口、云资源或部署。

实际批准语句：

```text
批准按 DETERMINISTIC_FUSION_DESIGN.md 第10节执行 V2-C2.1
```

## 11. 官方依据

- [Qdrant Search：exact search与stable ordering](https://qdrant.tech/documentation/search/)
- [Qdrant Hybrid Queries：RRF公式与zero-based rank](https://qdrant.tech/documentation/search/hybrid-queries/)
- [Qdrant Query Decomposition：Python客户端RRF示例](https://qdrant.tech/documentation/improve-search/query-decomposition/)

## 12. 实施结果

- 离线合同与回归共372项通过；Dense携带`SearchParams(exact=True)`，Sparse与Dense共享Filter，同分窗口覆盖64/128/256与Manifest上限。
- 旧`retrieval-v2`的50题各运行3次，最终Top-5、candidate Top-20、源路rank和闭合窗口全部稳定；报告明确不使用旧质量指标发布。
- 新`retrieval-v3`在首次查询前冻结20题，五类各4题；语义SHA-256为`689873c28f5b9528a9d5b32c73e1cbac80fcfa9abe5aa6cb12057641235b4c01`，与V2问题和相关Chunk重合均为0。
- Dense、旧生产路径与Client RRF依次各运行一次；Recall@5分别为0.75、0.80、0.95，Hybrid candidate Recall@20为1.00，三模式各20/20重复稳定。
- Hybrid相对旧生产路径MRR提升0.0975、nDCG提升0.1097，无新增生产命中失败；P95为8.011秒，低于旧生产8.113秒。
- 发布门14/14通过，活动build为`740d893f-20e4-4677-8e7c-74a4d45de92e`；API health/ready为200，Qdrant容器未重启，外部API调用0。
- C3双门未通过：candidate Recall差0.05，只有1题落在6～20名。因此不下载Reranker。
