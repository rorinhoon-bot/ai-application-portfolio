# G2-A 冻结范围与证据核验：验收和交接

2026-09-21。助手协作实现与测试，不代表学生独立实现或学校毕业设计验收通过。G2-A 已完成本机增量验收，完整 G2 尚未完成。

## 交付内容

研究项目支持问题、约束和资料版本选择，创建后保存不可变范围与 SHA-256 合同。检索仅读取被冻结版本；资料库修订不会改变原项目结果。核验接口只返回属于冻结范围且哈希一致的服务端原文，不信任客户端引文。持久化、容量上限、并发幂等、审计、权限和数据完整性均由确定性代码控制。

原P1/P2/P3及integrations业务文件未改。原固定研究任务流程继续保留，新项目没有task_id/run_id/checkpoint/报告或MCP记录，创建不调用任何引擎。后续连接点为project_id + contract_hash + version_id + chunk_id，不能将保存范围宣称为人工审批通过。

## 自动验收

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/evaluate.py --output apps/course-platform/docs/results/graduation-g2a-tests.json
```

结果：**49/49，64.057秒，0跳过、0失败、0错误**。其中原36项保留，新13项位于tests/test_projects.py。证据：[结果JSON](../results/graduation-g2a-tests.json)。原三个项目的全量回归未重跑；应用回归包含实际P1/P2/P3离线审批/恢复/导出/拒绝链路。

新增测试检查：合同创建/重开/事件、重复与并发创建、范围摘要、source顺序规范化、非法Unicode/字段/布尔类型、未知版本与同源多版本、容量失败不新增记录、旧版检索不漂移、越界chunk与错误hash拒绝、资料正文/段落损坏拒绝、空结果及实际HTTP权限和路由。HTTP测试替换为禁止执行的引擎，任何意外引擎调用都会失败。

失败记录：首次单跑13项时，一个错误CSRF请求遭遇Windows `ConnectionAbortedError [WinError 10053]`，未收到响应；其余12项通过。该项单独复现通过，随后完整49项通过，没有隐藏重试或跳过。根因尚未确定，保留为本机HTTP连接稳定性风险；不能把这次通过写成已修复该网络问题。

本阶段未改词法排序，也未把G1的20题合成检索指标当成本轮新实验。新增测试证明版本隔离与引用绑定，不证明真实资料相关性、结论质量或模型事实正确。

## 浏览器与演示

新隔离预览：[研究项目](http://127.0.0.1:8880/#projects)。项目 `[演示验证] 冻结资料技术选型` 使用助手原创文本。先通过网页导入，再保存研究范围，检索“断点恢复”并核验原文；随后将资料库正文改为包含 `updatedword` 的新版，原项目搜新版词返回0段、搜 `原始 checkpoint` 仍返回冻结原文。刷新与列表返回后范围保留。HTML样例按文字显示，结果区img数量为0。

空库创建按钮禁用；未选择资料保存时提示“请至少选择一份资料”。桌面宽1266、375视口文档宽360、768视口文档宽754，均无页面横向溢出；手机弹窗宽312且无内部横向溢出。浏览器未记录应用脚本错误。并非完整无障碍或跨浏览器认证。

截图：[桌面](../screenshots/graduation-g2a/project-desktop.jpg)、[手机](../screenshots/graduation-g2a/project-mobile.jpg)。结构化证据：[浏览器与Git记录](../results/graduation-g2a-browser.json)。该状态目录专属本轮演示，旧8878/8879状态未操作。

进程退出后在端口空闲时重开：

```powershell
projects/02-agent-research-workflow/.venv/Scripts/python.exe -B apps/course-platform/server.py --port 8880 --state-dir apps/course-platform/.runtime/graduation-g2a-state
```

日志放独立 `.runtime/g2a-logs`，不要预先写入空状态目录。无新增依赖或环境变量，不安装、联网下载、真实API、commit或push。

## 交接与限制

实现分支codex/course-platform-ui，HEAD `9e2a77219ac7fbb83d28f6ca2f3e3756a4189201`。apps整体此前已未提交；本轮仅续做G2-A，不能把全目录记作本轮新增。原开发工作树codex/graduation-integration、HEAD `dcb164e95059b060ffd6aebbaa093a7626177614`，668条全量状态保留。

已存在但无research_project_scopes的旧初稿项目不会静默迁移，详情返回PROJECT_INTEGRITY；不得自动按最新资料补齐。当前没有已知需迁移的正式项目。研究项目最多200个、1—50份资料、8条约束，HTTP总请求仍限8KiB，长字段与多版本同时使用可能触及传输上限。单用户、无项目编辑/删除或独立权限。只对约定破坏场景检测完整性，哈希不是身份签名。

下一步G2-B：先定义动态候选与资料适配合同，冻结范围审批后交给P2图；建立任务/run/checkpoint与范围hash的绑定，补人工修订、报告哈希审批失效、P3受限工具收据与可验证导出。普通验证继续用离线脚本，不修改历史gold/失败记录。P2真实内容质量未通过，417/500分、109/109调用容量冻结不变。G3身份、G4真实授权语料评估/新机器复现、导师要求与AI辅助披露仍待完成。
