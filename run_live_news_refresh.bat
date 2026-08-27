@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo ATLAS v0.24.22 - LIVE NEWS SCHEDULE REFRESH
echo ============================================================
python run_live_news_refresh.py %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo SUCCESS: Live-news schedule refreshed and validated.
  echo File: runtime\news_events.json
) else (
  echo NOT READY: Configure a trusted/licensed news JSON endpoint.
)
if not defined ATLAS_NO_PAUSE pause
exit /b %RC%
