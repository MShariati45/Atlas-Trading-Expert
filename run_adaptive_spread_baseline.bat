@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo ATLAS v0.24.24 - ADAPTIVE SPREAD BASELINE BUILD
echo READ ONLY - NO ORDERS - ZERO AI CALLS
echo ============================================================
python run_adaptive_spread_baseline.py
set RC=%ERRORLEVEL%
echo.
if %RC% EQU 0 (
  echo SUCCESS - adaptive spread baseline updated from observed broker samples.
) else (
  echo FAILED - review broker spread sample data.
)
pause
exit /b %RC%
