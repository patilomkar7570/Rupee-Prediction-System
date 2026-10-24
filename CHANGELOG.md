# Changelog

## v4.1.0-rc1 release-candidate hardening — 2026-10-24

- Replaced the MIT License with the PolyForm Noncommercial License 1.0.0. Use, modification, and redistribution are limited to purposes permitted by that license; commercial use requires separate permission.
- Updated license notices in the README, security policy, and source register.
- Added a fail-closed live-validation freshness gate for invalid, future-dated, or more-than-seven-calendar-day-old USD/INR target history.
- Expanded tests for target freshness, data-quality blocking conditions, and the complete shadow-forecast record/scoring loop.
- Added a CI-produced source ZIP and SHA-256 checksum on the release-candidate branch, only after all four platform/Python test jobs pass. This does not publish a GitHub Release or tag.

## v4.1.0-rc1 — Point-in-time guardrails & release preparation (2026-10-24)

- Added a public RBI DBIE reference-rate table connector through a documented third-party read-only mirror API, including a local snapshot cache and clear stale-cache/source-provenance warnings. The mirror is not a live RBI feed; check the latest observation date before use.
- Added strict reference-rate import normalization with date/rate column detection, positive/range checks and duplicate-date rejection. Imports never silently blend target definitions.
- Added an explicit point-in-time helper for local macro data: reference dates and `AvailableAt` are combined conservatively, releases after 17:00 IST shift to the next weekday, invalid non-empty publication timestamps are excluded, and date-only inputs remain flagged as unaudited. This weekday rule is an approximation, not a full exchange-holiday calendar.
- Stopped forward-filling USD/INR target observations across missing dates; optional predictor features retain separate as-of carry rules.
- Expanded software tests and release metadata.
- Remaining limitation: historical publication vintages are not complete for all automatic macro feeds. These changes reduce common timing/ingestion risks but do not certify historical leakage-free real-market results or predictive skill.

## v4.0.0 — Data integrity, uncertainty & release gates (2026-10-23)

- Added a data-quality audit and downloadable report for raw file duplicates/invalid dates, target freshness, invalid levels, long date gaps, extreme target moves, sparse recent features, per-source freshness, overdue-refresh warnings and point-in-time review flags.
- Added prediction blocking for critical target-data integrity issues and clearly stale target observations. The gate does not certify model skill or full point-in-time availability.
- Added `/api/health`, bounded retry support for transient public-feed GET failures, and rotating structured JSONL request logs stored under `runtime/logs/`.
- Added moving-block bootstrap intervals for directional balanced accuracy and paired direction performance versus a random-walk baseline.
- Added paired moving-block intervals for numerical MAE skill versus the random-walk level forecast, with supportive/against/inconclusive evidence labels.
- Enhanced the dashboard with a data-quality/release-gate view and bootstrap interval columns in model comparison tables.
- Expanded macro CSV template with optional reference period, availability timestamp, source, units and notes lineage fields.
- Removed full-sample feature-column pruning so future data availability cannot retrospectively decide the feature schema in earlier walk-forward folds.
- Included future-dated target observations in the hard prediction guardrail and exposed per-feed refresh timestamps.
- Centralized version identifier in `VERSION` and documented limitations, validation procedures, local-only operations and release gates.

## v3.1.0 — Forecasting Lab and dual themes (2026-10-23)

- Added saved light/dark appearance preferences and responsive theme styles.
- Added numerical exchange-rate regressors with empirical 80%/95% residual intervals.
- Expanded chronological walk-forward evaluation, probability metrics, numerical random-walk comparisons, feature-family ablation and prospective shadow-forecast scoring.
- Added explicit target-series selection without blending Yahoo proxy and user-imported reference-rate histories.

## v3.0.2 — India feeds and factor audit (2026-10-23)

- Added best-effort India macro/capital-flow feeds, source freshness diagnostics and factor sign/weight review.
- Separated tracked templates from local runtime data.

## v3.0.1 — GitHub release preparation (2026-10-23)

- Added noncommercial license, repository/security/contribution docs and real-data validation workflow.

## v3.0.0 — Multi-horizon research system

- Added multi-horizon forecasts, model comparisons, macro features, basic walk-forward tests and local dashboard.
