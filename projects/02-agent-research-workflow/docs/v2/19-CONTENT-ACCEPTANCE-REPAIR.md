# P2 V2 内容验收修复审计

日期：2026-09-16。状态：**工程修复完成；内容验收仍未通过。** 本文记录失败后做了什么，避免把修复代码、历史模型输出和新的真实质量证据混为一类。

## 失败复核

完整六题固定回归仍是唯一真实质量证据：[机器结果](../../evals/results/v2-final-regression-complete-20260916.json)。它包含2份带备注批准、4份拒绝；未改变输入、gold、原始响应或人工复核结论。

主要错误如下：

- `selection-typed-output` 把“未指定 `output_type` 或含 `str` 时允许普通文本”写成强制结构化输出，颠倒官方原文条件。
- `selection-explicit-graph` 把节点重启与从暂停行继续混淆，并扩大了已读证据的未知范围。
- `gap-compliance` 的恢复规则caveat没有绑定对应的 `rules-of-interrupts` 章节，且将认证/授权与监管合规混写。
- `gap-exactly-once` 用“最多一次副作用”当作“恰好一次”的充分证明；零次副作用同样通过该判据。

41/41引用身份、hash、定位有效，只证明引用链完整，不证明以上句子的语义正确。

## 本轮工程改动

1. 草稿与审校 Prompt 明确要求保留原文否定、默认值、量词和配置前提；claim及caveat均需由所引证据支持；实验必须说明观察、保证边界和不能证明的内容。
2. 审校输出只允许阻塞错误，不混入“nonblocking”确认；要求指出报告字段、原话、证据ID和推理问题。
3. 报告人工批准前重验内容hash、推荐与`decision_status`一致性、以及已知的整快照缺证据断言；任一失败返回稳定错误，不能导出。
4. 导出前再次核对已批准的revision/hash与当前报告内容，阻止checkpoint或内存状态被篡改后的绕过。
5. `resume --action request-changes --feedback "..."` 将长度不超过900字符的公开反馈带入下一稿；反馈不能用于首次需求门、批准或空文本。模型把它当作不可信纠错请求，仍须对照来源核实。

这些变更位于 `src/agent_research/v2/graph.py`、`model_client.py`、`scripts/run_research_v2.py`，对应测试在`tests/test_v2_graph.py`与`test_v2_cli.py`。

## 验证

```powershell
$env:LANGGRAPH_STRICT_MSGPACK='true'
$env:LANGSMITH_TRACING='false'
.\.venv\Scripts\python.exe -m pytest tests/test_v2_graph.py tests/test_v2_cli.py tests/test_v2_model_client.py tests/test_v2_content_evaluation.py -q
.\.venv\Scripts\python.exe -m compileall -q src scripts
.\.venv\Scripts\python.exe -m pip check
```

结果：定向65项测试通过，耗时53.10秒；`compileall`和`pip check`通过。JUnit记录：`.runtime/p2-budget/content-acceptance-targeted-20260916.xml`。完整套件259项通过是本轮此前完整运行记录；本次代码改动之后没有重复完整套件，因为没有改依赖、V1或其他模块。

## 仍不能签发的结论

初始修复后没有真实API调用；用户随后提供后台累计1.56元/174次并明确继续。D5l的18次回执核销后，追加了固定9次调用容量而非新费用额度，运行了三个新冻结题。结果为2份有限批准、1份拒绝；详见[新三题机器证据](../../evals/results/v2-content-completion-verification-20260916.json)。有效保守占用为417/500分，调用容量109/109，不能自动增加、重置或换账本规避限制。

因此不能把Prompt和规则修复写成“模型质量已经改善”，也不能把助手对旧稿的纠错当成新模型输出成绩。P2已有新预注册三题，但其中一题仍拒绝；还缺逐原子事实人工评分、至少一名独立同学复核，以及学习者自己的讲解证据。满足这些真实证据前，`STATUS.md`必须保持`in_progress / content-acceptance-not-passed`。
