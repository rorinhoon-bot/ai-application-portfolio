"""Strict wire contracts. No client-controlled filesystem or approval fields."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mcp_notes.contracts import Keyword, validate_keyword, validate_task_field

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
NoteId = Annotated[str, Field(pattern=r"^[a-f0-9]{16}$")]
CallId = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
ErrorCode = Literal[
    "invalid-arguments", "unknown-tool", "permission-denied", "not-registered",
    "snapshot-invalid", "index-build-failed", "content-too-large", "io-error",
    "tool-timeout", "audit-unavailable", "output-invalid", "internal-error",
    "confirmation-required", "confirmation-identity-mismatch", "confirmation-mismatch",
    "confirmation-expired", "confirmation-already-consumed", "confirmation-invalid-id",
    "idempotency-conflict", "task-conflict", "task-write-failed", "task-invalid-id",
    "task-root-unsafe",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SearchArgs(StrictModel):
    keyword: Annotated[str, Field(min_length=1, max_length=80)]

    @field_validator("keyword")
    @classmethod
    def safe_keyword(cls, value):
        result = validate_keyword(value)
        if not isinstance(result, Keyword):
            raise ValueError("invalid-arguments")
        return result.value


class ReadArgs(StrictModel):
    note_id: NoteId


class CreateArgs(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("title", "description")
    @classmethod
    def safe_field(cls, value, info):
        result = validate_task_field(value, 1, 120 if info.field_name == "title" else 1000)
        if result is None:
            raise ValueError("invalid-arguments")
        return result


class Hit(StrictModel):
    note_id: NoteId
    title: Annotated[str, Field(max_length=80)]
    excerpt: Annotated[str, Field(max_length=120)]
    match_count: Annotated[int, Field(ge=1)]
    content_sha256: Digest


class Document(StrictModel):
    note_id: NoteId
    title: Annotated[str, Field(max_length=80)]
    text: Annotated[str, Field(max_length=8192)]
    content_sha256: Digest
    untrusted: Literal[True] = True

    @model_validator(mode="after")
    def correct_digest(self):
        import hashlib
        if (len(self.text.encode("utf-8")) > 8192 or
                hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.content_sha256):
            raise ValueError("snapshot-invalid")
        return self


class Intent(StrictModel):
    task_id: Annotated[str, Field(pattern=r"^task-[a-f0-9]{16}$")]
    confirmation_id: Annotated[str, Field(pattern=r"^conf-[a-f0-9]{16}$")]


class Result(StrictModel):
    schema_version: Literal["p3-tool-v2"] = "p3-tool-v2"
    call_id: CallId
    snapshot_hash: Digest
    status: Literal["ok", "error", "pending", "unchanged"]
    error_code: ErrorCode | None = None
    hits: Annotated[list[Hit], Field(max_length=5)] = Field(default_factory=list)
    total_matched: Annotated[int, Field(ge=0, le=64)] = 0
    document: Document | None = None
    intent: Intent | None = None

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "error") != (self.error_code is not None):
            raise ValueError("output-invalid")
        if self.status == "error" and (self.hits or self.total_matched or self.document or self.intent):
            raise ValueError("output-invalid")
        if len(self.hits) > self.total_matched:
            raise ValueError("output-invalid")
        if (self.status in ("pending", "unchanged")) != (self.intent is not None):
            raise ValueError("output-invalid")
        if self.document is not None and (self.hits or self.total_matched or self.intent):
            raise ValueError("output-invalid")
        return self


INPUT_MODELS = {"search_notes": SearchArgs, "read_note": ReadArgs, "create_task": CreateArgs}


class ToolFailure(Exception):
    def __init__(self, code: ErrorCode):
        self.code = code
        super().__init__(code)
