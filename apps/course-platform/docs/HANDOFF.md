# 演示与开发交接

以下早期阶段记录保留原状；其中“未提交”“单用户”是当时状态。最新进展见文末更新与[复现记录](REPRODUCIBILITY.md)。

## 当前交付

研据工作台为完整本机离线操作闭环，源代码在apps/course-platform。工作分支codex/course-platform-ui，基线HEAD9e2a77219ac7fbb83d28f6ca2f3e3756a4189201，未提交/推送。本分支位于同仓库的独立course-platform工作树；原开发工作树仍保留668条已有改动，不能全量git add或把它们当成UI改动。

工程测试命令与21/21结果见ACCEPTANCE.md。设计先于实现；D0设计、D1后端、D2前端、D3验证完成。学校最终项目仍需对照老师要求适配。所有本轮实现和演示审批均由助手协作完成。

本次最终预览位于`http://127.0.0.1:8878`，独立状态目录`.runtime/final-preview/`。8877保留早期预览。停止并重启预览进程的工具操作被自动审批审查拒绝（未提供更具体原因），因此没有终止已有进程；另开独立端口完成最终版验证。默认启动器仍使用8877，已占用时按README选择空闲端口。两处预览均为本应用新建状态，不是原P1/P2/P3服务。

## 五分钟演示

1. 根目录启动start-course-platform.cmd；打开127.0.0.1:8877。
2. 说明固定两个方案、六段资料、无真实调用。新建任务，使用默认比较问题。
3. 在范围页检查候选、工具调用/人工审批/故障恢复三个维度。记录决定、勾选确认并批准。
4. 等待报告审核页；展示6条证据、来源定位和8次实际MCP调用。说明脚本模型不是内容质量证据。
5. 批准当前报告；下载交付包。展示审批hash与MCP回执关联。教师若需要可运行verify_bundle.py。
6. 演示复制、取消、归档和搜索；恢复按钮不自动批准。使用测试任务，保留审计。

失败演示：复制后拒绝，检查没有继续分析；未完成时无下载按钮；文本搜索无结果有空状态。安全/过期hash/重复请求/中断恢复通过固定测试展示，不向原项目状态注入故障。

## 后续开发入口

- 产品范围：PRD.md；原模块接口与流程：ARCHITECTURE.md、REUSE-AND-COURSE-MAPPING.md。
- HTTP与安全：server.py/domain.py；业务状态：service.py/store.py。
- 替换适配器：engine.py中的Engine协议；实际整合：engine_worker.py。
- UI：web/index.html/styles.css/app.js；动态数据转义与审批hash绑定不可删除。
- 测试：tests/test_platform.py；固定结果生成：evaluate.py；环境只读检查：check_environment.py。

优先等待老师的题目、技术栈、数据库、部署、论文和评分表，再补明确缺口。若需发布，先对新应用范围做隐私审查并精确选择文件，不提交.runtime、联接环境、测试数据库和用户研究内容。本轮没有push，远程main不会自动出现UI代码。

## 当前限制必须保留

P2真实内容质量未通过，预算417/500分、调用容量109/109已封顶。新任务SQLite不是新真实调用账本。P1实时服务、向量数据库、云部署未在此UI路径验证。单用户本机访问不是账号认证。内置浏览器下载事件未验证到OS落盘，详见验收失败记录。

## UI V2交接（2026-09-19）

当前视觉规范以UI-REFRESH.md为准；UI-DESIGN.md保留首版设计历史。新版截图在screenshots/ui-v2/，验收在results/ui-v2.json。浏览器验证任务“[UI V2 演示验证] 入口与取消”由助手执行，已经取消并归档，仅在应用忽略目录.runtime/final-preview中；不可写作学生独立完成。

当前预览：http://127.0.0.1:8878/#knowledge。若进程已退出，使用README启动命令加 `--port 8878 --state-dir apps/course-platform/.runtime/final-preview`；不要关闭其他服务。源码在ai-application-portfolio-course-platform工作树，分支codex/course-platform-ui、HEAD9e2a77219ac7fbb83d28f6ca2f3e3756a4189201，尚未提交或推送。UI刷新不改变P2质量、预算、权限或原工作树状态。

## 毕设适配初审交接（2026-09-19）

先读GRADUATION-SUITABILITY-REVIEW.md。用户询问能否作为厦门理工学院软件工程毕业设计，以及GitHub是否有更合适方案。判断：保留当前基线值得继续，但尚不能确认合规达标。学校文件目录已核实，附件全文/专业当届细则/AI使用规则/既有项目复用规则未取得；不得引用未经核验的评分、字数或必选框架。现有六段夹具和脚本模型只证明工程链路，不能伪装真实业务或独立实现。下一步为导师选题对齐与明确个人贡献，不自动替换平台或开启真实调用。

## G2-A交接（2026-09-21）

先读graduation/G2A-ACCEPTANCE.md。新预览http://127.0.0.1:8880/#projects，专属状态.runtime/graduation-g2a-state。源码仍在course-platform工作树、codex/course-platform-ui分支。新项目冻结资料并可核验原文；尚未接入动态研究任务、模型、审批或报告。下一步G2-B只通过冻结范围合同扩展，不修改P2历史或预算。完整回归49/49、浏览器版本隔离与窄屏通过；未提交推送。

## G2-B交接（2026-09-22）

先读`graduation/G2B-WORKFLOW.md`和`graduation/G2B-ACCEPTANCE.md`。最新新预览为`http://127.0.0.1:8881/#projects`，独立状态`.runtime/graduation-g2b-state`；旧8878/8879/8880保持独立。浏览器演示项目和任务标明助手原创合成，已走冻结候选、范围批准、P1分词/P2图/P3 MCP、人工修订、重新批准及交付提示。全套应用52项离线测试结果见`docs/results/graduation-g2b-tests.json`；后续G3/G4、真实内容评分和学校当届要求未完成。新包必须用`frozen_bundle_cli.py`，旧包仍用原integrations验证器。分支和HEAD仍为`codex/course-platform-ui`/`9e2a77219ac7fbb83d28f6ca2f3e3756a4189201`，无暂存、commit或push。

## 最新交接：G3发布与隔离复现（2026-09-22）

本机身份模式与三角色权限已实现。系统提交`b7476219cf9bd427dc3537154485223a3ef4a911`，隔离复现证据提交`6ebdab4`；工作分支`codex/course-platform-ui`，未push或合并main。原开发工作树668条既有状态路径未改。旧固定示例默认模式与新身份状态目录互斥。三角色浏览器历史证据在`graduation/G3-ACCEPTANCE.md`；干净源码检出重新运行三角色HTTP行为测试55/55，未在该检出再次做浏览器三角色全流程。

新机器操作顺序见[安装核对清单](INSTALLATION-CHECKLIST.md)，学习者亲自演示与追问见[五分钟答辩草案](graduation/DEFENSE-DEMO.md)。正式条款与获授权资料到位后才做G4独立内容评分。不能把脚本报告、哈希一致性或助手演示写作生产安全、真实内容质量或学生独立完成。

## 最新交接：事务安全与 G4 评分工具（2026-09-22）

当前交付、测试命令、浏览器未验证项见 [NEXT-STEPS-ACCEPTANCE.md](graduation/NEXT-STEPS-ACCEPTANCE.md)。身份模式项目创建与绑定已合并事务；`score_content.py` 可生成空白评分表并校验独立人工标签。完整应用回归 59/59、0跳过。评分工具使用说明见 [G4-RATING-HANDOFF.md](graduation/G4-RATING-HANDOFF.md)，不得把模拟评审标签作真实质量结论。

浏览器控制连接两次失败，未在 detached 干净检出复演三角色 UI 或验证操作系统 ZIP 下载目录。待界面工具恢复，先用新状态目录重走此项；正式资料/要求/独立人评仍需外部输入。原开发工作树 668 条状态路径保留，P2 预算冻结。此处的工程成果由助手协作完成，学生独立讲解待验证。

## 最新交接：依赖与复现准备（2026-09-22）

先读 [DEPENDENCY-READINESS.md](DEPENDENCY-READINESS.md) 和 [逐包清单](results/dependency-audit.json)。本机三套运行锁共153条项目依赖记录；P1当前虚拟环境缺9包，19条许可证元数据需复核。`pip check`三环境均通过但不检测锁文件缺包。完整应用离线回归61/61、0跳过，见 [结果](results/dependency-readiness-tests.json)。没有安装或下载软件；不把此盘点写成全新机器复现或许可证批准。浏览器接口仍失败，隔离检出 UI/OS ZIP 落盘待补。正式条款、资料授权、真实内容独立评分和学生本人演示仍待后续。

## 最新交接：HTTP ZIP 存盘与浏览器边界（2026-09-22）

见 [HTTP-DOWNLOAD-PERSISTENCE.md](graduation/HTTP-DOWNLOAD-PERSISTENCE.md)。身份模式 HTTP E2E 额外证实授权用户收到相同 ZIP，临时文件落盘、读回及独立 CLI 复核成功，审计保留两名下载者；专项 1/1 通过。本轮只改测试及文档，未重跑完整61项。浏览器控制仍故障，**不能**把此结果写成浏览器下载目录已验证。课设工作树开始 HEAD `be42ee5`、原开发工作树668条既有改动保持；无新依赖、收费调用或外部操作。

## 最新交接：G4 仲裁工具（2026-09-22）

先读 [G4-ADJUDICATION-ACCEPTANCE.md](graduation/G4-ADJUDICATION-ACCEPTANCE.md) 与 [评分工具使用说明](graduation/G4-RATING-HANDOFF.md)。新增空白仲裁表、严格完整性校验和保留原始评分的描述统计；完整应用63/63通过，随后字段命名微调后专项5/5通过。合成标签只验证流程，不是真实独立人评；`adjudicator_id_distinct`也不证明真人身份。浏览器UI、操作系统下载目录、教师正式条款和真实资料仍待验证。开始分支`codex/course-platform-ui`/HEAD`69f327a`；P2真实预算冻结，不改原项目业务与原开发工作树。

## 最新交接：G4 ZIP 来源绑定（2026-09-22）

先读 [G4-BUNDLE-BINDING-ACCEPTANCE.md](graduation/G4-BUNDLE-BINDING-ACCEPTANCE.md) 与 [评分操作说明](graduation/G4-RATING-HANDOFF.md)。`g4-claims-v2` 必须从已验证 `frozen-delivery-v1` ZIP 生成，并在每次评分表、仲裁表和汇总时提供同一 ZIP。报告矩阵主张、来源段和格内限制逐项重建校验；旧 `g4-claims-v1` 仍可格式演示但标记 `source_binding: unverified`。首次全回归因进程级网络钩子导入副作用 53/63 通过、10错误；修复后 63/63 通过、0跳过，证据和失败均保留。分支 `codex/course-platform-ui`，阶段开始 HEAD `40dc6e0`；原开发工作树 668 条既有状态路径保持。未获取正式授权资料、真人独立评分、教师当届细则；浏览器工具故障后的干净检出 UI 和系统下载目录仍未复演。P2 真实预算继续冻结，学生独立讲解待验证。

## 最新交接：G4 报告整体覆盖复核（2026-09-23）

先读 [覆盖复核操作](graduation/G4-COVERAGE-HANDOFF.md) 和 [离线验收](graduation/G4-COVERAGE-ACCEPTANCE.md)。矩阵外摘要、推荐、限制及已读却未引用的证据现在进入独立人工核对表；每次验证重校完整 ZIP，完成标签只出描述计数，不能宣称真实质量。应用全套63/63通过、0跳过。开始分支 `codex/course-platform-ui`、HEAD `d7b0393`；原开发工作树 668 条既有状态路径保持。浏览器连接仍失败且原生 Edge 是无关页面，未做本轮 UI/系统下载复演。正式资料授权、当届条款、真人评审和学生本人讲解仍需后续；P2 真实预算冻结。

## 最新交接：提交源码独立复演（2026-09-23）

先读 [最新提交复现记录](REPRODUCIBILITY.md#最新提交的独立源码复演2026-09-23) 和三份 `results/repro-g4-*.json`。`5636d6d` 新 detached 检出状态干净，三个虚拟环境仅作 Junction 复用；环境探针通过，合成检索8篇20题与完整应用63/63通过，0跳过，185.602秒。旧 `b747621` 检出及原开发工作树668条既有状态路径保留。该证据不覆盖新机器安装、浏览器三角色 UI、系统下载目录、正式资料授权、教师条款或真实内容评分；P2 真实调用继续禁止。课设分支未 push/合并 main。
