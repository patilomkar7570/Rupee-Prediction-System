# Validation report — v4.1.0

## Scope

This repository is a local-first USD/INR forecasting research workbench. Software checks test implementation behavior; they do not establish forecasting skill, probability calibration on live markets, or profitability.

## Automated repository checks

The GitHub Actions workflow in `.github/workflows/tests.yml` runs on Ubuntu and Windows with Python 3.11 and 3.12. It compiles Python modules, checks the dashboard JavaScript syntax with Node.js, runs the unit and API smoke-test suite, and checks that required release files and the `VERSION` file are present.

The committed test suite includes deterministic checks for target construction, point-in-time timestamp handling, reference-rate CSV validation, moving-block bootstrap helpers, basic API/dashboard routes, data-quality blocking cases, and prospective shadow-forecast recording/scoring. Consult the repository's **Actions** tab for the latest CI result. The release gate also checks the dashboard JavaScript syntax when Node.js is installed locally.

## Not established by automated checks

- Current availability or freshness of external data providers.
- Successful end-to-end installation on every Windows configuration.
- Complete historical point-in-time vintages for all macroeconomic predictors.
- Leakage-free real-market performance for each forecast horizon.
- Reliable future probabilities, a durable trading edge, or profitability after costs and slippage.

## Recommended verification on Windows

1. Install Python 3.11 or 3.12 and extract the repository into a new folder.
2. Run `launch_windows.bat` and open the local dashboard at `http://127.0.0.1:8000`.
3. Refresh the data, then inspect source health and the data-quality / point-in-time audit.
4. Run `run_release_checks.bat`.
5. With internet access, run `run_real_market_validation.bat`; preserve its generated report and record the exact target definition and sample window.
6. Compare every horizon against simple baselines and uncertainty intervals. Do not treat synthetic checks as evidence of real-world accuracy.

The optional RBI DBIE reference-rate connector uses a third-party mirror and may lag. Check the latest observation date and compare it with primary RBI/FBIL publications before using it as a current forecast target.

## Research guardrails

Predictions are experimental and may be wrong, stale, or miscalibrated. Historical macro data may be revised, and some source availability dates are approximations rather than verified historical release timestamps. Review `SOURCES.md` and the point-in-time audit before making any performance claim. This application is for education and research, not financial advice.
