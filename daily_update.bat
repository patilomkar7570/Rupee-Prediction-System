@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run launch_windows.bat once first to create the v4.1.0-rc1 environment.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m backend.daily_update
if errorlevel 1 (
  echo Daily refresh or forecast failed. Review the error above.
  exit /b 1
)
echo Daily refresh and forecast completed. Output is in the configured runtime directory.
