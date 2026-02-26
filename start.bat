@echo off
title AI Day Trading System
color 0A
echo.
echo  ============================================
echo   AI Day Trading System - Starting up...
echo  ============================================
echo.

REM Check if venv exists, create it if not
if not exist "venv\Scripts\activate.bat" (
    echo  First time setup - creating virtual environment...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate.bat

REM Install / update dependencies silently
echo  Checking dependencies...
pip install -r requirements.txt -q --disable-pip-version-check

REM Copy .env if it doesn't exist yet
if not exist ".env" (
    copy .env.template .env >nul
    echo  Created .env settings file.
)

echo.
echo  Starting trading engine in background...
start "Trading Engine" /min cmd /k "call venv\Scripts\activate.bat && python main.py"

timeout /t 2 /nobreak >nul

echo  Starting web dashboard...
echo.
echo  Your browser will open automatically.
echo  Dashboard: http://localhost:5001
echo.
echo  Close this window to stop the dashboard.
echo  The trading engine keeps running minimised in the taskbar.
echo.

python web_dashboard.py

pause
