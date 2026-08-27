@echo off
setlocal
set "TARGET=C:\Atlas\Atlas_v0.24.32_TLS_Deployment_Boundary"
if not exist "%TARGET%\run_secure_staging_web.py" (
  echo ERROR: Atlas v0.24.32 deployment not found at %TARGET%
  exit /b 2
)
set "BACKUP=C:\Atlas\Backup_Pre_v0.24.33_Dashboard"
if not exist "%BACKUP%" mkdir "%BACKUP%"
copy /Y "%TARGET%\atlas\api\app_service.py" "%BACKUP%\app_service.py" >nul
copy /Y "%TARGET%\atlas\api\read_models.py" "%BACKUP%\read_models.py" >nul
copy /Y "%TARGET%\web\public\app\app.js" "%BACKUP%\app.js" >nul
copy /Y "%TARGET%\web\public\app\app.css" "%BACKUP%\app.css" >nul
copy /Y "%~dp0run_dashboard_activation.py" "%TARGET%\run_dashboard_activation.py" >nul
copy /Y "%~dp0start_dashboard_activation.bat" "%TARGET%\start_dashboard_activation.bat" >nul
copy /Y "%~dp0atlas\api\app_service.py" "%TARGET%\atlas\api\app_service.py" >nul
copy /Y "%~dp0atlas\api\read_models.py" "%TARGET%\atlas\api\read_models.py" >nul
copy /Y "%~dp0web\public\app\app.js" "%TARGET%\web\public\app\app.js" >nul
copy /Y "%~dp0web\public\app\app.css" "%TARGET%\web\public\app\app.css" >nul
copy /Y "%~dp0DASHBOARD_ACTIVATION_RUNBOOK_v0.24.33.md" "%TARGET%\DASHBOARD_ACTIVATION_RUNBOOK_v0.24.33.md" >nul
copy /Y "%~dp0TECHNICAL_HANDOFF_v0.24.33.md" "%TARGET%\TECHNICAL_HANDOFF_v0.24.33.md" >nul
copy /Y "%~dp0VERSION" "%TARGET%\VERSION" >nul
if not exist "%TARGET%\runtime\dashboard_state.json" copy /Y "%~dp0dashboard_state_waiting_template_v0.24.33.json" "%TARGET%\runtime\dashboard_state.json" >nul
echo Atlas v0.24.33 Dashboard Activation patch installed.
echo Auth DB, leads, execution ledger and MT5 credentials were NOT modified.
echo Next: cd /d "%TARGET%" ^&^& start_dashboard_activation.bat
endlocal
