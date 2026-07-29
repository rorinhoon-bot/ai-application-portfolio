# 技术选型约束

> synthetic test fixture
>
> source_id: procurement-constraints-v1

## [privacy-policy] 隐私约束

严格隐私任务禁止把研究资料、完整状态和报告草稿发送到第三方托管工作流服务。

## [recovery-requirement] 恢复要求

长任务必须在进程退出后从最后成功节点恢复。仅能手工输入步骤编号不算状态恢复。

## [approval-requirement] 审批要求

最终报告导出前必须由人批准具体 revision 和内容哈希。旧批准不能授权修改后的草稿。

## [cost-policy] 成本约束

没有模型 API 预算批准时，测试必须使用假模型。任何按运行次数计费的工作流服务必须另行批准预算。
