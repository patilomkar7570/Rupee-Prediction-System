# Validation report — v4.1.0

## Scope

This release is packaged as a local-first USD/INR forecasting research workbench. Offline software tests and synthetic fixtures test implementation behavior; they do not establish forecasting skill, probability calibration on live markets, or profitability.

## Reported software checks

The packaging workflow reported:

- 28/28 offline tests passing.
- Python compilation check passing.
- Frontend JavaScript syntax check passing.
- Synthetic walk-forward checks exercised 1-, 5-, and 20-session horizons.
- Release archive integrity check passing.

These are build-time checks from the packaging environment, not independently re-run from this GitHub repository after upload.

## Not established by these checks

- Current availability or freshness of external data providers.
- Successful end-to-end installation and launch on another Windows machine.
- Complete historical point-in-time vintages for all macroeconomic predictors.
- Leakage-free real-market performance for every horizon.
- Reliable future probabilities, trading edge, or profitability after execution costs.

## Recommended verification on Windows

1. Install Python 3.11 or 3.12 and extract the project to a new folder.
2. Run `launch_windows.bat` and check the local dashboard at `http://127.0.0.1:8000`.
3. Refresh data, then inspect the source health and data-quality/point-in-time audit.
4. Run `run_release_checks.bat`.
5. Run `run_real_market_validation.bat` with a working internet connection; preserve the report and record the exact target definition and sample window.
6. Review all horizon metrics against simple baselines and uncertainty intervals. Do not use synthetic checks as evidence of real-world accuracy.

The optional DBIE table mirror may lag. Check its latest observation date and compare it with primary RBI/FBIL publications before using it as a current forecast target.
