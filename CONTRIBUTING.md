# Contributing

Thanks for helping improve Rupee Prediction System.

## Before opening a pull request

- Keep source files, blank templates, and runtime/user data separate. Never commit downloaded market history, private input files, logs, API credentials, or generated report outputs.
- Run `run_release_checks.bat` on Windows, or run `python -m compileall -q backend tests` and `python -m unittest discover -s tests -v` in a configured Python environment.
- For changes to models, targets, date alignment, or feature engineering, explain the leakage controls and add a test where possible.
- Do not use synthetic data to claim real-world forecasting accuracy.
- Cite the source and availability date for external data, and make missing/stale values visible rather than silently fabricating observations.
- Keep current headline/LLM commentary separate from numerical model inputs unless a documented, timestamped, reproducible method is implemented and tested.

## Pull request checklist

- [ ] Tests pass.
- [ ] No credentials, private datasets, or runtime output are included.
- [ ] Data source, release-time, or look-ahead implications are documented.
- [ ] README and CHANGELOG are updated where appropriate.
- [ ] Any performance claim reports the horizon, sample period, benchmark, metric, and test method.
