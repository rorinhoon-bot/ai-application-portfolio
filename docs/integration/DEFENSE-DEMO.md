# 五分钟毕业设计演示脚本

状态：助手准备的讲解稿，尚未记录学生独立演示。不需要密钥、服务、容器或网络。学校时长和模板未提供，本稿按五分钟组织。

## 0:00—0:45：问题与边界

“本项目是可信AI应用方案研究与交付平台的离线工程原型。重点是让研究过程保留证据、审批和工具审计。P1处理知识资料，P2编排状态，P3通过MCP提供受限工具。当前使用原创合成资料和脚本模型，P2真实内容质量验收仍未通过。”

打开[总体架构](ARCHITECTURE.md)及[交付报告](../../integrations/graduation/demo/offline-20260917/delivery-report.md)。说明模型可以提出研究和写作内容，但权限、参数校验、审批绑定、预算、超时与导出由确定性代码控制。

## 0:45—2:00：沿一条证据解释调用链

以`graph-plan-human-approval#human-approval`为例：查看原创HTML的同名章节；P1实际解析器产生有原始文件哈希和章节定位的记录；P2的SourceStore适配器调用P3；P3只允许按ID读取受控快照；报告保留证据ID。工具调用及审批在[delivery.json](../../integrations/graduation/demo/offline-20260917/delivery.json)中通过run_id、request_hash、call_id关联。

说明本演示没有调用BGE/Qdrant，不能称为正式语义检索评测。八次MCP读取与六条唯一证据并不矛盾：不同查询会重复读取同一条证据。

## 2:00—3:00：现场复核留存包

仓库根目录PowerShell执行；只读，无需打开数据库：

```powershell
& .\projects\02-agent-research-workflow\.venv\Scripts\python.exe -I -B integrations\graduation\verify_bundle.py integrations\graduation\demo\offline-20260917 --expected-delivery-sha256 52d2ccab7f6972507255190763fca9b01b04ac5acfd7b94eb89b8c2e5f73e2db
```

预期：`bundle_consistent=true`、`anchor_status=matched`、2条审批、8次调用、16份收据。随后指出`content_quality=not_evaluated`、`actor_authenticity=not_verified`、`execution_replayed=false`。这些输出能帮助评阅者核对文件关系，不能证明作者身份或真实内容质量。锚值来自本次留存记录，未获得第三方签名。

## 3:00—4:15：展示一次真实失败修复

并排查看[17/18首轮失败](evaluation-20260917.json)与[18/18修正结果](evaluation-final-20260917.json)。故障发生在报告发布后、checkpoint完成前，实际进程以73退出。指出整合层`durability="sync"`修正与原P2接口的关系；说明故障后恢复没有增加模型调用，也没有重复报告。不要将此扩大为通用分布式exactly-once保证。

可选运行新加只读复核测试（只改新临时复制品）：

```powershell
& .\projects\02-agent-research-workflow\.venv\Scripts\python.exe -I -B -m unittest discover -s integrations\graduation\verification_tests -v
```

预期28项通过。无需为了演示失败而直接破坏原始交付包。

## 4:15—5:00：评价和未完成项

“工作流、工具安全、夹具检索和恢复分别报告测试结果，内容质量单独评价。当前已准备人工逐条评分表，还没有独立评分结果。P2真实内容验收失败、P1正式检索和部署未验证、P3部分平台专项跳过，都在验收文档中保留。本轮实现由助手完成，个人掌握程度需要通过独立解释和操作补充证据。”

如果演示时间更长，可按[README](../../integrations/graduation/README.md)运行新临时离线demo，或操作两门审批CLI。脚本demo的批准明确来自`scripted-test`；操作者CLI需阅读需求和报告后再批准，不能将自动批准包装成人工评审。

## 常见追问的回答范围

- 为什么MCP？统一工具发现与输入输出合同；权限、路径防护和审计仍由服务实现，协议本身不保证安全。
- 为什么不能只看引用数量？引用存在只证明可定位；还需判断正文是否支持主张，以及结论是否超出资料范围。
- 为什么分开request_hash、report_hash和artifact_sha256？前两者绑定结构化审批对象，后者校验导出文件字节；文件格式变化会改变字节哈希，不应混为一个含义。
- 复核包能否重跑所有证明？不能。原始请求/报告对象、完整MCP响应和checkpoint不在演示导出包内，复核器只校验保存的字节和关联。
- 当前能否真实部署？当前没有相应验收证据；需要分别补环境、检索、身份、运维及真实内容评估，不能从离线测试推断部署完成。
