# API、权限与威胁模型

接口均以`/api/`开头；响应JSON，异常包含稳定`error.code`和面向用户的message，不返回traceback或绝对路径。所有任务ID为`task-`加32位小写十六进制，request_id为32位小写十六进制；POST采用严格字段集合，未知字段拒绝。

| 方法/路径 | 用途 |
|---|---|
| GET /api/bootstrap | 应用配置、可用模板、边界及当前会话CSRF token |
| GET /api/tasks | 任务列表与统计 |
| POST /api/tasks | `{request_id,title,question}`创建，返回202与task/job |
| GET /api/tasks/{id} | 任务详情、图状态、应用审计 |
| POST /api/tasks/{id}/actions | `{request_id,action,expected_hash,note}`，action为approve/reject/cancel/recover |
| POST /api/tasks/{id}/archive | `{archived}`布尔，忙碌时拒绝 |
| GET /api/tasks/{id}/download | 已完成且复核通过的ZIP，attachment |
| GET /api/knowledge | 固定资料目录及实际解析文本 |
| GET /api/evaluations | 既有可追溯离线结果和来源标签 |

`POST`要求JSON Content-Type、精确Content-Length（一般上限8192 bytes；资料导入上限131072 bytes）、同源Origin、`X-CSRF-Token`及可信Host。token仅在内存中，重启失效，不进入日志。静态文件只有index.html/styles.css/app.js/library.js/projects.js白名单，无目录遍历。响应包含CSP、nosniff、no-referrer、frame-ancestors none和no-store；CORS关闭。默认127.0.0.1随机或显式本机端口，拒绝外网绑定。

请求说明和模型/资料正文均不可信。前端使用textContent或严格转义后的固定模板，不渲染任意HTML/脚本，不自动跟随资料中的URL。下载使用固定文件名，不接受文件路径。SQLite参数化查询；不支持用户SQL。文件根及祖先拒绝symlink/reparse，父目录须归可信OS用户管理。

威胁与边界：防普通恶意网页跨站修改本机状态、DNS重绑定Host、参数污染、过期审批、重复提交及文件遍历；不声称抵御同机管理员、窃取会话的恶意扩展、并发恶意文件替换或未经设计的公网暴露。local-browser是审计标签，不是已认证人类身份。真实多用户需替换认证、授权、会话与部署层，不能通过改监听地址实现。

默认最多200任务、1000次job记录、8个未完成job；worker最长120秒、输出最多2MiB，JSON输入最多8KiB。任务队列只执行脚本模型，0真实调用。状态文件绝不指向原P1/P2/P3目录。

## G2-A项目API

新增GET/POST /api/projects、GET /api/projects/{project_id}、POST /api/projects/{project_id}/search和/evidence，严格合同及错误码见graduation/G2-PROJECT-CONTRACT.md。所有POST保持现有Host/Origin/CSRF和8KiB限制；版本固定不代表许可签名，核验原文不代表认可结论。

## G2-B冻结执行API

`POST /api/projects/{project_id}/tasks`精确字段`request_id,expected_contract_hash,candidates,confirmed`，候选数组2—4项，每项仅`name,version_id`且版本必须在项目范围中并互不重复，`confirmed`必须为true。返回202和任务详情，任务保存project_id/contract_hash/execution_hash；创建时停在`NEEDS_HUMAN`。`POST /api/tasks/{task_id}/revisions`精确字段`request_id,expected_hash,summary,limitations,note,confirmed`，只允许待审冻结任务，最多2次；旧hash返回`STALE_APPROVAL`。旧`/actions`仍负责两个审批门和显式恢复。`GET /api/tasks/{id}/download`按任务模式返回旧固定示例包或新`frozen-delivery-v1`包；新包用`frozen_bundle_cli.py`验证。POST仍须本机同源、Host、Origin、CSRF与8KiB上限。后台动态worker最长240秒、stdout最多2MiB。新子进程输入来自服务器固定快照，不接受客户端文件路径或真实模型提供者。
