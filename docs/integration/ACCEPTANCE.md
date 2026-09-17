# A/B/C 最终离线验收

## C4追加验收（2026-09-17）

新增导出包只读复核，独立28/28测试通过，1.750s。原留存包的固定delivery.json SHA为`52d2ccab7f6972507255190763fca9b01b04ac5acfd7b94eb89b8c2e5f73e2db`；复核匹配，2条审批、8次调用、16份收据。命令与边界见[README](../../integrations/graduation/README.md)，原始证据见[测试日志](review-results/tests-final-20260917.txt)和[JSON结果](review-results/bundle-20260917.json)。这28项只读复核测试不并入C3的固定18项。

新增[实验章节](THESIS-EXPERIMENTS.md)、[未评分内容评审包](CONTENT-REVIEW.md)、[五分钟演示稿](DEFENSE-DEMO.md)。不声称已经完成独立人类评审、学校模板适配或学生独立答辩。C4仅改整合层新增复核器与文档，P1/P2/P3及旧运行/评估制品不变，因此下方组件与C3成绩引用此前执行记录，不是C4重新执行。

复核器不能从旧导出包独立重算请求/报告/MCP完整响应哈希，不能确认身份或质量。包内自hash不防整体一致篡改，固定外部hash也需独立可信保管。C4只在本机可信目录验证；真实链接/reparse对抗和其他平台未验证。

2026-09-17。结论：**P3 V2升级与P1/P2/P3离线端到端工程原型通过本机验收**。不等于真实内容、完整云部署、生产可用或整套毕业设计完成。

## 完成项与证据

| 阶段 | 本次实际结果 | 证据 |
|---|---|---|
| A：P1只读验收 | 74项纯函数/夹具定向测试通过；业务零修改、无服务/数据库操作 | [P1验收与接口](P1-READONLY-ACCEPTANCE.md) |
| B：P3 V2 | 全套263 tests（254通过、9跳过，31.942s）；V2固定16/16；旧40/40、旧演示8/8 | [P3验收](../../projects/03-mcp-tool-server/docs/v2/07-ACCEPTANCE.md) |
| C：整合固定评估 | **18/18，0跳过**；工作流5/5、检索1/1、工具安全8/8、恢复幂等4/4 | [最终机器结果](evaluation-final-20260917.json) |
| C：真实离线演示 | P1解析6段原创资料，P2两门，8次实际MCP读取、3次脚本调用；重放后1份P2制品 | [交付报告](../../integrations/graduation/demo/offline-20260917/delivery-report.md)、[运行结果](../../integrations/graduation/demo/offline-20260917/result.json)、[交付清单](../../integrations/graduation/demo/offline-20260917/delivery.json) |
| P2完整回归 | **266 passed in 114.41s**，0新增真实模型调用 | [完整测试日志](p2-regression-20260917.txt) |
| 环境 | P1/P2/P3各自pip check均无破损；未安装依赖 | 原项目精确锁文件原样保留 |

整合测试时长合计154.804s（JUnit testcase time求和，不等同于总墙钟）。命令从仓库根运行：

```powershell
& .\projects\02-agent-research-workflow\.venv\Scripts\python.exe integrations\graduation\evaluate.py --output docs\integration\evaluation-final-20260917.json
& .\projects\02-agent-research-workflow\.venv\Scripts\python.exe integrations\graduation\demo.py --output integrations\graduation\demo\offline-20260917
```

输出已存在，复跑请选新文件/目录，保留旧证据。P2完整pytest由clean_env白名单子进程执行，`-q -p no:cacheprovider`，仅测试临时数据库；未读旧.env、账本、索引或服务。P3旧HTTP回归只使用它自己启动的回环测试进程；V2与整合业务传输为stdio，无外部网络、费用、资料下载或部署。

## 保留失败与修正

首轮固定18例为17/18，见 [原失败结果](evaluation-20260917.json)，未覆盖。真实进程在报告文件发布后、checkpoint完成前 `os._exit(73)`，恢复得到REPORT_NOT_APPROVED。根因是整合invoke遗漏P2既有CLI的同步持久化参数；仅整合层改为durability="sync"。相同故障定向1 passed in 32.49s，随后同一案例集hash的18/18复跑通过。P2代码/gold/账本/真实报告零改动。

默认无模型写授权。两门绑定request/report hash；审批前再次验证MCP审计；无批准、拒绝、取消或漂移均不产生最终交付。实际进程崩溃恢复不增加模型调用、P2报告仍1份；这些保证仅针对被测故障边界，非通用分布式exactly-once。

## Git 与保护

当前 `codex/graduation-integration`，HEAD `dcb164e95059b060ffd6aebbaa093a7626177614`。起点已在P3分支；先A、再B，P3通过后才创建整合分支。两次基线见 `baselines/`。最初572条既有未提交路径不是本轮P3改动；不暂存、不commit、不push、不stash/reset/restore/clean。

本轮范围：P3 V2与P3入口资料、`docs/integration/`、`integrations/graduation/`。916个非秘密原文件SHA-256基线中仅P3四份文档变化；P3之外原文件变化0。`.env`类路径未读取/散列；P3 `.env.example`仅追加无密钥使用说明。最终详单见 `baselines/20260917-final/`。

## 未完成、风险与下一步

- P1当前工作树未找到HTTP/容器/隔离容器启动证据；本轮复用实际HTML解析与夹具关键词适配，未跑正式BGE/Qdrant检索。不能写完整云部署完成。
- P2真实内容验收继续失败：首批2有限批准/4拒绝，修复后2有限批准/1拒绝。417/500分与109/109容量不变；没有新增/重置付费账本，整合状态是0费用脚本账本。
- P3原9项真实链接/平台专项仍skip；Linux/WSL、新机器安装、负载、远程身份、多用户和云部署未验证。
- 审计hash与本地文件锁不是认证签名或恶意管理员防护。运行根由可信OS用户独占；资料正文不可信，不能执行其命令。
- 演示审批actor为scripted-test，不能当真人语义评分。助手完成的实现不能写为学习者独立成果；理解检查不阻塞本轮工程交付，但仍未验证。
- 下一步：审阅已生成报告，补独立内容评价与学生讲解，按学校要求完善论文/实验；再单独规划真实检索适配与部署。保持P2收费调用冻结，不通过换账本寻求内容达标。
> 发布版本差异：此次从远端新版P1建立独立发布分支，并保留它的API/容器/静态发布证据。下方P1“当前树未找到”的结论仅对应旧开发快照。新验证与筛选范围见[PUBLICATION.md](PUBLICATION.md)，不据此宣称整合已验证P1实时API。
