"""Run the fixed behavioral suite and record exact results; no external service."""
import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import time
import unittest

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(str(HERE / "tests"))
    stream = io.StringIO()
    start = time.monotonic()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    output = {"schema_version": "course-platform-evaluation-v1", "at": datetime.now(timezone.utc).isoformat(),
              "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "skipped": len(result.skipped), "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
              "accepted": result.wasSuccessful() and not result.skipped, "seconds": round(time.monotonic() - start, 3),
              "real_model_calls": 0, "new_dependencies": 0, "content_quality": "not_accepted",
              "scope": "application unit, loopback HTTP, real offline P1/P2/P3 E2E; not original full regressions",
              "command": "P2 .venv python -B apps/course-platform/evaluate.py --output " + args.output.as_posix()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(stream.getvalue())
    print(json.dumps(output))
    return 0 if output["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
