# 下一阶段独立工程验收

2026-09-22。助手协作实施；不代表学生独立实现或教师批准。工作树 `H:\暑假学习\编程学习\ai-application-portfolio-course-platform`，分支 `codex/course-platform-ui`，阶段开始 HEAD `e0c4e9320f223a8ee3ac82444b6c260406708a12` 且状态干净。原开发工作树 `codex/graduation-integration`/`dcb164e95059b060ffd6aebbaa093a7626177614` 的 668 条既有状态路径未改。

## 已验证

身份模式的研究项目、冻结范围、归属、审核者绑定与绑定审计现处于同一个 SQLite 事务。写入绑定阶段注入 `ACCESS_DENIED` 后，项目/范围/事件/绑定四张表均无残留；同一请求可重试，一致请求只保留一组绑定，更换审核者不可抢占。项目创建事务内重新核验资料归属及有效账户，避免请求前检查与写入之间的状态变化。旧默认单用户项目合同与数据保持原行为。针对性测试 `test_project_creation_rolls_back_access_failure_and_retry_is_idempotent` 通过。

G4 增加 `score_content.py`：从冻结主张/证据清单生成空白人工表，拒绝摘要变化、缺项与重复评审者，输出标签计数、一致率和分歧编号。`test_content_scoring.py` 三项行为测试通过，全部使用原创虚构文本与模拟标签，不含独立人工评分。

仓库根目录完整命令：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate.py --output apps/course-platform/.runtime/next-steps-tests.json
```

结果：**59/59 通过，0失败、0错误、0跳过，170.601秒**。结构化输出另存 [next-steps-tests.json](../results/next-steps-tests.json)。使用已存在的虚拟环境、临时应用目录与原创数据；真实模型调用0次、新依赖0个。未运行 P1/P2/P3 各自全套原项目回归，未操作其原数据库、服务或真实账本。

## 未验证与接续

计划在 detached 干净源码工作树重走三角色浏览器、检查操作系统 ZIP 下载目录。该工作树仍在 `b7476219cf9bd427dc3537154485223a3ef4a911` 且 `git status` 为空；浏览器控制接口两次报 `Browsers: Error: nodeRepl.fetch request failed`，因此本轮没有浏览器操作或 OS 下载目录验收。历史 G3 浏览器流程和本轮 HTTP/ZIP 测试仍各按原证据范围有效；不可写成此次干净检出浏览器验收已通过。后续浏览器接口可用时，在隔离状态重新复演并核对实际文件落盘与 ZIP 独立复核。

G4 真实内容质量仍需教师正式要求、可合法使用且冻结的资料、独立评审者原始标签与人工仲裁。脚本模型、格式、引用和两级审批不能替代内容质量评价；P2 原真实模型内容历史未通过，417/500 分、109/109 调用容量永久冻结，不增加真实调用。新机器从锁文件安装依赖及学生本人讲解也未验证。
