@echo off
setlocal EnableExtensions

if "%~4"=="" goto :usage
set "DATASET=%~1"
set "NEWS=%~2"
set "START=%~3"
set "END=%~4"

for %%S in (EURUSD GBPUSD) do (
  echo Replaying %%S from %START% to %END%...
  python run_broker_native_oos_replay.py --dataset "%DATASET%" --historical-news "%NEWS%" --symbol %%S --start "%START%" --end "%END%" --out "oos_%%S_result.json"
  if errorlevel 1 goto :fail
)

echo.
echo Replay complete. Results: oos_EURUSD_result.json and oos_GBPUSD_result.json
exit /b 0

:usage
echo Usage: run_mt5_oos_replay.bat DATASET NEWS_CSV START_UTC END_UTC
echo Example: run_mt5_oos_replay.bat historical_data\broker_native_oos historical_news.csv 2025-08-01T00:00:00+00:00 2026-08-01T00:00:00+00:00
exit /b 2

:fail
echo.
echo Replay failed. No strategy rules were changed and no orders were sent.
exit /b 2
