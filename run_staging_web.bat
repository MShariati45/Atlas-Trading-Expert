@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo ATLAS v0.24.22 - LOCAL STAGING WEB
echo DEMO/STAGING ONLY - EXECUTION LOCKED
echo ============================================================
python run_staging_web.py --host 127.0.0.1 --port 8080
if not defined ATLAS_NO_PAUSE pause
