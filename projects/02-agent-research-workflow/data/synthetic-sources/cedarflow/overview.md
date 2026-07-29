# CedarFlow 概览

> synthetic test fixture
>
> source_id: cedarflow-overview-v1

## [deployment-model] 部署模式

CedarFlow 是托管工作流服务。应用通过 HTTPS 提交状态和任务，供应商负责运行、升级和备份。

## [workflow-control] 工作流控制

CedarFlow 提供可视化有向图、条件边和循环上限。图配置保存在供应商工作区。

## [human-approval] 人工确认

CedarFlow 提供托管审批页面、审批通知和按 revision 的批准记录。审批页面不可离线使用。

## [tool-interface] 工具接口

工具通过托管 registry 和 JSON Schema 注册。平台能记录每次调用参数、结果状态和延迟。
