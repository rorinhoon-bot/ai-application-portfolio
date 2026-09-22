# 课设系统状态

2026-09-18，助手协作实现，不代表学习者独立实现。

- 分支：codex/course-platform-ui；原基线：9e2a77219ac7fbb83d28f6ca2f3e3756a4189201；课设发布提交：b7476219cf9bd427dc3537154485223a3ef4a911。
- 当前唯一目标：完成发布收口与干净源码复现；本阶段已通过。后续G4需正式条款、授权资料与独立内容评价。以下D0—D3、G1—G3为历史阶段。
- D0 完成：需求、架构、数据、权限、威胁模型、UI、扩展与验收方案。
- D1 完成：独立任务索引、异步工作进程、严格HTTP合同、显式双审批、恢复、验证后导出。
- D2 完成：工作台、任务管理、知识搜索、报告、证据、审计、历史评估、桌面与窄屏布局。
- D3 完成于本机离线范围：21/21 行为测试，0跳过，55.872秒；浏览器闭环及安全标题、取消、筛选与归档通过。
- 现有P1/P2/P3和原工作树保留；只新增apps/course-platform、启动入口并更新根README导航。
- 学校正式要求未提供；本版为可复用课设工程基线，不能宣称满足最终学校验收。
- P2真实内容未通过；417/500分与109/109调用容量永久冻结。只使用脚本模型与固定原创资料。

验收证据：docs/results/evaluation.json、docs/results/browser.json、docs/screenshots/、docs/ACCEPTANCE.md。

测试命令（仓库根）：`projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate.py --output apps/course-platform/docs/results/evaluation.json`。

Git：仍在codex/course-platform-ui，HEAD仍为上述基线，改动尚未提交/推送；main未改动。原开发工作树668条全量status与任务前一致。浏览器下载按钮返回成功提示，HTTP ZIP和内容一致性已验；内置浏览器download事件监听超时，不能宣称其操作系统落盘已验证。全新机器、独立浏览器下载、多用户、老师要求和真实内容质量仍待验证。

## UI V2（2026-09-19）

用户确认“浅色极简：清爽侧栏、文档阅读区、少量蓝色强调”。本轮完成原生前端视觉重构：浅色导航、研究问题入口与模板、真实任务统计、知识目录与阅读区、来源筛选、指纹视图、报告/审批/审计统一样式、手机与平板布局。辅助文字提升至至少12px；目录和阅读页签重绘后保留键盘焦点。

本轮仅改web三文件及本应用文档。原后端和测试文件SHA-256与上一轮delivery-review.json一致，P1/P2/P3与integrations没有代码差异。无新增依赖、远程技能安装、真实模型调用、commit或push。

验证：HTTPTests 6/6通过，3.455秒；命令为 `projects/02-agent-research-workflow/.venv/Scripts/python.exe -B -m unittest discover -s apps/course-platform/tests -p test_platform.py -k HTTPTests -v`。旧21/21完整回归是V1工程证据，本轮没有重复宣称新跑了21项。

浏览器行为：来源筛选Graph=3/Chain=3/全部=6；英文checkpoint与中文人工审批各2条；无匹配时0条且阅读区清空，键盘清空搜索恢复6条；选择目录同步正文与焦点；来源指纹可查。首页模板带入真实创建表单，新任务停在范围审批，脚本模型/MCP均0；取消需说明与勾选确认，取消后归档，审计保留。历史交付任务仍能展示6条证据、2次审批、8次MCP，评估页仍明确P2真实内容未通过。浏览器未记录应用脚本错误。

响应式：375×812与768×1024视口请求，浏览器扣除滚动条后的文档宽度分别360/754，scrollWidth与clientWidth相等；手机首页、知识页、报告页无整页横向溢出。桌面文档宽1266。已恢复默认视口。

证据：docs/results/ui-v2.json、docs/screenshots/ui-v2/；新版设计详见docs/UI-REFRESH.md。原截图、browser.json、evaluation.json和delivery-review.json保留为V1历史证据。此次UI验证不构成真实内容质量验收、完整无障碍认证或全新机器验收。

Git仍为codex/course-platform-ui，HEAD为9e2a77219ac7fbb83d28f6ca2f3e3756a4189201。原开发工作树仍为codex/graduation-integration、HEAD dcb164e95059b060ffd6aebbaa093a7626177614，668条全量status与任务前一致。main没有因此更新。

## 毕设适配初审（2026-09-19）

新增docs/GRADUATION-SUITABILITY-REVIEW.md：结论为适合作为毕业设计基础，尚不能确认满足厦门理工学院软件工程当届要求。已核查学校官方文件入口；指导意见附件需验证码，未核实全文及专业当届评分细则。建议保留现有工程，以真实技术选型场景补需求、资料检索、权限、实验和独立交付。建议尚未批准实施，本轮仅文档审查，未重跑测试或修改代码。分支codex/course-platform-ui、HEAD9e2a77219ac7fbb83d28f6ca2f3e3756a4189201未变。

## G1 资料基础（2026-09-19 实现，2026-09-21 续验）

已补毕业设计 PRD、架构、评估和实施交接；实现本机 UTF-8 TXT/Markdown 导入、来源/授权、不可变版本、行列/hash、词法检索、容量和并发控制、导入审计及浅色界面。原 P1/P2/P3 和整合引擎未改；资料库尚未参与固定脚本研究报告。

自动验收：新增行为测试15项；完整应用36/36通过，58.439秒，0跳过。检索评估使用8篇原创合成资料、20题，18题首位命中、2题无依据返回空，只证明夹具内机制，非真实质量认证。浏览器验证保存/重启、中文检索、定位、修订/旧版、HTML转义、刷新持久化及375/768视口通过。详见 docs/graduation/EVALUATION.md、docs/graduation/PLAN-HANDOFF.md。G2—G4、正式数据及当届学校验收尚未完成。无新依赖、真实调用或费用；未commit/push。

## G2-A（2026-09-21）

完成研究项目创建/列表/详情、问题与约束、明确版本冻结、范围hash、范围内检索、证据归属/hash核验、审计、200项目容量、并发幂等和浅色页面。13项新增行为测试；完整应用49/49通过，64.057秒。实际命令、失败记录、浏览器操作与限制见docs/graduation/G2A-ACCEPTANCE.md。冻结项目仍未触发模型或原图；G2-B、G3、G4未完成，不能称完整G2或毕业设计完成。分支codex/course-platform-ui，HEAD9e2a77219ac7fbb83d28f6ca2f3e3756a4189201不变；未commit/push。

## G2-B（2026-09-22）

当前唯一目标：完成冻结项目执行、修订、独立包复核和浏览器验收；该阶段已完成，下一阶段G3身份/权限及G4真实资料独立评估。G2-B已接入P1分词、P2真实V2状态图/checkpoint/脚本模型、P3只读MCP；项目版本/候选绑定、两门人工审批、有限修订与离线ZIP。最终完整应用52/52通过，0跳过，93.153秒；旧HTTP偶发断连失败与修复记录保留。浏览器创建原创资料/项目/任务、审批/修订/交付通过，证据见docs/graduation/G2B-ACCEPTANCE.md及docs/results/graduation-g2b-browser.json。未对真实内容质量、多用户身份、全新机器及学校要求验收；不称毕业设计全部完成。分支codex/course-platform-ui，HEAD9e2a77219ac7fbb83d28f6ca2f3e3756a4189201，未暂存、commit或push。

## G3（2026-09-22）

新本机状态目录已加入管理员、研究者、审核者身份、会话/CSRF、对象归属与拒绝审计；旧单用户目录保留且模式互斥。研究者不能自批，指派审核者可审批冻结任务，管理员可查权限审计。资料所有者与版本导入已合并事务。完整应用离线回归55/55、0跳过、184.660秒；浏览器三角色真实操作完成至交付，手机审计页无整页横向溢出。证据见docs/graduation/G3-ACCEPTANCE.md、docs/results/graduation-g3-tests.json、docs/results/graduation-g3-browser.json。临时8882预览已停止；原有服务未动。尚未验证操作系统下载落盘、全新机器、真实内容质量、公网安全或当届学校要求。P2真实调用预算永久冻结。分支codex/course-platform-ui，HEAD9e2a77219ac7fbb83d28f6ca2f3e3756a4189201；未暂存、commit或push。助手协作实现，学生独立讲解待验证。

## G4 离线准备（2026-09-22）

已写教师条款映射、正式资料授权、独立盲评、分项指标和执行门槛草案，见docs/graduation/G4-REAL-DATA-AND-COURSE-PLAN.md。未取得正式条款或授权语料，未跑真实内容评分；G4未完成。

## 发布提交与隔离复现（2026-09-22）

本应用94个有用文件提交为`b7476219cf9bd427dc3537154485223a3ef4a911`；截图扩展名按真实JPEG内容改为`.jpg`，原字节未变。暂存密钥/隐私模式扫描无命中，忽略状态与虚拟环境未入库；未push或改main。该提交的detached干净源码工作树`git status`为0，复用既有虚拟环境但使用当前检出P1/P2/P3源码，完整应用55/55、0跳过、170.923秒；合成检索8篇20题；新应用状态HTTP首页、bootstrap、session均200且服务已停止。证据见docs/REPRODUCIBILITY.md和docs/results/clean-source-*.json。全新机器重新安装依赖、三角色浏览器在此检出复演、系统下载落盘、正式内容质量、教师要求及学生独立讲解未完成；P2真实预算仍冻结。原工作树668条既有状态路径保持不变。

## 新机器与答辩准备（2026-09-22）

新增`docs/INSTALLATION-CHECKLIST.md`和`docs/graduation/DEFENSE-DEMO.md`；更新学习讲义中的30秒/2分钟介绍及公网安全边界。均为助手准备的操作稿，不是全新机器验收或学生独立答辩证据。后续先取得正式条款、明确资料授权及依赖安装清单，再执行G4评分和新机器实测。

## 后续独立工程（2026-09-22）

当前唯一目标：保留本机权限事务修复与 G4 离线人工评分工具；工程回归已通过，接续等待浏览器接口恢复后复演隔离检出三角色流程、ZIP 实际下载，再与教师要求及授权资料对齐。创建项目/绑定审核者/审计现为单事务；故障注入证明无孤儿项目，重试幂等。新增人工评分表生成、摘要校验、分歧汇总；助手虚构评分只测试工具，真实内容质量仍未验收。

实际分支 `codex/course-platform-ui`，阶段开始 HEAD `e0c4e9320f223a8ee3ac82444b6c260406708a12`；完整应用命令 `projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate.py --output apps/course-platform/.runtime/next-steps-tests.json`，59/59通过、0跳过、170.601秒，见`docs/results/next-steps-tests.json`。干净源码 detached 检出仍在`b747621...`且状态为空，浏览器控制连接连续失败，未完成本轮 UI/OS ZIP 落盘复验；原开发工作树 668 条状态路径未变。详见`docs/graduation/NEXT-STEPS-ACCEPTANCE.md`。无新依赖、费用、真实调用或 P1/P2/P3 原状态操作；未 push/合并 main。

## 新机器依赖只读盘点（2026-09-22）

当前唯一目标：继续完成无需教师条款和外部授权的复现准备，浏览器接口恢复后补三角色 UI 与 ZIP 落盘验收。分支 `codex/course-platform-ui`，阶段开始 HEAD `aadfd4c60708a8a1ef73235dca6b0e27c9c192a5`；本阶段只新增课设应用依赖审计脚本、两项行为测试及文档/结果，不改 P1/P2/P3 业务代码或原工作树。

只读核对 P1/P2/P3 运行锁和现有 `.venv` 元数据：153 条记录，P1 缺 9 个锁定包，已安装包版本差异 0，许可证元数据需复核 19 条（其中 1 条相互冲突）。三个环境 `python -m pip check` 均通过，但不检测锁文件缺包。完整应用命令 `projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate.py --output apps/course-platform/.runtime/dependency-readiness-tests.json`；**61/61 通过、0跳过、203.933秒**。见`docs/DEPENDENCY-READINESS.md`和`docs/results/dependency-readiness-tests.json`。本轮安装/下载/真实模型调用均0；未取得新机器、正式资料、独立内容评分或教师当届条款。浏览器工具仍报`nodeRepl.fetch request failed`，故下载目录复验继续未完成。
