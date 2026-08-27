@echo off
setlocal
cd /d "%~dp0"
echo ================================================================
echo ATLAS v0.24.15 - M15 CANDLESTICK S/R INDEPENDENT CHALLENGER
echo READ ONLY - NO ORDERS - SHADOW SUPERVISOR UNTOUCHED
echo ================================================================
python -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 (
  echo ERROR: MetaTrader5 Python package is not available.
  echo Install with: pip install MetaTrader5
  pause
  exit /b 1
)
python run_m15_candlestick_challenger.py
if errorlevel 1 (
  echo.
  echo ERROR: Candlestick challenger failed. Copy the error screen and send it for review.
  pause
  exit /b 1
)
echo.
echo SUCCESS: Candlestick challenger finished.
echo Open runtime\candlestick_sr_independent\REPORT.md or upload the runtime\candlestick_sr_independent folder.
pause
endlocal
