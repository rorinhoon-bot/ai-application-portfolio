# 毕设扩展架构与G1实现合同

## 架构

浏览器资料库页调用同一loopback HTTP服务；新增Library模块通过Store事务管理应用私有SQLite表。P1/P2/P3及现有Runtime代码不变。资料读取与检索不会触发Engine；后续G2以不可变version_id和chunk_id作为证据合同，单独设计适配器，不能修改历史任务的资料集。

新表：library_versions保存document_id、version_id、parent_version、标题、文件标签、source_ref、rights_note、原文、原文SHA-256、分段JSON与时间；library_requests保存request_id、payload_hash与返回版本；library_events记录导入版本及哈希，不记录全文。使用同一个BEGIN IMMEDIATE事务完成版本、请求和审计写入。

document_id由来源标签的SHA-256前32位派生；相同标签对应同一资料。version_id由规范化元数据与正文摘要派生；换行统一LF，正文不执行Markdown。分段保留行号；超长行按800字符分片并带列区间。chunk_id绑定版本和段落序号，旧版本永不覆盖。source_ref是文字标签，可填写来源网址；本阶段不自动访问或生成可执行链接。

## HTTP合同

- GET /api/library：资料最新版本摘要、历史版本摘要、容量和模式说明，不返回全部正文。
- GET /api/library/versions/ver-[64hex]：指定版本正文分段、来源、授权说明及hash。
- POST /api/library/import：严格字段request_id/title/filename/source_ref/rights_note/content/confirmed/expected_version。confirmed必须为true；新资料expected_version为空；更新匹配最新版本，否则LIBRARY_STALE。已有request_id且相同参数返回原版本；不同参数报IDEMPOTENCY_CONFLICT。
- POST /api/library/search：严格字段query/document_ids/top_k。document_ids为空表示全部最新资料；指定ID必须存在。query最多200字符，top_k为1—20整数。结果包含命中段落、定位、内容hash、版本和排序分；分数不是可信度。

保持现有Host/Origin/CSRF控制。仅import放宽HTTP请求上限到128KiB，其余保持8192字节。正文最多48000 UTF-8字节；最多50资料、200版本、1000导入请求；每篇最多128段。文件名限普通.txt/.md，拒绝路径、隐藏名、NUL和控制字符。服务器不接受磁盘路径，不扫描目录。用户手动确认授权不是许可证法律审查；本机账户仍可读取运行目录。

## 检索与实验

英文词与中文相邻双字构成词元；BM25式长度归一和逆文档频率排序，加精确短语匹配分，稳定ID打破并列。只查询最新版本，详情可以浏览历史。空查询/空库/无相关词元返回空列表。索引在应用内根据上限内的段落重建；此实现的规模边界需要测试，不能声称支持海量资料。

G1使用原创、明确标注合成的语料，比较精确子串基线与词法排序，验证定位、版本、中文查询和无结果。它只能证明检索机制和工程行为，不代表现实知识检索质量。真实数据评估留给G4。

## G2-B增量架构（2026-09-22）

原G1资料库和固定示例继续存在。`ResearchProjects`冻结范围；`frozen_contract.prepare`从应用私有Library校验并固定候选/版本全文/段落，`task_executions`随任务在同一事务存execution_hash。HTTP只保存严格输入与调度；`FrozenEngine`在P2解释器调用`frozen_worker.py`，并由`frozen_runtime.py`加载实际P2 graph、SqliteSaver、OperationLedger及Exporter。P1解释器仅运行`tokenize_sparse`，应用按词元交集确定性排序；P3独立stdio进程只读`read_note`，产双回执。三个解释器环境互不共享密钥或数据库。实际进程、合同与上限见G2B-WORKFLOW.md。

状态关联为 project_id/contract_hash/execution_hash、应用task_id/request_id、P2 run_id/checkpoint/request_hash/report_hash、P3 call_id/receipt_hash。确定性代码控制候选范围、路径、审批、检索排序、版本与证据核对、修订边界及导出验证；脚本模型只参与计划/报告草稿，不能设置权限或真实预算。新交付schema为`frozen-delivery-v1`，独立CLI不解压验证。文件哈希没有身份签名，后续G3需设计认证与授权。

## UI设计

沿用UI V2的浅灰#f8f9fb、白#fff、正文#23272f、次级#626978、蓝#465dd9、边界#e7e9ef；Segoe UI/微软雅黑，正文15px、辅助12px、阅读16px。新增“项目资料”主导航，旧知识页称“离线示例”。布局为资料列表/版本选择与原文阅读；搜索结果显示实际定位。导入为独立确认表单，允许选TXT/MD或粘贴正文。不使用虚构资料统计、假上传入口或生成答案按钮。
