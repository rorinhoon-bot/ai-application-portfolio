# D2 官方快照证据覆盖审查

- 审查日期：2026-09-14
- 快照：`snapshot-1855a50c906058faffe87039`
- 输入：`source-plan-v1.json` 冻结的 6 个固定 commit 原文，共 `163080` bytes
- 目的：确认 V2 的只读检索器能否为当前两个候选和三个维度找到可定位章节；这不是模型质量评分，也不是对产品结论的金标准。

## 审查口径

当前产品范围是两个候选（LangGraph、PydanticAI）和三个维度：状态/结构化输出、人工审批、恢复/持久化。每个单元只记录“快照中是否存在可直接读取的官方章节”，不把章节存在误写成方案优劣结论。最终报告仍须让模型绑定 `evidence_id`，并由确定性合同检查候选、维度、快照和引用关系。

`SourceStore` 使用关键词检索；查询命中只是候选证据发现，不能替代人工核对。D2 的覆盖审查直接读取章节，避免用固定答案测试生产输出。

## 覆盖矩阵

| 候选 | 状态/结构化输出 | 人工审批 | 恢复/持久化 |
|---|---|---|---|
| LangGraph | **有**：`lg-01#core-benefits`（stateful workflow）、`lg-03#quickstart`（checkpointer 编译入口） | **有**：`lg-02#pause-using-interrupt`、`lg-02#resuming-interrupts`；需人工核对恢复语义和副作用边界 | **有**：`lg-03#checkpointer-vs-store`、`lg-03#next-steps`；需补运行时故障样本验证 |
| PydanticAI | **有**：`pa-01#structured-output-data-structured-output`（结构化输出与校验） | **有**：`pa-02#human-in-the-loop-tool-approval`、`pa-02#resolving-deferred-calls-with-a-handler` | **有但较窄**：`pa-03#durable-execution` 说明 durable agent 方向和受支持后端；该页没有后端操作细节，不能单独证明本项目的 SQLite 恢复行为 |

## 结果与缺口

- 六个单元均有至少一个可读取章节，说明快照可以进入后续 live 研究输入；真实章节读取已由本地 `.venv` 手工验证。
- LangGraph 的人工暂停、恢复和 checkpoint 章节较完整，适合先验证 V2 的显式状态图设计。
- PydanticAI 的结构化输出和工具审批章节可比较；durable execution 页面是入口索引，后端细节不在本批 6 页内，报告必须标注证据范围，不得推断完整实现能力。
- 当前没有做发布时间、版本发布日期、性能、价格、模型兼容性或生产部署结论；这些属于 D3-live/D4 的独立审查项。
- 关键词检索仍可能返回跨候选噪声。下一步应让计划节点按 `candidate_id` 过滤并让人工在报告门核对章节；若真实任务暴露遗漏，再单独评估 BM25/向量检索，不提前引入依赖。

## 可复核命令

在 P2 目录执行：

```powershell
@'
from pathlib import Path
import sys
sys.path.insert(0, 'src')
from agent_research.v2.source_store import load_snapshot, SourceStore, _sections

root = Path('data/real-sources/snapshot-1855a50c906058faffe87039')
manifest, texts = load_snapshot(root, root / 'manifest.json')
for entry in manifest.entries:
    print(entry.source_id, entry.candidate_id, entry.title)
    for section_id, title, _ in _sections(texts[entry.source_id]):
        print(' ', section_id, '|', title)
'@ | .\.venv\Scripts\python.exe -
```

该命令只读本地快照，不访问网络，不调用模型，不产生费用。
