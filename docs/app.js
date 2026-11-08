/* What the World Needs Now - client. All data files are AES-GCM encrypted;
   the passphrase only ever exists in the visitor's head and the SITE_PASSPHRASE secret. */
(() => {
  "use strict";

  const KEY_SLOT = "wtwn.k";
  const $ = (s, el = document) => el.querySelector(s);
  const state = { key: null, meta: null, index: null, days: {}, view: "today", date: null, charts: [], range: 30 };

  // ------------------------------------------------------------------ utils
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : "#");
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const toB64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
  const fmtDate = (d) => new Date(d + "T00:00:00Z").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  const shortDate = (d) => new Date(d + "T00:00:00Z").toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
  const sum = (o) => Object.values(o || {}).reduce((a, b) => a + b, 0);
  const SOURCE_LABEL = {
    hackernews: "Hacker News", reddit: "Reddit", stackexchange: "Stack Exchange", github: "GitHub issues",
    app_store: "App Store", shopify_apps: "Shopify apps", wordpress_plugins: "WordPress plugins", jobs: "Job posts", fixture: "Fixture",
  };
  const srcLabel = (s) => SOURCE_LABEL[s] || s;
  const fitBadge = (f) => `<span class="fit fit-${esc(f || "low")}" title="How well a software product could address this">SaaS fit: ${esc(f || "?")}</span>`;
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
      const pass = $("#pass").value.trim();
      if (!pass) return;
      if (!state.meta) state.meta = await loadMeta();
      if (!state.meta) { msg.textContent = "No data yet. The first daily run hasn't finished."; return; }
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
    sel.innerHTML = days.map((d) => `<option value="${esc(d)}">${esc(fmtDate(d))}</option>`).join("");
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
      else renderAbout(main);
    } catch (e) {
      main.innerHTML = `<div class="empty">Couldn't render this view: ${esc(e.message)}</div>`;
    }
  }

  // ------------------------------------------------------------------ today
  function problemCard(p, day, problemsIndex) {
    const byId = Object.fromEntries(day.items.map((it) => [it.id, it]));
    const hist = problemsIndex[p.key];
    const isNew = hist && hist.first_seen === day.date;
    const seen = hist ? hist.days_seen : 1;
    const evidence = p.item_ids.map((id) => byId[id]).filter(Boolean);
    const extra = p.method === "ai" ? `<dl>
        <div><dt>Who</dt><dd>${esc(p.who)}</dd></div>
        <div><dt>Why it's unmet</dt><dd>${esc(p.why_unmet)}</dd></div>
        <div><dt>Possible solution</dt><dd>${esc(p.solution_idea)}</dd></div></dl>` : "";
    return `<article class="card">
      <div class="meta">${fitBadge(p.saas_fit)}${isNew ? `<span class="new-badge">New</span>` : `<span class="chip">Seen ${seen} day${seen === 1 ? "" : "s"}</span>`}<span class="chip">${esc(p.theme || "")}</span></div>
      <h3>${esc(p.title)}</h3>
      <p>${esc(p.summary)}</p>
      ${extra}
      <div class="meta">${(p.sources || []).map((s) => `<span class="chip">${esc(srcLabel(s))}</span>`).join("")}<span class="muted">${evidence.length} mention${evidence.length === 1 ? "" : "s"}</span></div>
      <details><summary>Evidence</summary><ul>${evidence.slice(0, 12).map((it) =>
        `<li><a href="${safeUrl(it.url)}" target="_blank" rel="noopener noreferrer">${esc(it.title || it.text.slice(0, 90))}</a> <span class="muted">· ${esc(it.channel)}</span></li>`).join("")}</ul></details>
    </article>`;
  }

  function itemRow(it) {
    return `<div class="item">
      <div class="t"><a href="${safeUrl(it.url)}" target="_blank" rel="noopener noreferrer">${esc(it.title || "(untitled)")}</a></div>
      <div class="x">${esc(it.text.slice(0, 320))}${it.text.length > 320 ? "…" : ""}</div>
      <div class="meta">${fitBadge(it.saas_fit)}<span class="chip">${esc(it.kind_label)}</span><span class="chip">${esc(it.channel)}</span>
        ${(it.signals || []).slice(0, 3).map((s) => `<span class="chip">“${esc(s)}”</span>`).join("")}
        <span class="score" title="Pain score: strength of complaint language + engagement">● ${esc(it.pain_score)}</span></div>
    </div>`;
  }

  async function renderToday(main) {
    const day = await getDay(state.date);
    const probs = state.index.problems || {};
    const status = Object.entries(day.sources || {});
    const ok = status.filter(([, s]) => s.ok).length;
    const themeCounts = {};
    day.items.forEach((it) => it.themes.forEach((t) => { if (t !== "Other") themeCounts[t] = (themeCounts[t] || 0) + 1; }));
    const topTheme = Object.entries(themeCounts).sort((a, b) => b[1] - a[1])[0];
    const newCount = day.problems.filter((p) => probs[p.key]?.first_seen === day.date).length;
    const highFit = day.items.filter((it) => it.saas_fit === "high").length;
    let fitFilter = "all"; try { fitFilter = sessionStorage.getItem("wtwn.fit") || "all"; } catch { /* ignore */ }
    const shown = day.problems.filter((p) => fitFilter === "all" || p.saas_fit === fitFilter);

    main.innerHTML = `
      <h2>${esc(fmtDate(day.date))}</h2>
      <p class="sub">${day.ai && day.ai.startsWith("ok") ? "Problems grouped and summarised by Claude." : "Problems grouped by shared keywords (add an ANTHROPIC_API_KEY secret for written summaries)."}</p>
      <div class="tiles">
        <div class="tile"><div class="label">Pain points found</div><div class="value">${day.items.length}</div><div class="note">from ${day.new_count} new posts scanned</div></div>
        <div class="tile"><div class="label">Distinct problems</div><div class="value">${day.problems.length}</div><div class="note">${newCount} first seen today</div></div>
        <div class="tile"><div class="label">High SaaS fit</div><div class="value">${day.items.length ? Math.round(100 * highFit / day.items.length) : 0}%</div><div class="note">${highFit} pain points</div></div>
        <div class="tile"><div class="label">Loudest theme</div><div class="value" style="font-size:18px">${esc(topTheme ? topTheme[0] : "-")}</div><div class="note">${topTheme ? topTheme[1] + " mentions" : ""}</div></div>
      </div>
      <h2>Top problems</h2>
      <div class="toolbar"><span class="muted small">SaaS fit</span>
        <div class="seg" id="fit-seg">${["all", "high", "medium", "low"].map((f) => `<button data-f="${f}" aria-pressed="${f === fitFilter}">${f}</button>`).join("")}</div></div>
      ${shown.length ? `<div class="cards">${shown.map((p) => problemCard(p, day, probs)).join("")}</div>` : `<div class="empty">No problems match.</div>`}
      <h2>Loudest individual complaints</h2>
      <div class="items">${day.items.slice(0, 15).map(itemRow).join("") || `<div class="empty">Nothing today.</div>`}</div>
      <h2>Sources</h2>
      <div class="panel table-wrap"><table><thead><tr><th>Source</th><th>Status</th><th class="num">Items</th><th>Note</th></tr></thead><tbody>
      ${status.map(([n, s]) => `<tr><td>${esc(srcLabel(n))}</td><td class="${s.ok ? "status-ok" : "status-bad"}">${s.ok ? "✓ ok" : "✕ failed"}</td><td class="num">${esc(s.count ?? 0)}</td><td class="muted small">${esc(s.error || s.note || "")}</td></tr>`).join("")}
      </tbody></table><p class="muted small">${ok}/${status.length} sources responded. Generated ${esc(day.generated_at)}.</p></div>`;
    $("#fit-seg").addEventListener("click", (e) => {
      const f = e.target.closest("button")?.dataset.f; if (!f) return;
      try { sessionStorage.setItem("wtwn.fit", f); } catch { /* ignore */ }
      render();
    });
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

  function delta(days, getter, key) {
    const last = days.slice(-7), prev = days.slice(-14, -7);
    const a = last.reduce((s, d) => s + (getter(d)[key] || 0), 0);
    const b = prev.reduce((s, d) => s + (getter(d)[key] || 0), 0);
    return { a, b, pct: b ? (a - b) / b : (a ? Infinity : 0) };
  }

  function arrow(pct) {
    if (pct === Infinity) return `<span class="up">new</span>`;
    if (!isFinite(pct) || pct === 0) return `<span class="muted">–</span>`;
    return `<span class="${pct > 0 ? "up" : "down"}">${pct > 0 ? "▲" : "▼"} ${Math.abs(Math.round(pct * 100))}%</span>`;
  }

  function renderTrends(main) {
    chartDefaults();
    const days = rangeDays();
    const labels = days.map((d) => shortDate(d.date));
    const themeTotals = {};
    days.forEach((d) => Object.entries(d.by_theme || {}).forEach(([t, n]) => { if (t !== "Other") themeTotals[t] = (themeTotals[t] || 0) + n; }));
    const allThemes = Object.entries(themeTotals).sort((a, b) => b[1] - a[1]).map(([t]) => t);
    const picked = (state.pickedThemes || allThemes.slice(0, 6)).filter((t) => themeTotals[t]).slice(0, 8);
    const sourcesAll = [...new Set(days.flatMap((d) => Object.keys(d.by_source || {})))];

    const rising = allThemes.map((t) => ({ t, ...delta(state.index.days, (d) => d.by_theme || {}, t) }))
      .filter((r) => r.a >= 3).sort((x, y) => (y.pct === Infinity) - (x.pct === Infinity) || y.pct - x.pct).slice(0, 10);
    const kws = state.index.keywords || {};
    const dates = state.index.days.map((d) => d.date);
    const last7 = new Set(dates.slice(-7)), prev7 = new Set(dates.slice(-14, -7));
    const risingKw = Object.entries(kws).map(([k, c]) => {
      let a = 0, b = 0; Object.entries(c).forEach(([d, n]) => { if (last7.has(d)) a += n; else if (prev7.has(d)) b += n; });
      return { k, a, b, pct: b ? (a - b) / b : (a ? Infinity : 0) };
    }).filter((r) => r.a >= 3).sort((x, y) => (y.a - y.b) - (x.a - x.b)).slice(0, 15);

    main.innerHTML = `
      <h2>Trends</h2>
      <div class="toolbar">
        <div class="seg" id="range-seg">${[[14, "14 days"], [30, "30 days"], [90, "90 days"], [0, "All"]].map(([v, l]) => `<button data-r="${v}" aria-pressed="${state.range === v}">${l}</button>`).join("")}</div>
        <span class="muted small">${days.length} day${days.length === 1 ? "" : "s"} of data</span>
      </div>
      ${days.length < 2 ? `<div class="empty">Trends appear after the second daily run. Check back tomorrow.</div>` : ""}
      <div class="panel"><strong>Mentions per day, by theme</strong>
        <div class="toolbar small" style="margin-top:8px">
          <span class="muted">Themes (up to 8):</span>
          <div id="theme-pick" class="chips">${allThemes.slice(0, 20).map((t) => `<button class="chip-btn" data-t="${esc(t)}" aria-pressed="${picked.includes(t)}">${esc(t)}</button>`).join("")}</div></div>
        <div class="chart-box"><canvas id="c-themes"></canvas></div></div>
      <div class="grid2" style="margin-top:12px">
        <div class="panel"><strong>Pain points per day, by source</strong><div class="chart-box"><canvas id="c-sources"></canvas></div></div>
        <div class="panel"><strong>SaaS fit mix per day</strong><div class="chart-box"><canvas id="c-fit"></canvas></div></div>
      </div>
      <div class="grid2" style="margin-top:12px">
        <div class="panel"><strong>Rising themes</strong> <span class="muted small">last 7 days vs previous 7</span>
          <div class="table-wrap"><table><thead><tr><th>Theme</th><th class="num">Last 7d</th><th class="num">Prev 7d</th><th class="num">Change</th></tr></thead><tbody>
          ${rising.map((r) => `<tr><td>${esc(r.t)}</td><td class="num">${r.a}</td><td class="num">${r.b}</td><td class="num">${arrow(r.pct)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">Not enough data yet.</td></tr>`}
          </tbody></table></div></div>
        <div class="panel"><strong>Rising phrases</strong> <span class="muted small">two-word phrases gaining mentions</span>
          <div class="table-wrap"><table><thead><tr><th>Phrase</th><th class="num">Last 7d</th><th class="num">Prev 7d</th><th class="num">Change</th></tr></thead><tbody>
          ${risingKw.map((r) => `<tr><td>${esc(r.k)}</td><td class="num">${r.a}</td><td class="num">${r.b}</td><td class="num">${arrow(r.pct)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">Not enough data yet.</td></tr>`}
          </tbody></table></div></div>
      </div>`;

    $("#range-seg").addEventListener("click", (e) => { const r = e.target.closest("button")?.dataset.r; if (r != null) { state.range = +r; render(); } });
    $("#theme-pick").addEventListener("click", (e) => {
      const t = e.target.closest("button")?.dataset.t; if (!t) return;
      const cur = picked.slice();
      const i = cur.indexOf(t);
      if (i >= 0) cur.splice(i, 1); else if (cur.length < 8) cur.push(t);
      state.pickedThemes = cur; render();
    });

    lineChart($("#c-themes"), labels, picked.map((t) => ({ label: t, data: days.map((d) => (d.by_theme || {})[t] || 0) })));
    if (!picked.length) $("#c-themes").parentElement.innerHTML = `<div class="empty">Pick a theme above.</div>`;
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
    const dates = state.index.days.map((d) => d.date).slice(-30);
    const q = state.pq || "", fit = state.pfit || "all", sort = state.psort || "days_seen";
    const rows = Object.entries(state.index.problems || {}).map(([key, p]) => ({
      key, ...p, total: sum(p.counts), recent: dates.slice(-7).reduce((s, d) => s + (p.counts[d] || 0), 0),
    })).filter((p) => (fit === "all" || p.saas_fit === fit) && (!q || (p.title + " " + (p.summary || "") + " " + (p.theme || "")).toLowerCase().includes(q.toLowerCase())));
    rows.sort((a, b) => (sort === "first_seen" || sort === "last_seen") ? b[sort].localeCompare(a[sort]) : (b[sort] - a[sort]) || (b.total - a.total));

    main.innerHTML = `
      <h2>Recurring problems</h2>
      <p class="sub">Every problem ever detected. A problem that keeps showing up across many days and sources is the strongest signal that it's real and still unsolved.</p>
      <div class="toolbar">
        <input id="pq" class="input" type="search" placeholder="Search problems" value="${esc(q)}">
        <div class="seg" id="pfit">${["all", "high", "medium", "low"].map((f) => `<button data-f="${f}" aria-pressed="${f === fit}">${f}</button>`).join("")}</div>
        <select id="psort" aria-label="Sort">${[["days_seen", "Most days seen"], ["total", "Most mentions"], ["recent", "Most mentions, last 7 days"], ["last_seen", "Most recent"], ["first_seen", "Newest"]].map(([v, l]) => `<option value="${v}" ${v === sort ? "selected" : ""}>${l}</option>`).join("")}</select>
        <span class="muted small">${rows.length} problems</span>
      </div>
      <div class="panel table-wrap"><table>
        <thead><tr><th>Problem</th><th>Fit</th><th class="num">Days</th><th class="num">Mentions</th><th class="num">7d</th><th>Last 30 days</th><th>Last seen</th></tr></thead>
        <tbody>${rows.slice(0, 300).map((p) => `<tr class="clickable" data-key="${esc(p.key)}">
          <td><strong>${esc(p.title)}</strong><div class="muted small">${esc(p.theme || "")} · ${(p.sources || []).map(srcLabel).map(esc).join(", ")}</div>
            <div class="small detail" hidden>${esc(p.summary || "")}<br><span class="muted">First seen ${esc(p.first_seen)}</span></div></td>
          <td>${fitBadge(p.saas_fit)}</td><td class="num">${p.days_seen}</td><td class="num">${p.total}</td><td class="num">${p.recent}</td>
          <td>${sparkline(p.counts, dates)}</td><td class="small">${esc(shortDate(p.last_seen))}</td></tr>`).join("") || `<tr><td colspan="7" class="muted">No problems yet.</td></tr>`}
        </tbody></table></div>`;

    $("#pq").addEventListener("input", (e) => { state.pq = e.target.value; clearTimeout(state.pqT); state.pqT = setTimeout(() => { render().then(() => { const el = $("#pq"); el.focus(); el.setSelectionRange(el.value.length, el.value.length); }); }, 250); });
    $("#pfit").addEventListener("click", (e) => { const f = e.target.closest("button")?.dataset.f; if (f) { state.pfit = f; render(); } });
    $("#psort").addEventListener("change", (e) => { state.psort = e.target.value; render(); });
    main.querySelectorAll("tr.clickable").forEach((tr) => tr.addEventListener("click", () => { const d = tr.querySelector(".detail"); d.hidden = !d.hidden; }));
  }

  // ----------------------------------------------------------------- browse
  async function renderBrowse(main) {
    const day = await getDay(state.date);
    const q = state.bq || "", src = state.bsrc || "all", fit = state.bfit || "all", theme = state.btheme || "all";
    const themes = [...new Set(day.items.flatMap((it) => it.themes))].sort();
    const srcs = [...new Set(day.items.map((it) => it.source))];
    const items = day.items.filter((it) => (src === "all" || it.source === src) && (fit === "all" || it.saas_fit === fit)
      && (theme === "all" || it.themes.includes(theme)) && (!q || (it.title + " " + it.text).toLowerCase().includes(q.toLowerCase())));
    main.innerHTML = `
      <h2>Everything from ${esc(fmtDate(day.date))}</h2>
      <div class="toolbar">
        <input id="bq" class="input" type="search" placeholder="Search text" value="${esc(q)}">
        <select id="bsrc"><option value="all">All sources</option>${srcs.map((s) => `<option value="${esc(s)}" ${s === src ? "selected" : ""}>${esc(srcLabel(s))}</option>`).join("")}</select>
        <select id="btheme"><option value="all">All themes</option>${themes.map((t) => `<option ${t === theme ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
        <select id="bfit">${["all", "high", "medium", "low"].map((f) => `<option value="${f}" ${f === fit ? "selected" : ""}>${f === "all" ? "Any SaaS fit" : "SaaS fit: " + f}</option>`).join("")}</select>
        <span class="muted small">${items.length} of ${day.items.length}</span>
      </div>
      <div class="items">${items.slice(0, 400).map(itemRow).join("") || `<div class="empty">Nothing matches.</div>`}</div>`;
    const re = () => render();
    $("#bq").addEventListener("input", (e) => { state.bq = e.target.value; clearTimeout(state.bqT); state.bqT = setTimeout(() => re().then(() => { const el = $("#bq"); el.focus(); el.setSelectionRange(el.value.length, el.value.length); }), 250); });
    $("#bsrc").addEventListener("change", (e) => { state.bsrc = e.target.value; re(); });
    $("#btheme").addEventListener("change", (e) => { state.btheme = e.target.value; re(); });
    $("#bfit").addEventListener("change", (e) => { state.bfit = e.target.value; re(); });
  }

  // ------------------------------------------------------------------ about
  function renderAbout(main) {
    main.innerHTML = `<div class="prose">
      <h2>How it works</h2>
      <p>Once a day a GitHub Action scans public places where people describe problems, scores each post for "unmet need" language, groups similar complaints into problems, and adds them to the history you see here.</p>
      <h2>Where it looks, and why</h2>
      <ul>
        <li><strong>Reddit</strong> (45 niche business &amp; profession subreddits): people asking “is there a tool…”, “I wish there was…”, “would pay for…”.</li>
        <li><strong>Hacker News</strong>: Ask HN threads and comments with the same phrasing, plus “we built an internal tool” (companies building it themselves = demand).</li>
        <li><strong>Stack Exchange</strong> (Software Recommendations, Web Apps, Super User…): explicit requests for software that may not exist.</li>
        <li><strong>1–2★ App Store reviews</strong> of popular business apps: what incumbents get wrong.</li>
        <li><strong>1–2★ Shopify App Store reviews</strong> and <strong>WordPress plugin reviews</strong>: merchants and site owners stuck with a tool that doesn't fit.</li>
        <li><strong>Highly upvoted GitHub feature requests</strong>: needs inside existing tools that maintainers aren't meeting.</li>
        <li><strong>Job posts</strong> describing repetitive manual work (data entry, reconciliation, chasing): if a company pays a person to do it, software might do it cheaper.</li>
      </ul>
      <h2>Reading the scores</h2>
      <ul>
        <li><strong>Pain score</strong> adds up strong-need phrases (“would pay”, “is there a tool”, “manually”, “too expensive”…) and engagement (upvotes, comments, reactions).</li>
        <li><strong>SaaS fit</strong>: <em>high</em> means software clearly helps; <em>low</em> means the problem is structural or physical. Low-fit problems are kept on purpose when many people share them.</li>
        <li><strong>Days seen</strong> on the Problems tab is the best signal: the same pain, from different people, day after day.</li>
      </ul>
      <h2>Validating an idea from here</h2>
      <ol>
        <li>Open the evidence links and read the replies. Are others saying “same”?</li>
        <li>Check the problem appears in more than one <em>source</em>, not only one subreddit.</li>
        <li>Look for an incumbent with bad reviews: that's a market that already pays.</li>
        <li>Reply to or DM a few posters and ask how they handle it today and what it costs them.</li>
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
