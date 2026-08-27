@echo off
setlocal EnableExtensions

set "DATASET=historical_data\broker_native_oos"
set "NEWS=historical_news.csv"
set "ZIP=Atlas_MT5_OOS_Data.zip"
if not "%~1"=="" set "DATASET=%~1"
if not "%~2"=="" set "NEWS=%~2"
if not "%~3"=="" set "ZIP=%~3"

if exist "%ZIP%" del /q "%ZIP%"
powershell -NoProfile -Command "$items=@('%DATASET%','%NEWS%','oos_audit.json','oos_EURUSD_result.json','oos_GBPUSD_result.json') | Where-Object { Test-Path $_ }; if(-not $items){exit 2}; Compress-Archive -Path $items -DestinationPath '%ZIP%' -Force"
if errorlevel 1 goto :fail

echo Created %ZIP%
echo Upload this ZIP back to ChatGPT for the next Atlas validation step.
exit /b 0

:fail
echo Could not create the OOS handoff ZIP.
exit /b 2
