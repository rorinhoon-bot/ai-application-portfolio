"""Local Streamlit entry point."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cited_rag.cli import build_local_application  # noqa: E402
from cited_rag.ui import run_ui  # noqa: E402

run_ui(application_factory=build_local_application)
