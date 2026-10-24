@echo off
setlocal
cd /d "%~dp0"
title Rupee Prediction System - Real-Market Validation
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Run launch_windows.bat once first to install dependencies.
  pause
  exit /b 1
)
echo This downloads fresh market history and runs walk-forward evaluations.
echo It may take several minutes and requires working internet access.
echo It does NOT guarantee or certify predictive accuracy.
echo.
".venv\Scripts\python.exe" -m backend.validate_real_data
if errorlevel 1 (
  echo.
  echo Validation did not complete. Review the message above.
  pause
  exit /b 1
)
echo.
echo Reports are saved under the configured runtime directory.
pause
