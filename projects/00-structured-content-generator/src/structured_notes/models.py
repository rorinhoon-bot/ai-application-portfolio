from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

NonEmptyString = Annotated[str, Field(min_length=1)]


class LearnerLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class GenerationInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    topic: str = Field(min_length=1, max_length=100)
    material: str = Field(min_length=100, max_length=10000)
    learner_level: LearnerLevel = LearnerLevel.BEGINNER


class GeneratedExample(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    text: NonEmptyString
    label: Literal["生成示例"]


class KeyConcept(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    name: NonEmptyString
    explanation: NonEmptyString
    example: GeneratedExample | None
    common_mistakes: list[NonEmptyString]


class QuizItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    question: NonEmptyString
    reference_answer: NonEmptyString


class LearningNote(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    title: NonEmptyString
    summary: NonEmptyString
    learning_objectives: list[NonEmptyString]
    key_concepts: list[KeyConcept]
    review_points: list[NonEmptyString]
    quiz: list[QuizItem]
    missing_information: list[NonEmptyString]


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_prompt: NonEmptyString
    user_payload: dict[str, object]
    response_schema: dict[str, object]


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
