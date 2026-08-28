# V2-B2 API 容器设计

- 文档状态：`implemented`
- 版本：`0.2`
- 日期：`2026-08-24`
- 前置：V2-A 与 V2-B1 已验收
- 实施状态：第9节已获学习者明确批准并完成；机器可读证据见 `data/api-container-report.json`

## 1. 目标

把现有只读 FastAPI 放入 Linux 容器，并继续复用已经验收的 Qdrant Server、固定 BGE 模型和 Server 活动索引。

本切片只证明：

- CPython 3.14 Linux 依赖可解析且只使用 wheel。
- API 镜像可复现构建、非 root 运行、只读根文件系统。
- API 与 Qdrant 通过 Compose 服务名通信；宿主机只从回环端口访问。
- 模型和 Server Manifest 只读挂载，不复制进镜像，不允许在线下载。
- 容器重启后 `/readyz` 恢复，Qdrant 身份和 point 数不漂移。

本切片不证明：公网部署、TLS、认证、限流、弹性扩容、高可用、多 worker 或真实用户并发。

## 2. 只读审计结果

### 2.1 Docker 与现有服务

- 学习者已于 `2026-08-24` 本人确认 Docker Desktop 许可。
- Docker Desktop/Engine 启动后，CLI/Engine 为 `29.7.2`，Compose 为 `5.4.0`。
- 现有 Qdrant 容器恢复为 healthy；`http://127.0.0.1:6333/readyz` 返回 `200`。
- 运行态仍只发布 `127.0.0.1:6333`，两个 named volume 未修改。
- H 盘剩余 `114,502,803,456` bytes。

### 2.2 基础镜像

选择 Docker Official Image：

```text
python:3.14.7-slim-bookworm@sha256:23c59390fc717bf09f9336908199a0ae75d9c4264bf296123f94ad772fea3b52
```

只读 registry manifest 审计结果：

| 项目 | 值 |
| --- | --- |
| index digest | `sha256:23c59390fc717bf09f9336908199a0ae75d9c4264bf296123f94ad772fea3b52` |
| linux/amd64 manifest | `sha256:ff4ceef5258b9303b40c004af0bd31ac82c6248a6b951f9d9b329bf456f1f4b7` |
| Debian | bookworm slim |
| glibc 基线 | 2.36 |
| amd64 压缩层 | 4 层，共 `44,791,060` bytes |
| 上游源码 revision | `228f71e70a42ba9f9a092321b971031603bb88ff` |
| 创建时间 | `2026-08-05T16:25:52Z` |

选择 bookworm 而非 Alpine：FastEmbed 的 ONNX Runtime、NumPy、gRPC 等已经提供 manylinux/glibc wheel；不引入 musl 兼容风险。固定 tag 与 digest，避免 tag 漂移。

### 2.3 Linux wheel

审计目标：CPython `3.14`、Linux amd64、Debian bookworm glibc `2.36`、`--only-binary=:all:`。

- 检查现有 `requirements.txt` 的 76 个精确版本：75 个有兼容 wheel；唯一不兼容项是 Windows 专用 `pywin32==312`。
- API 最小直接依赖为 FastAPI、FastEmbed、HTTPX、Pydantic、Pydantic Settings、Qdrant Client、Uvicorn。
- 初始 PyPI 元数据审计得到41包，但遗漏了 `qdrant-client` 经 `httpx[http2]` 引入的 `h2`、`hpack`、`hyperframe`。首次真实 `--require-hashes` 构建因此安全失败，没有生成镜像或容器。
- 补入现有锁中的三个精确包后，正确闭包为44个包；全部版本约束满足，全部有兼容 wheel。所选 wheel 大小合计 `65,250,778` bytes。
- 最大二进制项为 `onnxruntime==1.28.0`（`19,214,924` bytes）、`numpy==2.5.1`（`16,664,835` bytes）、`grpcio==1.83.0`（`7,043,416` bytes）。
- Streamlit、Pandas、PyArrow、PyDeck、GitPython、`pywin32` 和开发工具不进入 API 镜像。

实际锁定的44个包：

```text
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.14.2
certifi==2026.7.22
charset-normalizer==3.4.9
click==8.4.2
fastapi==0.141.1
fastembed==0.8.0
filelock==3.32.0
flatbuffers==25.12.19
fsspec==2026.6.0
grpcio==1.83.0
h11==0.16.0
h2==4.4.0
hf-xet==1.5.2
hpack==4.2.0
httpcore==1.0.9
httpx==0.28.1
huggingface-hub==1.25.1
hyperframe==6.1.0
idna==3.18
loguru==0.7.3
mmh3==5.2.1
numpy==2.5.1
onnxruntime==1.28.0
packaging==26.2
pillow==12.3.0
portalocker==3.2.0
protobuf==7.35.1
py-rust-stemmers==0.1.8
pydantic==2.13.4
pydantic-core==2.46.4
pydantic-settings==2.14.2
python-dotenv==1.2.2
PyYAML==6.0.3
qdrant-client==1.18.0
requests==2.34.2
starlette==1.3.1
tokenizers==0.23.1
tqdm==4.70.0
typing-extensions==4.16.0
typing-inspection==0.4.2
urllib3==2.7.0
uvicorn==0.51.0
```

已新增 `requirements-api.txt`，每行同时固定版本与所选 wheel 的 SHA-256；构建使用 `--require-hashes`、`--only-binary=:all:`，没有使用 sdist 或现场编译。

## 3. 运行拓扑

```text
browser / P2 later
       |
       | 127.0.0.1:8000 only
       v
FastAPI container (UID 10001, read-only rootfs)
       |
       | http://qdrant:6333 + read-only key
       v
Qdrant container (existing B1 service)
       |
       +-- qdrant_storage named volume
       +-- qdrant_snapshots named volume

FastAPI read-only mounts:
  data/models/fastembed   -> /app/data/models/fastembed
  data/server-indexes     -> /app/data/server-indexes
```

API 与 Qdrant 继续加入现有专用非 internal bridge。理由：API 必须向 MiMo HTTPS 出站，宿主机运维脚本仍需回环访问 Qdrant。当前切片不额外拆 egress/internal 双网络，避免同时重写备份和迁移路径。

这不放宽外部暴露：API 只发布 `127.0.0.1:8000`，Qdrant 仍只发布 `127.0.0.1:6333`，6334/6335 不发布。局域网和公网地址禁止。

## 4. Dockerfile 合同

实现文件：`deploy/Dockerfile.api` 与项目根 `.dockerignore`。

1. builder 与 runtime 都使用同一固定 Python 3.14.7 slim-bookworm digest。
2. builder 只下载带哈希的44个 Linux wheel；runtime 通过 BuildKit 只读 stage mount 离线安装，不把 wheelhouse 留在最终镜像。
3. BuildKit Dockerfile前端固定为 `docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e`。
4. 不执行 `apt-get`，不安装编译器、curl、Streamlit或开发依赖。
5. 只复制 `src/cited_rag/` 与 `data/model-assets.json`；使用 `PYTHONPATH=/app/src`，不把宿主机 `.venv` 复制进去。
6. `.dockerignore` 使用正向白名单，排除 `.env*`、Git、缓存、测试、文档、原始语料、模型、local/server索引、备份和评估输出。
7. 固定 `HF_HUB_OFFLINE=1`、`PYTHONDONTWRITEBYTECODE=1`、`PYTHONUNBUFFERED=1`。
8. 固定 `USER 10001:10001`、`WORKDIR /app`、`HOME=/tmp`。
9. 入口固定为一个 Uvicorn worker：`python -m uvicorn cited_rag.api:app --host 0.0.0.0 --port 8000 --workers 1`。

容器内监听 `0.0.0.0` 只为 bridge 转发；宿主机发布地址仍精确绑定回环。

## 5. 配置与密钥

- 新增 `QDRANT_PROFILE=container`；该 profile 只接受精确 URL `http://qdrant:6333`。
- 既有 `server` profile 继续只接受 `http://127.0.0.1:6333`；admin profile 不允许容器服务名。
- API 通过既有 Git 忽略 `.env` 和 `.env.qdrant-read` 注入 MiMo 配置与 read-only key；admin key不进入API容器。
- Compose 的显式 `environment` 覆盖 `.env.qdrant-read` 中的宿主机 profile/URL，但不覆盖 read-only key。
- HTTP 请求不能传入模型、Qdrant URL、Key、路径或索引控制参数。
- 本地 Docker 管理员可从容器配置看到环境变量；B2接受此单机限制。公开部署前必须换外部 secret manager 或文件型 secret。

## 6. Compose 合同

在 `deploy/compose.qdrant.yaml` 增加 `api` profile；默认 B1 命令仍只运行 Qdrant。

API 服务固定：

- `profiles: [api]`。
- `depends_on.qdrant.condition: service_healthy`。
- 只发布 `127.0.0.1:8000:8000`。
- 模型和 Server Manifest 使用长语法、`read_only: true` 的 bind mount。
- `read_only: true`；`/tmp` 使用 `tmpfs`，上限 128 MiB。
- `cap_drop: [ALL]`、`no-new-privileges:true`、PID 256、CPU 2、内存 1 GiB。
- JSON 日志轮转 10 MiB × 3。
- healthcheck 使用容器内 Python 标准库请求 `/readyz`；不新增 curl。start period 60秒；该检查会加载并验证本地模型/Qdrant，但不调用 MiMo。
- `restart: unless-stopped`；只运行一个 worker，避免每个 worker重复加载约95 MB模型。

当前机实施使用先 `build api`、再 `up -d --no-deps api`；不重建、不重启现有 Qdrant。

## 7. 实施验收

### 7.1 离线合同

- 新增 API 锁文件、Dockerfile、`.dockerignore`、Compose、container profile 合同测试。
- 现有300项测试零删除；新增21项容器/profile合同后，实施代码阶段为321项，加入机器可读证据合同后为322项。
- `compileall`、`pip check`、Compose解析和 `git diff --check` 通过。

### 7.2 镜像

- 构建只接受 linux/amd64 与固定 base digest。
- `python --version` 为 `3.14.7`；44个包版本精确匹配；`pip check`通过。
- 镜像历史不含 `.env`、Key、模型、原始HTML、索引或备份。
- 进程 UID/GID 为 `10001:10001`，rootfs只读，capabilities为空。

### 7.3 运行

- `127.0.0.1:8000/healthz=200`、`/readyz=200`。
- readiness 的 configuration/index/retriever 均为 `ok`；活动 index/build/collection 与 B1 完全一致，point数仍为1359。
- 非法 `/v1/answers` 返回脱敏422；本切片不发送合法问题，因此不调用 MiMo。
- API container restart 后 readiness恢复；Qdrant容器ID、collection、named volume和snapshot不漂移。
- 8000只绑定127.0.0.1；6333边界不变；无8000/6333局域网监听。
- 模型与Server Manifest挂载只读；容器写入尝试失败。

## 8. 回滚

只停止并删除无状态 API 容器；保留 API 镜像与构建缓存供审计，保留 Qdrant容器、网络、两个named volume、collection、snapshot、模型和Manifest。

宿主机 FastAPI仍可用既有 `server` profile连接 `127.0.0.1:6333`。禁止使用 `docker compose down -v`。

## 9. 已批准并执行的精确副作用

学习者于 `2026-08-24` 明确批准以下范围，随后执行：

1. 新增/修改 `requirements-api.txt`、`.dockerignore`、`deploy/Dockerfile.api`、Compose、Qdrant container profile、测试和运行文档。
2. 从 Docker Hub 拉取固定 Python base：linux/amd64 压缩层 `44,791,060` bytes；不拉其他基础镜像。
3. 构建时从 PyPI/files.pythonhosted.org下载44个带哈希wheel，合计 `65,250,778` bytes；没有使用sdist或编译。
4. 在 H 盘 Docker 数据根写入基础镜像、API镜像和BuildKit缓存；本切片新增磁盘硬上限为2 GiB，超过即停止并报告。
5. 构建本地镜像 `cited-rag-api:v2-b2`；不push registry。
6. 创建一个无状态API容器，挂载既有模型与Server Manifest为只读，加入现有专用bridge，发布`127.0.0.1:8000`。
7. 为验证执行API容器restart；必要时只删除并重建API容器。现有Qdrant不重建、不重启，named volume不删除。
8. 运行健康、就绪、非法请求、非root、只读挂载、端口、资源和身份漂移验证；不发送合法问答。

不在批准范围：MiMo调用、模型或语料下载、Qdrant镜像/数据重建、named volume删除、局域网/公网端口、TLS/反向代理、防火墙、云资源、镜像推送、PostgreSQL、Hybrid/Rerank。

实际批准语句：

```text
批准按 API_CONTAINER_DESIGN.md 第9节执行 V2-B2
```

### 9.1 实际构建与运行结果

- Python基础镜像固定摘要拉取成功，镜像大小 `44,804,306` bytes；同时构建器解析并缓存了固定BuildKit前端。
- 首次构建因缺少HTTP/2 extra的三个哈希包安全失败；错误为 `h2<5,>=3` 未用 `==` 固定。没有产生API镜像或容器。补入 `h2==4.4.0`、`hpack==4.2.0`、`hyperframe==6.1.0` 后构建通过。
- 最终镜像 `cited-rag-api:v2-b2` 的ID为 `sha256:bed22b58bbeacac4abbd12b2e7e0bb66aa6dc1d3881caaa4080fbbef666e0f50`，大小 `123,768,630` bytes，linux/amd64，运行用户 `10001:10001`。
- 从拉取基础镜像前到最终验收，H盘净使用 `908,906,496` bytes，低于批准的2 GiB硬上限。
- API仅发布 `127.0.0.1:8000`，Qdrant仍仅发布 `127.0.0.1:6333`；两者位于既有专用bridge。
- `/healthz`、`/readyz`、OpenAPI均为200；非法回答请求为脱敏422，`code=request_validation_failed`，响应头和错误体request ID一致；外域预检为405且没有CORS允许头。
- API容器restart后恢复healthy；API容器ID不变。Qdrant容器ID与 `StartedAt` 前后完全一致，因此没有重建或重启。
- 活动指针与Manifest前后SHA-256一致；index/build/collection/fingerprint不变，point数仍为1359。
- rootfs、模型挂载、Server Manifest挂载的写入均被拒绝；`/tmp` tmpfs可写。API环境没有admin key；镜像不含 `.env`、模型二进制、Server索引或原始HTML。
- 验收未发送合法回答请求，没有调用MiMo、下载模型/语料、重建Qdrant或删除named volume。完整值见 `data/api-container-report.json`。

## 10. 官方依据

- [Python Docker Official Image](https://hub.docker.com/_/python/)
- [Python 3.14 slim-bookworm Dockerfile](https://github.com/docker-library/python/blob/master/3.14/slim-bookworm/Dockerfile)
- [Docker build best practices](https://docs.docker.com/build/building/best-practices/)
- [Docker multi-stage builds](https://docs.docker.com/build/building/multi-stage/)
- [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)
- [Docker Compose service reference](https://docs.docker.com/reference/compose-file/services/)
- [Python platform compatibility tags](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/)
- [PyPI JSON API](https://docs.pypi.org/api/json/)
