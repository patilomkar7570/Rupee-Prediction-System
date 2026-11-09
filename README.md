# Rupee Prediction System

**A local-first USD/INR forecasting research workbench** built with Python, FastAPI, scikit-learn, and a responsive HTML/CSS/JavaScript dashboard.

> **Research software, not financial advice.** This project is experimental. Passing software tests does not prove forecasting skill, and no forecast should be treated as a trading signal or a guarantee of future performance.

## Overview

Rupee Prediction System brings together currency and macroeconomic monitoring, multi-horizon forecasts, chronological backtesting, baseline comparisons, data-quality checks, uncertainty estimates, feature analysis, and a prospective shadow-forecast journal.

### Features

- **Directional & Numerical Forecasts**: Multi-horizon predictions for 1-session (tomorrow), 5-session (next week), and 20-session (next month) horizons.
- **Executive Mode & Segmented Views**: Switch seamlessly between **🌟 Executive Forecast**, **📊 Macroeconomic Groups**, and **🔬 Deep Quant Analytics & Audit**.
- **Macroeconomic Driver Attribution & Pressure Gauge**: Visual headwind/tailwind analysis tracking Brent Crude Oil, US Dollar Index (DXY), RBI Repo Rate, FX Reserves buffer, and Foreign Portfolio Investment (FPI) flows.
- **Interactive Multi-Timeframe Charting**: Fast SVG trend analysis with client-side timeframe switching across `1M`, `3M`, `6M`, `1Y`, and `5Y`.
- **Executive PDF / Print Export**: One-click printable briefing export formatted via dedicated print stylesheets (`@media print`).
- **Unified Master Action**: Single `⚡ Run Analysis & Refresh` trigger consolidating data ingestion, feature extraction, and multi-model inference.
- **RBI Technical Intervention Signals**: 14-day RSI, 20-day Bollinger %b, and 5/20 EMA ratios to capture short-term mean-reversion and central-bank defense bands.
- **Parallel Multi-Horizon Engine**: Multi-threaded execution computing 1D, 5D, and 20D horizons concurrently.
- **Data Quality & Point-in-Time Guardrails**: Raw file duplicates, invalid rates, freshness audit, and fail-closed validation.
- **Evaluation & Uncertainty Diagnostics**: Chronological walk-forward backtesting, moving-block bootstrap confidence intervals, and append-only shadow-forecast ledger.
- **One Windows Entry Point**: `run.bat` automatically configures the environment and manages all dashboard, test, and validation modes.

## Macroeconomic Factor Architecture

The platform aggregates high-signal market indicators categorized into 4 core functional domains:

1. **Global FX & Dollar Strength**: US Dollar Index (DXY), Offshore Yuan (USD/CNH), CBOE Volatility Index (VIX), and Treasury Volatility (MOVE).
2. **Commodities & Energy Imports**: Brent Crude Oil (USD & INR proxy) and Gold Bullion (USD & INR proxy), reflecting India's key import bill pressures.
3. **Rates & Yield Spreads**: RBI Policy Repo Rate, India 10-Year Benchmark Yield, US 10-Year & 2-Year Treasury Yields, US Effective Fed Funds Rate, and ECB Policy Facility Rate.
4. **Capital Flows & External Sector**: RBI Foreign Exchange Reserves (USD Bn), Foreign Portfolio Investment (FPI) Net Equity/Debt Flows, Merchandise Trade Balance, and India CPI Inflation.

## Release candidate: v4.1.0-rc1 (not yet published)

Version 4.1.0-rc1 is the release candidate for the planned v4.1.0 release. It has not been published as a GitHub Release or tagged yet. The repository contains the source, blank data templates, documentation, tests, and a unified Windows launcher. The offline checks cover application code paths and synthetic cases only. Live-source freshness, real-market predictive skill, calibration quality, and profitability have **not** been established by those checks.

The default `INR=X` series is a Yahoo Finance USD/INR proxy and may not match an official reference rate or an executable quote. Data providers can change schemas, revise history, or become unavailable. Review the configured target definition and data-quality warnings before interpreting any result.

Read [CHANGELOG.md](CHANGELOG.md) for release notes, [SOURCES.md](SOURCES.md) for source limitations, [ROADMAP.md](ROADMAP.md) for open validation work, [VALIDATION.md](VALIDATION.md) for what has and has not been verified, and [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for the final release gates.

## Quick start (Windows 10/11)

The launcher uses the latest registered Python selected by the Windows Python Launcher (`py`), falling back to `python` on PATH when the launcher is unavailable.

1. Download the repository using GitHub's **Code → Download ZIP**, then extract it into a new folder.
2. Open the extracted folder.
3. Double-click **`run.bat`**.
4. On first launch, the launcher installs dependencies into the selected existing Python installation; it does not create a virtual environment. It records a checksum of `requirements.txt` and the selected Python executable, so later launches skip package installation unless the requirements or interpreter changes. Packages are shared with other projects using that Python installation.
5. The launcher starts the local backend in a separate terminal and opens the dashboard at [http://127.0.0.1:8000](http://127.0.0.1:8000). Keep the backend terminal open while using the dashboard.

The default launch does not run slow historical validation automatically. In the dashboard, refresh the data and inspect source health and the data-quality / point-in-time audit before running forecasts. The backend binds to loopback only; do not expose it directly to a public network.

## Optional commands

All local operations use the same batch file. Run these from Command Prompt or PowerShell opened in the project folder:

```bat
run.bat update         rem Refresh market data and write a daily forecast
run.bat test           rem Run offline software checks
run.bat validate       rem Download current history and run walk-forward validation
run.bat release-check  rem Run offline checks, then live-data validation
```

The live-data commands require internet access and may take several minutes. They do not establish durable forecasting skill or profitability. If a provider is unavailable or data is stale, inspect the error and the generated report rather than treating the gate as passed.

## Validation

`run.bat test` compiles Python modules, runs unit and API smoke tests, checks the frontend JavaScript syntax when Node.js is installed, and verifies the release file/version and single-launcher requirements.

`run.bat validate` downloads market history and runs a real-data walk-forward evaluation. Review the exact target definition, source freshness, coverage, baseline metrics, and uncertainty intervals in the generated report.

`run.bat release-check` runs both sets of checks sequentially. External provider or network failures are reported as a failed/incomplete live-data gate, not as evidence that forecasts are accurate. Live validation rejects invalid, future-dated, or more-than-seven-calendar-day-old target history.

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
