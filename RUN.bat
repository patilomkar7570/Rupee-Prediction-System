@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Rupee Prediction System v4.1.0-rc1

set "APP_VERSION=4.1.0-rc1"
set "APP_URL=http://127.0.0.1:8000"
set "MODE=%~1"
if not defined MODE set "MODE=start"

set "ACTION="
if /I "%MODE%"=="start" set "ACTION=start"
if /I "%MODE%"=="run" set "ACTION=start"
if /I "%MODE%"=="update" set "ACTION=update"
if /I "%MODE%"=="daily" set "ACTION=update"
if /I "%MODE%"=="test" set "ACTION=test"
if /I "%MODE%"=="check" set "ACTION=test"
if /I "%MODE%"=="validate" set "ACTION=validate"
if /I "%MODE%"=="live" set "ACTION=validate"
if /I "%MODE%"=="release-check" set "ACTION=release-check"
if /I "%MODE%"=="help" set "ACTION=help"
if not defined ACTION goto usage_error
if /I "%ACTION%"=="help" goto usage

call :ensure_environment
if errorlevel 1 goto failed

if /I "%ACTION%"=="start" goto start_app
if /I "%ACTION%"=="update" goto update_data
if /I "%ACTION%"=="test" goto test_mode
if /I "%ACTION%"=="validate" goto validate_mode
if /I "%ACTION%"=="release-check" goto release_check_mode
goto usage_error

:start_app
rem Reuse this project's already-running server instead of spawning a duplicate.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-RestMethod -Uri '%APP_URL%/api/health' -TimeoutSec 2; if ($r.application -eq 'Rupee Prediction System' -and $r.version -eq '%APP_VERSION%') { exit 0 } } catch {}; exit 1"
if not errorlevel 1 (
  echo Rupee Prediction System is already running. Opening the dashboard...
  start "" "%APP_URL%"
  exit /b 0
)

echo Starting the local dashboard...
echo The backend will run in a separate window. Keep that window open while using the app.
start "Rupee Prediction System Backend" /D "%CD%" "%CD%\.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

echo Waiting for the backend to become ready...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(45); do { try { $r=Invoke-RestMethod -Uri '%APP_URL%/api/health' -TimeoutSec 2; if ($r.application -eq 'Rupee Prediction System' -and $r.version -eq '%APP_VERSION%') { exit 0 } } catch {}; Start-Sleep -Milliseconds 500 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
  echo.
  echo ERROR: The dashboard did not become ready within 45 seconds.
  echo Check the backend window for details. Port 8000 may already be in use.
  echo If Python packages are broken, delete .venv\deps-installed.sha256 and run RUN.bat again.
  pause
  exit /b 1
)
start "" "%APP_URL%"
echo Dashboard opened at %APP_URL%.
exit /b 0

:update_data
echo Refreshing market data and writing the latest daily forecast...
"%CD%\.venv\Scripts\python.exe" -m backend.daily_update
if errorlevel 1 goto failed
echo Update completed. Outputs are stored under runtime.
call :pause_for_cli
exit /b 0

:test_mode
call :offline_checks
if errorlevel 1 goto failed
echo.
echo OFFLINE CHECKS PASSED. This does not establish market forecasting accuracy.
call :pause_for_cli
exit /b 0

:validate_mode
echo Running live-data walk-forward validation. This needs internet and may take several minutes.
echo It does not guarantee or certify predictive accuracy.
echo.
"%CD%\.venv\Scripts\python.exe" -m backend.validate_real_data
if errorlevel 1 goto failed
echo.
echo Validation completed. Review the reports under runtime before interpreting the results.
call :pause_for_cli
exit /b 0

:release_check_mode
call :offline_checks
if errorlevel 1 goto failed
echo.
echo Offline checks passed. Now running live-data validation...
echo.
"%CD%\.venv\Scripts\python.exe" -m backend.validate_real_data
if errorlevel 1 goto failed
echo.
echo RELEASE CHECKS COMPLETED. Review the generated report and the checklist before publishing.
call :pause_for_cli
exit /b 0

:ensure_environment
where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: The Python launcher ^(py^) was not found.
  echo Install Python 3.11 or 3.12 from https://www.python.org/downloads/windows/
  echo Enable the Python launcher during setup.
  exit /b 1
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3, 11), (3, 12)) else 1)" >nul 2>nul
  if errorlevel 1 (
    echo Rebuilding the project's private environment because its Python version is unsupported...
    rmdir /s /q ".venv"
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating the private Python environment...
  py -3.12 -m venv ".venv" >nul 2>nul
  if errorlevel 1 (
    if exist ".venv" rmdir /s /q ".venv"
    py -3.11 -m venv ".venv"
  )
  if errorlevel 1 (
    echo ERROR: Could not create a Python 3.11 or 3.12 environment.
    exit /b 1
  )
)

set "REQUIREMENTS_HASH="
for /f "delims=" %%H in ('powershell -NoProfile -Command "(Get-FileHash requirements.txt -Algorithm SHA256).Hash.ToLowerInvariant()"') do set "REQUIREMENTS_HASH=%%H"
if not defined REQUIREMENTS_HASH (
  echo ERROR: Could not calculate the requirements.txt checksum.
  exit /b 1
)

set "INSTALLED_HASH="
if exist ".venv\deps-installed.sha256" set /p "INSTALLED_HASH="<".venv\deps-installed.sha256"
if /I not "%INSTALLED_HASH%"=="%REQUIREMENTS_HASH%" (
  echo Installing or updating Python dependencies. This happens only on first run or when requirements.txt changes...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
  if errorlevel 1 exit /b 1
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 exit /b 1
  >".venv\deps-installed.sha256" echo %REQUIREMENTS_HASH%
) else (
  echo Python environment is ready; dependencies are unchanged.
)
exit /b 0

:offline_checks
echo [1/4] Compiling Python modules...
"%CD%\.venv\Scripts\python.exe" -m compileall -q backend tests
if errorlevel 1 exit /b 1

echo [2/4] Running offline and API tests...
"%CD%\.venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 exit /b 1

echo [3/4] Checking frontend JavaScript syntax when Node.js is installed...
where node >nul 2>nul
if errorlevel 1 (
  echo NOTE: Node.js is not installed locally; GitHub Actions checks JavaScript syntax.
) else (
  node --check frontend/app.js
  if errorlevel 1 exit /b 1
)

echo [4/4] Checking required release files, version, and the single-launcher rule...
"%CD%\.venv\Scripts\python.exe" -c "from pathlib import Path; required=['VERSION','README.md','ROADMAP.md','LICENSE','CHANGELOG.md','VALIDATION.md','.gitignore','requirements.txt','frontend/index.html','frontend/app.js','frontend/style.css','RUN.bat','backend/main.py','backend/paths.py','backend/validate_real_data.py','data/macro_inputs_template.csv','data/event_inputs_template.csv','data/factor_weights_template.csv','backend/india_macro_sources.py','backend/factor_audit.py','backend/numerical_forecast.py','backend/feature_ablation.py','backend/shadow_forecasts.py','backend/target_source.py','backend/data_quality.py','backend/evaluation_uncertainty.py','backend/operations.py','backend/http_client.py','data/official_usdinr_reference_template.csv','tests/test_api_smoke.py','tests/test_release_guardrails.py','tests/test_launcher_contract.py','backend/point_in_time.py','SOURCES.md','CONTRIBUTING.md','SECURITY.md','RELEASE_CHECKLIST.md']; missing=[x for x in required if not Path(x).exists()]; launchers=sorted(p.name for p in Path('.').glob('*.bat')); version=Path('VERSION').read_text().strip() if Path('VERSION').exists() else ''; print('Missing files:', missing); print('Root batch files:', launchers); print('Version:', version); raise SystemExit(bool(missing) or launchers != ['RUN.bat'] or version != '4.1.0-rc1')"
if errorlevel 1 exit /b 1
exit /b 0

:pause_for_cli
echo.
pause
exit /b 0

:usage
echo.
echo Rupee Prediction System v4.1.0-rc1
echo.
echo Double-click RUN.bat to start the dashboard.
echo Optional commands from a terminal in this folder:
echo   RUN.bat update        Refresh market data and write a forecast
echo   RUN.bat test          Run offline software checks
echo   RUN.bat validate      Run live-data walk-forward validation
echo   RUN.bat release-check Run offline checks followed by live validation
echo   RUN.bat help          Show this help
echo.
exit /b 0

:usage_error
echo Unknown command: %MODE%
goto usage

:failed
echo.
echo OPERATION FAILED. Review the messages above before retrying.
pause
exit /b 1
