# AtlasFlow 概览

> synthetic test fixture
>
> source_id: atlasflow-overview-v1

## [deployment-model] 部署模式

AtlasFlow 以自托管 Python 库运行。控制状态、研究资料和报告草稿默认留在用户机器。团队需要自行管理运行环境、升级和备份。

## [workflow-control] 工作流控制

AtlasFlow 使用显式有向状态图。开发者定义节点、条件边和终态；运行时不会自行增加未注册节点。每个循环必须由应用传入最大次数。

## [human-approval] 人工确认

AtlasFlow 支持在指定节点前暂停。恢复请求必须携带同一运行 ID 和审批版本。它不提供托管审批页面，应用需要自行实现 CLI 或 UI。

## [tool-interface] 工具接口

工具通过名称 allowlist 和 JSON Schema 注册。模型只能提出调用请求；应用负责权限、参数和预算校验。
