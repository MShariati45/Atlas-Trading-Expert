@echo off
setlocal
cd /d "%~dp0"
echo ================================================================
echo ATLAS v0.24.22 - OFFICIAL FOUR-CURRENCY NEWS REFRESH
echo ================================================================
echo This makes NO trades and NO AI calls.
echo Sources: BLS/Fed, ECB, Bank of Canada/Statistics Canada, BoJ/Statistics Bureau Japan.
echo.
python run_official_four_currency_news_refresh.py
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" (
  echo.
  echo SUCCESS: runtime\news_events.json created with USD/EUR/CAD/JPY primary-source coverage.
) else (
  echo.
  echo NOT READY: one or more official sources failed validation. Atlas must remain WAIT.
)
echo.
pause
exit /b %RC%
