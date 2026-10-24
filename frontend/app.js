"use strict";

const $ = (id) => document.getElementById(id);
let latestPrediction = null;
let hasData = false;

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
  const pre = document.createElement("pre");
  pre.className = "json-view";
  pre.textContent = JSON.stringify(value, null, 2);
  node.replaceChildren(pre);
}
function renderChart(history) {
  const node = $("chart");
  if (!Array.isArray(history) || history.length < 2) {
    node.innerHTML = '<div class="empty">Refresh market history to draw the chart.</div>';
    $("history-label").textContent = "Waiting for data";
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
  $("history-label").textContent = history.length + " observations";
}
function renderOverview(data) {
  if (!data || !data.data_available) {
    $("usd-inr").textContent = "—";
    $("rate-date").textContent = "No data loaded";
    $("regime").textContent = "Not assessed";
    $("regime-note").textContent = data && data.message ? data.message : "Click Fetch / refresh data to collect market history.";
    $("predict-button").disabled = true;
    $("factor-button").disabled = true;
    hasData = false;
    if (data && data.sources) renderSources(data.sources);
    return;
  }
  hasData = true;
  $("usd-inr").textContent = "₹" + fmt(data.usd_inr, 4);
  $("rate-date").textContent = (data.latest_date || "Latest date unavailable") + " · " + fmt(data.rows, 0) + " observations";
  $("brent").textContent = data.brent == null ? "—" : "$" + fmt(data.brent, 2);
  $("gold").textContent = data.gold == null ? "—" : "$" + fmt(data.gold, 2);
  $("dxy").textContent = fmt(data.dxy, 2);
  $("us10y").textContent = data.us10y == null ? "—" : fmt(data.us10y, 3) + "%";
  $("vix").textContent = fmt(data.vix, 2);
  const regime = data.market_regime || {};
  $("regime").textContent = regime.label || "Not assessed";
  $("regime-note").textContent = regime.description || "No regime description available.";
  $("target-note").textContent = "Target: " + (data.target_source || "not configured") + ". Refresh and rerun evaluation after changing it.";
  $("predict-button").disabled = false;
  $("factor-button").disabled = false;
  renderChart(data.history);
  if (data.sources) renderSources(data.sources);
  if (data.factor_analysis) {
    const f = data.factor_analysis;
    $("regime").title = f.pressure_label || "";
  }
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
  $("record-shadow").disabled = horizons.length !== 3;
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
        confidence: h.confidence, test_metrics: h.test_metrics, baseline_metrics: h.baseline_metrics,
        selected_baseline: h.baseline_selected, calibration: h.probability_calibration,
        numerical_forecast: h.numerical_forecast
      };
    })
  };
  renderJson("prediction-detail", details);
  notify("Forecast finished. Review the holdout, baseline, and source-timing caveats.", "success");
}
async function refreshData() {
  const b = $("refresh-button"); showBusy(b, true, "Refreshing sources…");
  try {
    notify("Fetching market and macro data. Optional sources may fail independently.");
    const result = await api("/api/refresh", {method:"POST"});
    renderOverview(result);
    if (!result.data_available) {
      const status = await api("/api/status");
      if (status.sources) renderSources(status.sources);
    }
    const target = await api("/api/target-source");
    $("target-source").value = target.target_source || "yahoo_proxy";
    notify(result.message || "Refresh finished; inspect source status.", result.data_available ? "success" : "warning");
  } catch (err) { notify("Refresh failed: " + err.message, "error"); }
  finally { showBusy(b, false); b.textContent = "↻ Fetch / refresh data"; }
}
async function loadOverview() {
  try {
    const data = await api("/api/overview");
    renderOverview(data);
    if (data.data_available) {
      try {
        const target = await api("/api/target-source");
        $("target-source").value = target.target_source || "yahoo_proxy";
        $("target-note").textContent = target.note || "Review target-source provenance before evaluation.";
      } catch (_) {}
      notify("Local dashboard ready. Check freshness before running forecasts.", "success");
    } else notify(data.message || "Fetch / refresh data to begin.");
  } catch (err) { notify("Could not reach the local backend: " + err.message, "error"); }
}
async function runPrediction() {
  const b = $("predict-button"); showBusy(b, true, "Evaluating models…");
  try {
    notify("Running chronological model selection, calibration, holdout evaluation, and forecasts.");
    const report = await api("/api/predict", {method:"POST"});
    renderForecasts(report);
  } catch (err) { notify("Forecast failed or was blocked by data-quality checks: " + err.message, "error"); }
  finally { showBusy(b, false, "Run forecast"); b.disabled = !hasData; }
}
async function runBacktest() {
  const b = $("backtest-button"); showBusy(b, true, "Testing horizons…");
  try {
    const result = await api("/api/backtest", {method:"POST"});
    const rows = [];
    Object.keys(result.horizons || {}).forEach(function (horizon) {
      const data = result.horizons[horizon];
      Object.keys(data.model_metrics || {}).forEach(function (model) {
        const m = data.model_metrics[model] || {};
        if (m.error) return;
        rows.push('<tr><td>' + escapeHtml(horizon) + '</td><td>' + escapeHtml(model) + '</td><td>' + pct(m.accuracy_pct) + '</td><td>' + pct(m.balanced_accuracy_pct) + '</td><td>' + pct(m.macro_f1_pct) + '</td><td>' + escapeHtml(m.rows == null ? "—" : m.rows) + '</td></tr>');
      });
    });
    $("backtest-result").innerHTML = '<div class="table-wrap"><table><thead><tr><th>Horizon</th><th>Model / baseline</th><th>Accuracy</th><th>Balanced acc.</th><th>Macro F1</th><th>Rows</th></tr></thead><tbody>' + rows.join("") + '</tbody></table></div><p class="footnote">' + escapeHtml(result.caveat || "Historical simulation, not a guarantee.") + '</p>';
    notify("Walk-forward evaluation completed. Read the baseline comparison and caveats.", "success");
  } catch (err) { notify("Backtest failed: " + err.message, "error"); }
  finally { showBusy(b, false, "Run backtest"); }
}
async function runFactorAudit() {
  const b = $("factor-button"); showBusy(b, true, "Auditing hypotheses…");
  try {
    const result = await api("/api/factor-audit");
    const rows = (result.factors || []).map(function (f) {
      return '<tr><td>' + escapeHtml(f.factor || f.factor_key) + '</td><td>' + escapeHtml(f.group || "—") + '</td><td>' + escapeHtml(f.observations == null ? "—" : f.observations) + '</td><td>' + fmt(f.pooled_spearman_rho, 3) + '</td><td>' + escapeHtml(f.sign_status || "—") + '</td><td>' + escapeHtml(f.review_hint || "") + '</td></tr>';
    }).join("");
    $("factor-result").innerHTML = '<p class="muted">' + escapeHtml(result.sample_method || "") + '</p><div class="table-wrap"><table><thead><tr><th>Factor</th><th>Group</th><th>Obs.</th><th>Spearman ρ</th><th>Sign status</th><th>Review note</th></tr></thead><tbody>' + rows + '</tbody></table></div><p class="footnote">' + escapeHtml((result.limitations || []).join(" ")) + '</p>';
    notify("Factor audit finished. Associations are descriptive, not causal.", "success");
  } catch (err) { notify("Factor audit failed: " + err.message, "error"); }
  finally { showBusy(b, false, "Run factor audit"); b.disabled = !hasData; }
}
async function runQualityAudit() {
  const b = $("quality-button"); showBusy(b, true, "Checking data…");
  try {
    const result = await api("/api/data-quality");
    const issues = (result.issues || []).map(function (item) {
      return '<li><span class="status-pill ' + escapeHtml(item.severity || "review") + '">' + escapeHtml(item.severity || "review") + '</span><strong>' + escapeHtml(item.code || "CHECK") + '</strong><p>' + escapeHtml(item.message || "") + '</p></li>';
    }).join("");
    const flags = (result.point_in_time_review_flags || []).map(function (item) { return '<li><strong>' + escapeHtml(item.source || "Timing review") + '</strong><p>' + escapeHtml(item.message || "") + '</p></li>'; }).join("");
    $("quality-result").innerHTML = '<div class="quality-head"><span>Release gate</span><strong>' + escapeHtml(result.release_gate || "Unknown") + '</strong><span>Rows: ' + escapeHtml(result.observations || 0) + ' · Target age: ' + escapeHtml(result.target_age_days == null ? "—" : result.target_age_days + " days") + '</span></div><h3>Findings (' + (result.issues || []).length + ')</h3><ul class="finding-list">' + (issues || '<li>No structural issues detected in this check.</li>') + '</ul><h3>Point-in-time limitations</h3><ul class="finding-list">' + (flags || '<li>No extra timing notes returned.</li>') + '</ul><p class="footnote">' + escapeHtml(result.interpretation || "") + '</p>';
    notify("Data-quality audit finished. A green-ish status is not proof of predictive skill.", "success");
  } catch (err) { notify("Data-quality audit failed: " + err.message, "error"); }
  finally { showBusy(b, false, "Run audit"); }
}
async function refreshNews() {
  const b = $("news-button"); showBusy(b, true, "Fetching headlines…");
  try {
    const result = await api("/api/news");
    const articles = result.articles || [];
    $("news-result").innerHTML = '<p class="muted">' + escapeHtml(result.note || "") + '</p>' + (articles.length ? '<div class="article-list">' + articles.map(function (a) {
      return '<article><a href="' + escapeHtml(a.url) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(a.title) + ' ↗</a><small>' + escapeHtml(a.domain || "") + ' · ' + escapeHtml(a.published || "Date unavailable") + '</small></article>';
    }).join("") + '</div>' : '<p>No headlines returned. You can still use timestamped historical event inputs.</p>');
    notify("Headline refresh completed. News remains context-only.", "success");
  } catch (err) { notify("Headline refresh failed: " + err.message, "error"); }
  finally { showBusy(b, false, "Refresh headlines"); }
}
async function analyzeNews() {
  const b = $("analyze-button"); showBusy(b, true, "Asking local model…");
  try {
    const model = $("ollama-model").value.trim() || "qwen2.5:7b";
    const result = await api("/api/news/analyze", {method:"POST",body:JSON.stringify({model:model,max_records:10})});
    renderJson("news-result", result);
    notify(result.status === "ok" ? "Local-model commentary generated; it is not a forecast." : (result.message || "No analysis returned."));
  } catch (err) { notify("Local headline analysis unavailable: " + err.message, "error"); }
  finally { showBusy(b, false, "Explain with local model"); }
}
async function loadShadowLedger() {
  const b = $("shadow-button"); showBusy(b, true, "Scoring ledger…");
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
    notify("Shadow ledger refreshed.", "success");
  } catch (err) { notify("Could not load shadow ledger: " + err.message, "error"); }
  finally { showBusy(b, false, "Refresh ledger"); }
}
async function recordShadow() {
  if (!latestPrediction) { notify("Run a forecast first.", "warning"); return; }
  const b = $("record-shadow"); showBusy(b, true, "Recording snapshot…");
  try {
    const result = await api("/api/shadow-forecast", {method:"POST",body:JSON.stringify({prediction_report:latestPrediction})});
    notify("Recorded " + result.recorded + " horizon snapshots. They will be scored only after future observations arrive.", "success");
    await loadShadowLedger();
  } catch (err) { notify("Could not record snapshot: " + err.message, "error"); }
  finally { showBusy(b, false, "Record forecast snapshot"); b.disabled = !latestPrediction || !Array.isArray(latestPrediction.horizons) || latestPrediction.horizons.length !== 3; }
}
async function saveTargetSource() {
  const b = $("save-target"); showBusy(b, true, "Saving…");
  try {
    const result = await api("/api/target-source", {method:"POST",body:JSON.stringify({target_source:$("target-source").value})});
    $("target-note").textContent = result.message || "Saved. Refresh data and rerun evaluation.";
    notify("Target selection saved. Refresh the dataset before the next forecast.", "success");
  } catch (err) { notify("Could not save target selection: " + err.message, "error"); }
  finally { showBusy(b, false, "Save"); }
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
  $("refresh-button").addEventListener("click", refreshData);
  $("predict-button").addEventListener("click", runPrediction);
  $("backtest-button").addEventListener("click", runBacktest);
  $("factor-button").addEventListener("click", runFactorAudit);
  $("quality-button").addEventListener("click", runQualityAudit);
  $("news-button").addEventListener("click", refreshNews);
  $("analyze-button").addEventListener("click", analyzeNews);
  $("record-shadow").addEventListener("click", recordShadow);
  $("shadow-button").addEventListener("click", loadShadowLedger);
  $("save-target").addEventListener("click", saveTargetSource);
  loadOverview();
});
