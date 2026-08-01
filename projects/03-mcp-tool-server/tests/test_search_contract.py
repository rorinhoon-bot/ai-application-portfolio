"""P3 Slice A 离线单测（标准库 unittest，无需安装 pytest）。

覆盖：
- search_notes 参数合同：合法、空白、超长、未知字段、非字符串、URL/命令语义、
  控制字符、绝对路径；非法统一返回稳定 ArgumentError(error_code=invalid-arguments)。
- 检索合同：正常多命中、无命中、note_id 稳定派生、NFKC+casefold（含 Unicode 反例）、
  excerpt<=120（含转义与省略号）、hits 硬上限 5、HTML 转义。
- 标题净化：不可信标题的 HTML 转义与限长。
- 所有用例默认继承 NetworkBlockedTestCase，测试期间阻断网络（P1-6）。
- 夹具来自 evals/fixtures/notes-v1（原创虚构，离线）。
"""

import os
import sys
import unittest

# 让测试可直接 `python -m unittest` 运行，无需 .venv 或安装
_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_SRC))
_TESTS = os.path.dirname(__file__)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from mcp_notes.contracts import (  # noqa: E402
    Keyword,
    NoteIndexEntry,
    INVALID_ARGUMENTS,
    ArgumentError,
    TITLE_MAX,
    EXCERPT_MAX,
    parse_search_notes_args,
    sanitize_title,
    validate_keyword,
)
from mcp_notes.index import build_index, compute_note_id  # noqa: E402
from mcp_notes.search import search_notes  # noqa: E402
from _network_block import NetworkBlockedTestCase  # noqa: E402

_FIXTURES = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "evals", "fixtures", "notes-v1")
)


def _provider_from_root(root):
    from mcp_notes.index import read_note_content

    def _provider(entry):
        return read_note_content(entry, root)

    return _provider


class TestKeywordContract(NetworkBlockedTestCase):
    def test_valid_keyword(self):
        kw = validate_keyword("RAG")
        self.assertIsInstance(kw, Keyword)
        self.assertEqual(kw.value, "RAG")

    def test_strip_whitespace(self):
        kw = validate_keyword("  MCP  ")
        self.assertIsInstance(kw, Keyword)
        self.assertEqual(kw.value, "MCP")

    def test_empty_keyword(self):
        err = validate_keyword("")
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)

    def test_whitespace_only(self):
        err = validate_keyword("   ")
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)

    def test_too_long_81(self):
        err = validate_keyword("a" * 81)
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)

    def test_max_length_80_ok(self):
        self.assertIsInstance(validate_keyword("a" * 80), Keyword)

    def test_control_char(self):
        err = validate_keyword("abc\x00def")
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)

    def test_absolute_path(self):
        err = validate_keyword("C:\\Users\\x")
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)

    def test_dotdot_segment(self):
        err = validate_keyword("..")
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)

    def test_url_scheme(self):
        err = validate_keyword("http://example.com")
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)

    def test_shell_token(self):
        err = validate_keyword("a;b")
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)

    def test_fullwidth_path_bypass_blocked(self):
        # 全角 ／ ＼ ： 经 NFKC 归一后变成 / \ :，必须被路径规则拦截（P1-1）
        err = validate_keyword("Ｃ：＼Ｕｓｅｒｓ＼ｘ")
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)

    def test_fullwidth_url_bypass_blocked(self):
        # 全角 ｈｔｔｐｓ：／／ 经 NFKC 归一后变成 https://，必须被 URL 规则拦截（P1-1）
        err = validate_keyword("ｈｔｔｐｓ：／／ｅｘａｍｐｌｅ．ｃｏｍ")
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)

    def test_fullwidth_shell_bypass_blocked(self):
        # 全角 ｜ ＆ ＜ ＞ 经 NFKC 归一后变成 | & < >，必须被 Shell 规则拦截（P1-1）
        err = validate_keyword("ａ｜ｂ")
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)


class TestParseArgs(NetworkBlockedTestCase):
    def test_valid_args(self):
        kw = parse_search_notes_args({"keyword": "笔记"})
        self.assertIsInstance(kw, Keyword)

    def test_unknown_field(self):
        err = parse_search_notes_args({"keyword": "x", "extra": 1})
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)

    def test_missing_keyword(self):
        err = parse_search_notes_args({})
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)

    def test_keyword_not_string(self):
        err = parse_search_notes_args({"keyword": ["a", "b"]})
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)

    def test_keyword_object(self):
        err = parse_search_notes_args({"keyword": {"a": 1}})
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)

    def test_args_not_dict(self):
        err = parse_search_notes_args("笔记")
        self.assertIsInstance(err, ArgumentError)
        self.assertEqual(err.error_code, INVALID_ARGUMENTS)


class TestSearchBehavior(NetworkBlockedTestCase):
    def setUp(self):
        super().setUp()
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

    def test_casefold_unicode(self):
        # Unicode 反例：关键字用大写无 ß 的 "STRASSE"，正文含德文 ß 的 "Hauptstraße"。
        # lower() 下 "STRASSE"→"strasse" 与 "Hauptstraße"→"hauptstraße" 无法匹配；
        # casefold 把 ß 折叠为 ss，使二者匹配（P1-2）。
        entry = NoteIndexEntry(
            note_id="c1", title="t", relative_path="c.md", size=0, sha256="x"
        )

        def provider(_entry):
            return "街道名称是 Hauptstraße 路口"

        kw = validate_keyword("STRASSE")
        self.assertIsInstance(kw, Keyword)
        result = search_notes(kw, [entry], provider)
        self.assertGreaterEqual(result.total_matched, 1)
        # 摘录基于 casefold 归一文本，ß 已折叠为 ss
        self.assertIn("strasse", result.hits[0].excerpt)

    def test_excerpt_within_limit(self):
        kw = validate_keyword("笔记")
        result = search_notes(kw, self.entries, self.provider)
        for h in result.hits:
            # 转义与省略号均计入总长度，最终必 <= EXCERPT_MAX（P1-3）
            self.assertLessEqual(len(h.excerpt), EXCERPT_MAX)

    def test_max_five_hits(self):
        # 合成 6 条全部命中的 entry，验证 hits 硬上限为 5，total_matched 仍为 6
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
            # 危险字符紧贴关键词上下文，确保落在 ±20 窗口内
            return "危险 <script> & 关键词 内容"

        kw = validate_keyword("关键词")
        result = search_notes(kw, [entry], provider)
        self.assertIn("&lt;script&gt;", result.hits[0].excerpt)
        self.assertIn("&amp;", result.hits[0].excerpt)

    def test_title_sanitized_from_untrusted_note(self):
        # 标题来自不可信笔记：含 HTML 与超长内容，必须转义并限长（P1-4）
        raw_title = "<img src=x onerror=alert(1)>" + "标题" * 40
        safe = sanitize_title(raw_title, TITLE_MAX)
        self.assertIn("&lt;img", safe)
        self.assertNotIn("<img", safe)
        # 限长：含省略号最终长度 <= TITLE_MAX
        self.assertLessEqual(len(safe), TITLE_MAX)
        self.assertTrue(safe.endswith("…"))

    def test_title_plain_short_not_truncated(self):
        safe = sanitize_title("普通标题", TITLE_MAX)
        self.assertEqual(safe, "普通标题")


if __name__ == "__main__":
    unittest.main()
