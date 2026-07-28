import json
from pathlib import Path

from structured_notes.models import LearningNote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "learning_note.schema.json"


def test_committed_schema_matches_learning_note_model() -> None:
    committed_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert committed_schema == LearningNote.model_json_schema()
