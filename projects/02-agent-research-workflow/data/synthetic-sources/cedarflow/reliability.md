# CedarFlow 可靠性

> synthetic test fixture
>
> source_id: cedarflow-reliability-v1

## [checkpointing] 状态持久化

CedarFlow 在托管数据库保存节点 checkpoint。任务进程重启后可从最后成功节点恢复。

## [retry-policy] 重试

平台能按错误类别配置重试和退避，并设置工作流总调用预算。权限错误和 Schema 错误默认不重试。

## [idempotency] 幂等

托管写工具支持用户提供 idempotency key。若自定义工具忽略该键，平台不能保证下游系统不重复写入。

## [recovery-limit] 恢复限制

工作区账号或网络不可用时，应用不能读取 checkpoint。导出快照只能用于审计，不能在本地执行。
