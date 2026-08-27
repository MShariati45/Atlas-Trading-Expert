@echo off
cd /d "%~dp0"
python run_h4_validation.py --data-dir "historical_data/one_year/bars" --symbol EURUSD
pause
