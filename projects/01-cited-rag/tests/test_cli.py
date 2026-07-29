from io import StringIO
import json
from uuid import UUID

from cited_rag.cli import main
from cited_rag.errors import RetrievalInputError
from cited_rag.models import AnswerResult


class FakeApplication:
    def __init__(self, result: AnswerResult) -> None:
        self.result = result
        self.calls = []

    def answer(self, *, question, python_version=None) -> AnswerResult:
        self.calls.append((question, python_version))
        return self.result


def refused_result(question: str) -> AnswerResult:
    return AnswerResult(
        question=question,
        status="refused",
        answer="当前知识库没有足够证据支持该问题。",
        citations=(),
        index_id=UUID("614f6c23-7c35-5832-8086-c29651d60866"),
        build_id=UUID("4facb454-cca4-476f-b623-fa29b40fcf00"),
    )


def test_cli_writes_validated_json_and_passes_version() -> None:
    output = StringIO()
    errors = StringIO()
    application = FakeApplication(refused_result("问题"))

    exit_code = main(
        [
            "ask",
            "--question",
            "问题",
            "--python-version",
            "3.14",
        ],
        application_factory=lambda: application,
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 0
    assert errors.getvalue() == ""
    assert application.calls == [("问题", "3.14")]
    assert json.loads(output.getvalue())["status"] == "refused"


def test_cli_returns_stable_domain_error_without_secret() -> None:
    class FailingApplication:
        def answer(self, *, question, python_version=None):
            raise RetrievalInputError("retrieval query is invalid")

    output = StringIO()
    errors = StringIO()

    exit_code = main(
        ["ask", "--question", "bad question"],
        application_factory=FailingApplication,
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 1
    assert output.getvalue() == ""
    assert json.loads(errors.getvalue()) == {
        "error": {
            "code": "RETRIEVAL_INPUT_ERROR",
            "reason": "retrieval query is invalid",
        }
    }


def test_cli_hides_unexpected_exception_details() -> None:
    class FailingApplication:
        def answer(self, *, question, python_version=None):
            raise RuntimeError("MODEL_API_KEY=must-not-leak")

    errors = StringIO()

    exit_code = main(
        ["ask", "--question", "问题"],
        application_factory=FailingApplication,
        stdout=StringIO(),
        stderr=errors,
    )

    assert exit_code == 1
    assert "must-not-leak" not in errors.getvalue()
    assert json.loads(errors.getvalue())["error"]["code"] == (
        "INTERNAL_ERROR"
    )
