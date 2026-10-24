# Data-source register

Rupee Prediction System is a research application. A source being listed here does not imply that every request succeeds or that every historical value is point-in-time clean. Check `runtime/source_status.json` and the dashboard freshness/timing review after every refresh.

| Series / purpose | Source used by code | Important limitation |
|---|---|---|
| Default USD/INR target | Yahoo Finance `INR=X` | An unofficial proxy; not guaranteed to equal an FBIL reference rate, dealer quote, or executable market price. |
| Optional historical reference target | User-imported CSV | The program validates structure and values but cannot authenticate the file or prove publication timestamps. |
| Optional RBI reference-rate history | RBI Database on Indian Economy (DBIE) table via `data-api.dbie.rbihub.in`, a public read-only third-party mirror API | The mirror's docs say data reflect the last scrape, not a live feed. At v4.1.0 release check (24 October 2026), this table page listed observations through 30 June 2026, which is stale for current forecasts. Validate the latest observation date against primary RBI/FBIL publications before use. See the table page: https://dbie.rbihub.in/tables?table=financial_markets.r691_daily_interbank_forex_rates_usd_vis_a_vis_inr and API documentation: https://dev.dbie.rbihub.in/docs/using-the-site. |
| US yields, policy rate and CPI | Federal Reserve Bank of St. Louis FRED public CSV endpoints | Some series are shifted by conservative timing approximations. Historical publication vintages are not complete in this application. |
| ECB main refinancing rate | European Central Bank Data Portal | Daily availability alignment is conservative and still needs provider-specific release-calendar verification. |
| Selected India macro/flow series and RBI repo rate | RBI DBIE mirror endpoints, other public source pages, and optional manual input CSV | Coverage, revisions, units, and publication dates vary. Read per-feed status messages; do not assume complete historical vintages. |
| Geopolitical risk index | Caldara-Iacoviello GPR downloads | The app applies a conservative weekday lag; verify the publication/update calendar for rigorous historical testing. |
| News/event features | User-maintained `runtime/inputs/event_inputs.csv` | Only use historical events with verified timestamps; current headlines are contextual only. |

## Required workflow before publishing performance claims

1. Fix the target definition for the entire experiment.
2. Check the target's latest observation date and provenance; a source page that loads successfully can still contain stale data.
3. Review missing features and point-in-time warnings.
4. Run `run_real_market_validation.bat` and preserve its report.
5. Report horizons, sample window, row count, baselines, metrics, uncertainty and data-source limits together.
6. Collect prospective shadow forecasts before their outcomes are known. Do not rewrite previous records after seeing outcomes.

Data provider terms may govern use, redistribution, or commercial use of downloaded data independently of this software's MIT License. This project does not bundle historical market data in the release ZIP.
