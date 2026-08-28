# P1 V2-D 可观测性与 CI 设计

- 文档状态：`accepted；D1运行已激活；D2 workflow-ready；D3 implemented`
- 版本：`0.4`
- 日期：`2026-08-27`
- 前置基线：V2-C2.1 已发布，活动检索为 `hybrid-client-rrf-v1`
- 本文范围：V2-D1 可观测性、V2-D2 CI、V2-D3有限重试；V2-C3 Reranker继续关闭

## 1. 目标

把当前可运行API补成可诊断、可回归的服务：

1. 一个请求可用request ID和trace ID串联HTTP、检索、融合、生成与错误。
2. 结构化日志、trace和metrics默认不保存用户问题、证据正文、回答正文、密钥或供应商响应。
3. 记录请求量、错误类别、阶段耗时、候选数、回答状态和Token。
4. GitHub Actions在无MiMo Key、无真实模型、无Qdrant Server时完成离线测试和镜像构建检查。
5. 遥测关闭或Collector不可达时，业务结果和就绪状态不改变。

## 2. 当前基线与缺口

已具备：

- 服务端生成UUID request ID，并在成功和错误响应中返回。
- `AnswerResult`保存prompt、completion和total Token；评估报告已有P50/P95。
- API与Qdrant容器已有`json-file`日志轮转。
- 372项普通测试离线通过，API合同、固定评估和容器合同均已存在。

缺少：

- 业务日志没有固定JSON Schema，也没有request ID上下文传播。
- API、Embedding、Dense/Sparse、融合和MiMo之间没有trace。
- 没有运行时Counter/Histogram，也没有安全指标端点。
- 仓库没有`.github/workflows/`，不能证明持续集成。

## 3. 切片顺序

### 3.1 V2-D1：可观测性

新增结构化日志、手工OpenTelemetry trace/metrics、离线内存导出测试和本地Collector。先证明隐私与故障隔离，再改运行镜像。

### 3.2 V2-D2：CI

新增GitHub Actions工作流、离线评估smoke、Git边界检查和API镜像构建。工作流在GitHub真实运行前只标记`workflow-ready`，不能标记`remote-passed`。

### 3.3 V2-D3：有限重试，后置

MiMo客户端已按D3合同实现有限重试。429、部分5xx、连接失败和超时的计费/幂等语义不同，因此最大尝试数、`Retry-After`、退避、总时限、重复计费和取消边界均固定，详见`docs/RETRY_DESIGN.md`。D1/D2原批准不包含该行为改变；D3由第10.1节单独批准后实施。

## 4. 依赖选择

直接依赖候选：

- `opentelemetry-api==1.44.0`
- `opentelemetry-sdk==1.44.0`
- `opentelemetry-exporter-otlp-proto-http==1.44.0`

CPython 3.14.3 binary-only dry-run已通过。新增递归包固定为`googleapis-common-protos==1.75.2`、`opentelemetry-exporter-otlp-proto-common==1.44.0`、`opentelemetry-proto==1.44.0`和`opentelemetry-semantic-conventions==0.65b0`；现有`requests`、`protobuf`等继续使用兼容锁定版本。

不选择`opentelemetry-instrumentation-fastapi`：当前`0.65b0`为pre-release，普通pip解析默认不会选择。项目路由少，手工埋点更容易固定字段、隐私和span层级，也避免自动HTTP客户端埋点意外记录上游URL或高基数字段。

OpenTelemetry Python当前trace与metrics为Stable，logs仍为Development。因此本阶段日志使用Python标准`logging`输出JSON，不接入OTel logs signal。

## 5. 结构化日志合同

每行一个JSON对象。允许字段：

```text
schema_version timestamp severity event service service_version
request_id trace_id span_id route method http_status duration_ms
stage outcome error_code answer_status candidate_count
prompt_tokens completion_tokens total_tokens index_id build_id
```

规则：

- `event`使用固定枚举，如`http.request.completed`、`rag.stage.completed`、`rag.request.failed`。
- route只保存模板`/v1/answers`，不保存原始URL或查询参数。
- `index_id`和`build_id`只进入日志/span，不进入metrics label，避免基数增长。
- 未知异常保存安全`error_code=internal_error`；默认不输出堆栈。开发模式可把堆栈写本地stderr，但仍不得含请求、证据或供应商正文。
- 禁止字段：question、evidence text、answer、citation excerpt、Authorization、API Key、Qdrant Key、完整供应商响应、绝对路径。
- request ID继续由服务端生成；不信任客户端`X-Request-ID`。

## 6. Trace合同

根span：`rag.http.request`。子span按实际执行产生：

```text
rag.http.request
└── rag.answer
    ├── rag.retrieval
    │   ├── rag.embedding
    │   ├── rag.qdrant.dense
    │   ├── rag.qdrant.sparse
    │   └── rag.fusion
    └── rag.generation
```

允许attribute：route、method、status code、answer status、Python版本、阶段outcome、候选数量、Token、index/build ID和安全错误码。禁止问题、证据、回答、Chunk正文、密钥和响应体。

实现使用手工span和`contextvars`传播request ID。未配置SDK时OpenTelemetry API为no-op；普通CLI、Streamlit和离线测试不需要Collector。Exporter使用BatchSpanProcessor；进程退出时执行有界flush，失败只写安全诊断，不改变HTTP状态。

## 7. Metrics合同

低基数指标：

- `rag.http.server.requests` Counter：route、method、status class。
- `rag.http.server.duration` Histogram，单位ms：route、method、outcome。
- `rag.stage.duration` Histogram，单位ms：stage、outcome。
- `rag.retrieval.candidates` Histogram：source=`dense|sparse|fused`。
- `rag.answers` Counter：status=`answered|refused|conflict`。
- `rag.errors` Counter：stage、error_code。
- `rag.model.calls` Counter：outcome；D1固定每个业务请求最多一次。
- `rag.model.tokens` Counter：kind=`prompt|completion`；total由两者相加，不重复计数。

P50/P95由Histogram计算；评估报告继续保存精确nearest-rank结果。运行端只暴露桶，不虚构SLA。

单次费用暂不生成数值。当前没有可核实、版本化的MiMo单价依据；报告写`cost_available=false`。只有固定价格来源、币种、单位和生效时间后才计算估算费用，不能用Token冒充费用。

## 8. Collector拓扑与安全

```text
API --OTLP/HTTP--> otel-collector:4318  # 仅Compose网络
                          |
                          ├── debug trace到Collector轮转日志
                          └── Prometheus exporter :9464
                                      |
                              127.0.0.1:9464
```

Collector固定：

```text
ghcr.io/open-telemetry/opentelemetry-collector-releases/
opentelemetry-collector-contrib:0.159.0@
sha256:1f2c54a30e713fac6b3ae77a1ec84010c2007e29ced8ec666214fc2f6739c1cc
```

linux/amd64 manifest digest为`sha256:4f4276c07cee9055f2ab630a86330243f85e208c388ee697bea2a44dab896c3f`。

边界：

- 4317/4318不发布到宿主机；9464只绑定`127.0.0.1`。
- Collector不接收鉴权头、问题或正文；配置只允许OTLP receiver、memory limiter、batch、debug和Prometheus exporter。
- 非root、只读rootfs、capabilities清空、no-new-privileges、资源限制和日志轮转。
- Collector不加入API readiness依赖；Collector停止时API仍healthy/ready，业务请求照常完成。
- D1不增加Prometheus Server、Grafana、Jaeger、云后端或遥测持久卷。

## 9. 离线测试与验收

### 9.1 日志

- 成功、422、503、502/504和500都带相同request ID关联。
- JSON逐行可解析，字段与枚举固定。
- 使用带伪密钥、问题、证据、回答和绝对路径的夹具，断言输出字节不含这些值。

### 9.2 Trace

- 内存SpanExporter验证父子关系、阶段顺序、状态和request ID。
- fake retriever/model形成完整`HTTP/answer/retrieval/generation`链，不加载BGE、Qdrant或MiMo。
- exporter抛错时回答结果不变。

### 9.3 Metrics

- InMemoryMetricReader重新计算Counter与Histogram数量。
- 低基数attribute allowlist固定；禁止question、chunk ID、index/build ID进入labels。
- Token缺失时不伪造0；usage完整时prompt/completion与`AnswerResult`一致。

### 9.4 Collector

- Compose配置解析通过；运行时只发布`127.0.0.1:9464`。
- health、ready和非法422产生trace/metrics，不发送合法问答，因此MiMo调用为0。
- 停止Collector后health、ready和离线假回答仍通过。

## 10. CI设计

文件：`.github/workflows/p1-ci.yml`。

安全：

- `permissions: contents: read`；`persist-credentials: false`。
- 第三方Action只用官方`actions/*`，固定完整commit SHA：
  - `actions/checkout` v7.0.1：`3d3c42e5aac5ba805825da76410c181273ba90b1`
  - `actions/setup-python` v7.0.0：`5fda3b95a4ea91299a34e894583c3862153e4b97`
- 不加载repository secrets，不运行`pull_request_target`，不执行PR内容拼接出的shell命令。
- job设置timeout与concurrency cancel；不push镜像或制品。

任务：

1. Windows CPython 3.14.3：安装精确`requirements-dev.txt`，执行`pip check`、`compileall`、全部离线pytest和Git边界检查。
2. 固定评估smoke：fake embedding/Qdrant/model，不访问网络、不读取`.env`，输出机器JSON并经过Pydantic重验。
3. Ubuntu镜像合同：构建固定digest API镜像，构建中使用带hash Linux wheel锁；不启动Qdrant、不调用MiMo、不push registry。

GitHub-hosted runner安装包和构建镜像会访问PyPI/GitHub/Docker registry；“离线”指测试执行不访问业务外部服务、不下载模型、不调用付费API。远程工作流首次成功前，只能声称配置和本地等价命令通过。

## 11. 发布门、回滚与限制

V2-D1发布门：

1. 既有377项测试零删除，新测试全部通过。
2. health/ready/API错误合同不变；活动index/build和Qdrant容器身份不变。
3. 敏感夹具在日志、trace attribute和metric label中出现次数为0。
4. Collector可用时产生关联trace和metrics；不可用时业务结果不变。
5. API镜像新增磁盘不超过512 MiB；Collector镜像新增磁盘不超过512 MiB。
6. 不调用MiMo、不写Qdrant、不下载模型、不删除collection/image/volume。

失败时：恢复`cited-rag-api:v2-c2-1`，移除未启用的Collector service；不回滚活动Hybrid索引，不删除Collector/API镜像，不删除named volume。

已知限制：单worker、本地回环、无遥测持久化、无告警、无公网身份、无远程CI结果、无可信单次费用。不能声称高可用、生产SLA或云监控。

### 11.1 V2-D1代码实施结果

学习者已批准第12.1节。当前完成：

- 三个直接依赖及四个固定递归依赖已进入Windows/Linux锁；现有依赖未升级，`pip check`通过。
- `observability.py`已实现字段allowlist JSON日志、request ID上下文、手工trace、低基数metrics、OTLP/HTTP exporter和2秒有界关闭。
- HTTP、answer、retrieval、embedding、Dense、Sparse、fusion和generation已手工埋点；问题、证据、回答、密钥和绝对路径隐私夹具出现0次。
- Compose已配置固定digest Collector、仅回环`9464`、未发布`4318`、非root/只读rootfs/资源上限；Collector不是API readiness依赖。
- 故障注入证明tracer与metric调用失败时离线fake回答仍为200；完整384项离线测试通过。

运行态已按补充授权激活：Docker Engine手工启动后，既有Qdrant因`restart: unless-stopped`发生一次受控重启；容器ID、启动后身份、活动Hybrid collection、Manifest、snapshot和named volume保持不变。固定Collector已启动，`cited-rag-api:v2-d1`已构建并只重建API；health/ready/OpenAPI/非法422和Collector故障隔离均通过。完整证据见`data/observability-runtime-release-report.json`。

### 11.2 V2-D1运行激活结果

- Collector使用固定GHCR index digest，Linux/amd64镜像108,615,156 bytes；本次H盘增量503,578,624 bytes，低于512 MiB门槛。容器为`10001:10001`、只读rootfs、`cap_drop=ALL`、256 MiB，仅发布`127.0.0.1:9464`。
- API镜像为Linux/amd64、`10001:10001`、只读rootfs、`cap_drop=ALL`；镜像124,906,372 bytes，本次H盘增量407,826,432 bytes，低于512 MiB门槛。固定依赖与`pip check`通过。
- 运行验收：`/healthz=200`、`/readyz=200`、`/openapi.json=200`、非法问答`422`；Collector可用时Prometheus `rag_*`指标和debug trace batch均出现。
- 故障隔离：Collector停止时API仍返回health/ready/422，API容器ID与启动时间不变；Collector恢复后`/metrics=200`。回滚验证将API切回`cited-rag-api:v2-c2-1`并恢复`v2-d1`，两次health/ready均为200。
- 隐私扫描敏感夹具出现0次；未发送合法真实问答，MiMo调用0，未下载模型、未写Qdrant、未删除collection/image/volume。

### 11.3 V2-D2本地实施结果

- 新增`.github/workflows/p1-ci.yml`：Windows CPython 3.14.3 job执行精确开发依赖、`pip check`、`compileall`、固定fake smoke、全量pytest和Git边界检查；Ubuntu job只构建固定digest API镜像。
- workflow使用官方`actions/checkout`与`actions/setup-python`完整commit SHA，`permissions: contents: read`、`persist-credentials: false`、timeout和并发取消均已固定；不使用repository secret，不包含`pull_request_target`、`docker compose up`或`docker push`。
- `scripts/run_ci_smoke.py`使用固定fake Embedding、Qdrant和Model，输出经Pydantic二次验证的机器JSON；不读取`.env`、不联网、不下载模型、不调用MiMo。固定结果见`data/ci-smoke-report.json`。
- `scripts/check_git_boundaries.py`拒绝追踪`.env`、私钥、模型文件、原始HTML和生成索引。当前本地等价命令通过；workflow状态只能标记`workflow-ready`，不能声称`remote-passed`。

## 12. 精确副作用与批准语句

### 12.1 V2-D1 可观测性实施

批准后允许：

1. 修改P1 Git工作树，新增日志、trace、metrics、测试、Collector配置和文档。
2. 在P1现有`.venv`安装第4节三个直接依赖及其固定递归闭包；更新Windows与Linux API锁，不升级Python/Docker/Qdrant/FastAPI。
3. 从官方GHCR拉取第8节固定Collector镜像；最大新增镜像磁盘512 MiB。
4. 构建`cited-rag-api:v2-d1`；最大新增镜像磁盘512 MiB。
5. 启动Collector并只重建/重启API；Qdrant容器不得重启，活动collection、Manifest、snapshot和named volume不得修改或删除。
6. 只请求health、ready、OpenAPI、非法422与离线fake链路；不发送合法真实问答，MiMo调用为0。
7. Collector故障隔离、回环端口、隐私扫描、完整测试和回滚验证通过后才激活V2-D1镜像。

本批准不包含V2-D2远程GitHub运行、V2-D3重试、MiMo调用、Qdrant写入、模型下载、系统设置、云资源、公开部署或删除旧资产。

建议批准语句：

`批准按 OBSERVABILITY_CI_DESIGN.md 第12.1节执行 V2-D1`

### 12.2 V2-D2 CI实施

另行批准后只允许新增本地workflow、smoke与合同测试，并运行本地等价命令；不会创建GitHub仓库、push、开启Actions或使用外部secret。真实GitHub运行等到仓库发布阶段单独批准。

建议批准语句：

`批准按 OBSERVABILITY_CI_DESIGN.md 第12.2节执行 V2-D2`

### 12.3 V2-D3有限重试设计

设计与实施均已完成。一次逻辑请求最多两次物理尝试，固定HTTP/传输错误白名单，不对不确定读取超时自动重试，等待时间裁剪到2秒，并区分物理调用、重试次数和潜在计费不确定性。离线fake、独立`v2-d3`镜像和未切流量回滚验收已通过；未安装依赖、未发送真实MiMo请求、未写入Qdrant。实现合同与证据见`docs/RETRY_DESIGN.md`、`data/retry-smoke-report.json`和`data/retry-runtime-release-report.json`。

本阶段使用的批准语句：

`批准按 RETRY_DESIGN.md 第10.1节执行 V2-D3`

## 13. 官方依据

- OpenTelemetry Python：https://opentelemetry.io/docs/languages/python/
- Python手工埋点：https://opentelemetry.io/docs/languages/python/instrumentation/
- OTLP exporter与Collector：https://opentelemetry.io/docs/languages/python/exporters/
- Collector官方发行：https://github.com/open-telemetry/opentelemetry-collector-releases/releases/tag/v0.159.0
- GitHub Actions Python：https://docs.github.com/actions/automating-builds-and-tests/building-and-testing-python
- GitHub Actions安全使用：https://docs.github.com/en/actions/reference/security/secure-use
- Prometheus Histogram：https://prometheus.io/docs/practices/histograms/
