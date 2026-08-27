@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo ATLAS v0.24.22 - STAGING INTEGRATION READINESS
echo ============================================================
python run_staging_readiness.py
set RC=%ERRORLEVEL%
if not defined ATLAS_NO_PAUSE pause
exit /b %RC%
