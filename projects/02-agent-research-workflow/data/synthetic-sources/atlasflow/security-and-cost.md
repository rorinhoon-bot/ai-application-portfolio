# AtlasFlow 安全与成本

> synthetic test fixture
>
> source_id: atlasflow-security-cost-v1

## [data-boundary] 数据边界

自托管模式不要求把研究资料发送给框架供应商。若应用接入外部模型，数据是否外发仍由模型适配器决定。

## [permission-boundary] 权限边界

AtlasFlow 不内置 shell 或文件写工具。应用只注册只读工具时，模型不能通过框架获得额外写权限。

## [cost-profile] 成本

AtlasFlow 没有按运行次数收取的框架费用。团队需要承担本地环境、监控、备份和维护时间。

## [operations-limit] 运维限制

小团队首次搭建 checkpoint、审计日志和人工界面时工作量较高。框架本身不提供托管运维服务。
