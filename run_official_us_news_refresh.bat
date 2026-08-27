@echo off
setlocal
cd /d "%~dp0"
echo ================================================================
echo ATLAS v0.24.22 - OFFICIAL BLS NEWS SOURCE CHECK (USD PARTIAL)
echo ================================================================
echo This makes NO trades and NO AI calls.
echo.
python run_official_us_news_refresh.py
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo FAILED with exit code %RC%.
if "%RC%"=="0" echo SUCCESS: runtime\news_bls_usd.json created (USD coverage only).
echo.
pause
exit /b %RC%
