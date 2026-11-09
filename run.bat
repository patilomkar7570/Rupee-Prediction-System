@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Rupee Prediction System v1.0.0

set "APP_VERSION=1.0.0"
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

call :ensure_python
if errorlevel 1 goto failed

call :ensure_dependencies
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
echo Pre-compiling Python bytecode...
"%PYTHON_EXE%" -m compileall -q backend
start "Rupee Prediction System Backend" /D "%CD%" "%ComSpec%" /k "call "%PYTHON_EXE%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"

echo Waiting for the backend to become ready...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(45); do { try { $r=Invoke-RestMethod -Uri '%APP_URL%/api/health' -TimeoutSec 2; if ($r.application -eq 'Rupee Prediction System' -and $r.version -eq '%APP_VERSION%') { exit 0 } } catch {}; Start-Sleep -Milliseconds 500 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
  echo.
  echo ERROR: The dashboard did not become ready within 45 seconds.
  echo Check the backend window for the Python error. Port 8000 may already be in use.
  echo If dependencies are broken, delete deps-installed.sha256 and run run.bat again.
  pause
  exit /b 1
)
start "" "%APP_URL%"
echo Dashboard opened at %APP_URL%.
exit /b 0

:update_data
echo Refreshing market data and writing the latest daily forecast...
"%PYTHON_EXE%" -m backend.daily_update
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
"%PYTHON_EXE%" -m backend.validate_real_data
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
"%PYTHON_EXE%" -m backend.validate_real_data
if errorlevel 1 goto failed
echo.
echo RELEASE CHECKS COMPLETED. Review the generated report and the checklist before publishing.
call :pause_for_cli
exit /b 0

:ensure_python
set "PYTHON_EXE="
rem The Windows Python Launcher selects the latest registered Python by default.
where py >nul 2>nul
if not errorlevel 1 (
  for /f "delims=" %%P in ('py -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%P"
)
rem Fall back to the python command on PATH when the launcher is unavailable.
if not defined PYTHON_EXE (
  where python >nul 2>nul
  if not errorlevel 1 (
    for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%P"
  )
)
if not defined PYTHON_EXE (
  echo ERROR: Python was not found.
  echo Install Python and enable the Python Launcher or Add Python to PATH.
  exit /b 1
)
"%PYTHON_EXE%" -c "import sys; print('Using Python ' + sys.version.split()[0] + ' at ' + sys.executable)"
if errorlevel 1 exit /b 1
exit /b 0

:ensure_dependencies
if not exist "requirements.txt" (
  echo ERROR: requirements.txt was not found in %CD%.
  exit /b 1
)
set "REQUIREMENTS_HASH="
for /f "delims=" %%H in ('powershell -NoProfile -Command "(Get-FileHash requirements.txt -Algorithm SHA256).Hash.ToLowerInvariant()"') do set "REQUIREMENTS_HASH=%%H"
if not defined REQUIREMENTS_HASH (
  echo ERROR: Could not calculate the requirements.txt checksum.
  exit /b 1
)
set "INSTALLED_HASH="
set "INSTALLED_PYTHON="
if exist "deps-installed.sha256" (
  set /p "INSTALLED_HASH="<"deps-installed.sha256"
  for /f "usebackq skip=1 delims=" %%P in ("deps-installed.sha256") do set "INSTALLED_PYTHON=%%P"
)
if /I "%INSTALLED_HASH%"=="%REQUIREMENTS_HASH%" if /I "%INSTALLED_PYTHON%"=="%PYTHON_EXE%" (
  echo Python dependencies are ready; requirements and Python installation are unchanged.
  exit /b 0
)

echo Installing or updating dependencies into the selected Python installation...
"%PYTHON_EXE%" -m pip install --disable-pip-version-check --quiet --upgrade pip 2>nul
"%PYTHON_EXE%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 exit /b 1
(
  echo %REQUIREMENTS_HASH%
  echo %PYTHON_EXE%
) > "deps-installed.sha256"
exit /b 0

:offline_checks
echo [1/4] Compiling Python modules...
"%PYTHON_EXE%" -m compileall -q backend tests
if errorlevel 1 exit /b 1

echo [2/4] Running offline and API tests...
"%PYTHON_EXE%" -m unittest discover -s tests -v
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
"%PYTHON_EXE%" -c "from pathlib import Path; required=['VERSION','README.md','ROADMAP.md','LICENSE','CHANGELOG.md','VALIDATION.md','.gitignore','requirements.txt','frontend/index.html','frontend/app.js','frontend/style.css','run.bat','backend/main.py','backend/paths.py','backend/validate_real_data.py','data/macro_inputs_template.csv','data/event_inputs_template.csv','data/factor_weights_template.csv','backend/india_macro_sources.py','backend/factor_audit.py','backend/numerical_forecast.py','backend/feature_ablation.py','backend/shadow_forecasts.py','backend/target_source.py','backend/data_quality.py','backend/evaluation_uncertainty.py','backend/operations.py','backend/http_client.py','data/official_usdinr_reference_template.csv','tests/test_api_smoke.py','tests/test_release_guardrails.py','tests/test_launcher_contract.py','backend/point_in_time.py','SOURCES.md','CONTRIBUTING.md','SECURITY.md','RELEASE_CHECKLIST.md']; missing=[x for x in required if not Path(x).exists()]; launchers=sorted(p.name for p in Path('.').glob('*.bat')); version=Path('VERSION').read_text().strip() if Path('VERSION').exists() else ''; print('Missing files:', missing); print('Root batch files:', launchers); print('Version:', version); raise SystemExit(bool(missing) or launchers != ['run.bat'] or version != '1.0.0')"
if errorlevel 1 exit /b 1
exit /b 0

:pause_for_cli
echo.
pause
exit /b 0

:usage
echo.
echo Rupee Prediction System v1.0.0
echo.
echo Double-click run.bat to start the dashboard.
echo Optional commands from a terminal in this folder:
echo   run.bat update        Refresh market data and write a forecast
echo   run.bat test          Run offline software checks
echo   run.bat validate      Run live-data walk-forward validation
echo   run.bat release-check Run offline checks followed by live validation
echo   run.bat help          Show this help
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
