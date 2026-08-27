@echo off
setlocal
cd /d "%~dp0"
echo ======================================================================
echo ATLAS v0.24.4 - READ-ONLY SHADOW PAPER SUPERVISOR
echo ======================================================================
echo This sends NO orders. MT5 execution remains hard locked.
echo.
python run_shadow_paper_supervisor.py
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo ERROR: Shadow Paper Supervisor exited with code %RC%.
if "%RC%"=="0" echo Shadow Paper Supervisor stopped normally.
echo State: runtime\atlas_shadow_supervisor_state.json
echo Journal: runtime\atlas_shadow_supervisor_journal.jsonl
pause
exit /b %RC%
