"""Fixed evaluation from real pytest JUnit outcomes; no source-inspection pseudo-tests."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from common import HERE, P2, clean_env, digest, write_once


def evaluate():
    frozen = json.loads((HERE / "fixtures/evaluation-cases.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="graduation-eval-") as temporary:
        xml = Path(temporary) / "results.xml"
        process = subprocess.run([str(P2 / ".venv/Scripts/python.exe"), "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                  str(HERE / "tests"), "--junitxml", str(xml)], cwd=HERE,
                                 env=clean_env(P2), capture_output=True, timeout=300)
        if not xml.exists():
            raise RuntimeError("EVALUATION_DID_NOT_COMPLETE")
        tests = list(ET.parse(xml).getroot().iter("testcase"))
        outcomes = [{"name": t.attrib["name"],
                     "passed": not any(t.find(tag) is not None for tag in ("failure", "error", "skipped")),
                     "skipped": t.find("skipped") is not None} for t in tests]
        groups = {}
        for category, names in frozen["categories"].items():
            cases = [outcome for outcome in outcomes if outcome["name"].split("[")[0] in names]
            if {o["name"].split("[")[0] for o in cases} != set(names):
                raise RuntimeError("EVALUATION_CASE_MISSING")
            groups[category] = {"passed": sum(c["passed"] for c in cases), "total": len(cases)}
        passed = sum(o["passed"] for o in outcomes)
        result = {"schema_version": "graduation-evaluation-v1", "cases_sha256": digest(frozen),
                  "groups": groups, "passed": passed, "total": len(outcomes),
                  "skipped": sum(o["skipped"] for o in outcomes), "exit_code": process.returncode,
                  "cases": outcomes, "content_quality": frozen["content_quality"],
                  "real_model_calls": 0, "cost_minor_units": 0}
        result["test_duration_seconds"] = round(sum(float(t.attrib.get("time", "0")) for t in tests), 3)
        result["accepted"] = process.returncode == 0 and passed == frozen["expected_total"] == len(outcomes)
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate()
    write_once(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["accepted"] else 1)
