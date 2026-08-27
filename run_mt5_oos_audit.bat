@echo off
setlocal EnableExtensions

set "DATASET=historical_data\broker_native_oos"
set "NEWS=historical_news.csv"
set "OUT=oos_audit.json"

if not "%~1"=="" set "DATASET=%~1"
if not "%~2"=="" set "NEWS=%~2"
if not "%~3"=="" set "OUT=%~3"

echo Auditing dataset hashes, rows, timestamps, required timeframes, and historical news...
python run_audit_mt5_oos_dataset.py --dataset "%DATASET%" --historical-news "%NEWS%" --out "%OUT%"
if errorlevel 1 goto :fail

echo.
echo Audit complete: %OUT%
echo Inspect replay_permission in the audit output. It must be true before calling the study fully gated.
exit /b 0

:fail
echo.
echo Audit failed. Do not use this dataset for Atlas OOS conclusions.
exit /b 2
