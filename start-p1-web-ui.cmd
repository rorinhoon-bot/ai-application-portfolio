@echo off
setlocal

title P1 Cited Knowledge Base Web UI

set "PROJECT_DIR=%~dp0projects\01-cited-rag"
set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] P1 virtual environment not found:
    echo %PYTHON_EXE%
    echo.
    echo Follow projects\01-cited-rag\README.md to install dependencies.
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"
set "PYTHONPATH=%PROJECT_DIR%\src"

if not exist ".env" (
    echo [NOTICE] projects\01-cited-rag\.env not found.
    echo UI can open, but MODEL_API_KEY is required before asking questions.
    echo.
)

echo Starting P1 Cited Knowledge Base Web UI...
echo Browser will open automatically. Press Ctrl+C to stop.
echo.

"%PYTHON_EXE%" -m streamlit run streamlit_app.py --server.headless false --server.showEmailPrompt false %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Web UI stopped with exit code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
