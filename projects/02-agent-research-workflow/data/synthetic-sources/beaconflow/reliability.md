# BeaconFlow 可靠性

> synthetic test fixture
>
> source_id: beaconflow-reliability-v1

## [checkpointing] 状态持久化

BeaconFlow 首版只在内存保存当前步骤和结果。进程退出后状态丢失，没有内置磁盘 checkpoint。

## [retry-policy] 重试

每个步骤可设置固定重试次数。框架不区分超时、权限错误和参数错误；应用若不拦截，确定性错误也会重复执行。

## [idempotency] 幂等

框架不记录外部写入键，也不检测重复执行。应用需要自行保存写入结果。

## [recovery-limit] 恢复限制

BeaconFlow 可从用户手工提供的步骤编号重新开始，但不会验证先前状态、工具结果或审批 revision。
