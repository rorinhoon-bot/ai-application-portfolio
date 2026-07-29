from pathlib import Path

from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SUCCESS_SCRIPT = """
from uuid import UUID

from cited_rag.models import AnswerCitation, AnswerResult
from cited_rag.ui import run_ui


class FakeApplication:
    def answer(self, *, question, python_version=None):
        excerpt = "ensure_ascii=False 可直接输出非 ASCII 字符。"
        citation = AnswerCitation(
            rank=1,
            chunk_id=UUID("00000000-0000-0000-0000-000000000314"),
            python_version="3.14",
            documentation_release="3.14.6",
            section_path=("json --- JSON 编码器和解码器", "基本用法"),
            citation_url=(
                "https://docs.python.org/zh-cn/3.14/"
                "library/json.html#basic-usage"
            ),
            excerpt=excerpt,
        )
        return AnswerResult(
            question=question,
            status="answered",
            answer="设置 `ensure_ascii=False`。",
            citations=(citation,),
            index_id=UUID(
                "614f6c23-7c35-5832-8086-c29651d60866"
            ),
            build_id=UUID(
                "4facb454-cca4-476f-b623-fa29b40fcf00"
            ),
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
        )


run_ui(application_factory=FakeApplication)
"""

ERROR_SCRIPT = """
from cited_rag.errors import ModelNetworkError
from cited_rag.ui import run_ui


class FakeApplication:
    def answer(self, *, question, python_version=None):
        raise ModelNetworkError("secret supplier detail")


run_ui(application_factory=FakeApplication)
"""


def _submit(script: str) -> AppTest:
    app = AppTest.from_string(script, default_timeout=10).run()
    app.text_area(key="question_input").set_value(
        "怎样输出中文 JSON？"
    )
    app.radio(key="version_scope").set_value("Python 3.14")
    return app.button(key="submit_question").click().run()


def test_production_page_loads_without_building_rag_runtime() -> None:
    app = AppTest.from_file(
        PROJECT_ROOT / "streamlit_app.py",
        default_timeout=10,
    ).run()

    assert not app.exception
    assert app.title == []
    assert app.text_area(key="question_input").max_chars == 500
    assert app.button(key="submit_question").label == (
        "检索并生成带引用回答"
    )


def test_successful_answer_renders_citation_and_trace() -> None:
    app = _submit(SUCCESS_SCRIPT)

    assert not app.exception
    assert any(
        "设置 `ensure_ascii=False`" in item.value
        for item in app.markdown
    )
    assert any(
        "ensure_ascii=False 可直接输出" in item.value
        for item in app.code
    )
    assert any(item.value == "120" for item in app.metric)


def test_network_error_is_safe_and_actionable() -> None:
    app = _submit(ERROR_SCRIPT)

    assert not app.exception
    assert any("无法连接生成模型" in item.value for item in app.error)
    assert all(
        "secret supplier detail" not in item.value
        for item in (*app.error, *app.caption)
    )
    assert any(
        "MODEL_NETWORK_ERROR" in item.value for item in app.caption
    )
