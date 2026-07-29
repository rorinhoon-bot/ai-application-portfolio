# BeaconFlow 概览

> synthetic test fixture
>
> source_id: beaconflow-overview-v1

## [deployment-model] 部署模式

BeaconFlow 是单进程本地 Python 库。它只需要少量配置，适合短任务和教学演示。

## [workflow-control] 工作流控制

BeaconFlow 按线性步骤列表执行，可用布尔条件跳过步骤。它不提供显式循环边；复杂回路需要应用代码自行管理。

## [human-approval] 人工确认

BeaconFlow 提供同步确认回调。用户必须在原进程仍运行时批准或拒绝，不能关闭进程后恢复同一确认点。

## [tool-interface] 工具接口

工具是普通 Python callable。框架检查工具名，但不强制 JSON Schema；参数边界需要应用包装器实现。
