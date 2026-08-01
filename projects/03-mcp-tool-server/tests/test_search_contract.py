"""P3 Slice A 离线单测（标准库 unittest，无需安装 pytest）。

覆盖：
- search_notes 参数合同：合法、空白、超长、未知字段、非字符串、URL/命令语义、
  控制字符、绝对路径。
- 检索合同：正常多命中、无命中、note_id 稳定派生、NFKC+大小写无关、excerpt<=120、
  hits 上限 5。
- 夹具来自 evals/fixtures/notes-v1（原创虚构，离线）。
"""

import os
import sys
import unittest

# 让测试可直接 `python -m unittest` 运行，无需 .venv 或安装
_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_SRC))

from mcp_notes.contracts import (  # noqa: E402
    Keyword,
    NoteIndexEntry,
    INVALID_ARGUMENTS,
    parse_search_notes_args,
    validate_keyword,
)
from mcp_notes.index import build_index, compute_note_id  # noqa: E402
from mcp_notes.search import search_notes  # noqa: E402

_FIXTURES = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "evals", "fixtures", "notes-v1")
)


def _provider_from_root(root):
    from mcp_notes.index import read_note_content

    def _provider(entry):
        return read_note_content(entry, root)

    return _provider


class TestKeywordContract(unittest.TestCase):
    def test_valid_keyword(self):
        kw = validate_keyword("RAG")
        self.assertIsInstance(kw, Keyword)
        self.assertEqual(kw.value, "RAG")

    def test_strip_whitespace(self):
        kw = validate_keyword("  MCP  ")
        self.assertIsInstance(kw, Keyword)
        self.assertEqual(kw.value, "MCP")

    def test_empty_keyword(self):
        self.assertIsNone(validate_keyword(""))

    def test_whitespace_only(self):
        self.assertIsNone(validate_keyword("   "))

    def test_too_long_81(self):
        self.assertIsNone(validate_keyword("a" * 81))

    def test_max_length_80_ok(self):
        self.assertIsInstance(validate_keyword("a" * 80), Keyword)

    def test_control_char(self):
        self.assertIsNone(validate_keyword("abc\x00def"))

    def test_absolute_path(self):
        self.assertIsNone(validate_keyword("C:\\Users\\x"))

    def test_dotdot_segment(self):
        self.assertIsNone(validate_keyword(".."))

    def test_url_scheme(self):
        self.assertIsNone(validate_keyword("http://example.com"))

    def test_shell_token(self):
        self.assertIsNone(validate_keyword("a;b"))


class TestParseArgs(unittest.TestCase):
    def test_valid_args(self):
        kw = parse_search_notes_args({"keyword": "笔记"})
        self.assertIsInstance(kw, Keyword)

    def test_unknown_field(self):
        self.assertIsNone(parse_search_notes_args({"keyword": "x", "extra": 1}))

    def test_missing_keyword(self):
        self.assertIsNone(parse_search_notes_args({}))

    def test_keyword_not_string(self):
        self.assertIsNone(parse_search_notes_args({"keyword": ["a", "b"]}))

    def test_keyword_object(self):
        self.assertIsNone(parse_search_notes_args({"keyword": {"a": 1}}))

    def test_args_not_dict(self):
        self.assertIsNone(parse_search_notes_args("笔记"))


class TestSearchBehavior(unittest.TestCase):
    def setUp(self):
        self.entries = build_index(_FIXTURES)
        self.provider = _provider_from_root(_FIXTURES)

    def test_index_has_three_notes(self):
        self.assertEqual(len(self.entries), 3)

    def test_note_id_stable_from_relative_path(self):
        for e in self.entries:
            self.assertEqual(e.note_id, compute_note_id(e.relative_path))
            self.assertEqual(len(e.note_id), 16)

    def test_multi_hit_keyword(self):
        # “笔记” 在三篇笔记标题/正文中均出现
        kw = validate_keyword("笔记")
        result = search_notes(kw, self.entries, self.provider)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.total_matched, 3)
        self.assertEqual(len(result.hits), 3)
        ids = {h.note_id for h in result.hits}
        self.assertEqual(ids, {e.note_id for e in self.entries})

    def test_single_hit_keyword(self):
        # “MCP” 仅出现在 note-02
        kw = validate_keyword("MCP")
        result = search_notes(kw, self.entries, self.provider)
        self.assertEqual(result.total_matched, 1)
        self.assertEqual(result.hits[0].title, "项目笔记：MCP 工具服务")

    def test_no_match(self):
        kw = validate_keyword("量子计算")
        result = search_notes(kw, self.entries, self.provider)
        self.assertEqual(result.total_matched, 0)
        self.assertEqual(result.hits, ())

    def test_case_insensitive(self):
        kw = validate_keyword("rag")
        result = search_notes(kw, self.entries, self.provider)
        # note-01 含 “RAG”
        self.assertGreaterEqual(result.total_matched, 1)

    def test_nfkc_fullwidth(self):
        # 全角 “ＲＡＧ” 经 NFKC 归一后应与 “RAG” 匹配
        kw = validate_keyword("ＲＡＧ")
        self.assertIsInstance(kw, Keyword)
        result = search_notes(kw, self.entries, self.provider)
        self.assertGreaterEqual(result.total_matched, 1)

    def test_excerpt_within_limit(self):
        kw = validate_keyword("笔记")
        result = search_notes(kw, self.entries, self.provider)
        for h in result.hits:
            self.assertLessEqual(len(h.excerpt), 120 + 2)  # 内部 120 + 最多两个省略号

    def test_max_five_hits(self):
        # 合成 6 条全部命中的 entry，验证 hits 上限为 5，total_matched 仍为 6
        entries = [
            NoteIndexEntry(
                note_id=f"id{i:02d}", title=f"t{i}", relative_path=f"n{i}.md",
                size=0, sha256="x",
            )
            for i in range(6)
        ]

        def provider(_entry):
            return "这是一段包含关键词示例的笔记内容，关键词在此出现。"

        kw = validate_keyword("关键词")
        result = search_notes(kw, entries, provider)
        self.assertEqual(len(result.hits), 5)
        self.assertEqual(result.total_matched, 6)

    def test_excerpt_escapes_html(self):
        entry = NoteIndexEntry(
            note_id="x1", title="t", relative_path="n.md", size=0, sha256="x"
        )

        def provider(_entry):
            return "危险内容 <script> 与 & 符号附近关键词出现"

        kw = validate_keyword("关键词")
        result = search_notes(kw, [entry], provider)
        self.assertIn("&lt;script&gt;", result.hits[0].excerpt)
        self.assertIn("&amp;", result.hits[0].excerpt)


if __name__ == "__main__":
    unittest.main()
