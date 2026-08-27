@echo off
setlocal
cd /d "%~dp0"
echo ================================================================
echo ATLAS v0.24.11 - H4 BACKWARD STRATEGIC RECONSTRUCTION RESEARCH
echo ================================================================
echo READ ONLY. This sends NO orders and does NOT modify shadow state.
echo.
python run_structure_v2_research.py
if errorlevel 1 (
  echo.
  echo ERROR: H4 strategic hierarchy research exited with code %errorlevel%.
) else (
  echo.
  echo SUCCESS: Research report created.
  echo Report: runtime\structure_v2_research.json
  echo H4 diagnostics: runtime\eurusd_h4_teaching_window.csv etc.
)
echo.
pause
endlocal
