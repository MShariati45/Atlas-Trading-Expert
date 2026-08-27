@echo off
setlocal EnableExtensions

rem Atlas v0.22.7 broker-native OOS collection helper.
rem Read-only: this workflow does not send, modify, or close orders.

set "DATASET=historical_data\broker_native_oos"
set "WATCHLIST=config\demo_watchlist.json"
set "ACCOUNT_ID=DEMO"

if not "%~1"=="" set "DATASET=%~1"

echo [1/4] Checking Python...
python --version || goto :fail

echo [2/4] Checking MetaTrader5 Python package...
python -c "import MetaTrader5; print('MetaTrader5 package OK')" || (
  echo MetaTrader5 package is missing. Run: python -m pip install -r requirements-mt5-windows.txt
  goto :fail
)

echo [3/4] Read-only MT5 connectivity probe...
python run_mt5_demo_probe.py --account-id "%ACCOUNT_ID%" --symbol EURUSD --symbol GBPUSD || goto :fail

echo [4/4] Collecting broker-native D1/H4/H1/M15 history for the configured watchlist...
python run_collect_mt5_history.py --watchlist "%WATCHLIST%" --out "%DATASET%" --account-id "%ACCOUNT_ID%" || goto :fail

echo.
echo Collection complete: %DATASET%
echo Next: populate historical_news.csv, then run run_mt5_oos_audit.bat "%DATASET%" historical_news.csv
exit /b 0

:fail
echo.
echo Atlas MT5 collection failed. No orders were sent.
exit /b 2
