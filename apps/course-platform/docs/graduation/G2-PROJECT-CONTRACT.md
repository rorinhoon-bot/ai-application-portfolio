# G2 研究合同：设计、实施与验收

2026-09-21。G2-A 为 G2 的第一个可运行增量：创建研究范围、冻结资料版本、在冻结范围内检索与验证证据。G2-B 再接动态候选、P2 图执行、人工修订/批准及 P3 回执；不能把 G2-A 称作完整 G2。

## 产品行为

研究者填写名称、研究问题、最多8条约束，选择1—50份已导入资料的明确版本，并确认用途。创建后版本不随资料库最新版本漂移；同一资料不可重复选择两个版本。名称和约束不作为命令执行。确认仅保存范围，不等于审批研究、启动模型或批准报告。旧任务继续用原合同。

界面入口“研究项目”，列表显示真实项目、来源数量和日期；详情左侧展示问题/约束，右侧列出冻结来源与版本；下方提供范围内检索及逐条原文核验。无资料时引导导入，无证据时返回空，不补写结论。沿用白色#ffffff、浅灰#f8f9fb、正文#23272f、次级#626978、蓝#465dd9、边界#e7e9ef，Segoe UI/微软雅黑；正文15px、辅助不低于12px，左对齐，手机改为单栏。页面强调研究范围与证据的关系，不展示假模型进度或假报告。

## 服务端合同与数据流

- POST /api/projects：严格字段 request_id/title/question/constraints/version_ids/confirmed，沿用8KiB请求上限。确认必须是true；项目最多200个。同请求同规范化内容返回原项目，不同内容拒绝，幂等重试先于容量检查。
- GET /api/projects：摘要列表；GET /api/projects/project-[32hex]：范围、manifest、contract_hash、创建审计。项目ID服务端生成，客户端不得作为文件路径。
- POST /api/projects/{id}/search：query/top_k，只读取被冻结版本。返回project_id、contract_hash及带version/chunk/hash/locator的原文。空结果不是自动否定技术方案。
- POST /api/projects/{id}/evidence：version_id/chunk_id/content_hash，先验证版本属于项目，再定位段落并核对SHA-256，返回服务端原文；不接受客户端提供的引文作为事实。

research_projects 保留项目字段；research_project_scopes 保存版本manifest与contract_hash；research_project_events 保存创建事件。一次 BEGIN IMMEDIATE 内校验版本存在、每资料唯一、容量并写项目/范围/审计。manifest绑定来源、授权、文件标签、标题、内容hash；contract_hash绑定问题/约束及manifest。读取时复核摘要；缺失或损坏报 PROJECT_INTEGRITY，不能静默改为最新资料。哈希不防同一OS账户重写整个数据库。

原文仍在 library_versions，不复制到日志。搜索、证据核验只读，不产生无限审计行；创建审计声明actor=local-browser及engine_started=false。当前仅本机单用户，无研究/审核身份隔离。约束中的金额只是研究需求，不是API预算授权。控制字符/无效Unicode拒绝，SQL参数化，所有动态页面字段转义。

## 实施与验收计划

先补初稿的容量、输入与完整性控制，再完成HTTP、UI和行为测试。必须覆盖：创建/重开/重试/冲突/并发；非法字段和Unicode；未知资料、重复版本/同源双版本；更新资料后项目检索不漂移；越界证据和假hash拒绝；容量失败原子性；HTTP权限继承；旧36项回归。浏览器验证创建、冻结源、检索、核验、刷新、空结果和窄屏。普通测试用临时应用状态、合成文本，0外部调用，0新依赖。

后续任务必须携带project_id和contract_hash，范围审批必须绑定该hash；P2 checkpoint以run_id关联冻结范围。模型只提供候选草稿及引用建议；确定性代码控制版本归属、审批失效、预算、MCP权限和导出。G2-A 没有实际任务/checkpoint/报告关联，不修改P2 gold、账本或历史结果。
