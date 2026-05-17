@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0\.."

REM Run the BioBot desktop application.
REM Requires the local .venv to exist with project dependencies installed.

set "PYTHON_EXE=%~dp0\..\.venv\Scripts\python.exe"
call "%PYTHON_EXE%" main.py
