@echo off
setlocal
cd /d "%~dp0"

:: Check if Python is installed
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Python is not installed or not added to your PATH.
    echo Please install Python from python.org and check "Add Python to PATH".
    pause
    exit /b 1
)

:: Install dependencies
echo Installing required dependencies...
IF EXIST app\requirements.txt (
    python -m pip install -r app\requirements.txt
) ELSE (
    python -m pip install -r requirements.txt
)
IF %ERRORLEVEL% NEQ 0 (
    echo Failed to install dependencies. Please check your internet connection or permissions.
    pause
    exit /b 1
)

:: Run the application silently
echo Starting ROMY Agent...
IF EXIST app\main.py (
    start "" pythonw app\main.py
) ELSE (
    start "" pythonw main.py
)
