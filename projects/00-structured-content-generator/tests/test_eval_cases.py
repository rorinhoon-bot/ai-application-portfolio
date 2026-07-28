import json
from collections import Counter
from pathlib import Path

from structured_notes.models import GenerationInput

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = PROJECT_ROOT / "evals" / "cases.jsonl"


def load_cases() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_fixed_eval_set_has_required_coverage() -> None:
    cases = load_cases()
    categories = Counter(str(case["category"]) for case in cases)

    assert len(cases) == 10
    assert categories == {
        "normal": 4,
        "insufficient": 2,
        "contradiction": 1,
        "prompt_injection": 1,
        "code_or_command": 1,
        "input_boundary": 1,
    }


def test_fixed_eval_case_ids_are_unique() -> None:
    case_ids = [str(case["id"]) for case in load_cases()]

    assert len(case_ids) == len(set(case_ids))


def test_every_eval_input_passes_generation_input_validation() -> None:
    for case in load_cases():
        GenerationInput.model_validate(case["input"])


def test_every_eval_case_has_review_expectations() -> None:
    for case in load_cases():
        expectations = case["expectations"]

        assert isinstance(expectations, dict)
        assert expectations["must_cover"]
        assert expectations["forbidden_facts"]
        assert expectations["missing_information_behavior"]
        assert isinstance(expectations["allow_generated_example"], bool)


def test_boundary_case_is_close_to_a_length_limit() -> None:
    boundary_case = next(
        case for case in load_cases() if case["category"] == "input_boundary"
    )
    material = boundary_case["input"]["material"]

    assert isinstance(material, str)
    assert 100 <= len(material) <= 150
