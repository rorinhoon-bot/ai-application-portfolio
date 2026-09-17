# P2 V2 进程退出恢复验证

日期：2026-09-15。承接13号交付审计，本轮只补恢复入口和离线证据，零真实API调用，未改5元授权或总账本。

## 原问题与修复

原CLI的resume只能处理人工门，进程退出后停在计算节点时没有明确续跑入口。新增recover：读取已有checkpoint，以graph.invoke(None, config, durability="sync")继续未完成节点；不发送新的人工批准。

特殊窗口：文件发布完成后、下一checkpoint写入前强退，最后checkpoint可能仍展示REPORT_NEEDS_HUMAN，但批准已作为__resume__ pending write持久化。recover只接受与当前run_id、thread_id、report_revision、report_hash（需求门为request_hash）完全匹配的已有approve值。不存在匹配记录时返回RECOVER_REQUIRES_HUMAN_DECISION。已保存的编辑、拒绝或返修决定不在本次自动恢复批准路径内，保持人工处理。

live recover与live resume一样要求项目固定总预算路径；不能通过恢复命令换目录或新建账本绕过累计额度。当前真实调用仍停止。

CLI的start/resume/recover现在统一使用同步checkpoint：下一节点开始前等待前一节点进度持久化。代价是增加SQLite写入等待；单用户本地CLI优先保证恢复边界。已到EXPORT_READY且批准hash/revision与当前报告匹配时，也可恢复导出，不依赖残留中断标记。

旧异步状态还可能已合并EXPORT_READY，却没有可运行的export_report任务。仅当当前报告hash/revision与已批准字段匹配时，recover用update_state(as_node="report_gate")重建这条已批准的导出转换，再续跑；不扩大研究范围或预算，不产生新的批准。曾失败的旧async现场已实际恢复到COMPLETED，调用日志仍为plan/draft/review各一次、制品一份。

## 实际行为验证

`tests/test_v2_process_recovery.py`每次启动独立Python进程，使用真实CLI、LangGraph、SQLite和文件导出，在明确边界调用os._exit(73)。子进程阻断socket连接、移除真实模型与tracing环境变量，只使用ScriptedModelClient和合成快照。它验证进程终止，不等于断电、磁盘损坏或供应商网络测试。

| 故障点 | 重启结果 | 外部动作不重复的证据 |
|---|---|---|
| generate进入后、响应返回前 | RECOVERY_REVIEW | 脚本调用日志仅1次plan；再次recover不新增调用，无导出 |
| record_success提交后、图checkpoint前 | 从账本重放plan，再继续draft/review | 总调用顺序仅plan/draft/review各1次；最终1份制品 |
| export原子发布后、图checkpoint前 | 复用已存批准与已有制品 | 模型总计3次，文件1份；再次recover字节与artifact_id不变 |
| 旧异步模式下发布后退出 | 用保存的匹配批准续跑 | 单独兼容用例强制async；不额外调用或生成第二份文件 |
| 未批准的需求门/报告门 | 明确拒绝recover | 不增加模型调用、不生成文件 |

第一版恢复保护误把已保存批准当成未批准；以上published测试失败后定位到pending writes，定向修复后通过；全量回归又发现异步状态/中断标记时序差异，进一步切换同步持久化并补旧async兼容测试。最终结果见下方记录。保留这个失败原因，不能只记录最终passed。

## 命令

在P2目录运行：

```powershell
$env:LANGGRAPH_STRICT_MSGPACK='true'
$env:LANGSMITH_TRACING='false'
.\.venv\Scripts\python.exe scripts\run_research_v2.py --runtime-root <原运行目录> recover --thread-id <原thread_id>
.\.venv\Scripts\python.exe -m pytest -q tests\test_v2_process_recovery.py tests\test_v2_cli.py
```

人工门仍使用resume --action approve，不应把recover当“自动批准”。完成态recover只返回状态；RECOVERY_REVIEW不会自动重发未知请求。

## 仍未完成

本轮未运行真实模型，内容验收未通过的结论不变。没有完整故障矩阵、独立人类评审、新环境重新安装或学生独立讲解证据。其他任务顺序和累计预算保持13号审计所述。

定向验证：5个真实子进程用例通过，覆盖3个业务窗口、旧async兼容与双人工门保护。全量结果以最新STATUS为准。
