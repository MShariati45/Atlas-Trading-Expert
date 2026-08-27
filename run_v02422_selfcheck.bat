@echo off
setlocal
cd /d "%~dp0"
echo ===============================================================
echo ATLAS v0.24.22 - MULTI-ACCOUNT / DEMO PREP SELF-CHECK
echo NO ORDERS - NO AI CALLS
echo ===============================================================
python run_v02422_selfcheck.py
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo SELF-CHECK FAILED with code %RC%.
if "%RC%"=="0" echo SUCCESS: v0.24.22 offline staging self-check passed.
pause
exit /b %RC%
