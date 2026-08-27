@echo off
setlocal
cd /d %~dp0
python run_collect_mt5_history.py
if errorlevel 1 (
  echo.
  echo Atlas historical collection failed. Make sure MetaTrader 5 is open and logged in to the demo account.
  pause
  exit /b 1
)
echo.
echo Historical collection completed.
python run_audit_historical_dataset.py historical_data/one_year
echo.
pause
