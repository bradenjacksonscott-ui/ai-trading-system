@echo off
title Backtest - AI Trading System
color 0B
echo.
echo  ============================================
echo   Backtest Engine - AI Trading System
echo  ============================================
echo.

call venv\Scripts\activate.bat 2>nul
if errorlevel 1 (
    echo  ERROR: Please run start.bat first to set up the system.
    pause
    exit
)

echo  How many days of history to test?
echo  (Press Enter for default: 90 days)
echo.
set /p DAYS="  Days [90]: "
if "%DAYS%"=="" set DAYS=90

echo.
echo  Test a specific symbol or all symbols?
echo  (Press Enter to test all symbols)
echo.
set /p SYM="  Symbol (or blank for all): "

echo.
echo  Running backtest...
echo.

if "%SYM%"=="" (
    python backtest.py --days %DAYS%
) else (
    python backtest.py --days %DAYS% --symbol %SYM%
)

echo.
echo  Done! Results saved to the trades\ folder.
echo  Open trades\backtest_results_*.csv in Excel to see full details.
echo.
pause
