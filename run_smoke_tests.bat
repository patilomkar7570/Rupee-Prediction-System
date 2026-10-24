@echo off
setlocal
cd /d "%~dp0"
title Rupee Prediction System - Offline Tests
if not exist ".venv\Scripts\python.exe" (
  echo Run launch_windows.bat once first to create the v4.1.0 environment.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 (
  echo OFFLINE TESTS FAILED.
  pause
  exit /b 1
)
echo OFFLINE TESTS PASSED. These tests do not establish market forecasting accuracy.
pause
exit /b 0
