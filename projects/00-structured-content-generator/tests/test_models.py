import pytest
from pydantic import ValidationError

from structured_notes.models import (
    GeneratedExample,
    GenerationInput,
    KeyConcept,
    LearningNote,
    LearnerLevel,
    QuizItem,
)


def test_generation_input_accepts_valid_data() -> None:
    item = GenerationInput(
        topic="Transformer",
        material="a" * 100,
        learner_level="intermediate",
    )

    assert item.topic == "Transformer"
    assert len(item.material) == 100
    assert item.learner_level is LearnerLevel.INTERMEDIATE


def test_generation_input_uses_beginner_by_default() -> None:
    item = GenerationInput(
        topic="Transformer",
        material="a" * 100,
    )

    assert item.learner_level is LearnerLevel.BEGINNER


def test_generation_input_rejects_missing_topic() -> None:
    with pytest.raises(ValidationError) as exc_info:
        GenerationInput(
            material="a" * 100,
        )

    errors = exc_info.value.errors()

    assert errors[0]["loc"] == ("topic",)
    assert errors[0]["type"] == "missing"


def test_generation_input_rejects_topic_over_max_length() -> None:
    with pytest.raises(ValidationError) as exc_info:
        GenerationInput(
            topic="a" * 101,
            material="b" * 100,
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("topic",)
    assert error["type"] == "string_too_long"


def test_generation_input_rejects_material_under_min_length() -> None:
    with pytest.raises(ValidationError) as exc_info:
        GenerationInput(
            topic="Transformer",
            material="a" * 99,
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("material",)
    assert error["type"] == "string_too_short"


def test_generation_input_rejects_invalid_learner_level() -> None:
    with pytest.raises(ValidationError) as exc_info:
        GenerationInput(
            topic="Transformer",
            material="a" * 100,
            learner_level="expert",
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("learner_level",)
    assert error["type"] == "enum"


def test_generation_input_rejects_extra_field() -> None:
    with pytest.raises(ValidationError) as exc_info:
        GenerationInput.model_validate(
            {
                "topic": "Transformer",
                "material": "a" * 100,
                "unexpected": "value",
            }
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("unexpected",)
    assert error["type"] == "extra_forbidden"


def test_generation_input_strips_surrounding_whitespace() -> None:
    item = GenerationInput(
        topic="  Transformer  ",
        material=f"  {'a' * 100}  ",
    )

    assert item.topic == "Transformer"
    assert item.material == "a" * 100


def test_generation_input_rejects_whitespace_only_topic() -> None:
    with pytest.raises(ValidationError) as exc_info:
        GenerationInput(
            topic="   ",
            material="a" * 100,
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("topic",)
    assert error["type"] == "string_too_short"


def test_generation_input_rejects_material_over_max_length() -> None:
    with pytest.raises(ValidationError) as exc_info:
        GenerationInput(
            topic="Transformer",
            material="a" * 10001,
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("material",)
    assert error["type"] == "string_too_long"


def test_generated_example_accepts_valid_data_and_strips_whitespace() -> None:
    example = GeneratedExample(
        text="  注意力机制会关注相关信息。  ",
        label="生成示例",
    )

    assert example.text == "注意力机制会关注相关信息。"
    assert example.label == "生成示例"


def test_generated_example_requires_label() -> None:
    with pytest.raises(ValidationError) as exc_info:
        GeneratedExample.model_validate(
            {
                "text": "注意力机制会关注相关信息。",
            }
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("label",)
    assert error["type"] == "missing"


def test_generated_example_rejects_wrong_label() -> None:
    with pytest.raises(ValidationError) as exc_info:
        GeneratedExample(
            text="注意力机制会关注相关信息。",
            label="普通示例",
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("label",)
    assert error["type"] == "literal_error"


def test_generated_example_rejects_whitespace_only_text() -> None:
    with pytest.raises(ValidationError) as exc_info:
        GeneratedExample(
            text="   ",
            label="生成示例",
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("text",)
    assert error["type"] == "string_too_short"


def test_generated_example_rejects_extra_field() -> None:
    with pytest.raises(ValidationError) as exc_info:
        GeneratedExample.model_validate(
            {
                "text": "注意力机制会关注相关信息。",
                "label": "生成示例",
                "source": "external",
            }
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("source",)
    assert error["type"] == "extra_forbidden"


def test_key_concept_accepts_nested_generated_example() -> None:
    concept = KeyConcept(
        name="  注意力机制  ",
        explanation="  根据相关程度关注输入信息。  ",
        example={
            "text": "  阅读时重点关注与问题相关的句子。  ",
            "label": "生成示例",
        },
        common_mistakes=["  把注意力理解为固定权重。  "],
    )

    assert concept.name == "注意力机制"
    assert concept.explanation == "根据相关程度关注输入信息。"
    assert concept.example is not None
    assert concept.example.text == "阅读时重点关注与问题相关的句子。"
    assert concept.common_mistakes == ["把注意力理解为固定权重。"]


def test_key_concept_accepts_null_example_and_empty_mistakes() -> None:
    concept = KeyConcept(
        name="注意力机制",
        explanation="根据相关程度关注输入信息。",
        example=None,
        common_mistakes=[],
    )

    assert concept.example is None
    assert concept.common_mistakes == []


def test_key_concept_requires_example_field() -> None:
    with pytest.raises(ValidationError) as exc_info:
        KeyConcept.model_validate(
            {
                "name": "注意力机制",
                "explanation": "根据相关程度关注输入信息。",
                "common_mistakes": [],
            }
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("example",)
    assert error["type"] == "missing"


@pytest.mark.parametrize("field_name", ["name", "explanation"])
def test_key_concept_rejects_blank_required_text(field_name: str) -> None:
    data = {
        "name": "注意力机制",
        "explanation": "根据相关程度关注输入信息。",
        "example": None,
        "common_mistakes": [],
    }
    data[field_name] = "   "

    with pytest.raises(ValidationError) as exc_info:
        KeyConcept.model_validate(data)

    error = exc_info.value.errors()[0]

    assert error["loc"] == (field_name,)
    assert error["type"] == "string_too_short"


def test_key_concept_rejects_blank_common_mistake() -> None:
    with pytest.raises(ValidationError) as exc_info:
        KeyConcept(
            name="注意力机制",
            explanation="根据相关程度关注输入信息。",
            example=None,
            common_mistakes=["   "],
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("common_mistakes", 0)
    assert error["type"] == "string_too_short"


def test_key_concept_rejects_invalid_nested_example() -> None:
    with pytest.raises(ValidationError) as exc_info:
        KeyConcept(
            name="注意力机制",
            explanation="根据相关程度关注输入信息。",
            example={
                "text": "阅读时重点关注相关句子。",
                "label": "普通示例",
            },
            common_mistakes=[],
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("example", "label")
    assert error["type"] == "literal_error"


def test_key_concept_rejects_extra_field() -> None:
    with pytest.raises(ValidationError) as exc_info:
        KeyConcept.model_validate(
            {
                "name": "注意力机制",
                "explanation": "根据相关程度关注输入信息。",
                "example": None,
                "common_mistakes": [],
                "source": "external",
            }
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("source",)
    assert error["type"] == "extra_forbidden"


def test_quiz_item_accepts_valid_data_and_strips_whitespace() -> None:
    item = QuizItem(
        question="  注意力机制有什么作用？  ",
        reference_answer="  它根据相关程度关注输入信息。  ",
    )

    assert item.question == "注意力机制有什么作用？"
    assert item.reference_answer == "它根据相关程度关注输入信息。"


@pytest.mark.parametrize("field_name", ["question", "reference_answer"])
def test_quiz_item_rejects_blank_required_text(field_name: str) -> None:
    data = {
        "question": "注意力机制有什么作用？",
        "reference_answer": "它根据相关程度关注输入信息。",
    }
    data[field_name] = "   "

    with pytest.raises(ValidationError) as exc_info:
        QuizItem.model_validate(data)

    error = exc_info.value.errors()[0]

    assert error["loc"] == (field_name,)
    assert error["type"] == "string_too_short"


def test_quiz_item_rejects_extra_field() -> None:
    with pytest.raises(ValidationError) as exc_info:
        QuizItem.model_validate(
            {
                "question": "注意力机制有什么作用？",
                "reference_answer": "它根据相关程度关注输入信息。",
                "difficulty": "easy",
            }
        )

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("difficulty",)
    assert error["type"] == "extra_forbidden"


def valid_learning_note_data() -> dict[str, object]:
    return {
        "title": "Transformer 基础",
        "summary": "Transformer 使用注意力机制处理序列。",
        "learning_objectives": ["理解注意力机制"],
        "key_concepts": [
            {
                "name": "注意力机制",
                "explanation": "根据相关程度关注输入信息。",
                "example": {
                    "text": "阅读时重点关注相关句子。",
                    "label": "生成示例",
                },
                "common_mistakes": ["把注意力理解为固定权重。"],
            }
        ],
        "review_points": ["注意力权重取决于输入。"],
        "quiz": [
            {
                "question": "注意力机制有什么作用？",
                "reference_answer": "根据相关程度关注输入信息。",
            }
        ],
        "missing_information": [],
    }


def test_learning_note_accepts_complete_nested_output() -> None:
    note = LearningNote.model_validate(valid_learning_note_data())

    assert note.title == "Transformer 基础"
    assert note.key_concepts[0].example is not None
    assert note.key_concepts[0].example.label == "生成示例"
    assert note.quiz[0].question == "注意力机制有什么作用？"
    assert note.missing_information == []


def test_learning_note_requires_every_top_level_field() -> None:
    with pytest.raises(ValidationError) as exc_info:
        LearningNote.model_validate({})

    missing_locations = {error["loc"] for error in exc_info.value.errors()}

    assert missing_locations == {
        ("title",),
        ("summary",),
        ("learning_objectives",),
        ("key_concepts",),
        ("review_points",),
        ("quiz",),
        ("missing_information",),
    }


def test_learning_note_rejects_invalid_nested_quiz_item() -> None:
    data = valid_learning_note_data()
    data["quiz"] = [
        {
            "question": "   ",
            "reference_answer": "根据相关程度关注输入信息。",
        }
    ]

    with pytest.raises(ValidationError) as exc_info:
        LearningNote.model_validate(data)

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("quiz", 0, "question")
    assert error["type"] == "string_too_short"


def test_learning_note_rejects_blank_list_item() -> None:
    data = valid_learning_note_data()
    data["review_points"] = ["   "]

    with pytest.raises(ValidationError) as exc_info:
        LearningNote.model_validate(data)

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("review_points", 0)
    assert error["type"] == "string_too_short"


def test_learning_note_rejects_extra_field() -> None:
    data = valid_learning_note_data()
    data["sources"] = []

    with pytest.raises(ValidationError) as exc_info:
        LearningNote.model_validate(data)

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("sources",)
    assert error["type"] == "extra_forbidden"
