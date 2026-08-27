@echo off
setlocal
cd /d "%~dp0"
if exist "C:\Atlas\.venv\Scripts\activate.bat" call "C:\Atlas\.venv\Scripts\activate.bat"
python run_supervised_demo_runtime.py --poll-seconds 15
endlocal
