# 整合开发交接

2026-09-17 C4交接：只读verify_bundle.py和独立verification_tests已完成；最后命令`P2本地python -I -B -m unittest discover -s integrations/graduation/verification_tests -v`得到28/28、1.750s。原包外部SHA匹配，2审批/8调用/16收据；证据在review-results。新增THESIS-EXPERIMENTS、CONTENT-REVIEW、content-review-form.json和DEFENSE-DEMO；评分全部留空，学生讲解/学校要求未确认。当前分支仍codex/graduation-integration，HEAD仍dcb164e95059b060ffd6aebbaa093a7626177614。

C4不启动服务或打开数据库；不重跑已有业务回归，不改P1/P2/P3或旧演示，未装依赖/真实API/收费/提交/push。复核器只保证被保存字节及关联一致，非签名、非独立语义验证。下一步先按CONTENT-REVIEW做真实独立逐条评分或按学校要求适配论文；不把材料准备完成写成毕业设计整体完成。C4前后工作树与源码hash见baselines/20260917-review。

2026-09-16，助手实现。A：P1只读验收74 tests通过，当前树缺HTTP/容器证据。B：P3 V2 263 tests（254通过、9跳过），16/16新固定评估，旧40/40与8/8；验收通过。

C0：按用户命令新建 `codex/graduation-integration`，HEAD保持 `dcb164e95059b060ffd6aebbaa093a7626177614`。前后status/stat完整记录于 `baselines/20260916-pre-integration/`。旧文件572条不能归入本轮；首次哈希基线中P3外改动0。

当前唯一目标：交付已通过验收的离线原型。C1/C2代码在 `integrations/graduation/`：common为进程/原子发布合同，p1_worker实际P1解析，p3_worker实际MCP桥，workflow_runtime复用P2图，cli与demo分别提供显式操作者和标注的脚本审批。首轮真实演示两门/6证据/8 MCP调用/3脚本调用/1制品；首轮13 tests通过。随后补进程崩溃、报告拒绝、审计漂移及原子交付测试，最终固定18/18通过。

P2限额永久5元，417/500分、109/109调用容量；只用ScriptedModelClient与新临时0成本测试状态。不得读旧.env/数据库/真实账本、创建真实模型、下载资料或部署。三个项目各用自己本地.venv执行，不装新包。新增协调层和必要设计由助手完成，不写成学习者独立成果。

2026-09-17：交付报告新增限制、两门审批和每条MCP调用ID/result hash；审批前复验收据，审计漂移禁止导出。CLI新增recover，仅恢复持久未完成节点，不生成新人工决定；运行目录加OS文件锁避免同一run并发操作者。最终18/18，P2完整266 passed in 114.41s，三环境pip check通过，实际CLI start/status/reject通过；当前源代码已完成这些离线验证。

复现入口：仓库根用P2 `.venv/Scripts/python.exe integrations/graduation/demo.py`；完整命令见整合README。留存结果在 `integrations/graduation/demo/offline-20260917/`，所有审计原始收据可不打开数据库复核。固定评估旧失败 `evaluation-20260917.json` 与通过 `evaluation-final-20260917.json` 使用同一cases_sha256；原因/修正见DECISIONS I-007。

后续不以本轮通过解锁真实收费操作。先审阅交付报告与GRADUATION-SCOPE，再做独立内容评价和学生讲解；真实P1检索/HTTP、部署、学校论文要求与多平台仍未验证。当前分支和HEAD见STATUS；最终工作树保护证据见baselines/20260917-final/。
> 公开交接（2026-09-17）：新版P1来自远端main，P2/P3升级与整合经过筛选进入独立发布分支。最终新检出验证：P1定向77、P2完整266、P3 254通过/9跳过、整合18/18、包复核28/28。见[发布说明](PUBLICATION.md)与[最终结果](publication-results/ready.json)。下方是旧开发工作树历史，私有baselines不公开。
