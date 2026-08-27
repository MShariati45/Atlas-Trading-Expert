@echo off
setlocal
cd /d "%~dp0"
echo ATLAS v0.24.26 - DEMO TRANSPORT OFFLINE SELFCHECK
echo -------------------------------------------------
python run_demo_transport_selfcheck.py
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" (
  echo RESULT: FAILED
  exit /b %RC%
)
echo RESULT: PASS - no real orders were sent.
endlocal
