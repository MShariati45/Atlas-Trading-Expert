@echo off
setlocal
cd /d "%~dp0"
echo ================================================================
echo ATLAS v0.24.12.1 - H4 BLIND HISTORICAL VALIDATION
echo ================================================================
echo READ ONLY. This sends NO orders and does NOT modify shadow state.
echo Teaching answers are NOT used by this runner.
echo.
python run_h4_blind_historical_validation.py
if errorlevel 1 (
  echo.
  echo ERROR: Blind H4 historical validation exited with code %errorlevel%.
  pause
  exit /b %errorlevel%
)
echo.
echo SUCCESS: Blind H4 historical validation set created.
echo Review runtime\h4_blind_historical_summary.csv and runtime\h4_blind_cases\
pause
