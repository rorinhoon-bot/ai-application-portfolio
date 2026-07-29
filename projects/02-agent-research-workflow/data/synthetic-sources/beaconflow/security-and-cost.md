# BeaconFlow 安全与成本

> synthetic test fixture
>
> source_id: beaconflow-security-cost-v1

## [data-boundary] 数据边界

BeaconFlow 本身不联网，资料可留在本机。应用注册的工具仍可能联网，框架不审计目标地址。

## [permission-boundary] 权限边界

框架接受任意 Python callable，默认没有工具权限分级。应用必须建立 allowlist，并拒绝模型生成的路径和命令。

## [cost-profile] 成本

BeaconFlow 没有框架运行费用，初始代码量少。若项目需要持久化、审计和恢复，团队要自行补齐这些能力。

## [operations-limit] 运维限制

短任务维护成本低；长任务发生进程故障时需要人工重跑，可能重复模型调用或外部副作用。
