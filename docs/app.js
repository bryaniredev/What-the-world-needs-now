/* What the World Needs Now - client. All data files are AES-GCM encrypted;
   the passphrase only ever exists in the visitor's head and the SITE_PASSPHRASE secret. */
(() => {
  "use strict";

  const KEY_SLOT = "wtwn.k";
  const $ = (s, el = document) => el.querySelector(s);
  const state = { key: null, meta: null, index: null, days: {}, view: "today", date: null, charts: [], range: 12 };

  // ------------------------------------------------------------------ utils
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : "#");
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const toB64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
  const fmtDate = (d) => new Date(d + "T00:00:00Z").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  const shortDate = (d) => new Date(d + "T00:00:00Z").toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
  const sum = (o) => Object.values(o || {}).reduce((a, b) => a + b, 0);
  const SOURCE_LABEL = {
    reddit: "Reddit communities", forums: "Merchant & pro forums", freelance: "Freelance gigs", hackernews: "Hacker News",
    stackexchange: "Stack Exchange", bluesky: "Bluesky", fixture: "Fixture",
  };
  const srcLabel = (s) => SOURCE_LABEL[s] || s;
  const weekLabel = (d) => `Week to ${fmtDate(d)}`;
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const fitBadge = (f) => `<span class="fit fit-${esc(f || "low")}" title="How well a software product could address this">SaaS fit: ${esc(f || "?")}</span>`;
  const COMPLAINT_LABEL = { missing_feature: "Missing feature", hard_to_use: "Hard to use", too_expensive: "Too expensive",
    unreliable: "Unreliable", integrations: "Integrations", bad_support: "Bad support", slow: "Slow",
    acquired_or_changed: "Changed or shut down", other: "Other" };
  const costBadges = (c) => {
    const arr = Array.isArray(c) ? c : c === "both" ? ["time", "money"] : (c === "time" || c === "money") ? [c] : [];
    return arr.map((x) => x === "time" ? `<span class="cost" title="Costs people time">⏱ time</span>` : `<span class="cost" title="Costs people money">$ money</span>`).join("");
  };
  const q = encodeURIComponent;
  function validateLinks(kw) {
    const links = [
      ["Google (ads + competitors)", `https://www.google.com/search?q=${q(kw)}`],
      ["“What is …” questions", `https://www.google.com/search?q=${q("what is " + kw)}`],
      ["Google Trends", `https://trends.google.com/trends/explore?q=${q(kw)}`],
      ["G2", `https://www.g2.com/search?query=${q(kw)}`],
      ["Capterra", `https://www.capterra.com/search/?query=${q(kw)}`],
      ["Reddit", `https://www.reddit.com/search/?q=${q(kw)}`],
      ["Keyword Planner", "https://ads.google.com/aw/keywordplanner/home"],
    ];
    return `<details class="validate"><summary>Validate “${esc(kw)}”</summary>
      <p class="small muted">Ads and several competing products = a market that already pays. Check search volume, then read competitors' 1-star reviews.</p>
      <div class="links">${links.map(([l, u]) => `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(l)} ↗</a>`).join("")}</div></details>`;
  }
  const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const series = () => [1, 2, 3, 4, 5, 6, 7, 8].map((i) => cssVar(`--s${i}`));

  // ----------------------------------------------------------------- crypto
  async function deriveKey(pass, meta) {
    const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pass), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey(
      { name: "PBKDF2", salt: b64(meta.salt), iterations: meta.iterations, hash: "SHA-256" },
      base, { name: "AES-GCM", length: 256 }, true, ["decrypt"]);
  }
  async function checkKey(key, meta) {
    try {
      const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(meta.check.iv) }, key, b64(meta.check.ct));
      return new TextDecoder().decode(pt) === "wtwn-ok";
    } catch { return false; }
  }
  async function decryptBlob(blob) {
    const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(blob.iv) }, state.key, b64(blob.ct));
    const stream = new Blob([pt]).stream().pipeThrough(new DecompressionStream("gzip"));
    return JSON.parse(await new Response(stream).text());
  }
  async function fetchEnc(path) {
    const r = await fetch(path + "?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return decryptBlob(await r.json());
  }
  async function getDay(date) {
    if (!state.days[date]) state.days[date] = await fetchEnc(`data/days/${date}.json`);
    return state.days[date];
  }

  // ------------------------------------------------------------------- gate
  async function loadMeta() {
    try {
      const r = await fetch("data/meta.json?t=" + Date.now(), { cache: "no-store" });
      return r.ok ? r.json() : null;
    } catch { return null; }
  }

  async function unlock(key) {
    state.key = key;
    try { sessionStorage.setItem(KEY_SLOT, toB64(await crypto.subtle.exportKey("raw", key))); } catch { /* private mode */ }
    state.index = await fetchEnc("data/index.json");
    $("#gate").hidden = true;
    $("#app").hidden = false;
    setupApp();
  }

  async function initGate() {
    state.meta = await loadMeta();
    const msg = $("#gate-msg");
    if (state.meta) {
      try {
        const saved = sessionStorage.getItem(KEY_SLOT);
        if (saved) {
          const key = await crypto.subtle.importKey("raw", b64(saved), "AES-GCM", true, ["decrypt"]);
          if (await checkKey(key, state.meta)) return unlock(key);
        }
      } catch { /* ignore */ }
    }
    $("#gate-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const pass = $("#pass").value.trim().toLowerCase();  // capitalisation never matters
      if (!pass) return;
      if (!state.meta) state.meta = await loadMeta();
      if (!state.meta) { msg.textContent = "No data yet. The first weekly run hasn't finished."; return; }
      const btn = $("#gate-form button");
      btn.disabled = true; msg.textContent = "Checking…";
      try {
        const key = await deriveKey(pass, state.meta);
        if (await checkKey(key, state.meta)) { msg.textContent = ""; await unlock(key); }
        else { msg.textContent = "Not quite."; $("#pass").select(); }
      } catch (err) {
        msg.textContent = "Couldn't load data: " + err.message;
      } finally { btn.disabled = false; }
    });
  }

  // -------------------------------------------------------------------- app
  function setupApp() {
    const days = state.index.days.map((d) => d.date).reverse();
    const sel = $("#day-select");
    sel.innerHTML = days.map((d) => `<option value="${esc(d)}">${esc(weekLabel(d))}</option>`).join("");
    state.date = days[0];
    sel.addEventListener("change", () => { state.date = sel.value; render(); });
    document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
      state.view = b.dataset.view;
      document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
      try { localStorage.setItem("wtwn.view", state.view); } catch { /* ignore */ }
      render();
    }));
    try {
      const v = localStorage.getItem("wtwn.view");
      if (v) document.querySelector(`.tabs button[data-view="${v}"]`)?.click();
    } catch { /* ignore */ }
    $("#lock").addEventListener("click", () => { try { sessionStorage.removeItem(KEY_SLOT); } catch { /* ignore */ } location.reload(); });
    $("#theme-toggle").addEventListener("click", () => {
      const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      const next = cur === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("wtwn.theme", next); } catch { /* ignore */ }
      render();
    });
    render();
  }

  function destroyCharts() { state.charts.forEach((c) => c.destroy()); state.charts = []; }

  async function render() {
    destroyCharts();
    $("#day-select").hidden = !["today", "browse"].includes(state.view);
    const main = $("#main");
    if (!state.index.days.length) { main.innerHTML = `<div class="empty">No runs yet.</div>`; return; }
    try {
      if (state.view === "today") await renderToday(main);
      else if (state.view === "trends") renderTrends(main);
      else if (state.view === "problems") renderProblems(main);
      else if (state.view === "browse") await renderBrowse(main);
      else if (state.view === "mines") renderMines(main);
      else renderAbout(main);
    } catch (e) {
      main.innerHTML = `<div class="empty">Couldn't render this view: ${esc(e.message)}</div>`;
    }
  }

  // -------------------------------------------------------------- this week
  const nicheChip = (n) => (n && n !== "General" ? `<span class="chip niche">${esc(n)}</span>` : "");

  function problemCard(p, run, problemsIndex) {
    const byId = Object.fromEntries(run.items.map((it) => [it.id, it]));
    const hist = problemsIndex[p.key];
    const isNew = hist && hist.first_seen === run.date;
    const seen = hist ? hist.days_seen : 1;
    const evidence = p.item_ids.map((id) => byId[id]).filter(Boolean);
    const extra = p.method === "ai" ? `<dl>
        <div><dt>Who</dt><dd>${esc(p.who)}</dd></div>
        <div><dt>Why it's unmet</dt><dd>${esc(p.why_unmet)}</dd></div>
        <div><dt>Possible solution</dt><dd>${esc(p.solution_idea)}</dd></div>
        ${(p.mvp_features || []).length ? `<div><dt>Bare-minimum MVP</dt><dd><ol class="mvp">${p.mvp_features.map((f) => `<li>${esc(f)}</li>`).join("")}</ol></dd></div>` : ""}</dl>` : "";
    const costs = p.costs || [...new Set(evidence.flatMap((it) => it.costs || []))];
    return `<article class="card">
      <div class="meta">${fitBadge(p.saas_fit)}${isNew ? `<span class="new-badge">New</span>` : `<span class="chip">Seen ${plural(seen, "week")}</span>`}${nicheChip(p.niche)}${costBadges(costs)}</div>
      <h3>${esc(p.title)}</h3>
      <p>${esc(p.summary)}</p>
      ${extra}
      <div class="meta">${(p.sources || []).map((s) => `<span class="chip">${esc(srcLabel(s))}</span>`).join("")}<span class="muted">${plural(evidence.length, "lead")}</span></div>
      <details><summary>Evidence</summary><ul>${evidence.slice(0, 12).map((it) =>
        `<li><a href="${safeUrl(it.url)}" target="_blank" rel="noopener noreferrer">${esc(it.need || it.title)}</a> <span class="muted">· ${esc(it.channel)}</span></li>`).join("")}</ul></details>
      ${validateLinks(p.search_keyword || p.title)}
    </article>`;
  }

  function itemRow(it) {
    const need = it.need && it.need !== it.title && !it.need.startsWith(it.title.replace(/…$/, "")) ? `<div class="need">“${esc(it.need)}”</div>` : "";
    return `<div class="item">
      <div class="t"><a href="${safeUrl(it.url)}" target="_blank" rel="noopener noreferrer">${esc(it.title || "(untitled)")}</a></div>
      ${need}
      <div class="x">${esc(it.text.slice(0, 280))}${it.text.length > 280 ? "…" : ""}</div>
      <div class="meta">${fitBadge(it.saas_fit)}${nicheChip(it.niche)}<span class="chip">${esc(it.channel)}</span>${costBadges(it.costs)}
        ${(it.signal_labels || []).slice(0, 3).map((s) => `<span class="chip sig">${esc(s)}</span>`).join("")}
        <span class="score" title="Lead score: strength of the stated need + engagement">● ${esc(it.pain_score)}</span></div>
    </div>`;
  }

  const nicheOptions = (list, cur) => `<option value="all">All niches</option>${list.map((n) => `<option ${n === cur ? "selected" : ""}>${esc(n)}</option>`).join("")}`;

  async function renderToday(main) {
    const run = await getDay(state.date);
    const probs = state.index.problems || {};
    const status = Object.entries(run.sources || {});
    const ok = status.filter(([, s]) => s.ok).length;
    const nicheCounts = {};
    run.items.forEach((it) => { if (it.niche !== "General") nicheCounts[it.niche] = (nicheCounts[it.niche] || 0) + 1; });
    const nichesSorted = Object.entries(nicheCounts).sort((a, b) => b[1] - a[1]);
    const newCount = run.problems.filter((p) => probs[p.key]?.first_seen === run.date).length;
    const highFit = run.items.filter((it) => it.saas_fit === "high").length;
    let fitFilter = "all"; try { fitFilter = sessionStorage.getItem("wtwn.fit") || "all"; } catch { /* ignore */ }
    const nf = state.tniche || "all";
    const shown = run.problems.filter((p) => (fitFilter === "all" || p.saas_fit === fitFilter) && (nf === "all" || p.niche === nf));
    const leads = run.items.filter((it) => nf === "all" || it.niche === nf);
    const filtered = sum(run.filtered);

    main.innerHTML = `
      <h2>${esc(weekLabel(run.date))}</h2>
      <p class="sub">${run.ai && run.ai.startsWith("ok") ? "Problems named and written up by Claude from this week's leads."
        : "Problems are grouped by who has them and what kind of problem it is. Add an ANTHROPIC_API_KEY secret for named problems with written summaries."}</p>
      <div class="tiles">
        <div class="tile"><div class="label">Leads this week</div><div class="value">${run.items.length}</div><div class="note">posts stating an unmet need, from ${(run.new_count || 0).toLocaleString()} read</div></div>
        <div class="tile"><div class="label">Problem areas</div><div class="value">${run.problems.length}</div><div class="note">${newCount} first seen this week</div></div>
        <div class="tile"><div class="label">Niches with leads</div><div class="value">${nichesSorted.length}</div><div class="note">${nichesSorted[0] ? `most: ${esc(nichesSorted[0][0])} (${nichesSorted[0][1]})` : ""}</div></div>
        <div class="tile"><div class="label">High SaaS fit</div><div class="value">${run.items.length ? Math.round(100 * highFit / run.items.length) : 0}%</div><div class="note">${highFit} leads${filtered ? ` · ${filtered} promo/support posts removed` : ""}</div></div>
      </div>
      <h2>Top problems</h2>
      <div class="toolbar"><span class="muted small">SaaS fit</span>
        <div class="seg" id="fit-seg">${["all", "high", "medium", "low"].map((f) => `<button data-f="${f}" aria-pressed="${f === fitFilter}">${f}</button>`).join("")}</div>
        <select id="tniche" aria-label="Niche">${nicheOptions(nichesSorted.map(([n]) => n), nf)}</select></div>
      ${shown.length ? `<div class="cards">${shown.map((p) => problemCard(p, run, probs)).join("")}</div>` : `<div class="empty">No problems match.</div>`}
      <h2>Strongest individual leads</h2>
      <div class="items">${leads.slice(0, 20).map(itemRow).join("") || `<div class="empty">Nothing this week.</div>`}</div>
      <h2>Sources</h2>
      <div class="panel table-wrap"><table><thead><tr><th>Source</th><th>Status</th><th class="num">Posts read</th><th class="num">Leads kept</th><th>Note</th></tr></thead><tbody>
      ${status.map(([n, s]) => `<tr><td>${esc(srcLabel(n))}</td><td class="${s.ok ? "status-ok" : "status-bad"}">${s.ok ? "✓ ok" : "✕ failed"}</td><td class="num">${esc((s.read ?? "").toLocaleString())}</td><td class="num">${esc(s.count ?? 0)}</td><td class="muted small">${esc(s.error || s.note || "")}</td></tr>`).join("")}
      </tbody></table><p class="muted small">${ok}/${status.length} sources responded. Generated ${esc(run.generated_at)}.</p></div>`;
    $("#fit-seg").addEventListener("click", (e) => {
      const f = e.target.closest("button")?.dataset.f; if (!f) return;
      try { sessionStorage.setItem("wtwn.fit", f); } catch { /* ignore */ }
      render();
    });
    $("#tniche").addEventListener("change", (e) => { state.tniche = e.target.value; render(); });
  }

  // ----------------------------------------------------------------- trends
  function rangeDays() {
    const all = state.index.days;
    return state.range === 0 ? all : all.slice(-state.range);
  }

  function chartDefaults() {
    Chart.defaults.color = cssVar("--text-2");
    Chart.defaults.borderColor = cssVar("--grid");
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  }

  function lineChart(canvas, labels, datasets, opts = {}) {
    const colors = opts.colors || series();
    const ch = new Chart(canvas, {
      type: opts.type || "line",
      data: {
        labels,
        datasets: datasets.map((d, i) => ({
          label: d.label, data: d.data,
          borderColor: colors[i % 8], backgroundColor: colors[i % 8],
          borderWidth: 2, pointRadius: labels.length > 40 ? 0 : 3, pointHoverRadius: 5, tension: 0.25,
          borderRadius: opts.type === "bar" ? 4 : 0, borderSkipped: "start",
          ...(opts.type === "bar" ? { borderColor: cssVar("--surface"), borderWidth: { top: 2 } } : {}),
        })),
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true } },
          tooltip: { itemSort: (a, b) => b.raw - a.raw },
        },
        scales: {
          x: { stacked: !!opts.stacked, grid: { display: false } },
          y: { stacked: !!opts.stacked, beginAtZero: true, ticks: { precision: 0 } },
        },
      },
    });
    state.charts.push(ch);
    return ch;
  }

  // latest week against the week before
  function delta(getter, key) {
    const all = state.index.days;
    const a = all.length ? (getter(all[all.length - 1])[key] || 0) : 0;
    const b = all.length > 1 ? (getter(all[all.length - 2])[key] || 0) : 0;
    return { a, b, pct: b ? (a - b) / b : (a ? Infinity : 0) };
  }

  function arrow(pct) {
    if (pct === Infinity) return `<span class="up">new</span>`;
    if (!isFinite(pct) || pct === 0) return `<span class="muted">–</span>`;
    return `<span class="${pct > 0 ? "up" : "down"}">${pct > 0 ? "▲" : "▼"} ${Math.abs(Math.round(pct * 100))}%</span>`;
  }

  function pickerChart(main, id, field, skip, stateKey, days, labels) {
    const totals = {};
    days.forEach((d) => Object.entries(d[field] || {}).forEach(([t, n]) => { if (t !== skip) totals[t] = (totals[t] || 0) + n; }));
    const all = Object.entries(totals).sort((a, b) => b[1] - a[1]).map(([t]) => t);
    const picked = (state[stateKey] || all.slice(0, 6)).filter((t) => totals[t]).slice(0, 8);
    $(`#${id}-pick`).innerHTML = all.slice(0, 24).map((t) => `<button class="chip-btn" data-t="${esc(t)}" aria-pressed="${picked.includes(t)}">${esc(t)}</button>`).join("");
    $(`#${id}-pick`).addEventListener("click", (e) => {
      const t = e.target.closest("button")?.dataset.t; if (!t) return;
      const cur = picked.slice(), i = cur.indexOf(t);
      if (i >= 0) cur.splice(i, 1); else if (cur.length < 8) cur.push(t);
      state[stateKey] = cur; render();
    });
    if (picked.length) lineChart($(`#${id}`), labels, picked.map((t) => ({ label: t, data: days.map((d) => (d[field] || {})[t] || 0) })));
    else $(`#${id}`).parentElement.innerHTML = `<div class="empty">Pick one above.</div>`;
    return all;
  }

  function risingTable(title, names, field) {
    const rows = names.map((t) => ({ t, ...delta((d) => d[field] || {}, t) })).filter((r) => r.a >= 2)
      .sort((x, y) => (y.a - y.b) - (x.a - x.b)).slice(0, 12);
    return `<div class="panel"><strong>${title}</strong> <span class="muted small">latest week vs the week before</span>
      <div class="table-wrap"><table><thead><tr><th>${title.replace("Rising ", "").replace(/^./, (c) => c.toUpperCase())}</th><th class="num">Latest</th><th class="num">Before</th><th class="num">Change</th></tr></thead><tbody>
      ${rows.map((r) => `<tr><td>${esc(r.t)}</td><td class="num">${r.a}</td><td class="num">${r.b}</td><td class="num">${arrow(r.pct)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">Not enough data yet.</td></tr>`}
      </tbody></table></div></div>`;
  }

  function renderTrends(main) {
    chartDefaults();
    const days = rangeDays();
    const labels = days.map((d) => shortDate(d.date));
    const sourcesAll = [...new Set(days.flatMap((d) => Object.keys(d.by_source || {})))];
    main.innerHTML = `
      <h2>Trends</h2>
      <div class="toolbar">
        <div class="seg" id="range-seg">${[[8, "8 weeks"], [12, "12 weeks"], [26, "26 weeks"], [52, "1 year"], [0, "All"]].map(([v, l]) => `<button data-r="${v}" aria-pressed="${state.range === v}">${l}</button>`).join("")}</div>
        <span class="muted small">${plural(days.length, "weekly run")} of data</span>
      </div>
      ${days.length < 2 ? `<div class="empty">Trends appear after the second weekly run.</div>` : ""}
      <div class="panel"><strong>Leads per week, by niche</strong>
        <div class="toolbar small" style="margin-top:8px"><span class="muted">Niches (up to 8):</span><div id="c-niches-pick" class="chips"></div></div>
        <div class="chart-box"><canvas id="c-niches"></canvas></div></div>
      <div class="panel" style="margin-top:12px"><strong>Leads per week, by problem area</strong>
        <div class="toolbar small" style="margin-top:8px"><span class="muted">Problem areas (up to 8):</span><div id="c-themes-pick" class="chips"></div></div>
        <div class="chart-box"><canvas id="c-themes"></canvas></div></div>
      <div class="grid2" style="margin-top:12px" id="rising"></div>
      <div class="grid2" style="margin-top:12px">
        <div class="panel"><strong>Leads per week, by source</strong><div class="chart-box"><canvas id="c-sources"></canvas></div></div>
        <div class="panel"><strong>SaaS fit mix per week</strong><div class="chart-box"><canvas id="c-fit"></canvas></div></div>
      </div>`;
    $("#range-seg").addEventListener("click", (e) => { const r = e.target.closest("button")?.dataset.r; if (r != null) { state.range = +r; render(); } });
    const niches = pickerChart(main, "c-niches", "by_niche", "General", "pickedNiches", days, labels);
    const themes = pickerChart(main, "c-themes", "by_theme", "Other needs", "pickedThemes", days, labels);
    $("#rising").innerHTML = risingTable("Rising niches", niches, "by_niche") + risingTable("Rising problem areas", themes, "by_theme");
    lineChart($("#c-sources"), labels, sourcesAll.slice(0, 8).map((s) => ({ label: srcLabel(s), data: days.map((d) => (d.by_source || {})[s] || 0) })), { type: "bar", stacked: true });
    lineChart($("#c-fit"), labels, ["high", "medium", "low"].map((f) => ({ label: f, data: days.map((d) => (d.by_fit || {})[f] || 0) })),
      { type: "bar", stacked: true, colors: [cssVar("--seq-3"), cssVar("--seq-2"), cssVar("--seq-1")] });
  }

  // --------------------------------------------------------------- problems
  function sparkline(counts, dates) {
    const vals = dates.map((d) => counts[d] || 0);
    const max = Math.max(1, ...vals), w = 120, h = 26, n = vals.length;
    if (n < 2) return "";
    const pts = vals.map((v, i) => `${(i / (n - 1)) * (w - 4) + 2},${h - 2 - (v / max) * (h - 4)}`).join(" ");
    return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline fill="none" stroke="${cssVar("--s1")}" stroke-width="2" stroke-linejoin="round" points="${pts}"/></svg>`;
  }

  function renderProblems(main) {
    const dates = state.index.days.map((d) => d.date).slice(-12);
    const latest = dates[dates.length - 1];
    const q = state.pq || "", fit = state.pfit || "all", sort = state.psort || "days_seen", nf = state.pniche || "all";
    const all = Object.entries(state.index.problems || {}).map(([key, p]) => ({ key, ...p, total: sum(p.counts), recent: p.counts[latest] || 0 }));
    const niches = [...new Set(all.map((p) => p.niche).filter((n) => n && n !== "General"))].sort();
    const rows = all.filter((p) => (fit === "all" || p.saas_fit === fit) && (nf === "all" || p.niche === nf)
      && (!q || (p.title + " " + (p.summary || "") + " " + (p.theme || "") + " " + (p.niche || "")).toLowerCase().includes(q.toLowerCase())));
    rows.sort((a, b) => (sort === "first_seen" || sort === "last_seen") ? b[sort].localeCompare(a[sort]) : (b[sort] - a[sort]) || (b.total - a.total));

    main.innerHTML = `
      <h2>Recurring problems</h2>
      <p class="sub">Every problem ever detected. One that keeps coming back week after week, from different people and sources, is the strongest sign that it's real and still unsolved.</p>
      <div class="toolbar">
        <input id="pq" class="input" type="search" placeholder="Search problems" value="${esc(q)}">
        <div class="seg" id="pfit">${["all", "high", "medium", "low"].map((f) => `<button data-f="${f}" aria-pressed="${f === fit}">${f}</button>`).join("")}</div>
        <select id="pniche" aria-label="Niche">${nicheOptions(niches, nf)}</select>
        <select id="psort" aria-label="Sort">${[["days_seen", "Most weeks seen"], ["total", "Most leads"], ["recent", "Most leads, latest week"], ["last_seen", "Most recent"], ["first_seen", "Newest"]].map(([v, l]) => `<option value="${v}" ${v === sort ? "selected" : ""}>${l}</option>`).join("")}</select>
        <span class="muted small">${plural(rows.length, "problem")}</span>
      </div>
      <div class="panel table-wrap"><table>
        <thead><tr><th>Problem</th><th>Fit</th><th class="num">Weeks</th><th class="num">Leads</th><th class="num">Latest</th><th>Last 12 runs</th><th>Last seen</th></tr></thead>
        <tbody>${rows.slice(0, 300).map((p) => `<tr class="clickable" data-key="${esc(p.key)}">
          <td><strong>${esc(p.title)}</strong><div class="muted small">${(p.sources || []).map(srcLabel).map(esc).join(", ")}</div>
            <div class="small detail" hidden>${esc(p.summary || "")}<br><span class="muted">First seen ${esc(p.first_seen)}</span>${p.search_keyword ? validateLinks(p.search_keyword) : ""}</div></td>
          <td>${fitBadge(p.saas_fit)}</td><td class="num">${p.days_seen}</td><td class="num">${p.total}</td><td class="num">${p.recent}</td>
          <td>${sparkline(p.counts, dates)}</td><td class="small">${esc(shortDate(p.last_seen))}</td></tr>`).join("") || `<tr><td colspan="7" class="muted">No problems yet.</td></tr>`}
        </tbody></table></div>`;

    $("#pq").addEventListener("input", (e) => { state.pq = e.target.value; clearTimeout(state.pqT); state.pqT = setTimeout(() => { render().then(() => { const el = $("#pq"); el.focus(); el.setSelectionRange(el.value.length, el.value.length); }); }, 250); });
    $("#pfit").addEventListener("click", (e) => { const f = e.target.closest("button")?.dataset.f; if (f) { state.pfit = f; render(); } });
    $("#pniche").addEventListener("change", (e) => { state.pniche = e.target.value; render(); });
    $("#psort").addEventListener("change", (e) => { state.psort = e.target.value; render(); });
    main.querySelectorAll("tr.clickable").forEach((tr) => tr.addEventListener("click", (e) => {
      if (e.target.closest("a, summary, details")) return;
      const d = tr.querySelector(".detail"); d.hidden = !d.hidden;
    }));
  }

  // ------------------------------------------------------------ idea mines
  function windowDates(n) { return state.index.days.map((d) => d.date).slice(-n); }
  function inWindow(counts, dates) { return dates.reduce((s, d) => s + ((counts || {})[d] || 0), 0); }
  const weeksIn = (counts, dates) => dates.filter((d) => (counts || {})[d]).length;

  function renderMines(main) {
    const win = state.mwin || 12;
    const dates = windowDates(win);
    const chips = (obj, label = (t) => t) => Object.entries(obj).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([t, n]) => `<span class="chip">${esc(label(t))} ${n}</span>`).join("");
    const quotes = (list) => `<ul class="quotes">${(list || []).map((x) => `<li><a href="${safeUrl(x.url)}" target="_blank" rel="noopener noreferrer">“${esc(x.need || x.text || x.title)}”</a> <span class="muted">· ${esc(x.where || "")} · ${esc(x.date || "")}</span></li>`).join("")}</ul>`;

    const niches = Object.entries(state.index.niches || {}).map(([name, e]) => ({
      name, ...e, n: inWindow(e.counts, dates), weeks: weeksIn(e.counts, dates),
      themesW: Object.fromEntries(Object.entries(e.themes || {}).map(([t, c]) => [t, inWindow(c, dates)]).filter(([, n]) => n)),
    })).filter((r) => r.n && r.name !== "General").sort((a, b) => b.n - a.n);

    const products = Object.values(state.index.products || {}).map((p) => ({
      ...p, n: inWindow(p.counts, dates),
      typesW: Object.fromEntries(Object.entries(p.types || {}).map(([t, c]) => [t, inWindow(c, dates)]).filter(([, n]) => n)),
    })).filter((p) => p.n).sort((a, b) => b.n - a.n);

    const sheetRows = Object.entries(state.index.spreadsheet_uses || {}).map(([phrase, e]) => ({
      phrase, ...e, n: inWindow(e.counts, dates), weeks: weeksIn(e.counts, dates),
    })).filter((r) => r.n).sort((a, b) => (b.weeks - a.weeks) || (b.n - a.n)).slice(0, 60).map((r) => `<tr>
        <td><strong>${esc(r.phrase)}</strong>${(r.examples || []).length ? `<div class="small muted">e.g. ${r.examples.slice(0, 2).map((x) =>
          `<a href="${safeUrl(x.url)}" target="_blank" rel="noopener noreferrer">${esc((x.title || "").slice(0, 60))}</a> (${esc(x.where || "")})`).join(" · ")}</div>` : ""}</td>
        <td class="num">${r.n}</td><td class="num">${r.weeks}</td></tr>`).join("");

    main.innerHTML = `
      <h2>Idea mines</h2>
      <p class="sub">Three other ways to read the same leads: who is struggling, which products people are trying to leave, and what is still being done in spreadsheets.</p>
      <div class="toolbar"><div class="seg" id="mwin">${[[4, "4 weeks"], [12, "12 weeks"], [26, "26 weeks"], [5200, "All"]].map(([v, l]) => `<button data-w="${v}" aria-pressed="${win === v}">${l}</button>`).join("")}</div></div>

      <h2>Niches with the most unmet needs</h2>
      <p class="sub">Each row is a group of people, how many of them stated a need, and what kind. Click a row to read examples in their own words.</p>
      <div class="panel table-wrap"><table>
        <thead><tr><th>Niche</th><th>What they need help with</th><th class="num">Leads</th><th class="num">Weeks</th></tr></thead>
        <tbody>${niches.slice(0, 60).map((r) => `<tr class="clickable">
          <td><strong>${esc(r.name)}</strong></td>
          <td><div class="chips">${chips(r.themesW)}</div><div class="detail small" hidden>${quotes(r.examples)}</div></td>
          <td class="num">${r.n}</td><td class="num">${r.weeks}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">Nothing in this window yet.</td></tr>`}</tbody></table></div>

      <div class="grid2" style="margin-top:12px">
        <div class="panel table-wrap"><strong>Products people want to leave</strong>
          <p class="small muted">Named in “alternative to…”, “switching from…”, “outgrown…” posts. Many people leaving the same product for the same reason is an opening for a leaner alternative.</p>
          <table><thead><tr><th>Product</th><th>Why, and who</th><th class="num">Mentions</th></tr></thead>
          <tbody>${products.slice(0, 50).map((p) => `<tr class="clickable">
            <td><strong>${esc(p.name)}</strong></td>
            <td><div class="chips">${chips(p.typesW, (t) => COMPLAINT_LABEL[t] || t)}</div>
              <div class="small muted">${Object.entries(p.niches || {}).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([n]) => esc(n)).join(", ")}</div>
              <div class="detail small" hidden>${quotes(p.quotes)}</div></td>
            <td class="num">${p.n}</td></tr>`).join("") || `<tr><td colspan="3" class="muted">Nothing in this window yet.</td></tr>`}</tbody></table></div>
        <div class="panel table-wrap"><strong>What people use spreadsheets for</strong>
          <p class="small muted">“We track X in a spreadsheet.” Each one is a workflow that might deserve real software.</p>
          <table><thead><tr><th>Used for</th><th class="num">Mentions</th><th class="num">Weeks</th></tr></thead>
          <tbody>${sheetRows || `<tr><td colspan="3" class="muted">Nothing yet.</td></tr>`}</tbody></table></div>
      </div>`;

    $("#mwin").addEventListener("click", (e) => { const w = e.target.closest("button")?.dataset.w; if (w) { state.mwin = +w; render(); } });
    main.querySelectorAll("tr.clickable").forEach((tr) => tr.addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      const d = tr.querySelector(".detail"); d.hidden = !d.hidden;
    }));
  }

  // ----------------------------------------------------------------- browse
  async function renderBrowse(main) {
    const run = await getDay(state.date);
    const q = state.bq || "", src = state.bsrc || "all", fit = state.bfit || "all", theme = state.btheme || "all", nf = state.bniche || "all";
    const themes = [...new Set(run.items.flatMap((it) => it.themes))].sort();
    const niches = [...new Set(run.items.map((it) => it.niche))].sort();
    const srcs = [...new Set(run.items.map((it) => it.source))];
    const items = run.items.filter((it) => (src === "all" || it.source === src) && (fit === "all" || it.saas_fit === fit)
      && (theme === "all" || it.themes.includes(theme)) && (nf === "all" || it.niche === nf)
      && (!q || (it.title + " " + it.text + " " + it.channel).toLowerCase().includes(q.toLowerCase())));
    main.innerHTML = `
      <h2>Every lead, ${esc(weekLabel(run.date).toLowerCase())}</h2>
      <div class="toolbar">
        <input id="bq" class="input" type="search" placeholder="Search text" value="${esc(q)}">
        <select id="bniche" aria-label="Niche">${nicheOptions(niches, nf)}</select>
        <select id="btheme"><option value="all">All problem areas</option>${themes.map((t) => `<option ${t === theme ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
        <select id="bsrc"><option value="all">All sources</option>${srcs.map((s) => `<option value="${esc(s)}" ${s === src ? "selected" : ""}>${esc(srcLabel(s))}</option>`).join("")}</select>
        <select id="bfit">${["all", "high", "medium", "low"].map((f) => `<option value="${f}" ${f === fit ? "selected" : ""}>${f === "all" ? "Any SaaS fit" : "SaaS fit: " + f}</option>`).join("")}</select>
        <span class="muted small">${items.length} of ${run.items.length}</span>
      </div>
      <div class="items">${items.slice(0, 400).map(itemRow).join("") || `<div class="empty">Nothing matches.</div>`}</div>`;
    const re = () => render();
    $("#bq").addEventListener("input", (e) => { state.bq = e.target.value; clearTimeout(state.bqT); state.bqT = setTimeout(() => re().then(() => { const el = $("#bq"); el.focus(); el.setSelectionRange(el.value.length, el.value.length); }), 250); });
    $("#bsrc").addEventListener("change", (e) => { state.bsrc = e.target.value; re(); });
    $("#btheme").addEventListener("change", (e) => { state.btheme = e.target.value; re(); });
    $("#bniche").addEventListener("change", (e) => { state.bniche = e.target.value; re(); });
    $("#bfit").addEventListener("change", (e) => { state.bfit = e.target.value; re(); });
  }

  // ------------------------------------------------------------------ about
  function renderAbout(main) {
    main.innerHTML = `<div class="prose">
      <h2>How it works</h2>
      <p>Every Monday a GitHub Action reads the past week's posts in places where people who do a job talk to each other, keeps only the posts where someone states a need that isn't being met, works out who they are (the niche) and what kind of problem it is, and adds the result to the history you see here.</p>
      <h2>Where it looks, and why</h2>
      <ul>
        <li><strong>Reddit communities of practitioners</strong> (about 160, grouped into some 50 niches: dental practices, landlords, HVAC contractors, bookkeepers, restaurant owners, teachers, caregivers…). The whole week of posts is read, not a keyword search, so “how do you all handle X?” is caught as well as “is there a tool for X?”.</li>
        <li><strong>Merchant and professional forums</strong>: the Shopify Community (merchants asking “is there an app that…”), Spiceworks (IT admins asking for software), Mac Power Users, and the Make community (workflows people can't automate).</li>
        <li><strong>Freelance gigs</strong> on Freelancer.com where a business pays for a custom tool or for repetitive manual work. Nothing off the shelf fit, and there's a budget on the table.</li>
        <li><strong>Hacker News</strong>: Ask HN posts, comments using an unambiguous need phrase, and every reply in “what problem do you wish was solved?” threads.</li>
        <li><strong>Stack Exchange Software Recommendations</strong>: every question is someone who looked for software and couldn't find it.</li>
        <li><strong>Bluesky</strong>: “I wish there was an app that…” from the general public.</li>
      </ul>
      <h2>What counts as a lead</h2>
      <p>A post is kept only if it does at least one of these: asks for a tool, wishes something existed, says they'd pay, says nothing on the market fits, asks how others cope, describes doing something by hand or in a spreadsheet that has become painful, or wants to leave a named product. Removed on purpose: people promoting or validating their own product, and one-product support questions (“won't load after the update”).</p>
      <h2>Reading it</h2>
      <ul>
        <li><strong>Niche</strong>: who has the problem. From the community the post came from, or from the text (“I run a landscaping company”).</li>
        <li><strong>The quote</strong> on each lead is the sentence where the person states the need.</li>
        <li><strong>SaaS fit</strong>: <em>high</em> means software clearly helps; <em>low</em> means the problem is structural or physical. Low-fit problems are kept when many people share them.</li>
        <li><strong>Weeks seen</strong> on the Problems tab is the best signal: the same need, from different people, week after week.</li>
        <li><strong>⏱ time / $ money</strong>: what the problem costs them. Those are the problems people pay to remove.</li>
      </ul>
      <h2>Validating an idea from here</h2>
      <ol>
        <li>Open the evidence links and read the replies. Are others saying “same”? Did anyone name a tool that solves it?</li>
        <li>Check the problem appears in more than one source and in more than one week.</li>
        <li>Use the <em>Validate</em> links on each problem: are there ads and competitors for the search phrase? Is search volume steady or rising?</li>
        <li>Look at <em>Products people want to leave</em> for an incumbent in that niche: that's a market that already pays.</li>
        <li>Reply to or DM a few posters and ask how they handle it today and what it costs them.</li>
        <li>Before building, put up a one-page landing page with an email form, share it where those people are, and aim for 20–30 sign-ups.</li>
      </ol>
      <p class="muted small">Index last updated ${esc(state.index.updated || "")}.</p>
    </div>`;
  }

  // ------------------------------------------------------------------- boot
  try { const t = localStorage.getItem("wtwn.theme"); if (t) document.documentElement.dataset.theme = t; } catch { /* ignore */ }
  if (!window.crypto?.subtle || typeof DecompressionStream === "undefined") {
    $("#gate-msg").textContent = "This browser is too old to open the data.";
  } else {
    initGate();
  }
})();
