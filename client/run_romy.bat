@echo off
setlocal
cd /d "%~dp0"
:: Use the embedded python.exe to run the application
start "" "python\pythonw.exe" "app\main.py"
