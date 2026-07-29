# Chunk 切分设计

- 状态：`accepted`
- 版本：`0.3`
- 日期：`2026-07-28`
- 前置输入：已验证的 `ImportedDocument`
- 本阶段边界：只切分并生成 `DocumentChunk`；不做 Embedding、Qdrant 或模型调用

## 1. 要解决的问题

HTML 清洗后得到5003个 `ContentBlock`。检索不能直接把整页或整章送入 Embedding：

- 整章太长，主题混杂，检索定位不准。
- Block 太碎，单独索引会缺少上下文。
- 代码或列表可能超过普通 Chunk 上限。
- 引用必须能回查到真实 Block 和块内字符范围。

Chunker 负责把相邻 Block 合并成适中、可追踪、可重复生成的检索单元。它不摘要、不改写正文。

## 2. 真实输入分布

对25份真实文档的离线分析结果：

- 文档：25
- Block：5003
- 章节：531
- 清洗正文：467,402字符
- Block 长度：中位60，P90 190，P95 284，P99 517，最大8705
- 长度超过520的 Block：50
  - `code`：44
  - `list_item`：6
- 长度超过520的章节：276
- 最长 Block：`venv` 文档中的207行代码，8705字符

结论：大多数 Block 可直接按章节合并；少量超长 Block 必须确定性拆分。只保存 `block_start`/`block_end` 不足以定位拆分片段。

## 3. 基线配置

新增严格、不可变的 `ChunkingConfig`：

```text
schema_version = "1"
max_characters = 520
overlap_characters = 80
block_separator = "\n\n"
minimum_split_characters = 260
include_section_path = true
```

规则：

- 长度使用 Python `len(str)`，即 Unicode 码点数量。
- `DocumentChunk.text` 中插入的 `\n\n` 也计入520字符上限。
- Chunk算法不依赖 tokenizer；配置选择由固定 BGE tokenizer 的无截断审计约束。
- 520和80只是首个token安全基线；后续仍需通过固定检索评估比较，不声明最优。

## 4. DocumentChunk 合同补充

现有字段保留，新增：

```text
chunking_schema_version
chunk_config_sha256
block_start_offset
block_end_offset
```

含义：

- `block_start_offset`：Chunk 在 `block_start.clean_text` 中的起点，0-based、包含。
- `block_end_offset`：Chunk 在 `block_end.clean_text` 中的终点，0-based、不包含。
- 普通完整 Block：起点为0，终点为 `len(clean_text)`。
- 多 Block Chunk：首尾偏移描述边界，中间 Block 必须完整包含。
- Chunk 内容只能来自从首边界到尾边界的连续 Block 范围。
- `chunking_schema_version` 首版为 `chunker-v1`。
- `chunk_config_sha256` 是规范化配置 JSON 的 SHA-256。

这四个字段由程序生成，模型不得生成或修改。

## 5. 章节边界

- 使用真实 `section_anchor` 和 `section_path` 分组。
- Chunk 不跨 `section_anchor`。
- 章节变化立即结束当前 Chunk。
- 新章节首个 Chunk不复用上一章节内容。
- 同名标题但不同 anchor 仍视为不同章节。

## 6. 普通 Block 合并

同一章节内按 `block_order` 贪心合并：

1. 当前 Chunk 为空时加入下一个内容片段。
2. 拼接使用固定 `\n\n`。
3. 加入后不超过 `max_characters`，继续。
4. 超过上限，结束当前 Chunk，再建立下一个。
5. 每个新 Chunk 必须至少加入一个尚未覆盖的新片段，防止重叠导致死循环。

小型代码块、列表项和段落可与同章节相邻 Block 合并，只要最终文本不超上限。

同一超长 Block 的相邻分段重新进入同一 Chunk 时不插入分隔符，因为两段本来是同一连续文本。不同 Block 之间才插入 `\n\n`。

## 7. 超长 Block 拆分

### 7.1 普通文本、列表和提示块

当 `clean_text` 超过520字符：

1. 在260～520字符范围内选择最靠后的换行边界。
2. 没有换行时，选择最靠后的句末边界：`。！？.!?；;`。
3. ASCII 句末符仅在后面为空白或文本结尾时有效；边界包含其后仍位于上限内的连续空白，避免下一片以空白开头。
4. 没有句末时，选择最靠后的空白边界。
5. 仍没有安全边界时，在520字符处硬切。
6. 不删除、不添加、不重排原字符；最终片段可以短于260字符。

### 7.2 代码块

- 优先按完整行切分，每片不超过520字符。
- 保留所有换行、空格和缩进。
- 单行本身超过520字符时，按字符硬切。
- 不按句号切代码。
- 代码片段不添加 Markdown 围栏或解释文字。

## 8. 重叠

- 只在同一章节的相邻 Chunk 之间重叠。
- 只复用上一 Chunk 尾部的完整、未拆分 `ContentBlock`。
- 选择可放入80字符的最大连续 Block 后缀；`\n\n` 计入重叠长度。
- 超过80字符的 Block 不做部分重叠。
- 超长 Block 的拆分片段不参与重叠。
- 加入重叠后，下一 Chunk 总长度仍不得超过520。
- 下一 Chunk 必须包含新内容，不能只有重叠。

此规则可能让部分 Chunk 的实际重叠为0。换取边界简单、代码不被重复截断、引用范围清楚。

## 9. 引用文本与 Embedding 文本

```text
text = 按范围提取的 clean_text，用 "\n\n" 连接
embedding_text = " > ".join(section_path) + "\n\n" + text
```

- `text` 不添加标题、标签、Markdown或模型摘要。
- `embedding_text` 加入真实标题路径，帮助检索。
- `section_path` 已包含页面 `h1`，不再重复添加页面标题。
- 引用只展示 `text`；标题前缀不作为原文引用。

## 10. 稳定身份

```text
chunk_config_sha256 = SHA256(规范化 ChunkingConfig JSON)

chunk_id = UUIDv5(
  固定项目命名空间,
  snapshot_id
  + chunking_schema_version
  + chunk_config_sha256
  + chunk_order
  + block_start
  + block_start_offset
  + block_end
  + block_end_offset
  + content_sha256
)
```

- 相同输入和配置产生相同 Chunk、哈希与 ID。
- 文本、边界、顺序、配置或 chunker schema 变化时 ID 改变。
- `content_sha256` 继续等于 `SHA256(text UTF-8)`。

## 11. 失败边界

新增稳定错误码 `CHUNKING_ERROR`。以下情况整份文档失败，不返回部分结果：

- Block 顺序不连续。
- Block 的 Snapshot ID 与文档 Snapshot 不一致。
- Block 文本为空。
- 同一 Chunk 候选出现不同章节。
- 偏移越界或不能重建 `text`。
- 生成空 Chunk。
- Chunk 超过配置上限。
- 内容覆盖出现缺口。
- Chunk ID、文本哈希或配置哈希不能复现。

错误只包含 `source_id`、稳定错误码和短原因，不输出大段正文。

## 12. 最小固定验收夹具

确认后新增固定输入与期望 JSON：

1. `basic_merge_and_overlap`
   - 同章节三个短 Block，测试贪心合并与完整 Block 重叠。
   - 第四个 Block 位于新章节，验证不跨章节、不跨章节重叠。
2. `long_text_split`
   - 一个超长列表项，含多个中文句子。
   - 验证句末优先、半开区间偏移、无字符丢失。
3. `long_code_split`
   - 多行代码超过上限。
   - 验证完整行优先及缩进、换行完全保真。
4. `single_long_code_line`
   - 单行超过上限。
   - 验证硬切和精确偏移。
5. `deterministic_identity`
   - 相同输入重复切分，结果逐字段相同。
   - 改变一个配置字段，配置哈希与 Chunk ID 改变。
6. `invalid_block_sequence`
   - Block 顺序缺号，固定返回 `CHUNKING_ERROR`。

测试使用小上限，例如30字符，使期望结果短而可人工核对。生产默认仍为800/120。

## 13. 短例子

测试配置：

```text
max_characters = 30
overlap_characters = 12
block_separator = "\n\n"
```

同章节输入：

```text
B1 = "alpha beta."   # 11字符
B2 = "gamma delta."  # 12字符
B3 = "theta kappa."  # 12字符
```

结果：

```text
Chunk 1: B1 + "\n\n" + B2
Chunk 2: B2 + "\n\n" + B3
```

第二个 Chunk 的 B2 是完整 Block 重叠。若 B3 属于新章节，则新 Chunk 只包含 B3。

超长文本例子：

```text
原文："第一句。第二句。第三句。"
上限：8
片段1：[0, 8)  "第一句。第二句。"
片段2：[8, 12) "第三句。"
```

偏移直接对应原 `clean_text`，不用模型猜测。

## 14. 实现与真实验证结果

- `ChunkingConfig`、`DocumentChunk` 偏移字段和 `CHUNKING_ERROR` 已实现。
- 六类固定夹具逐字段通过。
- 单 Block 分段时，真实5003个 Block 生成5082个片段；50个超长 Block 全部拆分成功，最大片段520字符。
- 真实25份文档生成1359个 Chunk。
- Chunk 文本长度：中位416、P90 508、P95 514、P99 519、最大520。
- 349个 Chunk 使用完整 Block 重叠。
- 固定 BGE tokenizer 关闭截断后，token中位241、P90 346、P95 369、P99 407、最大460，1359个 Chunk 全部不超过512。
- 全部 Chunk ID 唯一；相同输入与配置重复运行结果一致。
- 旧 `800/120/400` 基线曾产生974个 Chunk，其中94个 `embedding_text` 超过512 tokens；因此被 `520/80/260` 取代。
- 实现期间真实8705字符代码块触发一次半开区间上界错误；回归测试保证位于上限外的换行不会生成521字符片段。
- 全部普通测试离线运行，不访问网络、不运行 ONNX、不写向量索引。
