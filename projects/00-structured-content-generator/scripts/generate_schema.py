import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "learning_note.schema.json"

sys.path.insert(0, str(SRC_ROOT))

from structured_notes.models import LearningNote  # noqa: E402


def main() -> None:
    schema = LearningNote.model_json_schema()
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
