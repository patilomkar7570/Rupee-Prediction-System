# Roadmap — v4.1.0

This is a research workbench, not a validated trading product. Status describes software implementation, not proof of real-world forecast skill.

## Data reliability

- **Implemented foundation:** configurable USD/INR target selection, data-source status, stale-data warnings, schema checks, duplicate-date rejection for imported reference-rate series, and conservative availability-time handling for manual macro inputs.
- **Still needed:** verify live source coverage and the latest observation date; audit provider release calendars and historical vintages for revised macroeconomic series; compare any imported reference-rate file with its primary publication.

## Forecasting and evaluation

- **Implemented:** 1-, 5-, and 20-session directional and numerical forecast workflows, chronological model evaluation, random-walk baselines, probability metrics, feature-family ablation, and uncertainty estimates.
- **Still needed:** execute a full real-market walk-forward evaluation on verified data, review a protected holdout, predeclare metrics, and report results by horizon with sample size and uncertainty.

## Reliability and operations

- **Implemented:** local dashboard, source/data-quality views, health and status endpoints, structured rotating logs, Windows launch and validation scripts, and CI workflow for offline checks.
- **Still needed:** run the first-install workflow on the target Windows machine, verify live connectors, and collect prospective shadow forecasts before outcomes are known.

## Release gates

1. Verify target definition, data coverage, provenance, and source freshness.
2. Run all offline tests and the real-data validation workflow.
3. Compare every horizon against its stated baseline and preserve the holdout protocol.
4. Record prospective shadow forecasts and wait for outcomes to mature before describing performance.
5. Do not describe the system as accurate or profitable unless independently supported by reproducible evidence.
