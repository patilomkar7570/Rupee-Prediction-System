@echo off
setlocal
cd /d "%~dp0"
title Rupee Prediction System - Release Checks
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Run launch_windows.bat once first to install dependencies.
  pause
  exit /b 1
)
echo [1/5] Compiling Python source...
".venv\Scripts\python.exe" -m compileall -q backend tests
if errorlevel 1 goto failed
echo [2/5] Running offline tests...
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto failed
echo [3/5] Checking dashboard JavaScript syntax when Node.js is installed...
where node >nul 2>nul
if errorlevel 1 (
  echo NOTE: Node.js is not installed locally; GitHub Actions checks JavaScript syntax.
) else (
  node --check frontend/app.js
  if errorlevel 1 goto failed
)
echo [4/5] Checking release structure and version...
".venv\Scripts\python.exe" -c "from pathlib import Path; required=['VERSION','README.md','ROADMAP.md','LICENSE','CHANGELOG.md','VALIDATION.md','.gitignore','frontend/index.html','frontend/app.js','frontend/style.css','launch_windows.bat','run_real_market_validation.bat','run_smoke_tests.bat','backend/paths.py','backend/validate_real_data.py','data/macro_inputs_template.csv','data/event_inputs_template.csv','data/factor_weights_template.csv','backend/india_macro_sources.py','backend/factor_audit.py','backend/numerical_forecast.py','backend/feature_ablation.py','backend/shadow_forecasts.py','backend/target_source.py','backend/data_quality.py','backend/evaluation_uncertainty.py','backend/operations.py','backend/http_client.py','data/official_usdinr_reference_template.csv','tests/test_api_smoke.py','tests/test_release_guardrails.py','backend/point_in_time.py','SOURCES.md','CONTRIBUTING.md','SECURITY.md','RELEASE_CHECKLIST.md','run_release_candidate_validation.bat']; missing=[x for x in required if not Path(x).exists()]; version=Path('VERSION').read_text().strip() if Path('VERSION').exists() else ''; print('Missing:', missing); print('Version:', version); raise SystemExit(bool(missing) or version != '4.1.0-rc1')"
if errorlevel 1 goto failed
echo.
echo [5/5] RELEASE CHECKS PASSED. This confirms software checks, not financial accuracy.
if not defined RPS_NO_PAUSE pause
exit /b 0
:failed
echo.
echo RELEASE CHECKS FAILED.
if not defined RPS_NO_PAUSE pause
exit /b 1
