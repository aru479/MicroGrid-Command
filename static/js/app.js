(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let loadChart, socChart, lastRows = [];

  /* ---------- input table ---------- */
  function addRow(r) {
    r = r || {};
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td><input class="ts" value="${esc(r.timestamp)}" placeholder="YYYY-MM-DD HH:MM:SS"></td>` +
      `<td><input type="number" step="0.1" value="${esc(r.ambient_temp_c)}"></td>` +
      `<td><input type="number" step="0.1" value="${esc(r.humidity_pct)}"></td>` +
      `<td><input type="number" step="1" value="${esc(r.solar_irradiance_wm2)}"></td>` +
      `<td><button type="button" title="Remove row">✕</button></td>`;
    tr.querySelector("button").onclick = () => tr.remove();
    $("#input tbody").appendChild(tr);
  }
  const setRows = (rows) => { $("#input tbody").innerHTML = ""; rows.forEach(addRow); };
  function getRows() {
    return [...$("#input tbody").rows].map((tr) => {
      const v = [...tr.querySelectorAll("input")].map((x) => x.value);
      const n = (x) => (x === "" ? null : Number(x));
      return { timestamp: v[0], ambient_temp_c: n(v[1]), humidity_pct: n(v[2]), solar_irradiance_wm2: n(v[3]) };
    });
  }

  /* ---------- helpers ---------- */
  function banner(kind, msg) {
    const b = $("#banner");
    b.className = msg ? "banner " + kind : "banner";
    b.textContent = msg || "";
  }
  function setLoading(on) {
    $("#loading").hidden = !on;
    ["#btnRun", "#btnSample", "#file"].forEach((s) => ($(s).disabled = on));
    $("#btnRun").textContent = on ? "Forecasting…" : "Run forecast";
  }
  async function post(init) {
    setLoading(true);
    banner("", "");
    try {
      const res = await fetch("api/forecast", init);
      let d;
      try { d = await res.json(); } catch (_) { throw new Error("The server returned an unreadable response (HTTP " + res.status + ")."); }
      if (!res.ok || !d.ok) { if (d.log) renderLog(d.log); throw new Error(d.error || "Request failed (HTTP " + res.status + ")."); }
      render(d);
    } catch (e) {
      banner("warn", "⚠ " + e.message);
    } finally {
      setLoading(false);
    }
  }
  function renderLog(entries) {
    $("#log").innerHTML = entries.length
      ? entries.map((l) => `<div><time>${esc(l.t)}</time><span class="lvl-${esc(l.level)}">${esc(l.msg)}</span></div>`).join("")
      : '<span class="muted">No events yet.</span>';
  }

  /* ---------- actions ---------- */
  async function run() {
    const rows = getRows();
    if (!rows.length) return banner("warn", "Add telemetry rows or load the sample day first.");
    await post({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rows, soc: Number($("#soc").value) || 90 }) });
  }
  $("#btnRun").onclick = run;
  $("#btnAdd").onclick = () => {
    const last = $("#input tbody").lastElementChild;
    let ts = "";
    if (last) {
      const d = new Date(last.querySelector(".ts").value.replace(" ", "T") + "Z");
      if (!isNaN(d)) { d.setUTCHours(d.getUTCHours() + 1); ts = d.toISOString().slice(0, 19).replace("T", " "); }
    }
    addRow({ timestamp: ts });
  };
  $("#btnClear").onclick = () => setRows([]);
  $("#btnSample").onclick = async () => {
    try {
      const r = await (await fetch("api/sample")).json();
      setRows(r.rows);
      await run();
    } catch (e) { banner("warn", "⚠ Could not load the sample data: " + e.message); }
  };
  $("#file").onchange = async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    if (!/\.csv$/i.test(f.name)) return banner("warn", "⚠ Please choose a .csv file.");
    const fd = new FormData();
    fd.append("file", f);
    fd.append("soc", $("#soc").value || "90");
    await post({ method: "POST", body: fd });
    if (lastRows.length) setRows(lastRows.map((r) => ({ timestamp: r.timestamp, ambient_temp_c: r.ambient_temp_c, humidity_pct: r.humidity_pct, solar_irradiance_wm2: r.solar_irradiance_wm2 })));
  };
  $("#btnDownload").onclick = () => {
    if (!lastRows.length) return;
    const csv = "timestamp,target_demand_kw\n" + lastRows.map((r) => `${r.timestamp},${r.predicted_demand_kw}`).join("\n") + "\n";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "predictions.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  /* ---------- render ---------- */
  function render(d) {
    const R = d.rows, S = d.summary;
    lastRows = R;
    $("#btnDownload").disabled = false;
    const live = d.source === "quickml";
    const sb = $("#srcBadge");
    sb.textContent = live ? "● Predictions: Catalyst QuickML" : "● Predictions: local fallback (not QuickML)";
    sb.className = "badge " + (live ? "b-ren" : "b-warn");
    sb.title = d.fallback_reason || "Served by the live QuickML endpoint";

    const w = $("#warnings");
    w.hidden = !d.warnings.length;
    w.innerHTML = d.warnings.length ? "<b>Input notes</b><ul>" + d.warnings.map((x) => `<li>${esc(x)}</li>`).join("") + "</ul>" : "";

    const a = R[0];
    $("#activeState").innerHTML = `<span class="badge ${a.grid_mode.startsWith("Ren") ? "b-ren" : "b-grid"}" style="font-size:16px">${esc(a.grid_mode)}</span>`;
    $("#activeSub").textContent = `${a.timestamp} · ${a.predicted_demand_kw} kW predicted` + (a.overload_alert ? " · CRITICAL OVERLOAD" : "");
    $("#socNow").textContent = S.end_soc_pct + "%";
    $("#socBar").style.width = S.end_soc_pct + "%";

    if (S.overload_hours) banner("crit", `🚨 CRITICAL OVERLOAD ALERT — ${S.overload_hours} hour(s) forecast at ≥ 200 kW (peak ${S.peak_kw} kW at ${S.peak_time.slice(11, 16)}).`);
    else if (S.depleted_hours) banner("warn", `Battery reaches its 10% reserve in ${S.depleted_hours} hour(s) — grid assist required.`);
    else banner("ok", `Forecast complete for ${S.hours} row(s) — no overload expected.`);

    const k = [["Peak demand", S.peak_kw + " kW", S.peak_time.slice(11, 16)], ["Average demand", S.avg_kw + " kW", S.hours + " rows"],
      ["Renewable hours", S.renewable_hours, "of " + S.hours], ["Main-grid hours", S.main_grid_hours, "of " + S.hours],
      ["Overload hours", S.overload_hours, "≥ 200 kW"], ["Min battery SoC", S.min_soc_pct + "%", "reserve floor 10%"]];
    $("#kpis").innerHTML = k.map(([l, v, s]) => `<div class="card kpi"><div class="l">${l}</div><div class="v" style="${l === "Overload hours" && v > 0 ? "color:var(--crit)" : ""}">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");

    const labels = R.map((r) => r.timestamp.slice(5, 16));
    const pc = R.map((r) => (r.overload_alert ? css("--crit") : r.grid_mode.startsWith("Ren") ? css("--ren") : css("--grid")));
    const pr = R.length > 60 ? 0 : 5;
    if (loadChart) loadChart.destroy();
    loadChart = new Chart($("#loadChart"), { type: "line", data: { labels, datasets: [
      { label: "Predicted demand", data: R.map((r) => r.predicted_demand_kw), borderColor: css("--accent"), backgroundColor: css("--accent") + "22", fill: true, tension: .3, pointRadius: pr, pointBackgroundColor: pc, pointBorderColor: pc },
      { label: "160 kW — storage threshold", data: R.map(() => 160), borderColor: css("--ren"), borderDash: [6, 4], pointRadius: 0, borderWidth: 1.5 },
      { label: "200 kW — critical overload", data: R.map(() => 200), borderColor: css("--crit"), borderDash: [6, 4], pointRadius: 0, borderWidth: 1.5 }] },
      options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, scales: { y: { title: { display: true, text: "kW" } }, x: { ticks: { maxTicksLimit: 12 } } } } });
    if (socChart) socChart.destroy();
    socChart = new Chart($("#socChart"), { type: "line", data: { labels, datasets: [{ label: "SoC %", data: R.map((r) => r.soc_pct), borderColor: css("--ren"), backgroundColor: css("--ren") + "22", fill: true, stepped: true, pointRadius: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { min: 0, max: 100 }, x: { ticks: { maxTicksLimit: 6 } } }, plugins: { legend: { display: false } } } });

    $("#dispatch tbody").innerHTML = R.map((r) => `<tr class="${r.overload_alert ? "over" : ""}"><td>${esc(r.timestamp.slice(5, 16))}</td><td><b>${esc(r.predicted_demand_kw)}</b></td>` +
      `<td><span class="badge ${r.grid_mode.startsWith("Ren") ? "b-ren" : "b-grid"}">${esc(r.grid_mode.replace(" Mode", ""))}</span></td>` +
      `<td>${r.overload_alert ? '<span class="badge b-crit">OVERLOAD</span>' : "—"}</td><td>${r.battery_kw > 0 ? "▼ " + r.battery_kw : r.battery_kw < 0 ? "▲ " + -r.battery_kw : "0"}</td><td>${esc(r.grid_kw)}</td><td>${esc(r.soc_pct)}</td></tr>`).join("");
    renderLog(d.log);
  }

  /* first load: fetch the demo day into the input table (does not auto-run) */
  fetch("api/sample").then((r) => r.json()).then((r) => setRows(r.rows)).catch(() => banner("warn", "⚠ Backend not reachable."));
})();
