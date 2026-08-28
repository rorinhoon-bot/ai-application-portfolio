# P1 V2-B Qdrant Server 设计与执行记录

- 文档状态：`implemented`
- 版本：`0.2`
- 日期：`2026-08-23`
- 批准状态：学习者已批准第 11 节 V2-B1 副作用，并另行批准把 Qdrant 网络改为专用非 internal bridge；V2-B1 已按批准边界完成。MiMo 调用、API 镜像、公开端口、防火墙、云资源、named volume 删除和公开部署仍未批准。

## 1. 本切片目标

V2-B 拆成两个可独立验收的子切片：

1. **V2-B1，服务化存储**：Windows 宿主机继续运行已验收 FastAPI；Qdrant 改为 Docker 中的独立 Server。完成适配器、迁移、权限、重启、快照与恢复验证。
2. **V2-B2，API 容器化**：B1 稳定后再做 Python Linux wheel 审计、API Dockerfile 和完整 Compose。不能把 B1 的结果写成 API 已容器化。

当前只申请执行 V2-B1。这样可以把“存储迁移失败”与“Python 应用镜像失败”分开定位，并保留 V1 本地索引作为回退路径。

本切片不包含：

- MiMo 真实调用、模型下载、公开部署或云资源。
- 任意上传、网页抓取、管理 API 或摄取 worker。
- PostgreSQL、Redis、Kafka、Kubernetes、多节点 Qdrant。
- Hybrid、Sparse/BM25 或 Reranker；这些属于 V2-C。

## 2. 本机只读核验

2026-08-23 已完成只读检查，没有安装、启动或下载软件：

| 项目 | 结果 |
| --- | --- |
| Docker CLI / Docker Desktop | 未安装 |
| WSL | `2.7.8.0` |
| 默认发行版 | Ubuntu，WSL 2，当前 `Stopped` |
| Windows | Windows 11 家庭中文版，build `26200`，x86-64 |
| 内存 | `31.8 GiB` |
| Hypervisor | 已存在 |
| `LanmanServer` | `Running`，`Auto` |
| H 盘可用 | `109.36 GiB` |
| C 盘可用 | `169.2 GiB` |

Docker Desktop 官方 WSL 2 基线要求 WSL `2.1.5+`、Windows 11 build `22631+` 和至少 8 GB 内存；本机满足。当前不需要升级 WSL 或启用新的 Windows 功能。

Docker 官方同页明确：Windows Home 只能运行 Linux containers；本项目只使用 Linux Qdrant 容器。首次启动 Docker Engine 仍是安装后的强制 go/no-go 验收点；若失败则停止，不在本次批准范围外修改 BIOS、Windows 可选功能或系统策略。

## 3. 精确版本与制品

### 3.1 Docker Desktop

- 版本：`4.87.0`，Windows x86-64 build `236836`，发布于 `2026-08-17`。
- 官方安装包：`659,189,680` bytes，约 `628.65 MiB`。
- SHA-256：`9ac03d4e900c0fdee981d4bde083a55fdfb28ffba2cae77726eff2a437254822`。
- 安装模式：官方推荐的 per-user + WSL 2；不安装 Windows containers，不启用 Kubernetes。
- Docker Desktop 许可由学习者首次启动时亲自确认；安装命令不使用 `--accept-license`。

### 3.2 Qdrant Server

- Server：`1.19.0`，发布于 `2026-08-05`。
- 镜像：`qdrant/qdrant:v1.19.0-unprivileged`。
- Compose 固定多平台索引摘要：`sha256:a0e04fe623cb064502cd869cefc1dc7ce359d8edd481063b5bd351c0a0a2c91e`。
- 本机 linux/amd64 manifest：`sha256:80fb7b20ee4b49d57443b51aabdfb8514b910f333d3c4862e106fd02d1d66fa7`。
- amd64 压缩层：`70,706,168` bytes，约 `67.43 MiB`。
- Python Client：继续使用已锁定的 `qdrant-client==1.18.0`。官方只保证相邻 minor 兼容；Client 1.18 与 Server 1.19 正好相邻。真实集成测试必须保留默认兼容性检查。

不使用 `latest`、`v1` 或仅 minor 标签。执行前再次核对 tag 指向的摘要；摘要变化时停止，不自动接受新镜像。

### 3.3 不加入 PostgreSQL

V2-B1 没有异步任务表、用户账户或事务型业务数据。活动构建身份已经由不可变 Manifest 和原子指针表达。此时增加 PostgreSQL 没有可验证收益，留到摄取任务真正实现时再评估。

## 4. V2-B1 拓扑

```text
Browser / CLI / P2 later
          |
          v
FastAPI on Windows host
127.0.0.1:8000
          |
          | REST + read-only key
          v
Qdrant 1.19.0-unprivileged
127.0.0.1:6333 -> container:6333
          |
          v
Docker named volume
inside Docker Desktop WSL disk on H:
```

边界：

- 只发布 `127.0.0.1:6333`；不发布 `6334` gRPC 和 `6335` 集群端口。
- Qdrant 单节点运行；不启用 cluster。
- API 请求不能覆盖 URL、Key、集合名、索引根目录或超时。
- V1 的 `data/indexes/` 不修改；V2 Server 元数据使用独立 `data/server-indexes/`。
- B1 的 Compose 只管理 Qdrant。API Dockerfile 属于 B2。

## 5. Docker Desktop 本机落盘方案

### 5.1 安装与数据位置

1. 安装包下载到本机配置的Docker安装缓存路径。
   - 官方 URL：`https://desktop.docker.com/win/main/amd64/236836/Docker%20Desktop%20Installer.exe`。
2. 下载后先计算 SHA-256；不匹配立即停止，不执行安装包。
3. 使用 per-user、WSL 2 安装。
4. Docker Desktop 程序按官方 per-user 默认安装到 `%LOCALAPPDATA%\Programs\DockerDesktop`。
5. 使用安装参数 `--wsl-default-data-root=<configured-docker-data-root>`，让镜像、容器和 named volume 的主要增长数据位于专用数据盘。
6. 不传 `--accept-license`；学习者首次启动时自行阅读并接受条款。

不把 Docker Desktop 程序目录强行改到 H 盘。官方 per-user 模式固定使用用户目录；主要磁盘增长来自 WSL 数据盘，已经定向到 H 盘。

计划安装参数如下；这里只记录，不在批准前执行：

```powershell
Start-Process `
  -FilePath '<configured-docker-install-cache>\Docker Desktop Installer 4.87.0.exe' `
  -Wait `
  -ArgumentList @(
    'install',
    '--user',
    '--backend=wsl-2',
    '--wsl-default-data-root=<configured-docker-data-root>',
    '--no-windows-containers'
  )
```

### 5.2 空间预算

- 已核实网络下载：Docker Desktop `628.65 MiB`；Qdrant 压缩镜像 `67.43 MiB`。
- H 盘预留上限：本切片先保留 `10 GiB`，包含 WSL 虚拟盘、镜像、volume、快照和临时文件。
- 当前固定索引只有 1359 points；V1 本地索引约 `10.38 MiB`。Server 实际空间必须在验收报告中重新测量，不能用估算冒充结果。
- 执行前若 H 盘低于 `20 GiB` 可用空间则停止。

## 6. Compose 安全与运行合同

计划新增 `deploy/compose.qdrant.yaml`，使用以下默认值：

- `qdrant/qdrant:v1.19.0-unprivileged@sha256:a0e04fe623cb064502cd869cefc1dc7ce359d8edd481063b5bd351c0a0a2c91e`。
- 官方非 root UID/GID `1000:1000`。
- `read_only: true`；只给 `/qdrant/storage` 和 `/qdrant/snapshots` 挂载可写 named volume。
- `cap_drop: [ALL]`、`no-new-privileges:true`、`pids_limit: 512`、`cpus: 2.0`、`mem_limit: 1g`、`stop_grace_period: 30s`。
- 专用非 internal bridge；该网络不接入其他项目服务。实测证明 Compose `internal: true` 会让已声明的宿主机端口没有主机接口连接，因此无法同时满足 Windows FastAPI 访问；最终网络保留普通 bridge，但端口发布与 bridge 默认绑定地址都固定为 `127.0.0.1`。
- `127.0.0.1:6333:6333`；不使用 `0.0.0.0` 发布。
- `restart: unless-stopped`；用 `docker compose stop` 可明确停止。
- Docker `json-file` 日志轮转为 `10m × 3`；不把 API Key 或问题正文写入日志。
- `QDRANT__TELEMETRY_DISABLED=true`。
- `QDRANT__SERVICE__ENABLE_CORS=false`。
- `QDRANT__SERVICE__ENABLE_SNAPSHOT_URL_RECOVERY=false`，只允许本地文件或上传恢复，降低 SSRF 风险。
- `QDRANT__CLUSTER__ENABLED=false`。

认证使用两个随机高熵密钥：

- `QDRANT_ADMIN_API_KEY`：只给受控迁移/备份命令。
- `QDRANT_READ_ONLY_API_KEY`：只给在线 API，必须证明写操作返回拒绝。

两个值分别由 `secrets.token_urlsafe(48)` 生成；不复用 MiMo Key，不在控制台打印。

密钥分别保存于 Git 忽略的 `.env.qdrant-server`、`.env.qdrant-admin` 和 `.env.qdrant-read`，不与 MiMo `.env` 混用，不写 Compose、README、测试输出或聊天。Qdrant 当前不原生支持 Docker secret 的 `_FILE` 约定；本地 Compose 环境变量可被本机 Docker 管理员查看，因此这只是回环开发配置，不宣称公网生产密钥方案。

本切片不配置 TLS。原因是服务只映射到本机回环，且 B2 后会改为 Compose 内部网络。官方明确警告 API Key 不应经不可信明文链路传输；因此任何非回环、局域网或公网使用都必须先加入 TLS/反向代理并重新审批。

Qdrant 镜像未包含通用 HTTP 客户端。Compose 内部健康状态先用无额外包的监听检查，基线为 `interval: 5s`、`timeout: 3s`、`retries: 20`、`start_period: 30s`；验收脚本必须另外请求官方 `/readyz` 并要求 HTTP 200。不能只凭“容器进程存在”宣布就绪。

## 7. Server 适配器

实际实现：

```text
src/cited_rag/qdrant_connection.py
src/cited_rag/qdrant_runtime_files.py
src/cited_rag/qdrant_index.py
src/cited_rag/retrieval.py
src/cited_rag/cli.py
scripts/configure_qdrant_runtime.py
scripts/build_server_index.py
scripts/validate_qdrant_permissions.py
scripts/validate_qdrant_persistence.py
scripts/validate_qdrant_recovery.py
deploy/compose.qdrant.yaml
tests/test_qdrant_connection.py
tests/test_qdrant_compose_contract.py
tests/test_qdrant_runtime_files.py
tests/test_qdrant_operational_scripts.py
```

设计规则：

1. 本地测试适配器继续创建 `QdrantClient(path=...)`，普通 252 项测试不要求 Docker。
2. Server 适配器只从受控环境配置创建 `QdrantClient(url=..., api_key=..., timeout=..., prefer_grpc=False)`。
3. 在线检索只拿 read-only key；构建脚本显式读取 admin key。两个工厂不能共用同一个默认凭据。
4. 保持 `check_compatibility=True`；Client/Server 不兼容时失败，不静默关闭警告。
5. 连接失败、401/403、集合缺失、维度、距离、point 数或 payload 漂移统一落入现有安全错误边界。
6. 应用启动继续验证活动 Manifest 与物理 collection；不因 Server 可连就宣布业务 ready。
7. HTTP 请求模型不新增任何 Qdrant 参数。

## 8. 本地索引到 Server 的迁移

不把 Windows 上的 Qdrant Local 数据目录直接挂载给 Server。Qdrant 官方警告 Windows/WSL bind mount 不是完全 POSIX 兼容，可能在重启后损坏或把向量变成零值；Server 活数据必须使用 Linux named volume。

迁移使用可复现重建：

1. V1 `data/indexes/` 保持只读回退基线。
2. 从已提交的确定性语料归档离线恢复 25 个正文页面。
3. 从主工作树复制已批准且逐文件哈希固定的 5 个 BGE 必需文件到 V2 Git 忽略资产目录；精确内容 `95,221,432` bytes，不联网下载。
4. 用既有固定 revision、tokenizer、Chunk 配置和 Embedding 合同重新生成 1359 个向量。
5. 使用 admin key 写入一个新的 Server collection；不覆盖现有 collection。
6. 验证 512 维 Cosine、1359 points、全部 payload、唯一 ID、self-query 和 Python 3.13 过滤。
7. 验证通过后，才在独立 `data/server-indexes/` 写不可变 Manifest 和原子 `active-index.json`。
8. 若任一步失败，V2 Server 活动指针不变；V1 本地活动指针也不变。

同一 `IndexSpecification` 的 fingerprint 和 `index_id` 应与 V1 相同；Server 使用新的 `build_id` 和 collection 名。若 fingerprint 漂移则停止调查，不能改报告迁就结果。

该迁移只运行本地 ONNX，不调用 MiMo，不产生模型 API 费用。

## 9. 持久化、备份与恢复

验收顺序：

1. 构建并发布 Server collection。
2. `docker compose restart qdrant`，再次验证 ready、point 数、过滤和 self-query。
3. `docker compose down` 后重新 `up -d`，禁止使用 `-v`，再次验证数据仍在。
4. 使用 admin key 创建 collection snapshot。
5. 把 snapshot 下载到 Git 忽略的 `data/backups/qdrant/`，记录文件大小与 SHA-256；只提交不含数据的验收报告。
6. 将 snapshot 恢复为新的临时 recovery collection，验证配置、1359 points、payload、过滤和查询。
7. 经本次审批后，只删除该明确命名的临时 recovery collection；不删除活动 collection、V1 本地索引、named volume 或备份。

Qdrant collection snapshot 不包含 alias；本项目仍以活动 Manifest/指针为发布真相，因此备份必须同时保存 Server Manifest。恢复后只有验证通过才能切换指针。

回退：停止 Server profile，把运行配置切回 `local` 和 V1 `data/indexes/`。不删除 Server volume。Qdrant 官方不支持存储格式降级，所以升级镜像前始终先做 snapshot；本切片不做镜像升级实验。

## 10. 验收矩阵

| 证据 | 必须结果 |
| --- | --- |
| 离线回归 | 现有 252 项零删除；总计 300 项，普通测试零 Docker 依赖 |
| 配置测试 | 非法 URL、空 Key、错误 profile、请求覆盖全部拒绝 |
| 权限测试 | read-only key 可 count/query；create/upsert/delete 返回拒绝 |
| 发布测试 | 失败构建不替换旧活动指针 |
| 迁移 | 1359 points；维度、距离、payload、ID、过滤、自查询全通过 |
| 就绪 | Qdrant `/readyz` 200，P1 `/readyz` 200；不调用 MiMo |
| 重启 | restart 与 down/up 后身份和查询结果不漂移 |
| 恢复 | snapshot SHA-256 固定；临时 collection 恢复验证通过 |
| 安全 | 只监听回环；6334/6335 未发布；CORS/telemetry/URL recovery 关闭 |
| Git | `.env`、模型、Server 元数据、volume、snapshot 均未跟踪 |

V2-B1 完成后仍不能声称 API 已容器化、高可用、多节点或公网生产就绪。

## 11. 已批准的精确副作用

学习者已明确批准并执行：

1. 在专用数据盘创建Docker数据根目录。
2. 从 Docker 官方地址下载 Docker Desktop `4.87.0` 安装包 `628.65 MiB`，校验上述 SHA-256。
3. 安装 per-user Docker Desktop，WSL 2 数据根设为专用数据盘路径；不自动接受许可、不启用 Kubernetes/Windows containers。
4. 由学习者首次启动并确认 Docker Desktop 许可；随后启动 Docker Engine。
5. 拉取固定 Qdrant 镜像摘要，amd64 压缩层 `67.43 MiB`。
6. 创建两个 named volume、一个专用非 internal bridge、一个回环端口映射和 Git 忽略的本地密钥/运行目录。网络类型是执行中发现 internal 网络阻断宿主机访问后，经学习者单独批准修订。
7. 从主工作树复制固定模型必需文件 `95,221,432` bytes；不联网下载模型。
8. 本地运行 BGE，向 Server 新建并写入 1359-point collection。
9. 执行 Qdrant restart、down/up、snapshot、临时 recovery collection 恢复验证；验证后只删除临时 recovery collection。

不在本批准范围：MiMo 调用、Python API 镜像、公开端口、防火墙修改、云资源、付费服务、删除 named volume 或公开部署。

## 12. 实际执行与验收结果

### 12.1 运行环境

| 项目 | 实际结果 |
| --- | --- |
| Docker Desktop | `4.87.0`，per-user，安装命令未使用 `--accept-license` |
| Docker CLI / Engine | `29.7.2` / `29.7.2` |
| Docker Compose | `5.4.0` |
| WSL 数据根 | 本机配置的专用数据盘路径 |
| Qdrant image | 固定 `v1.19.0-unprivileged` index digest，linux/amd64，容器用户 `1000:1000` |
| Qdrant Client / Server | `1.18.0` / `1.19.0` |
| 网络 | `cited-rag-qdrant_qdrant_bridge`，driver `bridge`，`internal=false` |
| 端口 | 仅 `127.0.0.1:6333 -> 6333/tcp`；6334/6335 未发布 |
| 加固 | rootfs只读、`cap_drop=ALL`、no-new-privileges、1 GiB、2 CPU、512 PIDs |
| volume | `qdrant_storage` 与 `qdrant_snapshots` 均为 Linux named volume |

Docker Desktop 安装与 Engine 启动成功；学习者于`2026-08-24`确认已本人阅读并同意桌面端许可。没有自动点击或使用接受许可参数。

原 `internal: true` 配置下，容器内部健康，但 Docker 运行态显示 `6333/tcp` 没有宿主机 published endpoint，Windows `127.0.0.1:6333` 连接失败。改为经批准的专用普通 bridge 后，`NetworkSettings.Ports` 精确显示 `127.0.0.1:6333`，`/readyz` 返回 200；旧空 internal network 已删除，命名卷未删除。

只读rootfs使Qdrant启动日志出现一次无法在工作目录创建`.qdrant-initialized`标记的警告；进程、`/readyz`、storage/snapshot写入、restart和down/up均通过，实际可写状态只落在两个命名卷。qdrant-client还会对“HTTP + API Key”发通用警告；本切片仅因精确回环边界接受该取舍，任何非回环场景必须先加TLS。

### 12.2 迁移、权限与持久化

- 从确定性归档恢复 26 个语料文件，共 `3,581,318` bytes；模型只复制清单中的 5 个文件，共 `95,221,432` bytes，逐文件哈希与 revision 验证通过。
- 本地 ONNX 首建耗时 `59.798s`，写入 `1359` points；512维 Cosine、1359 payload、唯一ID、Python 3.13过滤与self-query全部通过，top score `1.0`。
- `index_id=614f6c23-7c35-5832-8086-c29651d60866`；`build_id=418359df-7c62-4345-9bfe-57459c251dd3`；活动 collection 为 `cited-rag-614f6c237c35-418359df7c62`。
- read-only key 的 count/scroll/query 均为 HTTP 200；create/upsert/delete 均为 HTTP 403。权限探针 collection 不存在，报告不含密钥。
- restart 与不带 `-v` 的 down/up 后，index/build/collection 身份及全部验证值不变，`embedded_count=0`；两个 named volume 均保留。
- 实测 volume 用量：storage `205,628,422` bytes；snapshots `19,845,184` bytes。该值包含 Qdrant Server 数据结构与快照开销，不用 V1 估算替代。

### 12.3 快照、恢复与应用就绪

- collection snapshot 下载大小 `9,922,560` bytes；SHA-256 `6f447e48ca32a7e60de2a5a1a01d5104881452c1c01ecca7067d1fa98ed36732`，与 Qdrant checksum 匹配。
- snapshot 只通过上传恢复到唯一临时 collection；1359 points、payload、ID、过滤和self-query全部通过。临时 collection随后按精确名称删除；最终 Server 只剩活动 collection 与1个 snapshot。
- 活动 Manifest 同步备份，SHA-256 `496cbfa8941a275f6e9a2c1aa94a7b317e62260b1be528c5fe3ed14fd2cbabd8`。snapshot、备份与 Server 元数据均受 Git ignore 保护。
- 真实 Uvicorn 使用 read-only key 连接 Server：`/healthz=200`、`/readyz=200`，configuration/index/retriever 均为 `ok`；就绪耗时 `12.496s`，未发 MiMo 请求。
- 最终离线回归 `300 passed`；`compileall`、`pip check` 与 Compose 解析通过。V1/V2-A 测试零删除。

机器可读证据：`data/server-index-build-report.json`、`data/qdrant-permission-report.json`、`data/qdrant-persistence-report.json`、`data/qdrant-recovery-report.json`。运维脚本默认拒绝覆盖这些历史报告；新环境显式使用 `--restore` 可重跑验证并保留报告字节。

V2-B1 只证明单机回环服务化存储，不代表 API 已容器化、支持 TLS、公开部署、高可用或多节点。

## 13. 官方依据

- [Docker Desktop Windows 安装、WSL 2 要求与安装参数](https://docs.docker.com/desktop/setup/install/windows-install/)
- [Docker Desktop 4.87.0 发布说明与官方 checksum](https://docs.docker.com/desktop/release-notes/#4870)
- [Docker Desktop WSL 数据默认位置](https://docs.docker.com/desktop/features/wsl/)
- [Docker Compose 网络与 internal 语义](https://docs.docker.com/compose/how-tos/networking/)
- [Docker 端口发布与回环绑定](https://docs.docker.com/engine/network/port-publishing/)
- [Qdrant 1.19.0 release](https://github.com/qdrant/qdrant/releases/tag/v1.19.0)
- [Qdrant Docker image tags](https://hub.docker.com/r/qdrant/qdrant/tags)
- [Qdrant Docker/Compose 安装与端口](https://qdrant.tech/documentation/installation/)
- [Qdrant 安全、只读 Key、回环绑定与容器加固](https://qdrant.tech/documentation/security/)
- [Qdrant `/healthz`、`/livez`、`/readyz`](https://qdrant.tech/documentation/ops-monitoring/monitoring/)
- [Qdrant Windows/WSL bind mount 风险](https://qdrant.tech/documentation/operations/common-errors/)
- [Qdrant snapshots](https://qdrant.tech/documentation/operations/snapshots/)
- [Qdrant Client/Server 相邻版本兼容边界](https://qdrant.tech/documentation/faq/)
