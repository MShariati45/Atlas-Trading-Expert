@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo ATLAS v0.24.19 - READ-ONLY MT5 DEMO PREFLIGHT
echo ============================================================
echo.
python --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python is not available on PATH.
  exit /b 10
)
python -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 (
  echo ERROR: MetaTrader5 Python package is missing.
  echo Install requirements with: pip install -r requirements-mt5-windows.txt
  exit /b 11
)
python run_pre_demo_selfcheck.py
if errorlevel 1 (
  echo ERROR: Atlas offline self-check failed. Do not continue.
  exit /b 12
)
echo.
echo Running read-only MT5 terminal/account/symbol/data preflight...
python run_mt5_demo_probe.py --news-json runtime/news_events.json --cost-policy config/broker_cost_policy.json %*
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (
  echo SUCCESS: Atlas is ready for READ-ONLY DEMO OBSERVATION.
  echo Report: runtime\demo_preflight_report.json
) else (
  echo NOT READY: Review the JSON report and correct the listed issues.
)
if not defined ATLAS_NO_PAUSE pause
exit /b %RC%
