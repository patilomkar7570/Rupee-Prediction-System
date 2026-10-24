# Rupee Prediction System

**A local-first USD/INR forecasting research workbench** built with Python, FastAPI, scikit-learn, and a responsive HTML/CSS/JavaScript dashboard.

> **Research software, not financial advice.** This project is experimental. Passing software tests does not prove forecasting skill, and no forecast should be treated as a trading signal or a guarantee of future performance.

## Overview

Rupee Prediction System brings together currency and macroeconomic monitoring, multi-horizon forecasts, chronological backtesting, baseline comparisons, data-quality checks, uncertainty estimates, feature analysis, and a prospective shadow-forecast journal.

### Features

- Directional and numerical forecasts for 1-, 5-, and 20-session horizons.
- Data refresh and source-status monitoring.
- Walk-forward evaluation with benchmark comparisons and uncertainty intervals.
- Feature ablation and factor-sign diagnostics.
- Point-in-time and data-quality checks, including stale or incomplete target history.
- Optional user-supplied USD/INR reference-rate CSVs and a configurable target definition.
- Local dashboard, health/status endpoints, structured logs, and append-only shadow forecasts.
- Windows launcher scripts and offline tests.

## Current release

This repository is being prepared for **v4.1.0**. The release package's offline checks cover application code paths and synthetic test cases only. Live-source freshness, real-market predictive skill, calibration quality, and profitability have **not** been established by those checks.

The default `INR=X` series is a Yahoo Finance USD/INR proxy and may not match an official reference rate or an executable quote. Data providers can change schemas, revise history, or become unavailable. Review the configured target definition and data-quality warnings before interpreting any result.

## Quick start (Windows 10/11)

The release requires Python 3.11 or 3.12.

1. Obtain the complete project source and extract it into a new folder.
2. Open the extracted folder.
3. Run `launch_windows.bat`.
4. Allow the first launch to install the dependencies listed in `requirements.txt`.
5. In the dashboard, refresh the data and inspect source health and the data-quality / point-in-time audit before running forecasts.

Keep the local backend terminal open while using the dashboard. The development server is intended to bind to loopback only; do not expose it directly to a public network.

## Validation

Run the offline checks from the project folder:

```powershell
python -m compileall -q backend tests
python -m unittest discover -s tests -v
```

These tests verify software behavior, not real-world predictive accuracy. For live-market evaluation, use the project's real-data validation workflow and review its coverage, data freshness, target definition, baseline metrics, and uncertainty intervals.

## Project layout

- `backend/` — data collection, features, models, evaluation, API, monitoring, and operations.
- `frontend/` — browser dashboard.
- `data/` — blank input templates only.
- `runtime/` — local data, reports, logs, inputs, and shadow forecasts created at runtime; these should not be committed.
- `tests/` — offline tests using synthetic fixtures.
- `.github/workflows/` — CI workflow.

## Data and security hygiene

Never commit API keys, `.env` files, locally collected market data, personal notes, logs, generated reports, or shadow-forecast ledgers. Use only blank templates in version control. Verify provider terms and data licenses before redistributing downloaded data.

## License

Released under the MIT License. See [LICENSE](LICENSE). Third-party dependencies and external data sources remain subject to their own licenses and terms.

## Disclaimer

For education and research only. Forecasts, scores, probabilities, and intervals can be wrong, stale, miscalibrated, or affected by revised data. No predictive accuracy or profitability is promised. Do not rely on a single model output to trade, convert a material amount, or size a position.
