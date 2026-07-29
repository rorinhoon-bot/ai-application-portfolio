# AtlasFlow 可靠性

> synthetic test fixture
>
> source_id: atlasflow-reliability-v1

## [checkpointing] 状态持久化

AtlasFlow 可把每个已完成节点后的状态写入本地 SQLite。进程退出后，应用能按运行 ID 读取最后成功 checkpoint 并继续。

## [retry-policy] 重试

框架提供重试钩子，但不替应用判断错误类型。应用必须区分瞬时错误和确定性错误，并设置最大尝试次数。

## [idempotency] 幂等

AtlasFlow 保存节点 revision，但外部写操作是否幂等由应用负责。推荐用运行 ID、批准 revision 和内容哈希生成写入键。

## [recovery-limit] 恢复限制

已持久化状态与最新图版本不兼容时，AtlasFlow 不自动迁移业务字段。应用必须拒绝恢复或提供显式迁移。
