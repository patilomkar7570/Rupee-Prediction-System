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
- **One Windows entry point:** `RUN.bat` starts the app, prepares dependencies when needed, and provides optional update and validation commands.

## Release candidate: v4.1.0-rc1 (not yet published)

Version 4.1.0-rc1 is the release candidate for the planned v4.1.0 release. It has not been published as a GitHub Release or tagged yet. The repository contains the source, blank data templates, documentation, tests, and a unified Windows launcher. The offline checks cover application code paths and synthetic cases only. Live-source freshness, real-market predictive skill, calibration quality, and profitability have **not** been established by those checks.

The default `INR=X` series is a Yahoo Finance USD/INR proxy and may not match an official reference rate or an executable quote. Data providers can change schemas, revise history, or become unavailable. Review the configured target definition and data-quality warnings before interpreting any result.

Read [CHANGELOG.md](CHANGELOG.md) for release notes, [SOURCES.md](SOURCES.md) for source limitations, [ROADMAP.md](ROADMAP.md) for open validation work, [VALIDATION.md](VALIDATION.md) for what has and has not been verified, and [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for the final release gates.

## Quick start (Windows 10/11)

The release requires Python 3.11 or 3.12.

1. Download the repository using GitHub's **Code → Download ZIP**, then extract it into a new folder.
2. Open the extracted folder.
3. Double-click **`RUN.bat`**.
4. On first launch, the launcher creates a private Python environment and installs dependencies. It records a checksum of `requirements.txt`, so later launches skip package installation unless the requirements change.
5. The launcher starts the local backend in a separate terminal and opens the dashboard at [http://127.0.0.1:8000](http://127.0.0.1:8000). Keep the backend terminal open while using the dashboard.

The default launch does not run slow historical validation automatically. In the dashboard, refresh the data and inspect source health and the data-quality / point-in-time audit before running forecasts. The backend binds to loopback only; do not expose it directly to a public network.

## Optional commands

All local operations use the same batch file. Run these from Command Prompt or PowerShell opened in the project folder:

```bat
RUN.bat update         rem Refresh market data and write a daily forecast
RUN.bat test           rem Run offline software checks
RUN.bat validate       rem Download current history and run walk-forward validation
RUN.bat release-check  rem Run offline checks, then live-data validation
```

The live-data commands require internet access and may take several minutes. They do not establish durable forecasting skill or profitability. If a provider is unavailable or data is stale, inspect the error and the generated report rather than treating the gate as passed.

## Validation

`RUN.bat test` compiles Python modules, runs unit and API smoke tests, checks the frontend JavaScript syntax when Node.js is installed, and verifies the release file/version and single-launcher requirements.

`RUN.bat validate` downloads market history and runs a real-data walk-forward evaluation. Review the exact target definition, source freshness, coverage, baseline metrics, and uncertainty intervals in the generated report.

`RUN.bat release-check` runs both sets of checks sequentially. External provider or network failures are reported as a failed/incomplete live-data gate, not as evidence that forecasts are accurate. Live validation rejects invalid, future-dated, or more-than-seven-calendar-day-old target history.

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
