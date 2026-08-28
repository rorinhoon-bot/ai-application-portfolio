# P1-F / V2-E 受限部署与求职展示设计

- 文档状态：`design-frozen；e1-implemented；e2-design-frozen；external-unexecuted`
- 版本：`0.3`
- 日期：`2026-08-28`
- 前置基线：V2-D1运行激活、V2-D2 `workflow-ready`、V2-D3本地验收完成
- 适用范围：公开证据页、可选受控实时演示；不开放摄取、索引管理或任意文件上传

## 1. 决策摘要

P1-F采用两条相互隔离的展示路径：

1. **默认路径：公开证据页**。使用GitHub Pages托管纯静态制品，展示固定评估结果、录制问答案例、架构、运行证据、失败案例和诚实限制。页面必须显著标注“录制证据，非实时推理”，不接收任意问题，不连接P1 API，不持有密钥，不产生模型调用。
2. **可选路径：受控实时演示**。只有资源测量、认证、持久配额、费用断路器、密钥、许可、恢复和回滚全部通过后，才考虑Cloud Run API与Qdrant Cloud。该路径不是P1-F首发完成条件，也不得以设计文档冒充已部署服务。

选择静态证据优先，不是把本地截图包装成在线AI：它把可复核工程证据公开化，同时避免匿名任意推理造成的滥用、密钥和费用风险。实时能力继续由本地容器、运行报告和后续受控部署证明。

## 2. 已验证基线与未知量

当前可用于设计的真实事实：

- 活动API镜像为`cited-rag-api:v2-d1`，Linux/amd64镜像大小`124,906,372` bytes；V2-D3只做过独立镜像验收，未切活动流量。
- 固定Embedding为`Qdrant/bge-small-zh-v1.5` revision `46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59`，5个资产共`95,221,432` bytes，许可记录为MIT。
- 活动Qdrant索引有`1,359` points、`512`维Dense向量和Sparse向量；API对Qdrant只有读权限。
- V2-D1已证明API、Qdrant与Collector本地容器拓扑可运行，V2-D2只达到`workflow-ready`，尚无远程GitHub Actions成功记录。
- 当前API没有公网认证、限流、持久配额、请求体总大小中间件、可信代理配置或全局费用断路器。

仍未测量或核实：

- 容器首次真实查询的峰值RSS、冷启动时间、Cloud Run环境下P95和并发行为。
- MiMo当前可核实单价、账户硬预算能力和真实重试成本。
- 云端模型资产分发、Qdrant迁移和恢复的完整运行证据。

因此，不能把现有`1 GiB`本地容器限制或平台标称内存直接当作云端容量证明。

## 3. 威胁模型

### 3.1 需要保护的资产

- MiMo API Key、Qdrant Key、云服务身份与部署凭据。
- 用户问题、证据正文、模型回答和运行遥测。
- 语料快照、Embedding模型文件、Qdrant数据与活动构建身份。
- API费用预算、平台配额和作品集可信度。

### 3.2 主要威胁

- 匿名脚本重复调用模型，放大Token、重试和云计算费用。
- 超长请求、并发请求或慢请求耗尽CPU、内存和worker。
- 伪造`X-Forwarded-For`绕过按IP限流；共享Token无法形成真实身份配额。
- 静态页偷偷连接实时API或第三方脚本，造成隐私泄漏和供应链风险。
- 把录制回答展示成实时回答，或把本地`workflow-ready`写成远程CI绿色。
- 云端Qdrant免费集群休眠/删除后静默失去索引；恢复时误覆盖活动数据。
- 通过公开端点触发导入、路径、URL、Prompt、模型或索引控制。

### 3.3 失败关闭原则

- 静态页构建不能验证来源、哈希或敏感边界时不发布。
- 实时服务缺失认证、持久配额、费用断路器或资源测量任一项时不公开。
- Qdrant身份、point数或配置不一致时`/readyz`返回503，不能降级到错误索引。
- 遥测、认证或配额错误不得放行请求；Collector错误仍不得改变业务结果。

## 4. 双路径拓扑

### 4.1 E1/E2：公开证据页

```text
Recruiter browser
       |
       v
GitHub Pages: static HTML/CSS/JS only
       |
       +--> committed evidence manifest + fixed demo cases
       +--> architecture / metrics / failure cases / screenshots
       +--> source links to repository reports and code

No FastAPI | No Qdrant | No MiMo | No secrets | No arbitrary input
```

### 4.2 E3：可选受控实时演示

```text
Approved demo identity
       |
       v
TLS + authentication + body limit + quota/cost gate
       |
       v
Cloud Run read-only FastAPI (min=0, max=1, concurrency=1 candidate)
       |                              |
       v                              v
Qdrant Cloud read-only key        MiMo secret

Protected operator path remains separate; no public ingestion/write route
```

E3图中的资源值只是待验证候选，不是已部署配置。Cloud Run预算告警不是硬费用上限；在持久计数与停止机制落地前，服务只能用于有明确开始/结束时间的演示窗口，不能长期匿名开放。

## 5. E1公开证据制品合同

### 5.1 页面内容

`portfolio-site/p1/`后续实现以下纯静态内容：

- 30秒项目摘要、目标用户、问题与V1→V2升级价值。
- 一张分层架构图：API、检索、Qdrant、MiMo、观测与CI边界。
- 只引用已提交机器报告的指标；区分V1、V2-C1和V2-C2.1题集，禁止跨题集拼接成单一提升值。
- 至少3个固定录制案例：有依据回答、低证据拒答、版本冲突/比较；每例包含来源报告、生成时间、模型、索引build和证据链接。
- 至少2个失败案例：服务端RRF不确定性导致发布失败、Collector故障隔离或有限重试的计费不确定性。
- 测试、容器、安全、恢复、已知限制和诚实参与边界。
- 90秒演示脚本；视频属于可选后续制品，未录制时不得显示占位在线链接。

### 5.2 数据来源与真实性

- 展示JSON只能由已追踪报告、固定评估集和文档导出；禁止在浏览器中重新计算或手填更好的指标。
- `evidence-manifest.json`记录每个输入文件的仓库相对路径、SHA-256、展示字段和导出器版本。
- 每个录制案例必须显示`recorded_evidence=true`与“非实时推理”；固定问题选择器不能伪装成任意问答框。
- 页面不得声称公网API、远程CI、SLA、高可用、零费用或exactly-once，除非存在对应机器证据。

### 5.3 浏览器与供应链边界

- 不使用远程JavaScript、字体、分析、广告、追踪像素、表单或第三方iframe；全部CSS/JS/图片来自同一静态制品。
- 不执行`fetch`、XHR、WebSocket或Service Worker；`connect-src 'none'`。
- 使用静态`<meta>` CSP、`Referrer-Policy: no-referrer`、`form-action 'none'`、`object-src 'none'`和`base-uri 'none'`。GitHub Pages不能提供项目自定义安全响应头，因此`frame-ancestors`等仅能由响应头完整执行的保护必须记录为平台限制。
- 外部官方文档与源码链接必须是编译时allowlist；新窗口链接使用`rel="noopener noreferrer"`。
- 构建产物不得包含`.env`、Key、绝对本机路径、原始HTML语料、模型文件、Qdrant数据或未脱敏遥测。

### 5.4 可访问性与窄屏

- 键盘可访问，焦点可见；图表同时提供文本结论，不只依赖颜色。
- 语义标题、landmark、图片替代文本、语言属性和足够颜色对比纳入合同测试与人工检查。
- 360px宽度不得横向溢出；大表格用卡片或可读滚动容器。

## 6. E2 GitHub Pages发布合同

选择GitHub Pages，因为当前仓库已经公开、证据天然与提交历史绑定、静态站不需要运行密钥和后端。发布前仍必须重新确认GitHub当前限制与仓库许可。

发布工作流与现有P1 CI隔离：

- 现有`p1-ci.yml`继续只有`contents: read`，不获得部署权限。
- Pages工作流只构建/校验`portfolio-site/`，部署job才拥有`pages: write`与`id-token: write`；不使用P1、MiMo或Qdrant secret。
- 官方Action固定完整commit SHA，禁用持久Git凭据；PR路径只构建不部署。
- 站点使用仓库子路径安全的相对URL；实际URL必须在首次成功发布后记录，不预先猜测。
- 发布前门禁：离线合同、敏感扫描、链接/资源清单、制品大小、移动端人工验收、证据哈希和Git diff检查。

回滚使用保留的上一个成功提交重新发布；需要停止公开时，必须由学习者批准后禁用Pages或移除部署源。设计阶段不更改GitHub设置、不push、不触发Actions。

## 7. E3受控实时服务先决条件

E3不是当前建议实施项。以后提出时必须先提交独立运行设计，至少满足：

1. **资源预检**：在与候选云配置一致的CPU/内存上测量启动、首问峰值RSS、P50/P95、超时和OOM；未测量前不选实例规格。
2. **身份**：`POST /v1/answers`必须在初始化Embedding和访问Qdrant/MiMo之前验证身份；每个演示者使用独立、可撤销凭据。共享公开Token无效。
3. **请求边界**：反向代理与应用同时限制请求体，JSON总大小候选上限`4 KiB`；保留现有问题`2,000`字符上限；只信任平台明确提供并由应用验证的代理头。
4. **持久配额**：按身份保存调用次数、Token预算和到期时间；进程重启不能重置预算。内存计数器不能作为长期公网配额。
5. **费用断路器**：全局日预算与每身份预算在发出MiMo请求前原子扣减；不确定计费尝试按最大风险计入。预算耗尽返回安全429/503并停止模型调用。
6. **并发与超时**：初始候选`max instances=1`、`concurrency=1`、`min instances=0`；平台超时必须大于应用总时限但保持有界。参数必须由真实预检修正。
7. **密钥**：Cloud Run使用Secret Manager；API只持有Qdrant read-only key。管理Key、快照与构建凭据不进入在线服务。
8. **数据与恢复**：先从固定snapshot恢复到新collection，验证向量/载荷/身份后才生成云活动配置；不得覆盖本地活动collection。免费集群休眠或删除必须有明确告警与恢复演练。
9. **公开面**：只允许health、ready和受保护answer；OpenAPI文档是否公开单独决定。没有导入、文件、URL、路径、模型、Prompt或索引参数。
10. **演示窗口**：在没有可证明硬云费用上限时，服务只在批准的时间窗启用；结束后收回访问并缩容/停用。预算告警不得描述成硬封顶。

任一项未通过，只保留E1/E2静态证据页，不以“先上线再补安全”为理由放宽门禁。

## 8. 平台核验与选择

平台事实于`2026-08-27`核验；执行前必须重新检查，因为免费层、价格和限制会变化。机器可读摘要见`data/deployment-capability-audit.json`。

### 8.1 已选择：GitHub Pages用于静态证据

- 官方限制页说明GitHub Free可为公开仓库使用Pages；站点大小上限`1 GB`，存在`100 GB/月`软带宽与`10次/小时`软构建限制。
- Pages不适合敏感交易；本方案恰好不接收输入、不持有密钥、不运行后端。
- 来源：<https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits>

### 8.2 条件候选：Cloud Run + Qdrant Cloud用于E3

- Cloud Run支持公开或受IAM保护的服务、Secret Manager、内存/并发/最大实例配置和按使用计费；默认内存`512 MiB`，候选`2 GiB`必须先做实测。
- 最大实例有助于限制并发资源，但官方说明短时可能超过配置值；Cloud Billing预算只告警，不自动硬封顶。因此二者都不能替代应用持久配额和断路器。
- Qdrant Cloud免费集群官方当前标注`1 node / 1 GB RAM / 0.5 vCPU / 4 GB disk`，无需信用卡，适合原型；闲置集群可能自动暂停并在长期不活跃后删除，不能作为无恢复计划的永久生产存储。
- 来源：<https://cloud.google.com/run/pricing>、<https://docs.cloud.google.com/run/docs/configuring/services/memory-limits>、<https://docs.cloud.google.com/run/docs/configuring/max-instances>、<https://docs.cloud.google.com/run/docs/about/concurrency>、<https://docs.cloud.google.com/run/docs/configuring/services/secrets>、<https://cloud.google.com/billing/docs/how-to/budgets>、<https://qdrant.tech/documentation/cloud/create-cluster/>、<https://qdrant.tech/pricing/>

### 8.3 未选择为默认路径

- **Hugging Face Spaces**：Docker Space的CPU Basic资源对当前模型更宽松，但计算Space、睡眠、持久化和可见性受当前账户计划与平台规则影响；默认磁盘非持久。它可作为用户已有合适计划时的备选，不作为零前提默认。来源：<https://huggingface.co/docs/hub/main/spaces-overview>、<https://huggingface.co/docs/hub/main/spaces-storage>、<https://huggingface.co/docs/hub/main/spaces-sdks-docker>。
- **Render Free**：官方当前免费Web Service为`0.1 CPU / 512 MB`并会在无流量后休眠，文件系统临时；未证明能承载当前Embedding和API，故不选。来源：<https://render.com/docs/free>、<https://render.com/docs/compute-plans>。
- **Fly.io**：官方当前没有免费层且要求支付方式；在预算未知时不选。来源：<https://fly.io/docs/about/pricing/>、<https://fly.io/docs/about/cost-management/>。

## 9. 验收矩阵

### 9.1 E1本地制品门

- 固定数据导出可重复；相同输入产生相同语义JSON和资源清单。
- 页面无任意文本输入、网络请求、远程资源、表单、secret、绝对路径或未脱敏正文。
- 所有指标都能回指已追踪报告及SHA-256；失败案例和限制不会被隐藏。
- 本地静态服务器下桌面与360px窄屏可用；键盘和无脚本降级内容可读。
- 新增合同测试、全量离线测试、`compileall`、`pip check`、Git边界和`git diff --check`通过。

### 9.2 E2公开发布门

- E1全部通过；GitHub Pages设置与发布workflow范围获学习者单独批准。
- 远程Pages workflow首次真实成功，在线URL返回200，资源和内部链接通过。
- 在线页面与批准提交、制品hash一致；无secret、API调用或第三方请求。
- 发布后记录截图、移动端检查、实际URL、Actions run和回滚提交；才可写入简历。

### 9.3 E3实时演示门

- 第7节全部通过，并有独立批准的账户、区域、资源、最大预算、调用次数、演示窗口与清理范围。
- 身份绕过、配额竞争、请求体超限、代理头伪造、超时、429/5xx、Qdrant不可用和Secret轮换均有测试。
- 云端snapshot恢复、read-only权限、健康/就绪、真实一次预算内问答、日志脱敏和停止/回滚有机器报告。
- 未达到任一门时，不公开实时URL，不在简历写“线上生产服务”。

## 10. 声明口径

E1/E2完成后允许：

- “构建并公开了可追溯的RAG工程证据站，固定展示评估、引用、发布失败与恢复证据。”
- “在线页面为静态录制证据；核心问答服务已在本地容器完成运行验收。”

E3未完成前禁止：

- “已上线公网RAG API”“支持真实用户并发”“零成本运行”“生产高可用”。
- 把GitHub Pages URL描述为实时模型服务。
- 把`workflow-ready`描述为远程CI通过。

## 11. 回滚与保留

- E1失败：只回退本次静态文件与导出代码；不改API、Qdrant、Collector、模型或运行卷。
- E2失败：保留失败Actions日志与制品，重新发布上一个成功提交；禁用Pages属于外部设置变更，需学习者批准。
- E3失败：停止新流量、关闭调用凭据、缩容服务，保留日志和机器报告；不删除本地活动build、旧API镜像、Qdrant named volume或snapshot。
- 不为“清理”删除失败评估、旧报告或安全事故记录。

## 12. 实施与批准边界

### 12.1 建议下一步：V2-E1本地静态证据制品

另行批准后，才允许：

1. 在`portfolio-site/p1/`新增纯静态HTML/CSS/JS、固定展示数据、证据manifest和本地预览说明。
2. 新增确定性导出/校验脚本与离线合同测试；只读取已追踪P1报告，不运行Qdrant、Embedding或MiMo。
3. 更新P1演示、README、架构、求职陈述和90秒脚本；不填写预测数字。
4. 不安装依赖，不创建云资源，不push，不触发远程Actions，不更改GitHub Pages设置，不公开URL，不产生费用。

### 12.2 后续暂停点：V2-E2公开GitHub Pages

E1本地验收后必须再次提交精确workflow SHA、权限、公开URL形状、仓库设置、回滚和公开内容清单。只有学习者单独批准，才允许push/触发Pages或更改GitHub设置。

### 12.3 后续暂停点：V2-E3受控实时演示

必须重新核验价格与平台合同，并提交云账户、区域、规格、身份、持久配额、硬停止方案、最大人民币预算、最大MiMo物理尝试数、数据迁移和销毁/保留范围。E1或E2批准不包含E3。

建议批准语句：

`批准按 RESTRICTED_DEPLOYMENT_DESIGN.md 第12.1节执行 V2-E1`

## 13. V2-E1实施结果（2026-08-28）

- `portfolio-site/p1/`已生成本地纯静态证据页；首页在只绑定回环地址的临时服务器返回HTTP 200。
- `scripts/export_portfolio_evidence.py`固定读取11份机器JSON和2张已追踪截图，生成规范JSON、同源JS、图片副本和输入/输出SHA-256清单；`--check`通过。
- 页面只展示录制证据：同一V3新20题检索对比、10题回答质量、3个问答案例、3类失败证据、运行身份、90秒脚本与限制；不接受任意输入，不连接API、Qdrant或MiMo。
- CSP、无网络运行API、无动态HTML注入、键盘tab、小屏布局、源/输出哈希、本地路径和密钥边界均由离线合同锁定；CI增加站点路径触发与导出一致性检查。
- 外部副作用保持0：未安装依赖、未调用模型、未写Qdrant、未改Docker、未push、未触发远程Actions、未更改Pages设置、未创建云资源或公开URL。
- 当前停在第12.2节。E1完成不授权E2；公开Pages仍需新的精确设计与学习者批准。

## 14. V2-E2发布设计结果（2026-08-28）

- 新增`docs/PAGES_RELEASE_DESIGN.md`与机器审计，把E2拆为E2A本地发布就绪和E2B公开激活；E2A完成不授权任何远程副作用。
- 冻结artifact根、文件/字节上限、安全验证器、默认项目站URL形状、四个GitHub官方Action完整SHA、最小job权限、PR不部署、main发布和回滚顺序。
- 远程仓库已确认public、默认分支为`main`；Pages实际设置、environment规则、run/deployment ID与`page_url`仍未知，必须在E2B授权后核验。
- V2-E2A已创建`.github/workflows/p1-pages.yml`、标准库artifact验证器与确定性readiness报告；`471 passed, 1 skipped`，依赖、编译、证据漂移与Git边界通过。
- 当前仍没有push、PR、远程run、Pages设置、deployment或公开URL；外部副作用保持0。下一批准点为`PAGES_RELEASE_DESIGN.md`第11.2节V2-E2B；E3实时服务不在该批准内。
