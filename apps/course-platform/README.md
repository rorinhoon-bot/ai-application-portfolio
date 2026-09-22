# 研据工作台

基于可追溯证据与人工审批的 AI 研究交付系统。将 P1 知识、P2 工作流和 P3 MCP 工具组织成可操作的 Web 课设工程。

**当前交付是本机离线闭环。** 默认状态目录保留单用户演示；G3在新的身份状态目录提供研究者、审核者、管理员权限与会话。可以管理资料/项目/任务、确认范围、审核报告、查看证据、恢复运行并下载可验证制品。老师正式要求尚未提供；本工程为可扩展课设基线，不代表最终学校验收完成。实现包含助手协作，不是学生独立实现证据。

## 启动

Windows，在仓库根目录双击 `start-course-platform.cmd`，或执行：

```powershell
.\projects\02-agent-research-workflow\.venv\Scripts\python.exe -B apps\course-platform\check_environment.py
.\projects\02-agent-research-workflow\.venv\Scripts\python.exe -B apps\course-platform\server.py --open-browser
```

访问 `http://127.0.0.1:8877`。终端 Ctrl+C 关闭本工作台。端口被占用时使用 `--port 8878`，不关闭其他服务。状态默认存于本应用 `.runtime/`，已排除 Git。也可指定 `--state-dir` 到新的空目录，不能指向任何 P1/P2/P3 运行目录。同一状态目录只允许一个实例。

本版新增依赖 **0**，前端不需 Node、构建步骤或 CDN。后端使用 Python 标准库；引擎复用三个项目各自 `.venv` 和既有依赖。环境探针只查询解释器与包版本，完整功能仍以端到端测试为准。新电脑若缺环境，按三个项目原 README 与锁文件准备；本应用不自动安装、下载资料或创建容器。本机开发工作树使用已有环境的目录联接，联接不进入 Git；尚未在全新机器重建验收。

已从发布提交做[干净源码检出复现](docs/REPRODUCIBILITY.md)：55项离线回归和新状态HTTP启动通过，虚拟环境仍复用本机已有依赖。全新机器依赖安装与启动仍待验证。

## 身份隔离模式（G3）

先选一个**全新的空状态目录**，在未运行该目录服务时依次创建管理员、研究者和审核者。命令会交互式读取并二次确认密码，不在参数、`.env` 或仓库文件保存密码：

```powershell
.\projects\02-agent-research-workflow\.venv\Scripts\python.exe -B apps\course-platform\auth_cli.py --state-dir apps\course-platform\.runtime\graduation-g3-state --username localadmin --role admin
.\projects\02-agent-research-workflow\.venv\Scripts\python.exe -B apps\course-platform\auth_cli.py --state-dir apps\course-platform\.runtime\graduation-g3-state --username researcher1 --role researcher
.\projects\02-agent-research-workflow\.venv\Scripts\python.exe -B apps\course-platform\auth_cli.py --state-dir apps\course-platform\.runtime\graduation-g3-state --username reviewer1 --role reviewer
.\projects\02-agent-research-workflow\.venv\Scripts\python.exe -B apps\course-platform\server.py --port 8882 --state-dir apps\course-platform\.runtime\graduation-g3-state --auth-required
```

浏览器访问 `http://127.0.0.1:8882`。研究者登录后导入自己的两份以上有权资料，在研究项目创建表单指定审核者，冻结版本并创建任务。研究者不能批准自己的范围或报告；审核者用自己的账户登录，检查指纹及依据后决定。研究者可修订摘要和限制，改动后的报告须审核者重新批准。管理员可在“权限审计”查看最近200条允许/拒绝记录。完成一名身份的操作后退出登录，再以另一身份进入。身份模式禁用旧固定示例任务创建；默认单用户目录继续支持原演示。旧目录和新目录有互斥标记，不能靠去掉 `--auth-required` 绕过新目录权限。

会话空闲30分钟或创建8小时后失效；Cookie为HttpOnly、SameSite=Strict，业务POST使用每会话CSRF；5次登录失败后15分钟窗口内锁定。此模式只验证本机应用层权限。CLI信任当前操作系统账户，同一OS账户可直接改写SQLite；本机HTTP没有TLS，不可直接公开部署。P2内部审批身份仍为`operator-cli`，应用独立审计记录实际本机会话用户；ZIP哈希不是身份签名。详见 [G3需求](docs/graduation/G3-PRD.md)、[权限架构](docs/graduation/G3-ARCHITECTURE.md)、[评估方案](docs/graduation/G3-EVALUATION.md)与[交接](docs/graduation/G3-PLAN-HANDOFF.md)。

## 项目资料库（G1）

进入“项目资料”，导入或粘贴自己编写/有权使用的 UTF-8 TXT、Markdown，填写来源标识与授权说明，勾选确认后保存。可按中英文关键词检索、定位原文行列、查看 SHA-256 和历史版本；“新增版本”保留旧版。来源标识相同视作同一份资料，URL 仅作文字标签，不自动抓取。

单篇最多 48000 UTF-8 字节、128 段；总计最多 50 份资料、200 个版本、1000 个不同导入请求。文件名仅作标签，不能填写磁盘路径。当前无 PDF/Word、语义向量检索、删除或把旧版原样恢复为最新版功能；多人同时修订会拒绝过期版本，须重新读取后确认。

导入资料可进入“研究项目”：先冻结指定版本，再为2—4个候选创建待审批任务。“离线示例”继续使用自己的固定资料；两种模式均为脚本模型，不能把导入成功当作开放研究能力或内容质量通过。

毕业设计方向为“面向软件项目技术选型的可追溯研究与审批系统”。见 [新版需求](docs/graduation/PRD.md)、[扩展架构](docs/graduation/ARCHITECTURE.md)、[评估结果](docs/graduation/EVALUATION.md)、[实施计划与交接](docs/graduation/PLAN-HANDOFF.md)。本机G2-B动态任务与G3身份模式已接入；真实资料评估与学校要求对齐仍待后续实施。

## 研究项目与动态任务（G2-A/B）

进入“研究项目”填写问题与约束，选择资料版本并确认保存。项目固定使用这些版本；资料库后续更新不改变原范围。项目内可检索并核验原文归属和指纹。当前上限200个项目，创建请求最大8KiB。

保存项目本身不启动引擎。在项目详情明确选择2—4份不同冻结版本，每份绑定候选名称，再创建任务。任务先停在范围审批；批准后，P1 `tokenize_sparse` 提供词元，应用按词元重合做确定性排序，P3 通过只读 MCP 读取命中段落，P2 用真实状态图、checkpoint 与脚本模型生成待审报告。该检索并非P1原向量检索/BM25服务。每次执行最多64段、96KiB分段正文且所选版本正文也不超过96KiB；超出拒绝。

报告待审时可改摘要与限制，最多两次；旧指纹批准失效，证据矩阵不可在界面修改。批准当前报告后下载新 `frozen-delivery-v1` ZIP，包含项目执行快照、原始版本正文、P2状态/报告、修订、两级审批、MCP工具事件与回执。独立复核：

```powershell
.\projects\02-agent-research-workflow\.venv\Scripts\python.exe -B apps\course-platform\frozen_bundle_cli.py <下载的zip路径>
```

旧固定示例仍使用下面的历史流程和 `integrations/graduation/verify_bundle.py`。新包不能用旧验证器。见 [G2-B执行设计](docs/graduation/G2B-WORKFLOW.md)、[G2-B验收](docs/graduation/G2B-ACCEPTANCE.md)。

## 使用流程

1. 旧固定示例：新建任务并描述问题；范围固定为两个原创方案、六段资料。动态研究请从“研究项目”进入。
2. 检查研究范围，填写审批说明并勾选确认。未批准前不进行模型分析。
3. 等待 P1 解析、P2 编排和真实 MCP 工具调用完成。
4. 阅读报告、六条引用和审计。批准当前报告哈希后，状态变为“已交付”。
5. 下载 `research-delivery.zip`；服务先验证原工作流交付包。解压后可以独立复核：

```powershell
.\projects\02-agent-research-workflow\.venv\Scripts\python.exe -B integrations\graduation\verify_bundle.py <解压目录>
```

任务可复制、搜索、筛选和归档。归档不删除审计。重启保留任务；中断任务显示错误并要求显式恢复，不会自动批准。重新创建任务只获得独立离线演示状态，**不获得真实模型预算**。

## 三个项目如何复用

| 模块 | 本版实际调用 | 当前未接入 |
|---|---|---|
| P1 | 固定示例使用原 HTML 解析器；动态任务复用 `tokenize_sparse` | 原数据库、实时 API、向量索引/BM25服务 |
| P2 | LangGraph、checkpoint、双审批、脚本模型、幂等制品；动态冻结执行与修订 | 新增真实模型调用 |
| P3 | 真实 stdio MCP、默认只读工具、调用回执 | 任意网络工具与未批准写入 |
| 新 Web 层 | 任务索引、冻结资料/范围、候选绑定、修订页面、应用审计、有界后台队列；新目录G3本机账户及角色权限 | 远程服务、OS账户间隔离 |

固定示例的问题文本不会扩展其资料范围。动态任务只访问所选冻结版本。脚本报告只验证工程链路；引用存在、格式正确或操作者批准，均不能证明真实内容质量。P2 真实模型首批 2 份有限批准、4 份拒绝；修复后 2 份有限批准、1 份拒绝。永久预算上限 ¥5，保守占用 417/500 分、调用容量 109/109；禁止通过此应用换账本继续调用。

## 文档与验证

- [需求分析](docs/PRD.md)、[架构与数据设计](docs/ARCHITECTURE.md)、[API 与权限](docs/API-AND-SECURITY.md)
- [威胁模型与部署边界](docs/THREAT-MODEL-AND-DEPLOYMENT.md)、[时序与复用扩展](docs/REUSE-AND-COURSE-MAPPING.md)
- [UI V2设计与GitHub参考](docs/UI-REFRESH.md)、[新版截图](docs/screenshots/ui-v2/knowledge-desktop.jpg)、[UI首版记录](docs/UI-DESIGN.md)、[实施与评估方案](docs/EVALUATION-AND-PLAN.md)
- [验收结果与失败案例](docs/ACCEPTANCE.md)、[演示与交接](docs/HANDOFF.md)、[学习复盘](LLH_Study.md)
- [G2-B验收与浏览器证据](docs/graduation/G2B-ACCEPTANCE.md)、[52项完整应用回归](docs/results/graduation-g2b-tests.json)
- [G3本机身份与权限验收](docs/graduation/G3-ACCEPTANCE.md)、[55项完整应用回归](docs/results/graduation-g3-tests.json)、[三角色浏览器复核](docs/results/graduation-g3-browser.json)
- [G4正式要求与独立内容评价准备](docs/graduation/G4-REAL-DATA-AND-COURSE-PLAN.md)
- [G4离线人工评分工具](docs/graduation/G4-RATING-HANDOFF.md)；只汇总人工标签，不代替独立评审
- [G4人工仲裁离线验收](docs/graduation/G4-ADJUDICATION-ACCEPTANCE.md)、[63项应用回归](docs/results/adjudication-tests.json)
- [G4交付ZIP与评分清单绑定](docs/graduation/G4-BUNDLE-BINDING-ACCEPTANCE.md)；逐格核对主张、引用与报告，仍须授权资料和独立人评
- [G4报告整体覆盖复核](docs/graduation/G4-COVERAGE-HANDOFF.md)、[63项离线验收](docs/graduation/G4-COVERAGE-ACCEPTANCE.md)；摘要、推荐、遗漏与限制仍由人判断
- [后续独立工程验收](docs/graduation/NEXT-STEPS-ACCEPTANCE.md)、[59项离线回归](docs/results/next-steps-tests.json)
- [干净源码检出复现记录](docs/REPRODUCIBILITY.md)、[55项复跑结果](docs/results/clean-source-tests.json)
- [新机器复现核对清单](docs/INSTALLATION-CHECKLIST.md)、[五分钟答辩演示草案](docs/graduation/DEFENSE-DEMO.md)
- [依赖只读盘点与复现缺口](docs/DEPENDENCY-READINESS.md)、[153条逐包元数据](docs/results/dependency-audit.json)
- [61项离线回归](docs/results/dependency-readiness-tests.json)
- [身份模式 HTTP ZIP 落盘与独立复核](docs/graduation/HTTP-DOWNLOAD-PERSISTENCE.md)；浏览器下载目录仍待验证

```powershell
.\projects\02-agent-research-workflow\.venv\Scripts\python.exe -B -m unittest discover -s apps\course-platform\tests -v
```

测试使用临时应用目录。HTTP 测试仅访问自建 loopback 服务，实际引擎阻断外部 socket；不访问原项目数据库。浏览器演示任务名称含“演示”，审批说明明确为离线演示。

## 已知限制

仅 Windows 现有环境验证；无公开部署、全新机器安装验证或独立内容评分。G3只在新目录提供本机认证和对象权限，未做公网安全审计。HTTP 标准库适合本机演示，不能直接公开暴露。动态检索是P1分词加应用词元交集；不支持通用领域、语义检索、真实模型质量承诺。状态及审计对同一 OS 账户管理员不防篡改；哈希证明一致性，不证明签名身份。固定示例的网页审批说明仍只留在应用任务索引；动态包保存P2审批、修订及MCP审计，但P2内部仍将应用操作者映射 `operator-cli`，认证用户ID由应用索引及权限审计单独保存，ZIP不包含可独立验真的用户签名。
