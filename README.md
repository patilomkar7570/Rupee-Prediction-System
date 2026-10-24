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
- Windows launcher scripts, offline tests, and a GitHub Actions quality-check workflow.

## Release candidate: v4.1.0-rc1 (not yet published)

Version 4.1.0-rc1 is the release candidate for the planned v4.1.0 release. It has not been published as a GitHub Release or tagged yet. The repository contains the source, blank data templates, documentation, tests, and local launch/validation scripts. The offline checks cover application code paths and synthetic cases only. Live-source freshness, real-market predictive skill, calibration quality, and profitability have **not** been established by those checks.

The default `INR=X` series is a Yahoo Finance USD/INR proxy and may not match an official reference rate or an executable quote. Data providers can change schemas, revise history, or become unavailable. Review the configured target definition and data-quality warnings before interpreting any result.

Read [CHANGELOG.md](CHANGELOG.md) for release notes, [SOURCES.md](SOURCES.md) for source limitations, [ROADMAP.md](ROADMAP.md) for open validation work, [VALIDATION.md](VALIDATION.md) for what has and has not been verified, and [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for the final release gates.

## Quick start (Windows 10/11)

The release requires Python 3.11 or 3.12.

1. Download the repository using GitHub's **Code → Download ZIP**, then extract it into a new folder.
2. Open the extracted folder.
3. Run `launch_windows.bat`.
4. Allow the first launch to install the dependencies listed in `requirements.txt`.
5. In the dashboard, refresh the data and inspect source health and the data-quality / point-in-time audit before running forecasts.

Keep the local backend terminal open while using the dashboard. The development server is configured to bind to loopback only; do not expose it directly to a public network.

## Validation

Run the offline checks from the project folder:

```powershell
run_release_checks.bat
```

Or run the core checks from an activated Python environment:

```powershell
python -m compileall -q backend tests
python -m unittest discover -s tests -v
node --check frontend/app.js
```

To download market history and run a real-data walk-forward evaluation, run `run_real_market_validation.bat`. This requires internet access and may take several minutes. Review the exact target definition, source freshness, coverage, baseline metrics, and uncertainty intervals in the generated report.

For the complete one-time pre-release gate on Windows, run `run_release_candidate_validation.bat`. It prepares the local Python environment, runs the offline checks, and then attempts the live-data evaluation. External provider or network failures are reported as an incomplete live-data gate, not as evidence that forecasts are accurate. Live validation also rejects invalid, future-dated, or more-than-seven-calendar-day-old target history.

Software tests verify implementation behavior; they do not prove real-world predictive accuracy.

## Project layout

- `backend/` — data collection, features, models, evaluation, API, monitoring, and operations.
- `frontend/` — browser dashboard.
- `data/` — blank input templates only.
- `runtime/` — local data, reports, logs, inputs, and shadow forecasts created at runtime; these are excluded from Git.
- `tests/` — offline tests, including API smoke checks.
- `.github/workflows/` — CI quality checks across Windows/Linux and supported Python versions.

## Data and security hygiene

Never commit API keys, `.env` files, locally collected market data, personal notes, logs, generated reports, or shadow-forecast ledgers. Use only blank templates in version control. Verify provider terms and data licenses before redistributing downloaded data.

## License

This project is licensed under the **PolyForm Noncommercial License 1.0.0**. You may use, modify, and redistribute it only for purposes permitted by that license. The license does not grant commercial-use rights; obtain separate permission from the copyright holder before commercial use. Read [LICENSE](LICENSE) and the [official license text](https://polyformproject.org/licenses/noncommercial/1.0.0). Third-party dependencies and external data sources remain subject to their own licenses and terms.

## Disclaimer

For education and research only. Forecasts, scores, probabilities, and intervals can be wrong, stale, miscalibrated, or affected by revised data. No predictive accuracy or profitability is promised. Do not rely on a single model output to trade, convert a material amount, or size a position.
