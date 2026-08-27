@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo ATLAS v0.24.22 - READ-ONLY BROKER SPREAD CALIBRATION
echo ============================================================
echo This sends NO orders. Default duration is 60 minutes.
echo.
python run_mt5_broker_calibration.py %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo SUCCESS: Calibration collection completed.
  echo Summary: runtime\broker_calibration_summary.json
  echo Samples: runtime\broker_spread_samples.csv
) else (
  echo ERROR: Calibration collector exited with code %RC%.
)
if not defined ATLAS_NO_PAUSE pause
exit /b %RC%
