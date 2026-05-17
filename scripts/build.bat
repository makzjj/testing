@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0\.."

REM Build check for the current Python desktop workspace application.
REM Requires the local .venv to exist with project dependencies installed.

set "PYTHON_EXE=%~dp0\..\.venv\Scripts\python.exe"

echo Running Python compile checks...
call "%PYTHON_EXE%" -m compileall main.py gui myconfig tests
if %errorlevel% neq 0 (
    echo Build check FAILED.
    exit /b 1
)

echo Build check completed.
