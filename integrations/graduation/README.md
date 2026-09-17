# 可信 AI 应用方案研究与交付平台

> 发布版本：保留远端新版P1及其已有API/容器/Pages证据；整合仍只调用HTML解析器，不操作实时服务。下文旧开发树未找到P1文件的描述是历史审查范围；版本差异、新兼容验证与公开筛选见[发布说明](../../docs/integration/PUBLICATION.md)。

可运行的本地离线毕业设计原型：P1解析可追溯知识，P2编排研究与双审批，P3通过真实MCP读取受控证据，输出报告、限制、审批和调用审计。

**当前只验证离线工程行为。P2真实模型内容验收未通过；未做云部署，不宣称生产可用或整套毕业设计完成。** 首批真实六题2份有限批准、4份拒绝，修复后三题2份有限批准、1份拒绝。P2上限永久5元，417/500分、109/109调用容量；此整合只用脚本模型，真实调用与费用均0。

## 已实现范围

- P1：调用原 `PythonDocsHtmlParser` 解析6段原创HTML资料；整合层做确定性关键词匹配，保留原文件SHA-256、章节、段落序号。模式明确为 `fixture-keyword`，没有调用BGE/Qdrant或原P1服务。
- P2：复用原V2 LangGraph、严格状态、两个人工门、独立SQLite checkpoint、0费用脚本操作账本与内容寻址导出。P1/P2业务代码和历史gold/失败/预算文件未改。
- P3：通过本地.venv启动真实MCP stdio服务，按ID读取与哈希比对；写工具关闭，调用前后有无覆盖收据。
- 协调层：固定解释器/脚本路径、子进程环境allowlist、超时、审批hash绑定、run独占锁、同步checkpoint、进程崩溃恢复、审计复验、幂等交付。

## 运行

在仓库根目录PowerShell执行，使用已经存在的三个项目 `.venv`，无需新增依赖：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& .\projects\02-agent-research-workflow\.venv\Scripts\python.exe integrations\graduation\demo.py
```

演示仅使用新临时目录，并明确 `approval_actor=scripted-test`。正常输出两门至COMPLETED、6条证据、8次真实MCP读取、3次脚本模型调用，重复批准仍1份P2报告。脚本审批不等于真人内容评分。

显式人工流程：

```powershell
& .\projects\02-agent-research-workflow\.venv\Scripts\python.exe integrations\graduation\cli.py start
# 阅读输出，记录 run_id 与 request_hash；先核对固定候选/资料边界。
& .\projects\02-agent-research-workflow\.venv\Scripts\python.exe integrations\graduation\cli.py approve <run_id> --expected-hash <request_hash>
# 现在停在REPORT_NEEDS_HUMAN。status输出完整报告，先复核正文、证据与限制。
& .\projects\02-agent-research-workflow\.venv\Scripts\python.exe integrations\graduation\cli.py status <run_id>
& .\projects\02-agent-research-workflow\.venv\Scripts\python.exe integrations\graduation\cli.py approve <run_id> --expected-hash <report_hash>
```

`reject`/`cancel`使用当前门的同一hash。`recover <run_id>`只恢复已持久化未完成节点，不替你批准人工门。`start --question "..."`可改问题文本；候选仍固定两个原创方案、三个维度，不是开放知识问答。运行目录在本整合目录 `.runs/<run_id>/`，不会打开P1/P2/P3原数据库。请勿编辑checkpoint或复制真实账本进入这里。

最终文件：`delivery-report.md`包含边界、两门审批、MCP调用ID/result hash和P2正文；`delivery.json`绑定全部证据；`artifacts/`保留唯一P2内容寻址报告；`mcp-audit/`保留逐调用收据。演示留存于 `demo/` 时无需打开任何数据库即可复核。

## 测试与评估

```powershell
& .\projects\02-agent-research-workflow\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider integrations\graduation\tests
# 输出路径必须不存在，历史评估不覆盖。
& .\projects\02-agent-research-workflow\.venv\Scripts\python.exe integrations\graduation\evaluate.py --output <新结果文件.json>
```

固定案例见 `fixtures/evaluation-cases.json`；分类独立报告工作流、工具安全、检索、恢复幂等。内容质量列not_evaluated，不把这些数值合并成内容质量分。第一轮17/18失败记录在根 `docs/integration/evaluation-20260917.json`，崩溃恢复修正后的最终结果另存；以[验收记录](../../docs/integration/ACCEPTANCE.md)为准。

## 只读复核与毕业设计材料

复核留存演示包，无需启动P1/P2/P3、打开数据库或安装依赖。`-I -B`使用隔离Python启动且不写pycache。复核器只依赖标准库，当前在P2已有环境验证：

```powershell
& .\projects\02-agent-research-workflow\.venv\Scripts\python.exe -I -B integrations\graduation\verify_bundle.py integrations\graduation\demo\offline-20260917 --expected-delivery-sha256 52d2ccab7f6972507255190763fca9b01b04ac5acfd7b94eb89b8c2e5f73e2db
& .\projects\02-agent-research-workflow\.venv\Scripts\python.exe -I -B -m unittest discover -s integrations\graduation\verification_tests -v
```

实际结果：原包两条审批、8次调用、16份收据关联通过；28项行为测试通过。此新增测试套件独立于C3固定18项，不改变旧评估分母。退出码0表示结构一致，1表示复核失败，2表示命令参数错误；失败返回稳定error_code，不输出文件正文。

仅支持`demo.py --output`产生的严格v1导出包；不能直接传`.runs/`。目录必须只含delivery.json、result.json、两份Markdown及mcp-audit目录，收据数量与调用列表精确对应。单文件最多4MiB、最多64次调用，拒绝链接/reparse路径及未知成员；目录必须由可信本机用户管理，未验证恶意并发路径替换或多平台链接行为。

不传外部SHA时显示`unanchored`。提供SHA也只证明与该锚匹配，不证明锚可信或有数字签名。复核不会重新执行工作流、确认操作者身份或评判内容；原始请求/报告对象和完整MCP响应未随旧包导出，相关哈希只做关联检查，不声称重新计算。报告字节哈希与结构化report_hash含义不同。

毕业设计入口：[实验章节草稿](../../docs/integration/THESIS-EXPERIMENTS.md)、[待评分内容评审包](../../docs/integration/CONTENT-REVIEW.md)、[五分钟演示](../../docs/integration/DEFENSE-DEMO.md)。材料由助手整理，学校格式、独立人工评分及学生独立讲解均待完成。

## 数据、依赖和限制

两个方案均是本仓库原创测试夹具，不是LangGraph/PydanticAI真实产品比较；HTML采用P1解析器要求的结构，但未伪装成Python官方资料。原创夹具以CC0-1.0提供。Manifest固定原始字节hash，首次缺h1 anchor的夹具修正已记录。

P1/P2使用各自Python3.14环境，P3使用3.13.14与mcp2.0.0。协调代码复用各项目解释器，不安装共同依赖环境；新机器需分别按三个项目锁文件准备，当前未重装验证。不共享Key、预算或外部授权。

未验证：真实BGE/Qdrant整合、P1 HTTP/容器、真实生成质量、多用户身份、Linux/WSL、负载、云部署和独立答辩能力。当前树未找到用户历史提及的P1容器/HTTP验收文件，不能据此宣传完成。审计hash不是数字签名，不能防本机管理员篡改；父目录须归可信OS用户管理。历史P3的9项链接/平台专项跳过不算通过。

本轮设计、代码和测试由助手完成；不能写成学习者独立实现。学习总结见 `LLH_Study.md`；设计、威胁模型、数据流、评估与交接见根 `docs/integration/`。
