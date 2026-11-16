/* What the World Needs Now - client. All data files are AES-GCM encrypted;
   the passphrase only ever exists in the visitor's head and the SITE_PASSPHRASE secret. */
(() => {
  "use strict";

  const KEY_SLOT = "wtwn.k";
  const $ = (s, el = document) => el.querySelector(s);
  const state = { key: null, meta: null, index: null, days: {}, view: "today", date: null, charts: [], range: 26, seg: "business" };

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
  const plural = (n, w, many) => `${n} ${n === 1 ? w : (many || w + "s")}`;
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
    try { state.seg = localStorage.getItem("wtwn.seg") || "business"; } catch { /* ignore */ }
    const segBox = $("#seg-toggle");
    const paintSeg = () => segBox.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.seg === state.seg)));
    segBox.addEventListener("click", (e) => {
      const v = e.target.closest("button")?.dataset.seg; if (!v) return;
      state.seg = v; try { localStorage.setItem("wtwn.seg", v); } catch { /* ignore */ }
      paintSeg(); render();
    });
    paintSeg(); paintShortlistCount();
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
    $("#seg-toggle").hidden = ["shortlist", "about"].includes(state.view);
    const main = $("#main");
    if (!state.index.days.length) { main.innerHTML = `<div class="empty">No runs yet.</div>`; return; }
    try {
      if (state.view === "today") await renderToday(main);
      else if (state.view === "trends") renderTrends(main);
      else if (state.view === "problems") renderProblems(main);
      else if (state.view === "browse") await renderBrowse(main);
      else if (state.view === "mines") renderMines(main);
      else if (state.view === "shortlist") renderShortlist(main);
      else renderAbout(main);
    } catch (e) {
      main.innerHTML = `<div class="empty">Couldn't render this view: ${esc(e.message)}</div>`;
    }
  }

  // ---------------------------------------------- segment, score, replies, stars
  const segOK = (x) => state.seg === "all" || (x.segment || "business") === state.seg;
  const segSum = (d) => (state.seg === "all" ? d : (d.seg && d.seg[state.seg]) || d);
  const SEG_NAME = { business: "business", consumer: "consumer", all: "all" };
  const OPP_PARTS = [["buyer", "Who pays", 25, "A business with a budget scores highest"], ["money", "Money", 20, "Would pay, prices named, losing money, paying a freelancer"],
    ["cost", "Cost of the problem", 20, "Hours lost, done by hand, staff tied up"], ["unmet", "Still unmet", 20, "What the replies say: others agree, or a tool was named"],
    ["demand", "Demand", 15, "How many people, sources and weeks"]];
  const oppClass = (v) => (v >= 65 ? "hi" : v >= 45 ? "mid" : "lo");
  const oppBadge = (v) => `<span class="opp opp-${oppClass(v || 0)}" title="Opportunity score, 0–100: who pays, money, cost of the problem, whether it is still unmet, demand">${Math.round(v || 0)}</span>`;
  function oppBars(parts, demandMax) {
    if (!parts) return "";
    return `<details class="why"><summary>Why this score</summary><div class="bars">${OPP_PARTS.map(([k, label, max, tip]) => {
      const m = k === "demand" && demandMax ? demandMax : max, v = parts[k] || 0;
      return `<div class="bar-row" title="${esc(tip)}"><span>${esc(label)}</span><span class="bar"><i style="width:${Math.min(100, Math.round(100 * v / m))}%"></i></span><span class="num">${v}/${m}</span></div>`;
    }).join("")}</div></details>`;
  }
  const REPLY_LABEL = { agree: "others say the same", open: "no tool suggested", objections: "tools suggested, not good enough", one_tool: "one tool suggested",
    solved: "likely solved", pitched: "only vendor pitches", none: "no replies yet", unread: "replies not read" };
  const REPLY_CLASS = { agree: "unmet", open: "unmet", objections: "unmet", one_tool: "maybe", pitched: "maybe", solved: "solved", none: "", unread: "" };
  const UNMET = ["agree", "open", "objections"];
  function replyChip(rep) {
    if (!rep) return "";
    const tools = (rep.tools || []).length ? ` (${rep.tools.slice(0, 3).map(esc).join(", ")})` : "";
    const same = rep.me_too ? ` · ${rep.me_too} “same here”` : "";
    return `<span class="chip reply ${REPLY_CLASS[rep.status] || ""}" title="From reading ${rep.read || 0} of ${rep.n || 0} replies">${esc(REPLY_LABEL[rep.status] || rep.status)}${tools}${same}</span>`;
  }

  const SL_KEY = "wtwn.shortlist";
  const SL_STATUS = ["Spotted", "Researching", "Talking to people", "Landing page up", "Pre-sold", "Dropped"];
  function loadSL() { try { return Object.assign({ problems: {}, leads: {} }, JSON.parse(localStorage.getItem(SL_KEY) || "{}")); } catch { return { problems: {}, leads: {} }; } }
  function saveSL(sl) { try { localStorage.setItem(SL_KEY, JSON.stringify(sl)); } catch { /* private mode */ } paintShortlistCount(); }
  function paintShortlistCount() {
    const sl = loadSL(), n = Object.keys(sl.problems).length + Object.keys(sl.leads).length;
    const b = document.querySelector('.tabs button[data-view="shortlist"]'); if (b) b.textContent = n ? `Shortlist (${n})` : "Shortlist";
  }
  const starBtn = (kind, id) => { const on = !!loadSL()[kind][id]; return `<button class="star" data-star="${kind}" data-id="${esc(id)}" aria-pressed="${on}" title="${on ? "Remove from shortlist" : "Add to shortlist"}">${on ? "★" : "☆"}</button>`; };
  function wireStars(root, snapshot) {
    root.querySelectorAll("button.star").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      const sl = loadSL(), kind = b.dataset.star, id = b.dataset.id;
      if (sl[kind][id]) delete sl[kind][id];
      else sl[kind][id] = { status: "Spotted", notes: "", added: new Date().toISOString().slice(0, 10), contacted: {}, ...(snapshot ? snapshot(kind, id) : {}) };
      saveSL(sl);
      const on = !!sl[kind][id]; b.setAttribute("aria-pressed", String(on)); b.textContent = on ? "★" : "☆";
    }));
  }
  function contactLink(x) {
    if (!x.author) return `<a href="${safeUrl(x.url)}" target="_blank" rel="noopener noreferrer">reply on the post ↗</a>`;
    const a = encodeURIComponent(x.author);
    const href = x.source === "reddit" ? `https://www.reddit.com/message/compose/?to=${a}` : x.source === "hackernews" ? `https://news.ycombinator.com/user?id=${a}`
      : x.source === "bluesky" ? `https://bsky.app/profile/${a}` : x.url;
    return `<a href="${safeUrl(href)}" target="_blank" rel="noopener noreferrer">${esc(x.author)} ↗</a>`;
  }

  // -------------------------------------------------------------- this week
  const nicheChip = (n) => (n && n !== "General" ? `<span class="chip niche">${esc(n)}</span>` : "");
  const nicheOptions = (list, cur) => `<option value="all">All niches</option>${list.map((n) => `<option ${n === cur ? "selected" : ""}>${esc(n)}</option>`).join("")}`;

  function replySummary(rep, nLeads) {
    if (!rep) return "";
    const bits = [];
    if (rep.unmet) bits.push(`<strong>${rep.unmet} of ${nLeads}</strong> still unmet after reading replies`);
    if (rep.me_too) bits.push(`${rep.me_too} “same here”`);
    if (rep.solved) bits.push(`${rep.solved} likely solved`);
    if ((rep.tools || []).length) bits.push(`tools people suggested: ${rep.tools.slice(0, 5).map(esc).join(", ")}`);
    return bits.length ? `<p class="replies small">${bits.join(" · ")}</p>` : "";
  }

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
      <div class="meta">${oppBadge(p.opp)}${isNew ? `<span class="new-badge">New</span>` : `<span class="chip">Seen ${plural(seen, "week")}</span>`}${nicheChip(p.niche)}${costBadges(costs)}<span class="grow"></span>${starBtn("problems", p.key)}</div>
      <h3>${esc(p.title)}</h3>
      <p>${esc(p.summary)}</p>
      ${extra}
      ${replySummary(p.replies, evidence.length)}
      ${(p.money_notes || []).length ? `<p class="small money">$ ${p.money_notes.map(esc).join(" · ")}</p>` : ""}
      <div class="meta">${fitBadge(p.saas_fit)}${(p.sources || []).map((s) => `<span class="chip">${esc(srcLabel(s))}</span>`).join("")}<span class="muted">${plural(evidence.length, "lead")} from ${plural(p.people || evidence.length, "person", "people")}</span></div>
      ${oppBars(p.opp_parts, 30)}
      <details><summary>Evidence</summary><ul>${evidence.slice(0, 12).map((it) =>
        `<li><a href="${safeUrl(it.url)}" target="_blank" rel="noopener noreferrer">${esc(it.need || it.title)}</a> <span class="muted">· ${esc(it.channel)} · ${esc(REPLY_LABEL[(it.replies || {}).status] || "")}</span></li>`).join("")}</ul></details>
      ${validateLinks(p.search_keyword || p.title)}
    </article>`;
  }

  function itemRow(it) {
    const need = it.need && it.need !== it.title && !it.need.startsWith(it.title.replace(/…$/, "")) ? `<div class="need">“${esc(it.need)}”</div>` : "";
    const notes = [...(it.money_notes || []), ...(it.time_note ? [it.time_note] : []), ...(it.events || [])];
    return `<div class="item">
      <div class="t">${oppBadge(it.opp ?? it.pain_score)} <a href="${safeUrl(it.url)}" target="_blank" rel="noopener noreferrer">${esc(it.title || "(untitled)")}</a><span class="grow"></span>${starBtn("leads", it.id)}</div>
      ${need}
      <div class="x">${esc(it.text.slice(0, 280))}${it.text.length > 280 ? "…" : ""}</div>
      ${notes.length ? `<div class="small money">${notes.map(esc).join(" · ")}</div>` : ""}
      <div class="meta">${replyChip(it.replies)}${nicheChip(it.niche)}<span class="chip">${esc(it.channel)}</span>${fitBadge(it.saas_fit)}${costBadges(it.costs)}
        ${(it.signal_labels || []).slice(0, 3).map((s) => `<span class="chip sig">${esc(s)}</span>`).join("")}</div>
    </div>`;
  }

  const leadSnapshot = (run) => (kind, id) => {
    if (kind !== "leads") return {};
    const it = run.items.find((x) => x.id === id); if (!it) return {};
    return { snap: { title: it.title, need: it.need, url: it.url, author: it.author, source: it.source, where: it.channel, niche: it.niche, date: run.date, opp: it.opp, reply: (it.replies || {}).status } };
  };

  async function renderToday(main) {
    const run = await getDay(state.date);
    const probs = state.index.problems || {};
    const status = Object.entries(run.sources || {});
    const ok = status.filter(([, s]) => s.ok).length;
    const items = run.items.filter(segOK);
    const nicheCounts = {};
    items.forEach((it) => { if (it.niche !== "General") nicheCounts[it.niche] = (nicheCounts[it.niche] || 0) + 1; });
    const nichesSorted = Object.entries(nicheCounts).sort((a, b) => b[1] - a[1]);
    const unmet = items.filter((it) => UNMET.includes((it.replies || {}).status)).length;
    const solved = items.filter((it) => (it.replies || {}).status === "solved").length;
    let fitFilter = "all"; try { fitFilter = sessionStorage.getItem("wtwn.fit") || "all"; } catch { /* ignore */ }
    const nf = state.tniche || "all";
    const problems = run.problems.filter(segOK);
    const shown = problems.filter((p) => (fitFilter === "all" || p.saas_fit === fitFilter) && (nf === "all" || p.niche === nf));
    const leads = items.filter((it) => nf === "all" || it.niche === nf);
    const best = problems[0];
    const segNote = state.seg === "all" ? "" : ` · ${state.seg} only`;

    main.innerHTML = `
      <h2>${esc(weekLabel(run.date))}</h2>
      <p class="sub">${run.ai && run.ai.startsWith("ok") ? "Problems named and written up by Claude from this week's leads."
        : "Ranked by opportunity: who would pay, what it costs them now, and whether the replies show it is still unmet."}${run.backfilled ? " This week was rebuilt from the archive, so it has fewer sources and fewer leads than a live week." : ""}</p>
      <div class="tiles">
        <div class="tile"><div class="label">Leads this week</div><div class="value">${items.length}</div><div class="note">from ${(run.new_count || 0).toLocaleString()} posts read${segNote}</div></div>
        <div class="tile"><div class="label">Still unmet after reading replies</div><div class="value">${unmet}</div><div class="note">${solved} already answered with a tool</div></div>
        <div class="tile"><div class="label">Niches with leads</div><div class="value">${nichesSorted.length}</div><div class="note">${nichesSorted[0] ? `most: ${esc(nichesSorted[0][0])} (${nichesSorted[0][1]})` : ""}</div></div>
        <div class="tile"><div class="label">Best opportunity</div><div class="value">${best ? Math.round(best.opp || 0) : "–"}<span class="of">/100</span></div><div class="note">${best ? esc(best.title) : ""}</div></div>
      </div>
      <h2>Top opportunities</h2>
      <div class="toolbar"><span class="muted small">SaaS fit</span>
        <div class="seg" id="fit-seg">${["all", "high", "medium", "low"].map((f) => `<button data-f="${f}" aria-pressed="${f === fitFilter}">${f}</button>`).join("")}</div>
        <select id="tniche" aria-label="Niche">${nicheOptions(nichesSorted.map(([n]) => n), nf)}</select>
        <span class="muted small">${plural(shown.length, "problem")}, best first · ☆ adds to your shortlist</span></div>
      ${shown.length ? `<div class="cards">${shown.slice(0, 30).map((p) => problemCard(p, run, probs)).join("")}</div>` : `<div class="empty">No problems match.</div>`}
      <h2>Strongest individual leads</h2>
      <div class="items">${leads.slice(0, 20).map(itemRow).join("") || `<div class="empty">Nothing this week.</div>`}</div>
      <h2>Sources</h2>
      <div class="panel table-wrap"><table><thead><tr><th>Source</th><th>Status</th><th class="num">Posts read</th><th class="num">Leads kept</th><th>Note</th></tr></thead><tbody>
      ${status.map(([n, s]) => `<tr><td>${esc(srcLabel(n))}</td><td class="${s.ok ? "status-ok" : "status-bad"}">${s.ok ? "✓ ok" : "✕ failed"}</td><td class="num">${esc((s.read ?? "").toLocaleString())}</td><td class="num">${n === "replies" ? "" : esc(s.count ?? 0)}</td><td class="muted small">${esc(s.error || s.note || "")}</td></tr>`).join("")}
      </tbody></table><p class="muted small">${ok}/${status.length} responded. Generated ${esc(run.generated_at)}.</p></div>`;
    $("#fit-seg").addEventListener("click", (e) => {
      const f = e.target.closest("button")?.dataset.f; if (!f) return;
      try { sessionStorage.setItem("wtwn.fit", f); } catch { /* ignore */ }
      render();
    });
    $("#tniche").addEventListener("change", (e) => { state.tniche = e.target.value; render(); });
    wireStars(main, leadSnapshot(run));
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
  function delta(field, key) {
    const all = state.index.days;
    const a = all.length ? ((segSum(all[all.length - 1])[field] || {})[key] || 0) : 0;
    const b = all.length > 1 ? ((segSum(all[all.length - 2])[field] || {})[key] || 0) : 0;
    return { a, b, pct: b ? (a - b) / b : (a ? Infinity : 0) };
  }

  function arrow(pct) {
    if (pct === Infinity) return `<span class="up">new</span>`;
    if (!isFinite(pct) || pct === 0) return `<span class="muted">–</span>`;
    return `<span class="${pct > 0 ? "up" : "down"}">${pct > 0 ? "▲" : "▼"} ${Math.abs(Math.round(pct * 100))}%</span>`;
  }

  function pickerChart(id, field, skip, stateKey, days, labels) {
    const totals = {};
    days.forEach((d) => Object.entries(segSum(d)[field] || {}).forEach(([t, n]) => { if (t !== skip) totals[t] = (totals[t] || 0) + n; }));
    const all = Object.entries(totals).sort((a, b) => b[1] - a[1]).map(([t]) => t);
    const picked = (state[stateKey] || all.slice(0, 6)).filter((t) => totals[t]).slice(0, 8);
    const use = picked.length ? picked : all.slice(0, 6);
    $(`#${id}-pick`).innerHTML = all.slice(0, 24).map((t) => `<button class="chip-btn" data-t="${esc(t)}" aria-pressed="${use.includes(t)}">${esc(t)}</button>`).join("");
    $(`#${id}-pick`).addEventListener("click", (e) => {
      const t = e.target.closest("button")?.dataset.t; if (!t) return;
      const cur = use.slice(), i = cur.indexOf(t);
      if (i >= 0) cur.splice(i, 1); else if (cur.length < 8) cur.push(t);
      state[stateKey] = cur; render();
    });
    if (use.length) lineChart($(`#${id}`), labels, use.map((t) => ({ label: t, data: days.map((d) => (segSum(d)[field] || {})[t] || 0) })));
    else $(`#${id}`).parentElement.innerHTML = `<div class="empty">Nothing to chart yet.</div>`;
    return all;
  }

  function risingTable(title, names, field) {
    const rows = names.map((t) => ({ t, ...delta(field, t) })).filter((r) => r.a >= 2)
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
    const sourcesAll = [...new Set(days.flatMap((d) => Object.keys(segSum(d).by_source || {})))];
    const filled = days.filter((d) => d.backfilled);
    const liveFrom = days.find((d) => !d.backfilled);
    main.innerHTML = `
      <h2>Trends</h2>
      <div class="toolbar">
        <div class="seg" id="range-seg">${[[8, "8 weeks"], [13, "13 weeks"], [26, "26 weeks"], [52, "1 year"], [0, "All"]].map(([v, l]) => `<button data-r="${v}" aria-pressed="${state.range === v}">${l}</button>`).join("")}</div>
        <span class="muted small">${plural(days.length, "week")} of data · showing ${esc(SEG_NAME[state.seg])} leads</span>
      </div>
      ${days.length < 2 ? `<div class="empty">Trends appear after the second weekly run.</div>` : ""}
      ${filled.length ? `<p class="note-box small">${plural(filled.length, "week")} up to ${esc(shortDate(filled[filled.length - 1].date))} ${filled.length === 1 ? "was" : "were"} rebuilt from the archive. Those weeks use Reddit, Hacker News and Stack Exchange only, and posts deleted or removed since then have no text, so they hold fewer leads than live weeks${liveFrom ? ` (from ${esc(shortDate(liveFrom.date))})` : ""}. Compare shapes within the backfilled period; don't read the jump at the boundary as a real rise.</p>` : ""}
      <div class="panel"><strong>Leads per week, by niche</strong>
        <div class="toolbar small" style="margin-top:8px"><span class="muted">Niches (up to 8):</span><div id="c-niches-pick" class="chips"></div></div>
        <div class="chart-box"><canvas id="c-niches"></canvas></div></div>
      <div class="panel" style="margin-top:12px"><strong>Leads per week, by problem area</strong>
        <div class="toolbar small" style="margin-top:8px"><span class="muted">Problem areas (up to 8):</span><div id="c-themes-pick" class="chips"></div></div>
        <div class="chart-box"><canvas id="c-themes"></canvas></div></div>
      <div class="grid2" style="margin-top:12px" id="rising"></div>
      <div class="grid2" style="margin-top:12px">
        <div class="panel"><strong>Leads per week, by source</strong><div class="chart-box"><canvas id="c-sources"></canvas></div></div>
        <div class="panel"><strong>What the replies said, per week</strong><div class="chart-box"><canvas id="c-reply"></canvas></div></div>
      </div>`;
    $("#range-seg").addEventListener("click", (e) => { const r = e.target.closest("button")?.dataset.r; if (r != null) { state.range = +r; render(); } });
    const niches = pickerChart("c-niches", "by_niche", "General", "pickedNiches", days, labels);
    const themes = pickerChart("c-themes", "by_theme", "Other needs", "pickedThemes", days, labels);
    $("#rising").innerHTML = risingTable("Rising niches", niches, "by_niche") + risingTable("Rising problem areas", themes, "by_theme");
    lineChart($("#c-sources"), labels, sourcesAll.slice(0, 8).map((s) => ({ label: srcLabel(s), data: days.map((d) => (segSum(d).by_source || {})[s] || 0) })), { type: "bar", stacked: true });
    const rs = (d, keys) => keys.reduce((n, k) => n + ((segSum(d).by_reply || {})[k] || 0), 0);
    lineChart($("#c-reply"), labels, [["Still unmet", UNMET], ["One tool or pitch", ["one_tool", "pitched"]], ["Likely solved", ["solved"]], ["No replies read", ["none", "unread"]]]
      .map(([label, keys]) => ({ label, data: days.map((d) => rs(d, keys)) })),
      { type: "bar", stacked: true, colors: [cssVar("--s3"), cssVar("--s4"), cssVar("--seq-1"), cssVar("--border")] });
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
    const dates = state.index.days.map((d) => d.date).slice(-13);
    const latest = dates[dates.length - 1];
    const q = state.pq || "", fit = state.pfit || "all", sort = state.psort || "opp", nf = state.pniche || "all";
    const all = Object.entries(state.index.problems || {}).map(([key, p]) => ({ key, ...p, opp: p.opp || 0, total: sum(p.counts), recent: p.counts[latest] || 0 })).filter(segOK);
    const niches = [...new Set(all.map((p) => p.niche).filter((n) => n && n !== "General"))].sort();
    const rows = all.filter((p) => (fit === "all" || p.saas_fit === fit) && (nf === "all" || p.niche === nf)
      && (!q || (p.title + " " + (p.summary || "") + " " + (p.theme || "") + " " + (p.niche || "")).toLowerCase().includes(q.toLowerCase())));
    rows.sort((a, b) => (sort === "first_seen" || sort === "last_seen") ? b[sort].localeCompare(a[sort]) : (b[sort] - a[sort]) || (b.opp - a.opp));

    main.innerHTML = `
      <h2>Recurring problems</h2>
      <p class="sub">Every problem ever detected, best opportunity first. The score rises when a problem keeps coming back, from different people and sources, and falls when replies show a tool already solves it.</p>
      <div class="toolbar">
        <input id="pq" class="input" type="search" placeholder="Search problems" value="${esc(q)}">
        <div class="seg" id="pfit">${["all", "high", "medium", "low"].map((f) => `<button data-f="${f}" aria-pressed="${f === fit}">${f}</button>`).join("")}</div>
        <select id="pniche" aria-label="Niche">${nicheOptions(niches, nf)}</select>
        <select id="psort" aria-label="Sort">${[["opp", "Best opportunity"], ["days_seen", "Most weeks seen"], ["total", "Most leads"], ["recent", "Most leads, latest week"], ["last_seen", "Most recent"], ["first_seen", "Newest"]].map(([v, l]) => `<option value="${v}" ${v === sort ? "selected" : ""}>${l}</option>`).join("")}</select>
        <span class="muted small">${plural(rows.length, "problem")}</span>
      </div>
      <div class="panel table-wrap"><table>
        <thead><tr><th></th><th>Problem</th><th class="num">Score</th><th class="num">Weeks</th><th class="num">Leads</th><th class="num">Latest</th><th>Last 13 weeks</th><th>Last seen</th></tr></thead>
        <tbody>${rows.slice(0, 300).map((p) => `<tr class="clickable" data-key="${esc(p.key)}">
          <td>${starBtn("problems", p.key)}</td>
          <td><strong>${esc(p.title)}</strong><div class="muted small">${(p.sources || []).map(srcLabel).map(esc).join(", ")}${(p.tools || []).length ? ` · tools suggested: ${p.tools.slice(0, 4).map(esc).join(", ")}` : ""}</div>
            <div class="small detail" hidden>${esc(p.summary || "")}<br>${(p.money_notes || []).length ? `<span class="money">$ ${p.money_notes.map(esc).join(" · ")}</span><br>` : ""}<span class="muted">First seen ${esc(p.first_seen)} · ${p.me_too || 0} “same here” replies</span>${oppBars(p.opp_parts, 30)}${p.search_keyword ? validateLinks(p.search_keyword) : ""}</div></td>
          <td class="num">${oppBadge(p.opp)}</td><td class="num">${p.days_seen}</td><td class="num">${p.total}</td><td class="num">${p.recent}</td>
          <td>${sparkline(p.counts, dates)}</td><td class="small">${esc(shortDate(p.last_seen))}</td></tr>`).join("") || `<tr><td colspan="8" class="muted">No problems yet.</td></tr>`}
        </tbody></table></div>`;

    $("#pq").addEventListener("input", (e) => { state.pq = e.target.value; clearTimeout(state.pqT); state.pqT = setTimeout(() => { render().then(() => { const el = $("#pq"); el.focus(); el.setSelectionRange(el.value.length, el.value.length); }); }, 250); });
    $("#pfit").addEventListener("click", (e) => { const f = e.target.closest("button")?.dataset.f; if (f) { state.pfit = f; render(); } });
    $("#pniche").addEventListener("change", (e) => { state.pniche = e.target.value; render(); });
    $("#psort").addEventListener("change", (e) => { state.psort = e.target.value; render(); });
    main.querySelectorAll("tr.clickable").forEach((tr) => tr.addEventListener("click", (e) => {
      if (e.target.closest("a, summary, details, button")) return;
      const d = tr.querySelector(".detail"); d.hidden = !d.hidden;
    }));
    wireStars(main);
  }

  // ------------------------------------------------------------ idea mines
  function windowDates(n) { return state.index.days.map((d) => d.date).slice(-n); }
  function inWindow(counts, dates) { return dates.reduce((s, d) => s + ((counts || {})[d] || 0), 0); }
  const weeksIn = (counts, dates) => dates.filter((d) => (counts || {})[d]).length;
  const EVENT_LABEL = { shutdown: "Shutting down", price_increase: "Price increase", acquisition: "Acquired", outage: "Outage", regulation: "New rule" };

  function renderMines(main) {
    const win = state.mwin || 13;
    const dates = windowDates(win);
    const chips = (obj, label = (t) => t) => Object.entries(obj).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([t, n]) => `<span class="chip">${esc(label(t))} ${n}</span>`).join("");
    const quotes = (list) => `<ul class="quotes">${(list || []).map((x) => `<li><a href="${safeUrl(x.url)}" target="_blank" rel="noopener noreferrer">“${esc(x.need || x.text || x.title)}”</a> <span class="muted">· ${esc(x.where || "")} · ${esc(x.date || "")}</span></li>`).join("")}</ul>`;
    const et = state.etype || "all";

    const events = Object.values(state.index.events || {}).map((e) => ({ ...e, n: inWindow(e.counts, dates), weeks: weeksIn(e.counts, dates),
      last: Object.keys(e.counts || {}).filter((d) => dates.includes(d)).sort().pop() }))
      .filter((e) => e.n && (et === "all" || e.type === et) && (e.type === "regulation" || e.n >= 2 || e.weeks >= 2 || dates.length <= 2))
      .sort((a, b) => (b.n - a.n) || String(b.last).localeCompare(String(a.last)));

    const niches = Object.entries(state.index.niches || {}).map(([name, e]) => ({
      name, ...e, n: inWindow(e.counts, dates), weeks: weeksIn(e.counts, dates),
      themesW: Object.fromEntries(Object.entries(e.themes || {}).map(([t, c]) => [t, inWindow(c, dates)]).filter(([, n]) => n)),
    })).filter((r) => r.n && r.name !== "General" && segOK(r)).sort((a, b) => b.n - a.n);

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
      <p class="sub">Other ways to read the same posts: what is forcing people to switch, who is struggling, which products people are trying to leave, and what is still being done in spreadsheets.</p>
      <div class="toolbar"><div class="seg" id="mwin">${[[4, "4 weeks"], [13, "13 weeks"], [26, "26 weeks"], [5200, "All"]].map(([v, l]) => `<button data-w="${v}" aria-pressed="${win === v}">${l}</button>`).join("")}</div></div>

      <h2>Forced changes</h2>
      <p class="sub">A product shutting down, raising prices, being bought or going down sends all its users looking for something else at once. So does a new rule with a deadline. These openings are time-limited. Product events are listed once at least two posts mention them.</p>
      <div class="toolbar"><div class="seg" id="etype">${[["all", "All"], ["shutdown", "Shutdowns"], ["price_increase", "Price rises"], ["acquisition", "Acquisitions"], ["outage", "Outages"], ["regulation", "New rules"]].map(([v, l]) => `<button data-e="${v}" aria-pressed="${et === v}">${l}</button>`).join("")}</div></div>
      <div class="panel table-wrap"><table>
        <thead><tr><th>What</th><th>Who is affected</th><th class="num">Posts</th><th class="num">Weeks</th><th>Last seen</th></tr></thead>
        <tbody>${events.slice(0, 60).map((e) => `<tr class="clickable">
          <td><span class="chip ev ev-${esc(e.type)}">${esc(EVENT_LABEL[e.type] || e.type)}</span> <strong>${esc(e.type === "regulation" ? "" : e.subject)}</strong>
            <div class="detail small" hidden>${quotes(e.examples)}</div>
            ${e.type === "regulation" ? `<div class="small">${esc((e.examples[0] || {}).title || "")}</div>` : ""}</td>
          <td class="small">${Object.entries(e.niches || {}).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([n]) => esc(n)).join(", ")}</td>
          <td class="num">${e.n}</td><td class="num">${e.weeks}</td><td class="small">${e.last ? esc(shortDate(e.last)) : ""}</td></tr>`).join("") || `<tr><td colspan="5" class="muted">Nothing in this window yet.</td></tr>`}</tbody></table>
        <p class="small muted">Click a row for the posts. Names are picked out by pattern, so check a row before acting on it.</p></div>

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
    $("#etype").addEventListener("click", (e) => { const v = e.target.closest("button")?.dataset.e; if (v) { state.etype = v; render(); } });
    main.querySelectorAll("tr.clickable").forEach((tr) => tr.addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      const d = tr.querySelector(".detail"); if (d) d.hidden = !d.hidden;
    }));
  }

  // -------------------------------------------------------------- shortlist
  function prospectRows(list, entry, kind, id) {
    return list.map((x) => `<tr>
      <td><input type="checkbox" data-contact="${esc(kind)}|${esc(id)}|${esc(x.url)}" ${entry.contacted && entry.contacted[x.url] ? "checked" : ""} aria-label="Contacted"></td>
      <td><a href="${safeUrl(x.url)}" target="_blank" rel="noopener noreferrer">“${esc(x.need)}”</a><div class="small muted">${esc(x.where || "")} · ${esc(x.date || "")}${x.reply ? ` · ${esc(REPLY_LABEL[x.reply] || x.reply)}` : ""}</div></td>
      <td class="small">${contactLink(x)}</td></tr>`).join("");
  }

  function shortlistCard(kind, id, entry, title, sub, opp, prospects, extra) {
    const done = Object.values(entry.contacted || {}).filter(Boolean).length;
    return `<article class="panel sl" data-kind="${esc(kind)}" data-id="${esc(id)}">
      <div class="meta">${oppBadge(opp)}<strong class="sl-title">${esc(title)}</strong><span class="grow"></span>
        <select data-status aria-label="Status">${SL_STATUS.map((s) => `<option ${s === entry.status ? "selected" : ""}>${s}</option>`).join("")}</select>
        <button class="icon-btn" data-remove title="Remove from shortlist">✕</button></div>
      <p class="small muted">${sub}</p>
      ${extra || ""}
      <label class="small muted" for="n-${esc(kind)}-${esc(id)}">Notes (what you learned, pricing they mentioned, who to follow up with)</label>
      <textarea id="n-${esc(kind)}-${esc(id)}" data-notes rows="3" placeholder="e.g. 3 of 5 said they'd pay $50/mo if it handled X…">${esc(entry.notes || "")}</textarea>
      <div class="meta small"><strong>${done} of ${prospects.length}</strong> contacted · aim for 5 real conversations before building anything
        <span class="grow"></span><button class="btn-sm" data-copy>Copy list</button></div>
      <div class="table-wrap"><table><thead><tr><th title="Contacted">✓</th><th>What they said</th><th>Who</th></tr></thead>
        <tbody>${prospectRows(prospects, entry, kind, id) || `<tr><td colspan="3" class="muted">No one listed yet.</td></tr>`}</tbody></table></div>
    </article>`;
  }

  function renderShortlist(main) {
    const sl = loadSL();
    const probs = state.index.problems || {};
    const pCards = Object.entries(sl.problems).map(([key, entry]) => {
      const p = probs[key];
      if (!p) return shortlistCard("problems", key, entry, key, "No longer in the data.", 0, [], "");
      const extra = `${(p.tools || []).length ? `<p class="small">Tools people suggested (your competitors to check): <strong>${p.tools.map(esc).join(", ")}</strong></p>` : ""}
        ${(p.money_notes || []).length ? `<p class="small money">$ ${p.money_notes.map(esc).join(" · ")}</p>` : ""}${p.search_keyword ? validateLinks(p.search_keyword) : ""}`;
      return shortlistCard("problems", key, entry, p.title, `${esc(p.summary || "")} · seen ${plural(p.days_seen, "week")}, ${plural(sum(p.counts), "lead")}`, p.opp, p.leads || [], extra);
    });
    const lCards = Object.entries(sl.leads).map(([id, entry]) => {
      const x = entry.snap || {};
      return shortlistCard("leads", id, entry, x.title || id, `${esc(x.niche || "")} · ${esc(x.where || "")} · ${esc(x.date || "")}`, x.opp, x.url ? [x] : [], "");
    });
    main.innerHTML = `
      <h2>Shortlist</h2>
      <p class="sub">The problems and leads you starred, with everyone who voiced them. These people are your first sales conversations, and they cost nothing to reach. Your shortlist, notes and ticks are saved in this browser only; use Export to back them up or move them to another device.</p>
      <div class="toolbar"><button class="btn-sm" id="sl-export">Export</button><button class="btn-sm" id="sl-import">Import</button><input type="file" id="sl-file" accept="application/json" hidden>
        <span class="muted small">${plural(pCards.length, "problem")}, ${plural(lCards.length, "lead")}</span></div>
      ${pCards.length + lCards.length ? "" : `<div class="empty">Nothing starred yet. Use ☆ on a problem card, a lead, or a row in the Problems tab.<br><br>
        A simple path: <strong>Spotted</strong> → read the evidence and the tools suggested → <strong>Talking to people</strong> (message five of the posters: how do you handle this today, what does it cost you?) → <strong>Landing page up</strong> (one page, an email box, share it where they are) → <strong>Pre-sold</strong> (someone pays or commits before you build).</div>`}
      ${pCards.length ? `<h2>Problems</h2><div class="sl-list">${pCards.join("")}</div>` : ""}
      ${lCards.length ? `<h2>Individual leads</h2><div class="sl-list">${lCards.join("")}</div>` : ""}`;

    const entryOf = (el) => { const c = el.closest(".sl"); const cur = loadSL(); return [cur, c.dataset.kind, c.dataset.id, cur[c.dataset.kind][c.dataset.id]]; };
    main.querySelectorAll("[data-status]").forEach((el) => el.addEventListener("change", () => { const [cur, , , en] = entryOf(el); if (en) { en.status = el.value; saveSL(cur); } }));
    main.querySelectorAll("[data-notes]").forEach((el) => el.addEventListener("input", () => { const [cur, , , en] = entryOf(el); if (en) { en.notes = el.value; saveSL(cur); } }));
    main.querySelectorAll("[data-remove]").forEach((el) => el.addEventListener("click", () => { const [cur, k, id] = entryOf(el); delete cur[k][id]; saveSL(cur); render(); }));
    main.querySelectorAll("[data-contact]").forEach((el) => el.addEventListener("change", () => {
      const [k, id, ...u] = el.dataset.contact.split("|"); const cur = loadSL(); const en = cur[k][id]; if (!en) return;
      en.contacted = en.contacted || {}; en.contacted[u.join("|")] = el.checked; saveSL(cur); render();
    }));
    main.querySelectorAll("[data-copy]").forEach((el) => el.addEventListener("click", async () => {
      const [, k, id, en] = entryOf(el);
      const list = k === "problems" ? ((probs[id] || {}).leads || []) : (en.snap ? [en.snap] : []);
      const text = ["Who\tWhere\tDate\tWhat they said\tLink", ...list.map((x) => [x.author || "", x.where || "", x.date || "", (x.need || "").replace(/\s+/g, " "), x.url].join("\t"))].join("\n");
      try { await navigator.clipboard.writeText(text); el.textContent = "Copied"; } catch { el.textContent = "Copy failed"; }
      setTimeout(() => { el.textContent = "Copy list"; }, 1500);
    }));
    $("#sl-export").addEventListener("click", () => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(loadSL(), null, 1)], { type: "application/json" }));
      a.download = `shortlist-${new Date().toISOString().slice(0, 10)}.json`; a.click(); URL.revokeObjectURL(a.href);
    });
    $("#sl-import").addEventListener("click", () => $("#sl-file").click());
    $("#sl-file").addEventListener("change", async (e) => {
      const f = e.target.files[0]; if (!f) return;
      try {
        const inc = JSON.parse(await f.text()), cur = loadSL();
        Object.assign(cur.problems, inc.problems || {}); Object.assign(cur.leads, inc.leads || {}); saveSL(cur); render();
      } catch { alert("That file isn't a shortlist export."); }
    });
  }

  // ----------------------------------------------------------------- browse
  async function renderBrowse(main) {
    const run = await getDay(state.date);
    const q = state.bq || "", src = state.bsrc || "all", rep = state.brep || "all", theme = state.btheme || "all", nf = state.bniche || "all";
    const pool = run.items.filter(segOK);
    const themes = [...new Set(pool.flatMap((it) => it.themes))].sort();
    const niches = [...new Set(pool.map((it) => it.niche))].sort();
    const srcs = [...new Set(pool.map((it) => it.source))];
    const repOK = (it) => { const s = (it.replies || {}).status; return rep === "all" || (rep === "unmet" ? UNMET.includes(s) : rep === "solved" ? s === "solved" : rep === "money" ? (it.money_notes || []).length > 0 : s === rep); };
    const items = pool.filter((it) => (src === "all" || it.source === src) && repOK(it)
      && (theme === "all" || it.themes.includes(theme)) && (nf === "all" || it.niche === nf)
      && (!q || (it.title + " " + it.text + " " + it.channel).toLowerCase().includes(q.toLowerCase())));
    main.innerHTML = `
      <h2>Every lead, ${esc(weekLabel(run.date).toLowerCase())}</h2>
      <div class="toolbar">
        <input id="bq" class="input" type="search" placeholder="Search text" value="${esc(q)}">
        <select id="bniche" aria-label="Niche">${nicheOptions(niches, nf)}</select>
        <select id="btheme"><option value="all">All problem areas</option>${themes.map((t) => `<option ${t === theme ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
        <select id="brep" aria-label="Replies">${[["all", "Any replies"], ["unmet", "Still unmet"], ["agree", "Others say the same"], ["objections", "Tools suggested, not good enough"], ["solved", "Likely solved"], ["money", "Money mentioned"]].map(([v, l]) => `<option value="${v}" ${v === rep ? "selected" : ""}>${l}</option>`).join("")}</select>
        <select id="bsrc"><option value="all">All sources</option>${srcs.map((s) => `<option value="${esc(s)}" ${s === src ? "selected" : ""}>${esc(srcLabel(s))}</option>`).join("")}</select>
        <span class="muted small">${items.length} of ${pool.length}, best opportunity first</span>
      </div>
      <div class="items">${items.slice(0, 400).map(itemRow).join("") || `<div class="empty">Nothing matches.</div>`}</div>`;
    const re = () => render();
    $("#bq").addEventListener("input", (e) => { state.bq = e.target.value; clearTimeout(state.bqT); state.bqT = setTimeout(() => re().then(() => { const el = $("#bq"); el.focus(); el.setSelectionRange(el.value.length, el.value.length); }), 250); });
    $("#bsrc").addEventListener("change", (e) => { state.bsrc = e.target.value; re(); });
    $("#btheme").addEventListener("change", (e) => { state.btheme = e.target.value; re(); });
    $("#bniche").addEventListener("change", (e) => { state.bniche = e.target.value; re(); });
    $("#brep").addEventListener("change", (e) => { state.brep = e.target.value; re(); });
    wireStars(main, leadSnapshot(run));
  }

  // ------------------------------------------------------------------ about
  function renderAbout(main) {
    main.innerHTML = `<div class="prose">
      <h2>How it works</h2>
      <p>Every Monday a GitHub Action reads the past week's posts in places where people who do a job talk to each other, keeps only the posts where someone states a need that isn't being met, reads the replies to see whether it really is unmet, scores each one for how much money is behind it, and adds the result to the history you see here.</p>
      <h2>The opportunity score (0–100)</h2>
      <ul>
        <li><strong>Who pays (25)</strong>: a business owner or practitioner scores highest; a private person lowest.</li>
        <li><strong>Money (20)</strong>: they say they'd pay, name a price they pay now, call the current option too expensive, are losing money, or are paying a freelancer.</li>
        <li><strong>Cost of the problem (20)</strong>: hours lost, work done by hand or in a spreadsheet, staff tied up.</li>
        <li><strong>Still unmet (20)</strong>: from the replies. “Same here” and “I haven't found anything either” raise it; tools suggested and accepted lower it; tools suggested and rejected by the poster keep it high.</li>
        <li><strong>Demand (15, or 30 for a problem)</strong>: engagement on the post; for a problem, how many different people, sources and weeks.</li>
      </ul>
      <p>It is arithmetic on public posts, not a forecast. Use it to decide what to look at first.</p>
      <h2>Business and consumer</h2>
      <p>The switch at the top right shows <em>business</em> leads by default: people speaking as someone doing a job. <em>Consumer</em> holds private wishes (budgeting, ADHD, caregiving, travel). Consumer products need thousands of customers at low prices; a business with an expensive problem needs far fewer.</p>
      <h2>Where it looks</h2>
      <ul>
        <li><strong>Reddit communities of practitioners</strong> (about 140, in some 50 niches). The whole week of posts is read, then the reply thread of each lead.</li>
        <li><strong>Merchant and professional forums</strong>: Shopify Community, Spiceworks, Mac Power Users, Make.</li>
        <li><strong>Freelance gigs</strong> where a business pays for a custom tool because nothing off the shelf fits.</li>
        <li><strong>Hacker News</strong>, <strong>Stack Exchange Software Recommendations</strong> and <strong>Bluesky</strong>.</li>
      </ul>
      <h2>What counts as a lead</h2>
      <p>A post is kept only if it asks for a tool, wishes something existed, says they'd pay, says nothing on the market fits, asks how others cope, describes work done by hand or in a painful spreadsheet, or wants to leave a named product. Removed on purpose: people promoting or validating their own product, one-product support questions, and career questions.</p>
      <h2>From a lead to a business</h2>
      <ol>
        <li>Star what looks promising. It goes to the <em>Shortlist</em> with everyone who voiced it.</li>
        <li>Check the tools people suggested and the <em>Validate</em> links: are there ads and competitors, and what do they charge?</li>
        <li>Message five of the posters. Ask how they handle it today and what it costs them. Tick them off and keep notes.</li>
        <li>Watch <em>Forced changes</em> for a shutdown or price rise in that niche: those openings are time-limited.</li>
        <li>Before building, put up one page with an email form and aim for 20–30 sign-ups, or better, one person who pays in advance.</li>
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
