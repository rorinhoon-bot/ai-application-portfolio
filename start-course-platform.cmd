@echo off
setlocal
cd /d "%~dp0"
if not exist "projects\02-agent-research-workflow\.venv\Scripts\python.exe" (
  echo P2 Python environment missing. See apps\course-platform\README.md.
  pause
  exit /b 1
)
"projects\02-agent-research-workflow\.venv\Scripts\python.exe" -B "apps\course-platform\server.py" --open-browser
if errorlevel 1 pause
