# Release readiness — v4.1.0-rc1

**Status:** release candidate; no formal GitHub Release has been published yet.

This checklist is deliberately small. The goal is to freeze the current scope after one careful verification pass, not to keep adding features indefinitely.

## Already in the repository

- Local-first FastAPI service and responsive dashboard.
- USD/INR directional and numerical forecasts for 1-, 5-, and 20-session horizons.
- Chronological backtesting, baseline comparisons, uncertainty estimates, feature analysis, data-quality checks, and a prospective shadow-forecast ledger.
- **One Windows batch file:** `RUN.bat` starts the dashboard and offers optional update, offline-test, live-validation, and release-check modes.
- GitHub Actions checks for Windows and Ubuntu with Python 3.11 and 3.12.

## Gates before publishing the release

1. **Final CI run is green.** Check the Actions tab for the commit that includes the final release-preparation changes. The `release-candidate/v4.1.0` branch builds a source ZIP and SHA-256 checksum artifact only after all four CI matrix jobs pass; it does not create a GitHub Release or tag.
2. **Clean Windows first run works.** On Windows 10/11, install Python 3.11 or 3.12, extract a fresh copy, and double-click `RUN.bat`.
3. **Offline software checks pass.** Run `RUN.bat test`. It compiles the Python modules, runs the unit/API smoke tests, checks release files/version and the single-launcher rule, and checks frontend JavaScript syntax when Node.js is installed.
4. **Live-data validation completes and is reviewed.** Run `RUN.bat validate` with internet access. If a source is down or the network blocks access, the live-data gate is incomplete; retry or document the provider limitation rather than describing the run as a pass.
5. **Forecast results are described conservatively.** Review source freshness, target definition, sample coverage, results per horizon, baseline comparisons, and uncertainty. Passing software checks does not prove predictive skill, profitability, or future accuracy.
6. **Inspect the candidate ZIP.** Download the `rupee-prediction-system-v4.1.0-rc1` artifact from the successful candidate-branch workflow. Confirm the ZIP and `SHA256SUMS.txt` exist, and compare the checksum before testing the ZIP extracted into a fresh folder.
7. **License and data terms are understood.** The project uses PolyForm Noncommercial License 1.0.0. Commercial use is not granted by that license, and data providers may impose separate terms.

## Freeze policy after the release

Once the gates above are satisfied, publish the stable v4.1.0 release and treat that scope as feature-complete. Do not add optional features just to keep the project moving. Limit follow-up work to release-blocking defects, security issues, and necessary compatibility fixes when dependencies or external data sources change.

A claim that the forecasts are accurate is a separate research claim. It needs reproducible out-of-sample evidence; stronger evidence comes from recording forecasts prospectively and scoring them after outcomes occur. A software release may be published as a research tool without claiming that the model is profitable or reliably predicts exchange rates.

## What CI currently proves

CI previously passed the four-job matrix (Windows and Ubuntu, Python 3.11 and 3.12) for an earlier repository state. Re-check the Actions tab after the final commit; this file does not pre-certify future CI runs.
