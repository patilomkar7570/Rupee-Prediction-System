@echo off
setlocal
cd /d "%~dp0"
title Rupee Prediction System - Release Candidate Validation

echo.
echo ==================================================
echo    RUPEE PREDICTION SYSTEM - RELEASE GATE
echo ==================================================
echo This runs offline software checks and then tests live market-data access.
echo The live-data step requires internet access and may take several minutes.
echo.

where py >nul 2>nul
if errorlevel 1 goto python_missing

if not exist ".venv\Scripts\python.exe" (
  echo [1/5] Creating a private Python environment...
  py -3.12 -m venv ".venv" 2>nul
  if errorlevel 1 py -3.11 -m venv ".venv" 2>nul
  if errorlevel 1 goto venv_failed
) else (
  echo [1/5] Reusing the existing project environment...
)

echo [2/5] Installing or updating project dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed

echo [3/5] Running offline release checks...
set RPS_NO_PAUSE=1
call run_release_checks.bat
if errorlevel 1 goto software_failed
set RPS_NO_PAUSE=

echo [4/5] Running live-data walk-forward validation...
".venv\Scripts\python.exe" -m backend.validate_real_data
if errorlevel 1 goto live_validation_failed

echo.
echo [5/5] RELEASE GATE COMPLETED.
echo Offline checks and live-data validation both completed successfully.
echo Review the generated report and confirm source freshness, target definition,
echo baseline comparisons, uncertainty intervals, and sample coverage before publishing.
echo.
pause
exit /b 0

:python_missing
echo ERROR: Python launcher (py) was not found.
echo Install Python 3.11 or 3.12 from https://www.python.org/downloads/windows/
echo During setup, enable the Python launcher.
goto failed

:venv_failed
echo ERROR: Could not create a virtual environment using Python 3.12 or 3.11.
echo Install a supported Python version and try again.
goto failed

:software_failed
set RPS_NO_PAUSE=
echo.
echo RELEASE BLOCKED: one or more offline software checks failed.
goto failed

:live_validation_failed
echo.
echo OFFLINE CHECKS PASSED, BUT LIVE-DATA VALIDATION DID NOT COMPLETE.
echo Inspect the error above. It may indicate a provider/network issue or a data/code defect.
echo Do not report the live-data gate as passed until the cause is resolved or documented.
goto failed

:failed
echo.
echo RELEASE GATE DID NOT FULLY PASS. Review the messages above before publishing.
pause
exit /b 1
