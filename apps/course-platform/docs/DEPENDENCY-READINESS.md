# 新机器依赖准备：本机只读盘点

2026-09-22。**未安装、更新或下载任何依赖；未在新机器复现。** 本记录只读取仓库的运行依赖锁文件和三个现有虚拟环境的发行包元数据。完整逐包清单见 [dependency-audit.json](results/dependency-audit.json)，含项目、包名、精确锁定版本、现装版本、元数据中的许可证声明/分类、用途与无安装时的离线处理；它不是许可证法律核准。

## 方法与结果

仓库根目录运行：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/audit_dependencies.py --output apps/course-platform/.runtime/dependency-audit.json
```

读取 P1 `requirements.txt`、P2 `requirements.txt`、P3 `requirements.lock.txt`；各项目只用自身现有 `.venv` 的 `importlib.metadata` 查询，不调用 `pip`、网络或原有数据库/服务。P1 `requirements-api.txt` 是 **CPython 3.14/Linux amd64** 的含哈希 API 锁，不能直接作为 Windows 新机器安装清单。开发测试依赖另在各项目 `requirements-dev.txt`，本表只覆盖运行依赖。

结果为 **153 条项目依赖记录、9 条现有环境缺包、0 条已安装包版本不一致、19 条许可证元数据缺失或冲突**。重复包在不同项目分别记录。缺包全属 P1：`annotated-doc==0.0.5`、`fastapi==0.141.1`、`googleapis-common-protos==1.75.2`、`opentelemetry-api==1.44.0`、`opentelemetry-exporter-otlp-proto-common==1.44.0`、`opentelemetry-exporter-otlp-proto-http==1.44.0`、`opentelemetry-proto==1.44.0`、`opentelemetry-sdk==1.44.0`、`opentelemetry-semantic-conventions==0.65b0`。因此现有 P1 环境不能当作完整 API/服务新装验证；课设离线动态流程只调用其分词适配器，59 项先前回归未验证 P1 完整服务。

三个现有解释器各执行只读 `python -m pip check`，均返回 `No broken requirements found.`；此命令只检查**已安装包之间**的声明依赖，不会发现锁文件中尚未安装的9个包。锁文件比对结果优先用于完整环境判断。

| 主要包 | 锁定版本 | 本机元数据许可证 | 用途 | 不安装时的处理 |
|---|---|---|---|---|
| P1 `fastembed` | 0.8.0 | `Apache License`；分类又标 `Other/Proprietary`，**冲突待官方核实** | 本地向量编码 | 只保留已验证的分词适配流程，不宣称完整向量服务 |
| P1 `qdrant-client` | 1.18.0 | `Apache-2.0` | 向量库客户端 | 课设流程不启动或访问 P1 数据库 |
| P1 `fastapi` | 0.141.1 | 当前环境缺包，许可证待核实 | P1 独立 HTTP API | 课设工作台不用该服务；完整 P1 API 验收延后 |
| P1 `streamlit` | 1.60.0 | `Apache-2.0` | P1 独立展示 | 课设工作台使用自身静态前端 |
| P2 `langgraph` | 1.2.9 | `MIT` | 状态图编排 | 无法安装则只保留历史离线证据，不伪装实时工作流 |
| P2 `langgraph-checkpoint-sqlite` | 3.1.0 | `MIT` | 本地 checkpoint | 无法安装则暂停恢复功能演示 |
| P3 `mcp` | 2.0.0 | `MIT` | stdio MCP 服务 | 无法安装则只展示历史回放，不能称实际工具调用 |

表中的许可证仅为本机已安装发行包自报的文字；19 条需人工复核，其中 9 条因未安装无法读取元数据，另含 `fastembed` 自报字段冲突。未逐包核验发布者、官方许可证文件或下载来源。未来若申请新机器安装，应先按完整 JSON 清单逐包核准许可证、平台 wheel、来源和费用，再取得必要授权；遇到未知/冲突不能自行推断可安装。使用现有环境的离线测试不扩大外部权限，也不证明全新机器可重建。

新增两项行为测试覆盖锁文件解析、缺包/版本差异分离及许可证元数据冲突。完整应用回归 **61/61 通过、0跳过、203.933秒**，见 [dependency-readiness-tests.json](results/dependency-readiness-tests.json)。命令：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate.py --output apps/course-platform/.runtime/dependency-readiness-tests.json
```

浏览器控制接口本轮再次报 `Browsers: Error: nodeRepl.fetch request failed`；因此干净检出三角色浏览器复演及 ZIP 操作系统下载目录检查仍未完成。HTTP/ZIP 字节测试不能替代这项证据。
