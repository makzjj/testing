@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0\.."

REM E2E automation is not applicable for this desktop Python workspace project.

echo No browser E2E suite is required for this project type.
