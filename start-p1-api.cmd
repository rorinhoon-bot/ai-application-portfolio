@echo off
setlocal

title P1 Cited RAG API

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
    echo /healthz will work; /readyz and answers may return 503.
    echo.
)

echo Starting P1 Cited RAG API on http://127.0.0.1:8000 ...
echo Local OpenAPI: http://127.0.0.1:8000/docs
echo Press Ctrl+C to stop.
echo.

"%PYTHON_EXE%" -m uvicorn cited_rag.api:app --host 127.0.0.1 --port 8000
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] API stopped with exit code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
