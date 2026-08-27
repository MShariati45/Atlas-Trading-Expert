@echo off
setlocal
cd /d %~dp0
python run_audit_historical_dataset.py historical_data/one_year
pause
