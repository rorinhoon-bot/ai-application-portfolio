# 本机离线验收与失败案例

日期：2026-09-18。执行者：助手。分支codex/course-platform-ui；HEAD基线9e2a77219ac7fbb83d28f6ca2f3e3756a4189201；本轮改动未提交/推送。

## 验收结论

当前单机离线课设闭环通过应用行为验证。应用测试21项，21通过、0失败、0错误、0跳过，55.872秒，见[机器结果](results/evaluation.json)。没有新增依赖，没有真实模型调用。不能据此宣称真实内容质量、全新电脑安装、生产部署或学校最终要求已通过。

```powershell
.\projects\02-agent-research-workflow\.venv\Scripts\python.exe -B apps\course-platform\evaluate.py --output apps\course-platform\docs\results\evaluation.json
```

| 维度 | 实际证据 | 不能外推的结论 |
|---|---|---|
| 工作流可靠性 | 创建停在NEEDS_HUMAN；第一批准后REPORT_NEEDS_HUMAN；第二批准后COMPLETED | 通用真实研究质量 |
| 工具与HTTP安全 | 实际P3 MCP、Host/Origin/CSRF、严格JSON、路径拒绝、容量/超时 | 全网络威胁、恶意OS管理员防护 |
| 检索行为 | 实际P1解析六段夹具；资料搜索checkpoint匹配两条 | 原向量检索、真实数据召回率 |
| 审批恢复幂等 | 请求重复不重建、过期hash拒绝、重启恢复不增调用、ZIP字节一致 | 所有崩溃时刻的exactly-once |
| UI | 创建、双审批、证据、审计、搜索、过滤、取消、归档、窄屏、XSS | 全浏览器兼容与无障碍标准认证 |
| 内容质量 | 明确固定资料、脚本模型、P2历史失败 | 真实内容质量达标 |

端到端测试实际生成6条证据、8条MCP工具事件、两门审批与验证后的ZIP；还验证未批准不能下载及拒绝后0模型调用。实际演示工作流重启后仍保留完成任务。浏览器独立记录见[UI结果](results/browser.json)与[screenshots](screenshots/)。

环境探针：P1/P2 Python3.14.3，P3 Python3.13.14；Pydantic2.13.4，P2 LangGraph1.2.9、SQLite checkpoint3.1.0，P3 MCP2.0.0。均为已有环境，未安装。完整依赖沿用各项目锁文件。

## 失败与修复

- 首版统计项换行与任务步骤条纵向堆叠：实际截图发现，调整grid/flex后重验。
- P2的tool_call_count为逻辑轮次，不等于实际MCP次数；UI改用tool_events长度，当前展示8。
- 拒绝被通用FAILED标签显示为运行失败：根据原拒绝错误码派生展示，不篡改P2状态。
- 取消确认最初沿用批准说明：改为“停止继续，保留记录，可复制重做”。
- 恶意标题`<img src=x onerror=alert(1)>`：创建后按文本显示，页面无新增img、无脚本弹窗；随后明确取消并归档测试任务。
- 内置浏览器等待download事件超时30秒：不记作下载落盘通过。再次点击显示“交付包校验通过”；独立HTTP读取得200/application/zip/16212字节，后端测试已验证ZIP内容与重复下载一致。外部浏览器落盘仍待复核。
- 原工作树status第一次比较因Git路径转义配置不同产生表面差异；统一core.quotePath=false后668条完全一致，HEAD未变。

## 未验证与后续

本轮未重跑P1/P2/P3所有原测试，因为业务文件没有修改；历史发布基线单独呈现，不能冒充本轮结果。未访问原数据库、容器或云资源。全新环境安装、远程身份隔离、正式资料摄取、真实模型质量、长时间并发与跨浏览器下载待后续按需求验收。学生独立讲解和教师评分要求待补。

## UI V2补充验收（2026-09-19）

视觉与交互改版已完成本机浏览器复核。新版证据为results/ui-v2.json、screenshots/ui-v2/、UI-REFRESH.md；前述21项是V1完整工程回归，本轮执行6项HTTP回归并实测筛选、搜索、来源阅读、任务创建/取消/归档、历史报告/证据/审计和响应式布局。原历史结果保留。内容质量、学校要求、公开部署、全新机器与OS下载落盘限制仍适用。


## G1资料基础补充（2026-09-21）

本轮资料库验收见 `docs/graduation/EVALUATION.md`、`docs/graduation/PLAN-HANDOFF.md` 和 `docs/results/graduation-g1-browser.json`。36/36完整离线回归通过，其中15项覆盖导入、版本、并发、路径、权限、检索和HTTP；浏览器验证导入、定位、历史、重启、转义及窄屏。资料为本机用户主动输入，当前不进入既有固定研究报告。
