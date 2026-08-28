# V2-C 分层检索评估

- 状态：`implemented`
- 日期：`2026-08-24`
- 评估集：`retrieval-v2`
- 评估集语义 SHA-256：`a3b30c755dc2a4036b9d715a9df2bd891bfb850ce2bc2c369b43447c2a8abd13`
- 索引 fingerprint：`ea641fef238f3e74d6f64fa923feb53f9a7f36d88b082f14cafdcaabb541c4cd`

## 1. 合同

题集由现有 1359 个已验证 payload 人工回查，不从当前检索 Top-K 反向生成。共 50 题：

| 题型 | 数量 |
| --- | ---: |
| `semantic-paraphrase` | 12 |
| `exact-identifier` | 12 |
| `mixed-semantic-identifier` | 10 |
| `version-specific` | 8 |
| `known-hard` | 8 |

拆分为 30 题 `development`、20 题 `locked-test`。旧 15 题及两份 V1 报告原字节保留；其中 15 个旧问题原文进入 V2 并重新标注题型和拆分。

相关证据只读核验结果：50 个唯一相关 Chunk 全部存在；point ID 与 payload `chunk_id` 一致；题目版本与 payload 版本错配为 0。

## 2. 测量协议

- 单进程、顺序查询。
- 每模式先执行 5 次不计时 warm-up。
- 50 题各重复 3 次，共 150 个 warm-query 样本。
- P50/P95 使用 nearest-rank。
- warm 延迟包含问题 Embedding、活动索引/collection 一致性检查和 Qdrant 查询；模型与索引初始化单独记为 cold-start。
- Qdrant 使用 Server read-only key；没有 Qdrant 写入、MiMo 调用、模型下载、依赖安装或容器重启。

当前两条检索器只暴露最终 Top-5，没有独立候选层。因此 `candidate Recall@20` 明确记录为 `null`，状态为 `unavailable-current-retriever-no-candidate-layer`；不把 Top-5 伪装成候选召回。C2 Hybrid 暴露 Dense/Sparse 候选后再填充该指标。

## 3. 总体结果

| 模式 | 命中 | Recall@5 | MRR@5 | nDCG@5 | P50 | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `dense` | 42/50 | 84.0% | 0.6313 | 0.6840 | 4.805 s | 5.304 s |
| `dense-plus-identifiers` | 45/50 | 90.0% | 0.7217 | 0.7673 | 4.807 s | 5.802 s |
| 绝对变化 | +3 | +6.0 pp | +0.0903 | +0.0833 | +0.002 s | +0.499 s |

当前生产路径在质量三项上均优于 Dense；P95 增加约 9.4%。本表只比较两条V2-C1只读路径，不代表后续Hybrid或Reranker结果。

## 4. 分层结果

### 4.1 Dense

| 分层 | Recall@5 | MRR@5 | nDCG@5 |
| --- | ---: | ---: | ---: |
| development | 83.3% | 0.6511 | 0.6965 |
| locked-test | 85.0% | 0.6017 | 0.6652 |
| semantic-paraphrase | 100.0% | 0.7917 | 0.8456 |
| exact-identifier | 83.3% | 0.6208 | 0.6733 |
| mixed-semantic-identifier | 80.0% | 0.5167 | 0.5893 |
| version-specific | 75.0% | 0.4938 | 0.5561 |
| known-hard | 75.0% | 0.6875 | 0.7039 |

### 4.2 Dense + identifiers

| 分层 | Recall@5 | MRR@5 | nDCG@5 |
| --- | ---: | ---: | ---: |
| development | 90.0% | 0.7583 | 0.7939 |
| locked-test | 90.0% | 0.6667 | 0.7274 |
| semantic-paraphrase | 100.0% | 0.7917 | 0.8456 |
| exact-identifier | 83.3% | 0.6736 | 0.7135 |
| mixed-semantic-identifier | 100.0% | 0.7000 | 0.7762 |
| version-specific | 87.5% | 0.7500 | 0.7827 |
| known-hard | 75.0% | 0.6875 | 0.7039 |

标识符通道新增命中 4 题：`path-read-text-314`、`list-sort-lambda-key`、`path-read-text-313`、`argparse-prog-313`；同时使 7 个已命中问题的首个相关排名提前。

它也造成 1 个退化：`template-string-314`。问题中的显式 ASCII 词触发文本通道，把相关 t-string 证据挤出 Top-5。这说明简单标识符提升不是单调安全的，也是 C2 需要更正式 Sparse/RRF 消融的直接依据。

## 5. 失败样例

生产路径仍失败 5 题：

- `path-walk-symlink-classification`
- `argparse-boolean-optional-action`
- `template-string-314`
- `module-name-attribute`
- `transpose-with-zip`

后两题是 V1 已保留的真实难例。不能通过删题、修改相关证据或只汇报 development 掩盖失败。

## 6. 运行资源

- Python `3.14.3`
- Qdrant Server `1.19.0`，Client `1.18.0`
- FastEmbed `0.8.0`
- BGE revision `46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59`
- 模型资产 `95,221,432` bytes
- collection storage `205,628,065` bytes
- Docker Qdrant内存快照：Dense `70,632,079` bytes；生产路径 `71,324,140` bytes
- 逻辑 CPU 16；模型加载后进程线程快照 35
- cold-start：Dense `8.096 s`；生产路径 `4.620 s`。后一次受操作系统文件缓存影响，只作为各自运行记录，不作模式优劣结论。
- 外部 API 调用 0

机器可读报告：

| 文件 | 字节 | 文件SHA-256 |
| --- | ---: | --- |
| `data/evaluation/retrieval-v2.json` | 21,880 | `30d789ee100a145280be8e499d2b2be04ef99d0cb2b1e5ddcf0d1ed7216e0b7c` |
| `data/retrieval-v2-dense-report.json` | 121,640 | `3def9db243f39a4f2d7282de5d6c44e269804dba0363f1fce340216595bb8394` |
| `data/retrieval-v2-dense-plus-identifiers-report.json` | 122,118 | `c91c42bbf359810e8fe9c08a04a8aac27e2dfad8d7221f726d116652d28bf19c` |

## 7. V2-C2 Hybrid结果

候选索引使用named Dense `dense-bge-v1`与Sparse `lexical-bm25-v1`，Dense/Sparse各预取20条，Qdrant执行等权`RRF(k=2)`。索引共1359 points、25,836个词表项与118,664个Sparse非零项；活动生产指针未切换。

development 30题各重复3次，配置冻结后结果如下：

| Recall@5 | candidate Recall@20 | P50 | P95 |
| ---: | ---: | ---: | ---: |
| 96.67%（29/30） | 96.67%（29/30） | 7.572 s | 8.309 s |

唯一一次locked运行在生成任何指标或报告前触发`EVALUATION_ERROR: V2 repeated retrieval ranking changed`。按锁定合同不重跑、不用锁定集修参数。客户端同分排序能稳定已返回结果，但不能约束Qdrant内部Prefetch/RRF同分名次、融合分数或第20名候选边界。

因此发布门安全失败：`passed=false`、locked指标不可用、Hybrid未激活、API未重建或重启。失败证据见`data/hybrid-locked-run-failure.json`与`data/hybrid-release-gate.json`。

机器可读C2证据：

| 文件 | 字节 | 文件SHA-256 |
| --- | ---: | --- |
| `data/hybrid-index-build-report.json` | 3,959 | `ba8f6f9a79f59c5c7fa354b4cbd7b376e23cf553ee477e6b9487ec56fed4061e` |
| `data/retrieval-v2-hybrid-development-report.json` | 50,339 | `ee8eef215400e4bd3abc3a61ccf3c9bb6186ba2970b590435a93535c497fe0d6` |
| `data/hybrid-locked-run-failure.json` | 840 | `0b3865bc752307b17a1453a99029e8dee96b56dc0437b8b01593021c3758d1d3` |
| `data/hybrid-release-gate.json` | 1,918 | `54cd4f5a3cf2e39a78526bc72ca8d330cba413bd6af3e57daaa54a5f4445f144` |

## 8. 下一决策门

V2-C2已按失败关闭结束。下一步若继续，必须先设计可复现的确定性融合方案，并单独审批；不能直接激活现有候选。

Reranker仍不下载。locked candidate指标不可用，development candidate Recall@20又不高于Recall@5，没有证明“候选已召回但Top-5排序不足”。
