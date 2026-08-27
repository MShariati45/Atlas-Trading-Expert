@echo off
setlocal
cd /d "%~dp0"
python run_v02425_selfcheck.py
set RC=%ERRORLEVEL%
echo.
if %RC% EQU 0 (echo Atlas v0.24.25 self-check complete.) else (echo Atlas v0.24.25 self-check FAILED with code %RC%.)
pause
exit /b %RC%
