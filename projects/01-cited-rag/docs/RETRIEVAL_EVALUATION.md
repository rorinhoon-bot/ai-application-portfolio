# 检索服务与固定 Recall@5 评估

- 状态：`accepted`
- 版本：`0.1`
- 日期：`2026-07-29`

## 1. 解决什么问题

Chunk进入Qdrant不代表用户问题能找到正确证据。本阶段验证三件事：

1. 查询只能读取经过校验的活动索引。
2. 每条结果能回查到真实Chunk和引用URL。
3. 固定问题集的正确证据能进入前5，而不是只看“感觉相关”。

本阶段不生成答案，不调用MiMo，不决定最终拒答阈值。

## 2. 输入合同

```json
{
  "schema_version": "1",
  "question": "Python 3.14 的 Path.read_text 返回什么？",
  "python_version": "3.14",
  "top_k": 5
}
```

- `question`：非空、无首尾空白、最多500字符。
- `python_version`：`3.13`、`3.14` 或 `null`。
- `top_k`：首版固定为5。
- 指定版本时执行Qdrant精确payload过滤。

空问题、错误版本、过长问题或其他 `top_k` 在Embedding前失败。

## 3. 结果合同

每次结果绑定：

- 活动 `index_id`、`build_id` 和collection名称。
- 连续rank和真实Cosine分数。
- 经 `ChunkPayload` 再校验的 `payload-v1`。
- `dense` 或 `identifier` 检索原因。
- 程序使用真实 `source_url + "#" + section_anchor` 组合的引用URL。

模型不得生成或修改版本过滤、Chunk ID、来源URL、anchor、分数、rank或引用URL。

## 4. 查询前一致性检查

查询前必须确认：

- 活动指针与不可变Manifest一致。
- collection存在。
- 向量配置为512维Cosine。
- point数等于Manifest。
- 查询Embedding维度等于活动索引维度。

返回后继续确认：

- point ID等于payload中的Chunk ID。
- payload符合严格schema。
- Chunk schema和配置哈希属于活动索引。
- 指定版本时所有结果都属于该版本。

## 5. 固定评估集

文件：`data/evaluation/retrieval-v1.json`

- 15题。
- 从已验证官方语料人工选择问题和直接证据。
- 每题绑定一个或多个可接受的真实Chunk ID。
- 覆盖教程、`venv`、`json`、`pathlib`、`argparse`、模块、类、异常、浮点和Python 3.13/3.14过滤。
- 绑定索引fingerprint `ea641fef238f3e74d6f64fa923feb53f9a7f36d88b082f14cafdcaabb541c4cd`。

命中定义：

```text
某题的任一 relevant_chunk_id 出现在前5 => hit
Recall@5 = hit题数 / 全部题数
```

评估集不把“当前实现返回了什么”反向当答案。相关Chunk先通过真实正文人工核对。

## 6. 稠密基线

命令：

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_retrieval.py --mode dense
```

结果：

- 10/15命中。
- `Recall@5=66.7%`。
- 目标为80%，未达到。
- 报告：`data/retrieval-evaluation-report.json`。

BGE中文查询指令在相同固定集上仍为10/15。指定版本后移除冗余版本词可达到11/15，但仍未达标。

## 7. 最小透明优化

生产配置为 `dense-plus-identifiers`：

1. 版本过滤已由元数据完成时，从向量文本移除冗余版本词。
2. 从用户原问题中提取直接出现的ASCII代码标识符，例如 `Path.read_text`、`json.dump`、`zip`。
3. 对payload正文匹配标识符，结果仍按同一问题向量的Cosine分数排序。
4. 标识符通道最多占2条。
5. 用稠密结果去重补满5条。

不做：

- 不猜测问题答案。
- 不添加用户没有输入的API名。
- 不使用生成模型改写问题。
- 不加入BM25或Reranker。

命令：

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_retrieval.py --mode dense-plus-identifiers
```

结果：

- 13/15命中。
- `Recall@5=86.7%`。
- 达到80%目标。
- 相比稠密基线提高20个百分点。
- 报告：`data/retrieval-evaluation-optimized-report.json`。

## 8. 保留的失败案例

- “导入模块后查看哪个属性获得模块名称”：问题未出现 `__name__`；目标证据未进入前5。
- “怎样用zip和参数解包转置矩阵”：标识符过滤返回其他 `zip` 片段；目标证据仍未进入前5。

这些失败不通过修改答案、放宽证据或删除问题解决。后续可用更大的独立评估集判断是否值得引入BM25、Reranker或更好的Embedding模型。

## 9. 稳定错误

| 错误码 | 含义 |
|---|---|
| `RETRIEVAL_INPUT_ERROR` | 问题、版本或top-k不合法 |
| `EMBEDDING_INPUT_TOO_LONG` | 完整查询输入超过模型token上限 |
| `RETRIEVAL_ERROR` | 本地Qdrant查询执行失败 |
| `INDEX_CONSISTENCY_ERROR` | 活动索引、collection、point或payload不一致 |
| `INDEX_VERSION_MISMATCH` | 评估集或结果不属于当前索引/config |
| `EVALUATION_ERROR` | 固定评估JSON无法严格加载 |

## 10. 下一边界

下一步单独建立拒答校准集。检索相关分数不能直接拍脑袋当拒答阈值；需要比较可回答、语料外、证据不足和版本冲突问题的分布。该校准不得修改当前固定检索集来迁就结果。
