@echo off
echo ===================================================
echo   ROMY Monorepo - One-Click Dev Environment
echo ===================================================
echo.
echo This script will set up Python virtual environments,
echo install dependencies, and launch:
echo   - Backend (FastAPI)   : http://127.0.0.1:8000
echo   - Client Agent (App)  : Background Process
echo   - Dashboard (Flutter) : http://127.0.0.1:3000
echo.

:: Check for python
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not installed or not added to PATH.
    echo Please install Python 3.10+ from python.org and check "Add python.exe to PATH".
    pause
    exit /b 1
)

:: Check for flutter
flutter --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Flutter is not installed or not added to PATH.
    echo The Dashboard will fail to start, but Backend and Client will proceed.
)

echo Starting dev_runner.py...
python dev_runner.py
pause
