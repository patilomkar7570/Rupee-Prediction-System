@echo off
setlocal
cd /d "%~dp0"
title Rupee Prediction System v4.1.0-rc1

echo.
echo  ==================================================
echo    RUPEE PREDICTION SYSTEM - v4.1.0 LOCAL RESEARCH
echo  ==================================================
echo.
echo This folder is independent from your older project versions.
echo First launch needs internet to install packages.
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python launcher ^(py^) was not found.
  echo Install Python 3.11 or 3.12 from https://www.python.org/downloads/windows/
  echo During setup, enable Add Python to PATH.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating a private Python environment for v4.1.0...
  py -3.12 -m venv .venv 2>nul
  if errorlevel 1 py -3.11 -m venv .venv 2>nul
  if errorlevel 1 (
    echo ERROR: Could not create the virtual environment. Check your Python install.
    pause
    exit /b 1
  )
)

if not exist ".venv\deps-installed.flag" (
  echo [2/3] Installing v4.1.0 dependencies. This may take a few minutes...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  if errorlevel 1 goto install_error
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto install_error
  echo installed>".venv\deps-installed.flag"
) else (
  echo [2/3] Dependencies already installed for this v4.1.0 folder.
)

echo [3/3] Starting the local backend...
echo Dashboard: http://127.0.0.1:8000
echo The backend opens in its own terminal window. Keep that window open while using the dashboard.
start "Rupee Prediction System Backend" /D "%CD%" "%CD%\.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

echo Waiting for the backend to respond before opening your browser...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(30); while ((Get-Date) -lt $deadline) { try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/status' -UseBasicParsing -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 (
  echo ERROR: The local backend did not become ready within 30 seconds.
  echo Check the backend terminal for a Python or port error, then open http://127.0.0.1:8000 manually.
  pause
  exit /b 1
)
start "" http://127.0.0.1:8000
echo Dashboard opened. Close the backend terminal or press Ctrl+C in it to stop the server.
pause
exit /b 0

:install_error
echo.
echo ERROR: Package installation failed. Check your internet connection and supported Python version.
echo Try Python 3.11 or 3.12, then run this file again.
pause
exit /b 1
