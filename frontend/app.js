"use strict";

const $ = (id) => document.getElementById(id);
let latestPrediction = null;
let hasData = false;
let cachedHistory = [];
let activeDays = 1300;

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
    return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch];
  });
}

function fmt(value, digits) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, {minimumFractionDigits: digits == null ? 2 : digits, maximumFractionDigits: digits == null ? 2 : digits});
}

function pct(value) {
  return value === null || value === undefined || !Number.isFinite(Number(value)) ? "—" : fmt(value, 2) + "%";
}

function notify(message, kind) {
  const node = $("toast");
  if (!node) return;
  node.textContent = message;
  node.className = "toast" + (kind ? " " + kind : "");
}

async function api(path, options) {
  const response = await fetch(path, Object.assign({headers: {"Content-Type":"application/json"}}, options || {}));
  let payload;
  try { payload = await response.json(); } catch (_) { payload = {}; }
  if (!response.ok) {
    const detail = payload && payload.detail ? payload.detail : ("HTTP " + response.status);
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

function showBusy(button, busy, label) {
  if (!button) return;
  if (busy) {
    button.dataset.previousLabel = button.textContent;
    button.disabled = true;
    button.textContent = label || "Working…";
  } else {
    button.disabled = false;
    if (button.dataset.previousLabel) button.textContent = button.dataset.previousLabel;
    delete button.dataset.previousLabel;
  }
}

function renderJson(id, value) {
  const node = $(id);
  if (!node) return;
  const pre = document.createElement("pre");
  pre.className = "json-view";
  pre.textContent = JSON.stringify(value, null, 2);
  node.replaceChildren(pre);
}

function drawSvgChart(nodeId, labelId, history) {
  const node = $(nodeId);
  if (!node) return;
  if (!Array.isArray(history) || history.length < 2) {
    node.innerHTML = '<div class="empty">Refresh market history to draw the chart.</div>';
    if ($(labelId)) $(labelId).textContent = "Waiting for data";
    return;
  }
  const values = history.map(function (x) { return Number(x.usdinr); }).filter(Number.isFinite);
  if (values.length < 2) return;
  const min = Math.min.apply(null, values), max = Math.max.apply(null, values);
  const range = max - min || 1;
  const points = history.map(function (row, index) {
    const x = 12 + (index / (history.length - 1)) * 776;
    const y = 196 - ((Number(row.usdinr) - min) / range) * 168;
    return x.toFixed(1) + "," + y.toFixed(1);
  }).join(" ");
  const first = history[0], last = history[history.length - 1];
  node.innerHTML = '<svg viewBox="0 0 800 220" role="img" aria-label="USD INR history line chart" preserveAspectRatio="none">' +
    '<line x1="12" y1="28" x2="788" y2="28" class="chart-grid"/><line x1="12" y1="112" x2="788" y2="112" class="chart-grid"/><line x1="12" y1="196" x2="788" y2="196" class="chart-grid"/>' +
    '<polyline points="' + points + '" class="chart-line"/></svg>' +
    '<div class="chart-labels"><span>' + escapeHtml(first.date) + '</span><span>₹' + fmt(min, 3) + '–₹' + fmt(max, 3) + '</span><span>' + escapeHtml(last.date) + '</span></div>';
  if ($(labelId)) $(labelId).textContent = history.length + " trading sessions";
}

function filterHistoryByDays(history, days) {
  if (!Array.isArray(history)) return [];
  if (days >= history.length) return history;
  return history.slice(-days);
}

function updateChartWithTimeframe(days) {
  activeDays = days;
  const sliced = filterHistoryByDays(cachedHistory, activeDays);
  drawSvgChart("chart", "history-label", cachedHistory);
  drawSvgChart("simple-chart", "simple-history-label", sliced);
}

function renderChart(history) {
  if (Array.isArray(history)) {
    cachedHistory = history;
  }
  updateChartWithTimeframe(activeDays);
}

function renderOverview(data) {
  const fields = ["rbi-repo", "india-10y", "fx-reserves", "india-cpi", "trade-balance", "fpi-flows"];
  if (!data || !data.data_available) {
    $("usd-inr").textContent = "—";
    $("rate-date").textContent = "No data loaded";
    if ($("simple-usd-inr")) $("simple-usd-inr").textContent = "₹—";
    if ($("simple-usd-change")) $("simple-usd-change").textContent = "No data loaded";
    $("regime").textContent = "Not assessed";
    $("regime-note").textContent = data && data.message ? data.message : "Click Run Analysis & Refresh to collect market history.";
    fields.forEach(function (f) { const el = $(f); if (el) el.textContent = "—"; });
    hasData = false;
    if (data && data.sources) renderSources(data.sources);
    return;
  }
  hasData = true;

  // Overview metrics
  $("usd-inr").textContent = "₹" + fmt(data.usd_inr, 4);
  $("rate-date").textContent = (data.latest_date || "Latest date unavailable") + " · " + fmt(data.rows, 0) + " sessions";
  $("brent").textContent = data.brent == null ? "—" : "$" + fmt(data.brent, 2);
  $("gold").textContent = data.gold == null ? "—" : "$" + fmt(data.gold, 2);
  $("dxy").textContent = fmt(data.dxy, 2);
  $("us10y").textContent = data.us10y == null ? "—" : fmt(data.us10y, 3) + "%";
  $("vix").textContent = fmt(data.vix, 2);
  const rbiRepo = $("rbi-repo"); if (rbiRepo) rbiRepo.textContent = data.rbi_repo == null ? "—" : fmt(data.rbi_repo, 2) + "%";
  const in10y = $("india-10y"); if (in10y) in10y.textContent = data.india_10y == null ? "—" : fmt(data.india_10y, 2) + "%";
  const fxRes = $("fx-reserves"); if (fxRes) fxRes.textContent = data.fx_reserves == null ? "—" : "$" + fmt(data.fx_reserves, 1) + "B";
  const inCpi = $("india-cpi"); if (inCpi) inCpi.textContent = data.india_cpi == null ? "—" : fmt(data.india_cpi, 2) + "%";
  const tb = $("trade-balance"); if (tb) tb.textContent = data.trade_balance == null ? "—" : "$" + fmt(data.trade_balance, 1) + "B";
  const fpi = $("fpi-flows"); if (fpi) fpi.textContent = data.fpi_flows == null ? "—" : (data.fpi_flows >= 0 ? "+$" : "-$") + fmt(Math.abs(data.fpi_flows), 2) + "B";
  const regime = data.market_regime || {};
  $("regime").textContent = regime.label || "Not assessed";
  $("regime-note").textContent = regime.description || "No regime description available.";
  $("target-note").textContent = "Target: " + (data.target_source || "not configured") + ". Auto-updates when changed.";

  // Sync target select
  if ($("target-source") && data.target_source) {
    $("target-source").value = data.target_source;
  }

  // Populate Macroeconomic Groups Tab
  const setTxt = function (id, val) { const el = $(id); if (el) el.textContent = val; };
  setTxt("grp-dxy", data.dxy == null ? "—" : fmt(data.dxy, 2));
  setTxt("grp-usdcnh", data.usdcnh == null ? "—" : fmt(data.usdcnh, 4));
  setTxt("grp-vix", data.vix == null ? "—" : fmt(data.vix, 2));
  setTxt("grp-move", data.move == null ? "—" : fmt(data.move, 2));
  setTxt("grp-brent", data.brent == null ? "—" : "$" + fmt(data.brent, 2));
  setTxt("grp-brent-inr", data.brent_inr == null ? "—" : "₹" + fmt(data.brent_inr, 2));
  setTxt("grp-gold", data.gold == null ? "—" : "$" + fmt(data.gold, 2));
  setTxt("grp-gold-inr", data.gold_inr == null ? "—" : "₹" + fmt(data.gold_inr, 2));
  setTxt("grp-rbi-repo", data.rbi_repo == null ? "—" : fmt(data.rbi_repo, 2) + "%");
  setTxt("grp-india-10y", data.india_10y == null ? "—" : fmt(data.india_10y, 2) + "%");
  setTxt("grp-us10y", data.us10y == null ? "—" : fmt(data.us10y, 3) + "%");
  setTxt("grp-us2y", data.us2y == null ? "—" : fmt(data.us2y, 3) + "%");
  setTxt("grp-fed-funds", data.fed_funds == null ? "—" : fmt(data.fed_funds, 2) + "%");
  setTxt("grp-ecb", data.ecb_mro == null ? "—" : fmt(data.ecb_mro, 2) + "%");
  setTxt("grp-fx-reserves", data.fx_reserves == null ? "—" : "$" + fmt(data.fx_reserves, 1) + "B");
  setTxt("grp-fpi-flows", data.fpi_flows == null ? "—" : (data.fpi_flows >= 0 ? "+$" : "-$") + fmt(Math.abs(data.fpi_flows), 2) + "B");
  setTxt("grp-trade-balance", data.trade_balance == null ? "—" : (data.trade_balance >= 0 ? "+$" : "-$") + fmt(Math.abs(data.trade_balance), 2) + "B");
  setTxt("grp-india-cpi", data.india_cpi == null ? "—" : fmt(data.india_cpi, 2) + "%");

  // Simple Hero Banner
  if ($("simple-usd-inr")) $("simple-usd-inr").textContent = "₹" + fmt(data.usd_inr, 4);
  if ($("simple-usd-change")) {
    const chg = data.daily_change_pct;
    if (chg != null) {
      const sign = chg >= 0 ? "+" : "";
      $("simple-usd-change").textContent = sign + fmt(chg, 2) + "% today";
      $("simple-usd-change").className = "change-badge " + (chg > 0 ? "positive" : "negative");
    } else {
      $("simple-usd-change").textContent = "Market steady";
      $("simple-usd-change").className = "change-badge";
    }
  }
  if ($("simple-rate-meta")) {
    $("simple-rate-meta").textContent = "As of " + (data.latest_date || "Today") + " · " + fmt(data.rows, 0) + " historical sessions analyzed";
  }

  // Simple Sentiment Gauge & Key Drivers
  if (data.factor_analysis) {
    const fa = data.factor_analysis;
    const score = Number(fa.pressure_score) || 0;
    if ($("simple-gauge-score")) $("simple-gauge-score").textContent = "Pressure Score: " + (score > 0 ? "+" : "") + fmt(score, 1);
    if ($("simple-gauge-marker")) {
      const markerPct = Math.min(95, Math.max(5, (score + 100) / 2));
      $("simple-gauge-marker").style.left = markerPct + "%";
    }
    if ($("simple-macro-summary")) {
      $("simple-macro-summary").textContent = fa.human_summary || fa.pressure_detail || "Macro conditions assessed.";
    }
    renderSimpleDrivers(fa.key_market_drivers || []);
  }

  renderChart(data.history);
  if (data.sources) renderSources(data.sources);
}

function renderSimpleDrivers(drivers) {
  const container = $("simple-drivers-grid");
  if (!container) return;
  if (!drivers || !drivers.length) {
    container.innerHTML = '<p class="muted">Key driver summaries will appear after refreshing data.</p>';
    return;
  }
  container.innerHTML = drivers.map(function (d) {
    return '<article class="driver-card">' +
      '<div class="driver-card-top">' +
        '<span class="driver-icon">' + escapeHtml(d.icon) + '</span>' +
        '<span class="status-pill ' + (d.status.includes("Headwind") ? "error" : (d.status.includes("Tailwind") ? "ok" : "")) + '">' + escapeHtml(d.status) + '</span>' +
      '</div>' +
      '<h4 class="driver-name">' + escapeHtml(d.name) + '</h4>' +
      '<div class="driver-value-row">' +
        '<span class="driver-val">' + escapeHtml(d.display_value) + '</span>' +
        '<span class="driver-change">' + escapeHtml(d.change_label) + '</span>' +
      '</div>' +
      '<p class="driver-why">' + escapeHtml(d.simple_explanation) + '</p>' +
    '</article>';
  }).join("");
}

function renderSources(sources) {
  if (!sources || typeof sources !== "object") return;
  const rows = Object.keys(sources).sort().map(function (key) {
    const s = sources[key] || {};
    return '<tr><td>' + escapeHtml(key) + '</td><td><span class="status-pill ' + escapeHtml(String(s.status || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "")) + '">' + escapeHtml(s.status || "unknown") + '</span></td><td>' + escapeHtml(s.latest_date || "—") + '</td><td>' + escapeHtml(s.rows == null ? "—" : s.rows) + '</td><td>' + escapeHtml(s.message || s.source || "") + '</td></tr>';
  }).join("");
  $("source-result").innerHTML = '<div class="table-wrap"><table><thead><tr><th>Source</th><th>Status</th><th>Latest date</th><th>Rows</th><th>Note</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
}

function renderForecasts(report) {
  latestPrediction = report;
  const horizons = Array.isArray(report.horizons) ? report.horizons : [];
  if ($("record-shadow")) $("record-shadow").disabled = horizons.length !== 3;

  // 1. Render Advanced Technical Forecast Grid
  $("forecast-grid").innerHTML = horizons.map(function (h) {
    const cls = h.prediction === "UP" ? "up" : h.prediction === "DOWN" ? "down" : "neutral";
    const pctVal = h.model_probabilities ? Math.max(Number(h.model_probabilities.UP || 0), Number(h.model_probabilities.FLAT || 0), Number(h.model_probabilities.DOWN || 0)) * 100 : null;
    return '<article class="forecast"><span>' + escapeHtml(h.horizon_days + " session" + (h.horizon_days === 1 ? "" : "s")) + '</span><strong class="' + cls + '">' + escapeHtml(h.prediction || "—") + '</strong><small>' + escapeHtml(h.selected_model || "Model unavailable") + '</small><small>Top class estimate: ' + pct(pctVal) + '</small><small>Holdout balanced accuracy: ' + pct(h.test_metrics && h.test_metrics.balanced_accuracy_pct) + '</small></article>';
  }).join("") || '<p class="muted">The backend returned no horizon results.</p>';

  const details = {
    as_of_date: report.as_of_date, usd_inr_close: report.usd_inr_close,
    note: report.note, probability_note: report.probability_note,
    horizons: horizons.map(function (h) {
      return {
        horizon_sessions: h.horizon_days, signal: h.prediction, model_prediction: h.model_prediction,
        selected_model: h.selected_model, model_probabilities: h.model_probabilities,
        confidence: h.confidence, test_metrics: h.test_metrics, numerical_forecast: h.numerical_forecast,
      };
    }),
  };
  renderJson("prediction-detail", details);

  // 2. Render Simple Forecast Cards for Regular Users
  horizons.forEach(function (h) {
    const d = h.horizon_days;
    const badgeEl = $("simple-badge-" + d + "d");
    const targetEl = $("simple-target-" + d + "d");
    const rangeEl = $("simple-range-" + d + "d");
    const confEl = $("simple-conf-" + d + "d");
    const fillEl = $("simple-fill-" + d + "d");
    if (!badgeEl) return;

    const num = h.numerical_forecast || {};
    const intervals = num.forecast_intervals || {};
    const int80 = intervals["80pct"] || {};

    let badgeText = "⏹️ Stable Range";
    let badgeClass = "neutral";
    if (h.model_prediction === "UP" || h.prediction === "UP") {
      badgeText = "🔼 Rupee Pressure (USD/INR Up)";
      badgeClass = "up";
    } else if (h.model_prediction === "DOWN" || h.prediction === "DOWN") {
      badgeText = "🔽 Rupee Support (USD/INR Down)";
      badgeClass = "down";
    } else {
      badgeText = "⏹️ Stable / Rangebound";
      badgeClass = "neutral";
    }

    badgeEl.textContent = badgeText;
    badgeEl.className = "card-direction-badge " + badgeClass;

    if (num.forecast_rate) {
      targetEl.textContent = "₹" + fmt(num.forecast_rate, 4);
    } else {
      targetEl.textContent = "₹" + fmt(report.usd_inr_close, 4);
    }

    if (int80.lower && int80.upper) {
      rangeEl.textContent = "Expected Range: ₹" + fmt(int80.lower, 2) + " – ₹" + fmt(int80.upper, 2);
    } else {
      rangeEl.textContent = "Expected Range: Stable around current rate";
    }

    const confScore = (h.confidence && h.confidence.raw_top_class_score_pct) ? h.confidence.raw_top_class_score_pct : 65;
    confEl.textContent = fmt(confScore, 0) + "%";
    fillEl.style.width = Math.min(100, Math.max(10, confScore)) + "%";
  });
}

function renderFactorAudit(data) {
  const f = data.factors || [];
  const rows = f.map(function (row) {
    const contrib = Number(row.contribution || 0);
    const cls = contrib > 0.05 ? "error" : (contrib < -0.05 ? "ok" : "muted");
    return '<tr><td><strong>' + escapeHtml(row.name) + '</strong><br><small class="muted">' + escapeHtml(row.group) + ' · ' + escapeHtml(row.unit) + '</small></td><td>' + escapeHtml(row.display_value) + '</td><td>' + escapeHtml(row.change_label) + '</td><td><span class="status-pill ' + cls + '">' + escapeHtml(row.signal) + '</span></td><td>' + fmt(row.contribution, 4) + '</td><td>' + escapeHtml(row.interpretation) + '</td></tr>';
  }).join("");
  $("factor-result").innerHTML = '<div class="quality-head"><div><span>Pressure score:</span> <strong>' + fmt(data.pressure_score, 1) + ' (' + escapeHtml(data.pressure_label || "Neutral") + ')</strong></div><div><span>Factor coverage:</span> <strong>' + fmt(data.factor_coverage_pct, 1) + '%</strong></div></div>' +
    '<div class="table-wrap"><table><thead><tr><th>Factor & group</th><th>Latest value</th><th>Recent change</th><th>Directional signal</th><th>Net contribution</th><th>Economic interpretation</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
}

function renderQuality(report) {
  const issues = report.issues || [];
  const pit = report.point_in_time_review_flags || [];
  const gateClass = report.release_gate === "passed" ? "ok" : "blocked";
  const head = '<div class="quality-head"><div><span>Release gate:</span> <strong class="status-pill ' + gateClass + '">' + escapeHtml(report.release_gate || "unknown").toUpperCase() + '</strong></div><div><span>Quality issues:</span> <strong>' + issues.length + '</strong></div><div><span>Timing flags:</span> <strong>' + pit.length + '</strong></div></div>';
  const issueHtml = '<h3>Data issues</h3><ul class="finding-list">' + (issues.map(function (i) {
    return '<li><strong>[' + escapeHtml(i.severity) + '] ' + escapeHtml(i.code) + '</strong><p>' + escapeHtml(i.message) + '</p></li>';
  }).join("") || '<li>No blocking data-quality issues found.</li>') + '</ul>';
  const pitHtml = '<h3>Point-in-time publication checks</h3><ul class="finding-list">' + (pit.map(function (p) {
    return '<li><strong>' + escapeHtml(p.source) + ' · ' + escapeHtml(p.code) + '</strong><p>' + escapeHtml(p.message) + '</p></li>';
  }).join("") || '<li>No immediate timing flags.</li>') + '</ul>';
  $("quality-result").innerHTML = head + issueHtml + pitHtml + '<p class="footnote"><a href="/api/data-quality.csv">Download quality audit CSV ↗</a></p>';
}

async function runPrediction() {
  try {
    const report = await api("/api/predict", {method:"POST"});
    renderForecasts(report);
  } catch (err) {
    console.warn("Prediction update skipped:", err.message);
  }
}

async function runFactorAudit() {
  try {
    const result = await api("/api/factor-audit");
    renderFactorAudit(result);
    if (result.key_market_drivers) renderSimpleDrivers(result.key_market_drivers);
  } catch (err) {
    console.warn("Factor audit skipped:", err.message);
  }
}

async function runQualityAudit() {
  try {
    const report = await api("/api/data-quality");
    renderQuality(report);
  } catch (err) {
    console.warn("Quality audit skipped:", err.message);
  }
}

async function refreshNews() {
  try {
    const result = await api("/api/news");
    const articles = result.articles || [];
    $("news-result").innerHTML = '<p class="muted">' + escapeHtml(result.headline_summary || "") + '</p><div class="article-list">' + articles.map(function (a) {
      return '<article><a href="' + escapeHtml(a.link || "#") + '" target="_blank" rel="noopener">' + escapeHtml(a.title) + '</a><small>' + escapeHtml(a.published || "") + ' · ' + escapeHtml(a.source || "") + '</small></article>';
    }).join("") + '</div>';
  } catch (err) {
    console.warn("News update skipped:", err.message);
  }
}

async function loadShadowLedger() {
  try {
    const result = await api("/api/shadow-forecasts");
    const summary = result.summary || [];
    const forecastRows = result.forecasts || [];
    const table = '<div class="table-wrap"><table><thead><tr><th>Horizon</th><th>Recorded</th><th>Scored</th><th>Pending</th><th>Directional accuracy</th></tr></thead><tbody>' + summary.map(function (s) {
      return '<tr><td>' + escapeHtml(s.horizon_sessions) + '</td><td>' + escapeHtml(s.recorded) + '</td><td>' + escapeHtml(s.evaluated) + '</td><td>' + escapeHtml(s.pending) + '</td><td>' + pct(s.model_direction_accuracy_pct) + '</td></tr>';
    }).join("") + '</tbody></table></div>';
    const records = '<h3>Recent snapshots</h3><div class="table-wrap"><table><thead><tr><th>As of</th><th>Horizon</th><th>Model signal</th><th>Recorded status</th><th>Outcome</th></tr></thead><tbody>' + forecastRows.slice(0,50).map(function (f) {
      return '<tr><td>' + escapeHtml(f.as_of_date) + '</td><td>' + escapeHtml(f.horizon_sessions) + '</td><td>' + escapeHtml(f.model_prediction) + '</td><td>' + escapeHtml(f.evaluated ? "Scored" : "Pending") + '</td><td>' + escapeHtml(f.actual_direction || "—") + '</td></tr>';
    }).join("") + '</tbody></table></div>';
    $("shadow-result").innerHTML = '<p class="muted">' + escapeHtml(result.note || "") + '</p>' + table + records;
  } catch (err) {
    console.warn("Shadow ledger skipped:", err.message);
  }
}

// Master Action: One single button updates all data, forecasts, factors, quality, and news
async function runAllAnalysis() {
  const b1 = $("master-run-button");
  const b2 = $("simple-refresh-button");
  showBusy(b1, true, "⚡ Analyzing & Updating…");
  showBusy(b2, true, "⚡ Analyzing & Updating…");
  notify("Fetching latest market feeds…", "warning");

  try {
    const data = await api("/api/refresh", {method:"POST"});
    renderOverview(data);

    notify("Running multi-horizon AI forecasts and macro audits…", "warning");
    await Promise.allSettled([
      runPrediction(),
      runFactorAudit(),
      runQualityAudit(),
      refreshNews(),
      loadShadowLedger()
    ]);
    notify("Analysis complete! All market data, forecasts, and macro drivers updated.", "success");
  } catch (err) {
    notify("Update failed: " + err.message, "error");
  } finally {
    showBusy(b1, false, "⚡ Run Analysis & Refresh");
    showBusy(b2, false, "⚡ Run Analysis & Refresh");
  }
}

async function loadInitialData() {
  try {
    const data = await api("/api/overview");
    renderOverview(data);
    if (data.data_available) {
      notify("Loading current forecasts and macro assessments…");
      await Promise.allSettled([
        runPrediction(),
        runFactorAudit(),
        runQualityAudit(),
        refreshNews(),
        loadShadowLedger()
      ]);
      notify("Workspace ready. All forecasts and macroeconomic drivers loaded.", "success");
    } else {
      notify("No local data yet. Click 'Run Analysis & Refresh' to start.", "warning");
    }
  } catch (err) {
    notify("Could not load workspace: " + err.message, "error");
  }
}

async function runBacktest() {
  const b = $("backtest-button"); showBusy(b, true, "Running backtest…");
  try {
    const result = await api("/api/backtest", {method:"POST"});
    const summary = result.summary || {};
    const horizons = summary.horizons || {};
    const table = '<div class="table-wrap"><table><thead><tr><th>Horizon</th><th>Best model</th><th>Balanced accuracy</th><th>Baseline (FLAT)</th><th>Skill delta</th></tr></thead><tbody>' + Object.keys(horizons).map(function (k) {
      const h = horizons[k];
      return '<tr><td>' + escapeHtml(k) + '</td><td><strong>' + escapeHtml(h.best_model_by_balanced_accuracy || "—") + '</strong></td><td>' + pct(h.best_model_balanced_accuracy_pct) + '</td><td>' + pct(h.flat_balanced_accuracy_pct) + '</td><td><strong>' + (h.balanced_accuracy_delta_vs_best_baseline_pp > 0 ? "+" : "") + fmt(h.balanced_accuracy_delta_vs_best_baseline_pp, 2) + ' pp</strong></td></tr>';
    }).join("") + '</tbody></table></div>';
    $("backtest-result").innerHTML = '<p class="muted">' + escapeHtml(summary.interpretation || "") + '</p>' + table + '<details><summary>Raw backtest JSON</summary><pre class="json-view">' + escapeHtml(JSON.stringify(result, null, 2)) + '</pre></details>';
    notify("Walk-forward backtest completed.", "success");
  } catch (err) { notify("Backtest failed: " + err.message, "error"); }
  finally { showBusy(b, false, "Run 5-Year Backtest Simulation"); }
}

async function analyzeNews() {
  const b = $("analyze-button"); showBusy(b, true, "Analyzing news…");
  try {
    const model = $("ollama-model").value || "qwen2.5:7b";
    const result = await api("/api/analyze-news", {method:"POST",body:JSON.stringify({model:model})});
    renderJson("news-result", result);
    notify(result.status === "ok" ? "Local-model commentary generated." : (result.message || "No analysis returned."));
  } catch (err) { notify("Local headline analysis unavailable: " + err.message, "error"); }
  finally { showBusy(b, false, "Explain with local model"); }
}

async function recordShadow() {
  if (!latestPrediction) { notify("Run a forecast first.", "warning"); return; }
  const b = $("record-shadow"); showBusy(b, true, "Recording snapshot…");
  try {
    const result = await api("/api/shadow-forecast", {method:"POST",body:JSON.stringify({prediction_report:latestPrediction})});
    notify("Recorded " + result.recorded + " horizon snapshots.", "success");
    await loadShadowLedger();
  } catch (err) { notify("Could not record snapshot: " + err.message, "error"); }
  finally { showBusy(b, false, "Save Forecast Snapshot"); b.disabled = !latestPrediction || !Array.isArray(latestPrediction.horizons) || latestPrediction.horizons.length !== 3; }
}

function initTabs() {
  const tabSimple = $("tab-simple");
  const tabGroups = $("tab-groups");
  const tabAdvanced = $("tab-advanced");
  const simpleView = $("simple-view");
  const groupsView = $("groups-view");
  const advancedView = $("advanced-view");

  const navSimple = $("nav-simple");
  const navGroups = $("nav-groups");
  const navOverview = $("nav-overview");

  function setMode(mode) {
    if (tabSimple) tabSimple.classList.toggle("active", mode === "simple");
    if (tabGroups) tabGroups.classList.toggle("active", mode === "groups");
    if (tabAdvanced) tabAdvanced.classList.toggle("active", mode === "advanced");

    if (simpleView) simpleView.style.display = mode === "simple" ? "block" : "none";
    if (groupsView) groupsView.style.display = mode === "groups" ? "block" : "none";
    if (advancedView) advancedView.style.display = mode === "advanced" ? "block" : "none";

    if (navSimple) navSimple.classList.toggle("active", mode === "simple");
    if (navGroups) navGroups.classList.toggle("active", mode === "groups");
    if (navOverview) navOverview.classList.toggle("active", mode === "advanced");
  }

  if (tabSimple) tabSimple.addEventListener("click", () => setMode("simple"));
  if (tabGroups) tabGroups.addEventListener("click", () => setMode("groups"));
  if (tabAdvanced) tabAdvanced.addEventListener("click", () => setMode("advanced"));

  if (navSimple) {
    navSimple.addEventListener("click", function (e) {
      e.preventDefault();
      setMode("simple");
      window.scrollTo({top: 0, behavior: "smooth"});
    });
  }
  if (navGroups) {
    navGroups.addEventListener("click", function (e) {
      e.preventDefault();
      setMode("groups");
      window.scrollTo({top: 0, behavior: "smooth"});
    });
  }
  ["overview", "forecasts", "factors", "evaluation", "quality", "sources", "news", "shadow"].forEach(function (sec) {
    const link = $("nav-" + sec);
    if (link) {
      link.addEventListener("click", function () {
        setMode("advanced");
      });
    }
  });
}

function initTheme() {
  const saved = localStorage.getItem("rps-theme");
  if (saved === "light") document.documentElement.dataset.theme = "light";
  $("theme-button").addEventListener("click", function () {
    const light = document.documentElement.dataset.theme !== "light";
    document.documentElement.dataset.theme = light ? "light" : "dark";
    localStorage.setItem("rps-theme", light ? "light" : "dark");
  });
}

document.addEventListener("DOMContentLoaded", function () {
  initTheme();
  initTabs();

  // Print PDF report triggers
  const triggerPrint = () => window.print();
  if ($("print-pdf-button")) $("print-pdf-button").addEventListener("click", triggerPrint);
  if ($("simple-print-button")) $("simple-print-button").addEventListener("click", triggerPrint);

  // Timeframe selector buttons
  document.querySelectorAll(".tf-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".tf-btn").forEach(function (b) { b.classList.remove("active"); });
      this.classList.add("active");
      const days = parseInt(this.getAttribute("data-days"), 10) || 1300;
      updateChartWithTimeframe(days);
    });
  });

  // Unified master button handlers
  if ($("master-run-button")) $("master-run-button").addEventListener("click", runAllAnalysis);
  if ($("simple-refresh-button")) $("simple-refresh-button").addEventListener("click", runAllAnalysis);

  // Target dropdown auto-save on change
  if ($("target-source")) {
    $("target-source").addEventListener("change", async function () {
      notify("Updating target source to " + this.value + "…", "warning");
      try {
        const res = await api("/api/target-source", {method:"POST", body:JSON.stringify({target_source: this.value})});
        notify(res.message || "Target updated. Refreshing analysis…", "success");
        runAllAnalysis();
      } catch (err) {
        notify("Failed to change target source: " + err.message, "error");
      }
    });
  }

  if ($("backtest-button")) $("backtest-button").addEventListener("click", runBacktest);
  if ($("analyze-button")) $("analyze-button").addEventListener("click", analyzeNews);
  if ($("record-shadow")) $("record-shadow").addEventListener("click", recordShadow);

  loadInitialData();
});
