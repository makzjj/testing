@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0\.."

REM Run the repository unit tests.
REM Requires the local .venv to exist with project dependencies installed.

set "PYTHON_EXE=%~dp0\..\.venv\Scripts\python.exe"
set "QT_QPA_PLATFORM=offscreen"

echo Running unit tests...
call "%PYTHON_EXE%" -m unittest discover -s tests -p "test_*.py"
if %errorlevel% neq 0 (
    echo Tests FAILED.
    exit /b 1
)

echo Tests completed.
