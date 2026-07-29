# P2 依赖提案

- 版本：v0.2
- 状态：accepted，已安装并验证
- 日期：2026-07-29
- Python：CPython 3.14.3
- 当前动作：P2 独立 `.venv` 已创建；45 个固定包已离线安装并验证

## 1. 推荐方案

首个实现阶段只直接安装状态图、SQLite checkpoint、结构化数据合同和测试所需的最小依赖。不直接增加完整 `langchain`、模型供应商 SDK、向量库、Embedding、Web UI 或多智能体框架。

解析结果显示 `langgraph` 依赖 `langchain-core`，后者传递依赖 `langsmith` 包。P2 不启用 LangSmith tracing，不配置 LangSmith Key，不访问 LangSmith 服务。

### 生产直接依赖

| 包 | 精确版本 | 用途 | 必要性 | Python 兼容性 | 许可证 |
|---|---:|---|---|---|---|
| `langgraph` | `1.2.9` | 显式状态图、条件边、中断、恢复和节点编排 | P2 核心目标；不用它就不能形成 LangGraph 作品证据 | PyPI 声明 Python `>=3.10`，提供 `py3-none-any` wheel；需在本机 CPython 3.14.3 独立验证 | MIT |
| `langgraph-checkpoint-sqlite` | `3.1.0` | 本地持久化 checkpoint 和恢复 | Human-in-the-loop、暂停恢复和故障恢复需要持久 checkpointer | PyPI 声明 Python `>=3.10`，提供 `py3-none-any` wheel；需在 CPython 3.14.3 验证 | MIT |
| `pydantic` | `2.13.4` | 严格状态、工具参数、人工动作和制品合同 | 拒绝未知字段并统一错误边界 | PyPI 声明 Python `>=3.9`，列出 Python 3.14；本机仍需验证原生 `pydantic-core` wheel | MIT |
| `pydantic-settings` | `2.14.2` | 环境变量、Secret 和安全配置 | 密钥不能进入源码、日志或 checkpoint | PyPI 声明 Python `>=3.10`，列出 Python 3.14 | MIT |

### 开发直接依赖

| 包 | 精确版本 | 用途 | 必要性 | Python 兼容性 | 许可证 |
|---|---:|---|---|---|---|
| `pytest` | `9.1.1` | 离线单元、集成和固定路径测试 | 项目完成标准要求自动测试 | PyPI 声明 Python `>=3.10`，列出 Python 3.14 和 Windows | MIT |

## 2. 版本选择原因

### `langgraph==1.2.9`

- LangGraph 1.x 是稳定主版本，官方将 1.0 设为 LTS。
- `1.2.9` 发布于 2026-07-10；`1.2.10` 发布于 2026-07-28，仅一天。首版选择已有更多观察时间的 `1.2.9`，避免刚发布补丁引入未知回归。
- 官方说明 LangGraph 可不依赖 LangChain 使用；P2 暂不安装 `langchain`。
- 已知不安全 checkpoint 反序列化影响 `langgraph<=1.0.9`，修复版本为 `1.0.10`；`1.2.9` 高于修复版本。

### `langgraph-checkpoint-sqlite==3.1.0`

- 官方定位为本地工作流和实验适用的 SQLite checkpointer。
- 已知 SQLite metadata filter SQL 注入影响 `<3.0.1`；`3.1.0` 高于修复版本。
- `3.1.0` 的 PyPI 安全提示要求限制 msgpack 反序列化。P2 将同时：
  - 设置 `LANGGRAPH_STRICT_MSGPACK=true`。
  - 状态只保存项目自有基础类型和严格 Pydantic 数据。
  - 不对用户开放 metadata filter key。
  - checkpoint 数据库只放在 P2 allowlist 目录。

### Pydantic 与 pytest

- 版本与 P1 已成功使用的固定版本一致，但 P2 会独立安装和验证，不复用 P1 环境。
- 这些版本的官方元数据明确包含 Python 3.14 支持。

## 3. 官方依据

- LangGraph 安装与可选 LangChain：<https://docs.langchain.com/oss/python/langgraph/install>
- LangGraph PyPI `1.2.9`：<https://pypi.org/project/langgraph/1.2.9/>
- LangGraph MIT 许可：<https://github.com/langchain-ai/langgraph/blob/main/LICENSE>
- LangGraph 持久化与 SQLite checkpointer：<https://docs.langchain.com/oss/python/langgraph/persistence>
- SQLite checkpointer PyPI `3.1.0`：<https://pypi.org/project/langgraph-checkpoint-sqlite/3.1.0/>
- SQLite checkpointer SQL 注入公告：<https://github.com/langchain-ai/langgraph/security/advisories/GHSA-9rwj-6rc7-p77c>
- checkpoint msgpack 公告：<https://github.com/langchain-ai/langgraph/security/advisories/GHSA-g48c-2wqr-h844>
- Pydantic PyPI `2.13.4`：<https://pypi.org/project/pydantic/2.13.4/>
- Pydantic Settings PyPI `2.14.2`：<https://pypi.org/project/pydantic-settings/2.14.2/>
- pytest PyPI `9.1.1`：<https://pypi.org/project/pytest/9.1.1/>

## 4. 暂不安装的包

| 包或类型 | 原因 |
|---|---|
| `langchain` | LangGraph 可独立使用；首步用假模型和项目自有工具合同，避免增加大依赖面 |
| 模型供应商 SDK、`httpx` | 当前不调用真实模型；模型和费用边界批准后再选最小适配器 |
| Qdrant、Embedding、Reranker | 首批原创资料很小，可用确定性内存检索夹具验证工作流 |
| Streamlit 或其他 UI | 先证明核心状态图；展示层后置 |
| LangSmith tracing 与服务 | `langsmith` 包由 `langchain-core` 传递安装，但不启用 tracing、不配置 Key、不访问服务 |
| AutoGen、CrewAI、A2A | D-001 已决定首版单工作流 |
| PostgreSQL、Redis | SQLite 足以验证本地 checkpoint；无公开部署 |

## 5. 安装与验证结果

已按批准边界执行：

1. 使用已存在的基础 CPython 3.14.3 创建 `projects/02-agent-research-workflow/.venv`。
2. 使用 pip 25.3 做生产与开发两次 `--dry-run --only-binary=:all:`：
   - 生产解析 40 个包。
   - 开发解析增加 5 个包，总计 45 个。
   - 所有制品都是 wheel；无源码构建。
3. 许可证审计：
   - 全部为 MIT、BSD、Apache-2.0、MPL-2.0、PSF-2.0 或这些许可的兼容组合。
   - `aiosqlite` 和 `colorama` 未提供 `license_expression`，但 PyPI classifier/官方资料分别确认 MIT 与 BSD-3-Clause。
   - 未发现未知、强 copyleft 或非商业限制。
4. 45 个 wheel 共 8,888,423 字节，即 8.48 MiB。
5. 完整解析结果固定为：
   - `requirements.txt`：40 个生产包。
   - `requirements-dev.txt`：引用生产锁并增加 5 个开发包。
6. 从本地 wheelhouse 离线安装；安装后：
   - Python 3.14.3、pip 25.3。
   - `pip check`：通过。
   - 锁文件 45 个包与实际环境 45 个包完全一致；缺失 0、额外 0。
   - `scripts/verify_environment.py`：通过。
   - LangGraph 最小图输入 `{"value": 1}`，输出 `{"value": 2}`。
   - SQLite checkpoint 关闭连接并重开后恢复 `{"value": 2}`。
   - 验证过程未访问网络、未调用模型 API。
7. 临时 wheelhouse 已安全删除，释放 8,888,423 字节。

### 固定文件哈希

| 文件 | SHA-256 |
|---|---|
| `requirements.in` | `413f4a8322779c3ef8654e158c564bbd64c3558865f7bb72ab0ae4ffc85bf47f` |
| `requirements-dev.in` | `192dc9d0b25b28fdb10ecd48d859b78632eaf46801d20380cf8f96912faeb08b` |
| `requirements.txt` | `5761efd80248f314bd44a2813ffb692b308c8f69ea9a4020833a96043efad099` |
| `requirements-dev.txt` | `ec2643a916d02c649aeb1b411a79a445be05052e1e45dfb46309834a37574564` |
| `data/dependency-resolution-production.json` | `e1c7be685d0dfe062270771ee2a47e7358bd214cc37cf40a90d6035ceb577dcf` |
| `data/dependency-resolution-dry-run.json` | `aadd338ac0741658303f22bc2b26c2a1c65a06c62d3bf28570b3f5314118577d` |

## 6. 预计影响

- 网络：只访问 PyPI 下载 wheel；未访问模型或研究资料站点。
- 磁盘：原 50 MiB 估算偏低。安装展开后含临时 wheelhouse 为 71.13 MiB；删除 wheelhouse 后稳定为 62.66 MiB。按默认批准将稳态边界修正为 65 MiB。
- 费用：PyPI 下载不产生模型 API 费用。
- 系统：只写 P2 `.venv` 和 P2 项目文件，不修改系统 Python、不写 P1 `.venv`。
- Git：`.venv/` 已由根 `.gitignore` 忽略；解析报告与锁文件可提交。

## 7. 批准边界

本提案的安装批准已用于：

- 创建 P2 独立 `.venv`。
- 查询和下载上述精确直接依赖及解析出的必要传递 wheel。
- 生成完整固定依赖清单。
- 运行本地兼容性与安全烟雾测试。

不包含：

- 下载真实研究资料或模型。
- 调用模型 API。
- 新增未列出的生产能力。
- 公开部署、Docker、数据库服务或系统设置修改。

直接版本未改变，无未知许可，无源码编译。实际稳态磁盘 62.66 MiB 超过原 50 MiB 估算；这是 wheel 解压和 `.pyc` 后的大小，不是新增依赖。依据学习者“类似安装默认批准”的授权，边界修正为 65 MiB，并已删除临时 wheelhouse。若后续超过 65 MiB，重新评估。
