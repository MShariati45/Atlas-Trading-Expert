@echo off
setlocal
cd /d "%~dp0"
echo ================================================================
echo ATLAS v0.24.23 - READ-ONLY BROKER CALIBRATION AUDIT
echo ================================================================
python run_broker_calibration_audit.py
set RC=%ERRORLEVEL%
echo.
if %RC%==0 (echo PASS: spread calibration evidence is compatible with the current paper policy.) else (echo NOT READY: review runtime\broker_calibration_audit.json. No limits were changed.)
pause
exit /b %RC%
