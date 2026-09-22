"""Read-only readiness probe; never install dependencies or load .env files."""
import json
import os
import subprocess

from domain import REPO


def main():
    packages = {"01-cited-rag": ["pydantic"],
                "02-agent-research-workflow": ["pydantic", "langgraph", "langgraph-checkpoint-sqlite"],
                "03-mcp-tool-server": ["mcp", "pydantic"]}
    results = []
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH") if k in os.environ}
    env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    for project, names in packages.items():
        python = REPO / "projects" / project / ".venv/Scripts/python.exe"
        if not python.is_file():
            results.append({"project": project, "ready": False, "error": "INTERPRETER_MISSING"})
            continue
        code = "import json,sys; from importlib.metadata import version; print(json.dumps({'python':sys.version.split()[0],'packages':{n:version(n) for n in " + repr(names) + "}}))"
        try:
            result = subprocess.run([str(python), "-I", "-B", "-c", code], env=env, capture_output=True, timeout=20)
            if result.returncode:
                raise ValueError()
            results.append({"project": project, "ready": True, **json.loads(result.stdout)})
        except (OSError, ValueError, subprocess.TimeoutExpired):
            results.append({"project": project, "ready": False, "error": "DEPENDENCY_PROBE_FAILED"})
    ready = all(r["ready"] for r in results)
    print(json.dumps({"schema_version": "course-environment-v1", "ready": ready, "results": results,
                      "installs": 0, "real_model_calls": 0}, ensure_ascii=False, indent=2))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
