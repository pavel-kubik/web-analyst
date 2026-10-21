// Dashboard: loads data/manifest.json, fetches the runs in the chosen window, computes trends with trends.js.
import {
  STATUS_CLASSES, THRESHOLDS, attention, fmtMetric, latencyTrend, pageMetrics, pathOf, recentChanges, rate, regressions,
  runsInWindow, siteSummary, statusTrend, topBy, urlSeries, verdictChanges,
} from "./trends.js";

const app = document.getElementById("app");
const daysSel = document.getElementById("days");
const bucketSel = document.getElementById("bucket");
const runCache = new Map();
// data/ and shots/ come from the R2 bucket in production; empty base = same origin for local preview.
const BASE = document.querySelector('meta[name="data-base"]')?.content || "";
let charts = [];
let pageChart = null;
// Site-page table state; survives re-renders so changing the window keeps the view.
const view = { sort: "content", dir: -1, filter: "", problems: false, overLimits: false, tier: "", tab: "content", all: false };
const PAGE_ROWS = 25;
const MIN_BUCKETS = 3; // fewer points than this is not a trend: show a note instead of a near-empty chart

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const fmt = (v, digits = 2) => (v == null ? "–" : Number(v).toFixed(digits));
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const when = (iso) => iso.slice(0, 16).replace("T", " ");
const siteHash = (id, extra = {}) => "#" + new URLSearchParams({ site: id, ...extra });

// Data format versions this page can read (manifest.version; run files live under data/v<N>/).
const SUPPORTED_VERSIONS = [1];

async function getJson(url, options) {
  const r = await fetch(url, options);
  if (!r.ok) throw new Error(`${url.replace(BASE, "")}: HTTP ${r.status}`);
  return r.json();
}

function loadRun(path) {
  if (!runCache.has(path)) runCache.set(path, getJson(BASE + path).catch((err) => { runCache.delete(path); throw err; }));
  return runCache.get(path);
}

/** Sites with the runs in the window. A run file that fails to load is skipped and counted; only the manifest is required. */
async function loadSites() {
  const manifest = await getJson(BASE + "data/manifest.json", { cache: "no-store" });
  if (!SUPPORTED_VERSIONS.includes(manifest.version)) {
    throw new Error(`data format v${manifest.version} is not supported by this page (expects v${SUPPORTED_VERSIONS.join(", v")}) – an upgrade is probably in progress`);
  }
  const days = Number(daysSel.value);
  let failed = 0;
  const sites = await Promise.all(manifest.sites.map(async (site) => {
    const settled = await Promise.allSettled(runsInWindow(site.runs, days).map((r) => loadRun(r.path)));
    failed += settled.filter((r) => r.status === "rejected").length;
    const runs = settled.filter((r) => r.status === "fulfilled").map((r) => r.value);
    const last = runs[runs.length - 1];
    const metrics = last ? last.pages.map(pageMetrics) : [];
    return { ...site, runs, last, metrics, summary: siteSummary(metrics) };
  }));
  return { sites, failed };
}

function chart(canvas, type, labels, datasets, yTitle, extra = {}) {
  const grid = css("--line"), text = css("--muted");
  const c = new Chart(canvas, {
    type,
    data: { labels, datasets },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      spanGaps: true,
      scales: {
        x: { stacked: type === "bar", ticks: { color: text, maxRotation: 0, autoSkipPadding: 12 }, grid: { color: grid } },
        y: { stacked: type === "bar", beginAtZero: true, title: { display: !!yTitle, text: yTitle, color: text }, ticks: { color: text }, grid: { color: grid }, ...extra.y },
      },
      plugins: { legend: { labels: { color: text, boxWidth: 12 } } },
    },
  });
  charts.push(c);
  return c;
}

const line = (label, data, color, dash) => ({ label, data, borderColor: color, backgroundColor: color, pointRadius: 2, borderDash: dash });

/** A chart slot, or a note while there are too few buckets to call it a trend. */
function chartSlot(title, buckets, note = "") {
  const body = buckets >= MIN_BUCKETS
    ? '<div class="chart"><canvas></canvas></div>'
    : `<div class="empty">${buckets ? `Measured in ${buckets} ${bucketSel.value}${buckets > 1 ? "s" : ""} so far` : "No data yet"} — the trend appears after ${MIN_BUCKETS}</div>`;
  return `<div><h3>${esc(title)}</h3>${body}${note ? `<p class="muted">${esc(note)}</p>` : ""}</div>`;
}

function excludedNote(trend) {
  const total = trend.reduce((a, t) => a + t.total, 0), excluded = trend.reduce((a, t) => a + t.excluded, 0);
  return total ? `${excluded} of ${total} samples excluded (non-2xx, browser check, error) — ${Math.round((100 * excluded) / total)} %` : "";
}

/** KPI tiles shared by the overview cards and the site page. */
function tiles(s) {
  const tile = (value, label, rating = "") => `<div class="tile ${rating}"><b>${value}</b><span>${esc(label)}</span></div>`;
  return `<div class="tiles">
    ${tile(fmtMetric("content", s.p90.content), "P90 time to content")}
    ${tile(fmtMetric("ttfb", s.p90.ttfb), "P90 TTFB", rate("ttfb", s.p90.ttfb) === "good" ? "" : rate("ttfb", s.p90.ttfb))}
    ${tile(fmtMetric("lcp", s.p90.lcp), "P90 LCP", rate("lcp", s.p90.lcp) === "good" ? "" : rate("lcp", s.p90.lcp))}
    ${tile(s.over.cls, `pages CLS > ${THRESHOLDS.cls[0]}`, s.over.cls ? "ni" : "")}
  </div>`;
}

function verdictPill(s) {
  const worst = s.FAIL ? "FAIL" : s.WARN ? "WARN" : "OK";
  return `<span class="pill ${worst}">${worst === "OK" ? `${s.OK} / ${s.pages} OK` : `${s[worst]} ${worst}`}</span>`;
}

function renderOverview(sites) {
  const live = sites.filter((s) => s.last);
  if (!live.length) {
    app.innerHTML = '<p class="muted">No results yet.</p>';
    return;
  }
  const total = live.reduce((a, s) => a + s.summary.pages, 0);
  const fail = live.reduce((a, s) => a + s.summary.FAIL, 0), warn = live.reduce((a, s) => a + s.summary.WARN, 0);
  const changed = live.reduce((a, s) => a + (s.runs.length > 1 ? verdictChanges(s.runs[s.runs.length - 2], s.last).length : 0), 0);
  const lastAt = live.map((s) => s.last.measured_at).sort().pop();
  const level = fail ? "fail" : warn ? "warn" : "ok";
  const headline = fail || warn
    ? [fail && `${fail} page${fail > 1 ? "s" : ""} failing`, warn && `${warn} with warnings`].filter(Boolean).join(", ") + ` of ${total}`
    : `All ${total} pages pass the Google Ads checks`;
  const problemSites = live.filter((s) => s.summary.FAIL || s.summary.WARN);

  // Things past Google's limits that don't fail the verdict, summed over sites.
  const insights = [
    ["cls", (s) => s.over.cls, "Layout shifts while loading", `CLS above Google's ${THRESHOLDS.cls[0]} limit`],
    ["lcp", (s) => s.over.lcp, "Main content appears late", `LCP above ${THRESHOLDS.lcp[0]} s`],
    ["ttfb", (s) => s.over.ttfb, "Slow server response", `TTFB above ${THRESHOLDS.ttfb[0]} s`],
    ["errors", (s) => s.errorPages, "Console errors", "pages log JavaScript errors on first visit"],
  ].map(([tab, count, title, what]) => {
    const per = live.map((s) => ({ s, n: count(s.summary) })).filter((x) => x.n);
    if (!per.length) return "";
    const n = per.reduce((a, x) => a + x.n, 0), top = per.sort((a, b) => b.n - a.n)[0].s;
    const worst = tab === "errors" ? null : topBy(top.metrics, tab, 1)[0];
    return `<a class="insight" href="${siteHash(top.id, { tab })}">
      <span><span class="pill ${tab === "errors" ? "" : "ni"}">${n} page${n > 1 ? "s" : ""}</span> <b>${esc(title)}</b></span>
      <span class="muted">${esc(what)} · ${per.map((x) => `${esc(x.s.name)} ${x.n}`).join(", ")}${worst ? ` · worst ${esc(worst.path)} ${fmtMetric(tab, worst[tab])}` : ""}</span></a>`;
  }).filter(Boolean);

  const events = live.flatMap((s) => recentChanges(s.runs).map((e) => ({ ...e, site: s }))).sort((a, b) => b.at.localeCompare(a.at)).slice(0, 8);

  app.innerHTML = `
    <section class="card banner ${level}">
      <div class="icon">${level === "ok" ? "✓" : "!"}</div>
      <div><b>${esc(headline)}</b>
        <span class="muted">Last run ${esc(when(lastAt))} UTC · ${live.length} site${live.length > 1 ? "s" : ""} · ${changed ? `${changed} verdict change${changed > 1 ? "s" : ""} since the previous run` : "no verdict changes since the previous run"}</span>
        ${problemSites.length ? `<div>${problemSites.map((s) => `<a href="${siteHash(s.id, { problems: 1 })}">${esc(s.name)}: ${s.summary.FAIL} FAIL, ${s.summary.WARN} WARN →</a>`).join(" · ")}</div>` : ""}
      </div>
    </section>
    ${insights.length ? `<div class="section-title">Worth a look · not failing</div><div class="grid">${insights.join("")}</div>` : ""}
    <div class="section-title">Sites</div>
    <div class="sites">${sites.map(siteCard).join("")}</div>
    ${events.length ? `<section class="card"><h2>Recent changes</h2><div class="changes">${events.map(changeRow).join("")}</div></section>` : ""}`;

  for (const site of live) {
    const canvas = app.querySelector(`[data-site="${CSS.escape(site.id)}"] canvas`);
    if (!canvas) continue;
    const bucket = bucketSel.value, http = latencyTrend(site.runs, "http", bucket), browser = latencyTrend(site.runs, "browser", bucket);
    chart(canvas, "line", http.map((t) => t.key), [
      line("P90 TTFB", http.map((t) => t.p90), css("--s1")),
      line("P90 time to content", browser.map((t) => t.p90), css("--s2")),
    ], "seconds");
  }
}

function siteCard(site) {
  if (!site.last) return `<section class="card"><h2>${esc(site.name)}</h2><p class="muted">No runs in this window.</p></section>`;
  const s = site.summary;
  const buckets = latencyTrend(site.runs, "http", bucketSel.value).length;
  const items = attention(site.metrics, 3);
  return `<section class="card" data-site="${esc(site.id)}" style="margin:0;display:flex;flex-direction:column;gap:14px">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:baseline">
      <div><h2><a href="${siteHash(site.id)}" style="color:inherit">${esc(site.name)}</a></h2>
        <span class="muted">${s.pages} pages · ${site.runs.length} runs in window · last ${esc(when(site.last.measured_at))} UTC</span></div>
      ${verdictPill(s)}
    </div>
    ${tiles(s)}
    ${chartSlot("P90 latency", buckets)}
    <div><h3>Needs attention</h3>${items.length
      ? `<div class="list">${items.map((i) => `<a href="${siteHash(site.id, { page: i.m.path })}"><span class="ellipsis">${esc(i.m.path)}</span><b class="${i.rating}">${esc(i.label)}</b></a>`).join("")}</div>`
      : '<p class="muted">Nothing past Google\'s limits.</p>'}</div>
    <a href="${siteHash(site.id)}" style="font-weight:600">Open ${esc(site.name)} →</a>
  </section>`;
}

function changeRow(e) {
  // Keep the host when it isn't the site's own (early runs measured middex.cz/ next to www.middex.cz/).
  const u = e.url && new URL(e.url), path = u && pathOf(e.url);
  const label = u && e.site.domain && u.host !== new URL(e.site.domain).host ? u.host + path : path;
  const what = e.type === "pages"
    ? `Pages measured ${e.from} → ${e.to}`
    : `<span class="pill ${e.from}">${e.from}</span> → <span class="pill ${e.to}">${e.to}</span> <a href="${siteHash(e.site.id, { page: path })}">${esc(label)}</a>`;
  return `<div><span class="muted">${esc(when(e.at))}</span><span>${esc(e.site.name)}</span><span>${what}</span></div>`;
}

const TABS = [
  { key: "content", label: "Slowest content" },
  { key: "ttfb", label: "Slowest TTFB" },
  { key: "kb", label: "Heaviest" },
  { key: "lcp", label: "Slowest LCP" },
  { key: "cls", label: "Layout shift" },
  { key: "regressed", label: "Regressed" },
  { key: "errors", label: "Console errors" },
];

const COLUMNS = [
  { key: "path", label: "Path", cls: "l" },
  { key: "verdict", label: "Verdict", cls: "l" },
  { key: "status", label: "Status", hide: true },
  { key: "ttfb", label: "TTFB s" },
  { key: "content", label: "Content s" },
  { key: "lcp", label: "LCP s" },
  { key: "cls", label: "CLS" },
  { key: "kb", label: "KB", hide: true },
  { key: "requests", label: "Req", hide: true },
  { key: "errors", label: "Err", hide: true },
];

function cell(m, key) {
  if (key === "path") return `<td class="path ellipsis" title="${esc(m.url)}">${esc(m.path)}</td>`;
  if (key === "verdict") return `<td class="l" data-label="Verdict"><span class="pill ${esc(m.verdict)}">${esc(m.verdict)}</span></td>`;
  const col = COLUMNS.find((c) => c.key === key);
  const v = m[key];
  const text = v == null ? "–" : key === "cls" ? fmt(v, 3) : key === "kb" || key === "requests" || key === "errors" || key === "status" ? Math.round(v) : fmt(v);
  const r = rate(key, v);
  return `<td data-label="${esc(col.label)}" class="${col.hide ? "hide-sm" : ""}"><b class="r ${r && r !== "good" ? r : ""}" style="font-weight:inherit">${text}</b></td>`;
}

function renderSite(site, params) {
  if (!site.last) {
    app.innerHTML = `<p><a href="#">← all sites</a></p><p class="muted">No runs for ${esc(site.name)} in this window.</p>`;
    return;
  }
  if (params.get("tab")) view.tab = params.get("tab");
  if (params.get("problems")) Object.assign(view, { problems: true, filter: "", overLimits: false, tier: "" }); // overview's "show failing pages" link
  const { last, metrics, summary: s } = site;
  const d = last.discovery;
  const problems = metrics.filter((m) => m.verdict !== "OK");
  const bucket = bucketSel.value;
  const http = latencyTrend(site.runs, "http", bucket), browser = latencyTrend(site.runs, "browser", bucket), st = statusTrend(site.runs, bucket);
  const regressed = [...regressions(site.runs, "browser"), ...regressions(site.runs, "http")];
  const counts = { cls: s.over.cls, regressed: regressed.length, errors: s.errorPages };

  app.innerHTML = `
    <p><a href="#">← all sites</a></p>
    <section style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;justify-content:space-between">
      <div><h1>${esc(site.name)}</h1>
        <span class="muted">${esc(site.domain || "")}${d ? ` · ${d.url_count} pages from ${d.sitemaps.length} sitemap${d.sitemaps.length === 1 ? "" : "s"}${d.capped ? " (capped)" : ""}` : ""} · last run ${esc(when(last.measured_at))} UTC</span></div>
      <div style="display:flex;gap:6px">${["OK", "WARN", "FAIL"].map((v) => `<span class="pill ${s[v] ? v : ""}">${s[v]} ${v}</span>`).join("")}</div>
    </section>
    ${d?.errors?.length ? `<ul class="WARN">${d.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>` : ""}
    <section class="card">${tiles(s)}</section>
    ${problems.length ? `<section class="card"><h2>Problems in the last run</h2><ul>${problems.map((p) => `<li><span class="pill ${esc(p.verdict)}">${esc(p.verdict)}</span> <a href="${siteHash(site.id, { page: p.path })}">${esc(p.path)}</a><ul>${p.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></li>`).join("")}</ul></section>` : ""}
    <section class="card">
      <div style="display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:center;margin-bottom:12px">
        <h2>Needs attention</h2>
        <div class="tabs" role="tablist" aria-label="Ranking">${TABS.map((t) => `<button role="tab" data-tab="${t.key}" aria-selected="${view.tab === t.key}">${esc(t.label)}${counts[t.key] != null ? ` · ${counts[t.key]}` : ""}</button>`).join("")}</div>
      </div>
      <div id="rank"></div>
    </section>
    <section class="card"><div class="charts">
      ${chartSlot("Pages by status (share)", st.length)}
      ${chartSlot("HTTP TTFB", http.length, excludedNote(http))}
      ${chartSlot("Browser time to real content (first visit)", browser.length, excludedNote(browser))}
    </div></section>
    <div class="split">
      <section class="card tablecard">
        <div class="toolbar">
          <input type="search" id="filter" placeholder="Filter by path" aria-label="Filter pages by path" value="${esc(view.filter)}">
          <label><input type="checkbox" id="problems" ${view.problems ? "checked" : ""}> Problems only</label>
          <label><input type="checkbox" id="over" ${view.overLimits ? "checked" : ""}> Over Google limits</label>
          <select id="tier" aria-label="Tier"><option value="">All tiers</option>${["full", "light"].map((t) => `<option ${view.tier === t ? "selected" : ""}>${t}</option>`).join("")}</select>
        </div>
        <div class="scroll"><table><thead><tr>${COLUMNS.map((c) => `<th class="${c.cls || ""}"><button data-sort="${c.key}">${esc(c.label)}</button></th>`).join("")}</tr></thead><tbody id="rows"></tbody></table></div>
        <div class="foot" id="foot"></div>
      </section>
      <aside class="card panel" id="panel" hidden></aside>
    </div>`;

  // Status share: page counts change as sitemaps grow, so absolute counts would look like traffic swings.
  const canvases = app.querySelectorAll(".charts canvas");
  const slots = [st.length, http.length, browser.length].map((n) => n >= MIN_BUCKETS);
  let ci = 0;
  if (slots[0]) {
    const colors = { "2xx": css("--ok"), "3xx": css("--s4"), "4xx": css("--warn"), "5xx": css("--fail"), error: css("--s3") };
    const share = (t, c) => { const n = STATUS_CLASSES.reduce((a, k) => a + t[k], 0); return n ? (100 * t[c]) / n : null; };
    chart(canvases[ci++], "bar", st.map((t) => t.key), STATUS_CLASSES.map((c) => ({ label: c, data: st.map((t) => share(t, c)), backgroundColor: colors[c] })), "% of pages", { y: { max: 100 } });
  }
  for (const [ok, trend] of [[slots[1], http], [slots[2], browser]]) {
    if (!ok) continue;
    chart(canvases[ci++], "line", trend.map((t) => t.key), [line("mean", trend.map((t) => t.mean), css("--s1")), line("P90", trend.map((t) => t.p90), css("--s2"), [4, 3])], "seconds");
  }

  const drawRank = () => {
    const tab = view.tab;
    app.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab));
    let rows;
    const key = tab;
    if (tab === "regressed") {
      rows = regressed.map((m) => ({ ...m, value: m.latest, label: `${fmtMetric("ttfb", m.latest)} vs ${fmtMetric("ttfb", m.baseline)}` }));
    } else {
      rows = topBy(metrics, tab, 6).map((m) => ({ ...m, value: m[tab], label: tab === "errors" ? `${m.errors} error${m.errors > 1 ? "s" : ""}` : fmtMetric(tab, m[tab]) }));
      // Layout shift and errors only list offenders; the latency tabs always rank the slowest pages.
      if (tab === "cls") rows = rows.filter((m) => rate("cls", m.value) !== "good");
      if (tab === "errors") rows = rows.filter((m) => m.errors > 0);
    }
    if (!rows.length) {
      app.querySelector("#rank").innerHTML = `<p class="muted">${tab === "regressed" ? "No page is much slower than its own history." : "Nothing here in the last run."}</p>`;
      return;
    }
    const t = THRESHOLDS[key];
    const max = Math.max(...rows.map((r) => r.value), t ? t[1] * 1.1 : 0);
    const ticks = t && tab !== "regressed" ? t.map((v) => `<span class="tick" style="left:${(100 * v) / max}%"></span>`).join("") : "";
    const more = tab === "cls" ? s.over.cls - rows.length : 0;
    app.querySelector("#rank").innerHTML = rows.map((r) => `<div class="rank">
        <a class="ellipsis" href="${siteHash(site.id, { page: r.path })}">${esc(r.path)}</a>
        <div class="track"><span class="fill ${rate(key, r.value) || ""}" style="width:${((100 * r.value) / max).toFixed(1)}%"></span>${ticks}</div>
        <b style="text-align:right" class="${rate(key, r.value) === "good" ? "" : rate(key, r.value) || ""}">${esc(r.label)}</b></div>`).join("")
      + `<p class="muted" style="font-size:12px;margin:6px 0 0">${t && tab !== "regressed" ? `Ticks mark Google's limits: ${t[0]} good, ${t[1]} poor. ` : ""}${tab === "regressed" ? "Latest value above 1.5 × the page's own P90 over the window. " : ""}${more > 0 ? `${more} more over the limit — use “Over Google limits” in the table.` : ""}</p>`;
  };

  const visible = () => {
    const q = view.filter.toLowerCase();
    const over = (m) => Object.keys(THRESHOLDS).some((k) => ["ni", "poor"].includes(rate(k, m[k])));
    return metrics
      .filter((m) => (!q || m.path.toLowerCase().includes(q)) && (!view.problems || m.verdict !== "OK") && (!view.overLimits || over(m)) && (!view.tier || m.tier === view.tier))
      .sort((a, b) => {
        const [x, y] = [a[view.sort], b[view.sort]];
        if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1; // missing values last either way
        return (typeof x === "string" ? x.localeCompare(y) : x - y) * view.dir;
      });
  };

  let selected = params.get("page");
  const drawTable = () => {
    const list = visible(), shown = view.all ? list : list.slice(0, PAGE_ROWS);
    app.querySelectorAll("[data-sort]").forEach((b) => {
      b.classList.toggle("on", b.dataset.sort === view.sort);
      b.textContent = COLUMNS.find((c) => c.key === b.dataset.sort).label + (b.dataset.sort === view.sort ? (view.dir < 0 ? " ↓" : " ↑") : "");
    });
    app.querySelector("#rows").innerHTML = shown.map((m) => `<tr class="pick ${m.path === selected ? "sel" : ""}" data-path="${esc(m.path)}">${COLUMNS.map((c) => cell(m, c.key)).join("")}</tr>`).join("")
      || `<tr><td colspan="${COLUMNS.length}" class="muted">No pages match.</td></tr>`;
    app.querySelector("#foot").innerHTML = `<span>${shown.length} of ${list.length} pages${list.length < metrics.length ? ` (${metrics.length} in total)` : ""} · chrome HTTP + first Chromium visit · click a column to sort</span>`
      + (list.length > shown.length ? `<button id="all">Show all ${list.length}</button>` : "");
    app.querySelector("#all")?.addEventListener("click", () => { view.all = true; drawTable(); });
    app.querySelectorAll("tr.pick").forEach((tr) => tr.addEventListener("click", () => select(tr.dataset.path, true)));
  };

  const select = (path, fromClick) => {
    selected = path;
    app.querySelectorAll("tr.pick").forEach((tr) => tr.classList.toggle("sel", tr.dataset.path === path));
    if (fromClick) history.replaceState(null, "", siteHash(site.id, { page: path }));
    drawPanel(site, metrics.find((m) => m.path === path));
    // On a phone the panel sits below the whole list.
    if (fromClick && matchMedia("(max-width: 640px)").matches) app.querySelector("#panel").scrollIntoView({ behavior: "smooth" });
  };

  app.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => { view.tab = b.dataset.tab; drawRank(); }));
  app.querySelectorAll("[data-sort]").forEach((b) => b.addEventListener("click", () => {
    const key = b.dataset.sort;
    view.dir = view.sort === key ? -view.dir : key === "path" || key === "verdict" ? 1 : -1;
    view.sort = key;
    drawTable();
  }));
  app.querySelector("#filter").addEventListener("input", (e) => { view.filter = e.target.value; drawTable(); });
  app.querySelector("#problems").addEventListener("change", (e) => { view.problems = e.target.checked; drawTable(); });
  app.querySelector("#over").addEventListener("change", (e) => { view.overLimits = e.target.checked; drawTable(); });
  app.querySelector("#tier").addEventListener("change", (e) => { view.tier = e.target.value; drawTable(); });

  drawRank();
  drawTable();
  if (!metrics.some((m) => m.path === selected)) selected = metrics[0]?.path;
  select(selected, false);
  if (params.get("page")) app.querySelector("#panel").scrollIntoView({ block: "nearest" });
}

function drawPanel(site, m) {
  const panel = app.querySelector("#panel");
  if (!m) { panel.hidden = true; return; }
  panel.hidden = false;
  const page = site.last.pages.find((p) => p.url === m.url);
  const verdicts = site.runs.map((r) => ({ at: r.measured_at, v: r.pages.find((p) => p.url === m.url)?.verdict })).filter((x) => x.v);
  const adsbot = page.samples.find((x) => x.kind === "http" && x.profile === "adsbot-google");
  const shots = page.samples.flatMap((x) => (x.screenshots || []).map((src) => ({ src, x })));
  const metric = (k, label, text) => {
    const r = rate(k, m[k]);
    return `<div><b class="${r && r !== "good" ? r : ""}">${text ?? fmtMetric(k, m[k])}</b>${esc(label)}</div>`;
  };
  panel.innerHTML = `
    <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">
      <div><span class="muted" style="font-size:12px">Selected page · tier ${esc(m.tier)}</span>
        <h2 style="word-break:break-all"><a href="${esc(m.url)}" target="_blank" rel="noopener" style="color:inherit">${esc(m.path)}</a></h2></div>
      <button class="close" aria-label="Close page details">×</button>
    </div>
    <p><span class="pill ${esc(m.verdict)}">${esc(m.verdict)}</span> ${m.reasons.length ? "" : '<span class="muted">no issues in the last run</span>'}</p>
    ${m.reasons.length ? `<ul>${m.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
    <h3 style="margin-top:12px">Verdict per run (${verdicts.length})</h3>
    <div class="strip">${verdicts.map((x) => `<span class="${esc(x.v)}" title="${esc(when(x.at))} ${esc(x.v)}"></span>`).join("")}</div>
    <h3 style="margin-top:12px">Latency over time</h3>
    <div class="chart" style="height:170px"><canvas id="pageChart"></canvas></div>
    <div class="metrics" style="margin-top:12px">
      ${metric("ttfb", "TTFB")}${metric("content", "time to content")}${metric("lcp", "LCP")}
      ${metric("cls", "CLS")}<div><b>${m.fcp == null ? "–" : `${Math.round(m.fcp)} ms`}</b>FCP</div><div><b>${m.kb == null ? "–" : `${Math.round(m.kb)} KB`}</b>weight</div>
      <div><b>${m.requests ?? "–"}</b>requests</div><div><b>${m.errors ?? "–"}</b>console errors</div>
      ${adsbot ? `<div><b class="${adsbot.status === 200 && !adsbot.challenge ? "" : "poor"}">${esc(adsbot.error ? "error" : adsbot.status)}${adsbot.challenge ? " (check)" : ""}</b>AdsBot status</div>` : ""}
    </div>
    ${shots.length ? `<h3 style="margin-top:12px">Screenshots (latest)</h3><div class="shots">${shots.map(({ src, x }) => `<figure><a href="${esc(BASE + src)}" target="_blank" rel="noopener"><img src="${esc(BASE + src)}" alt="${esc(x.profile)} ${esc(x.visit)} visit" loading="lazy"></a><figcaption>${esc(x.profile)} · ${esc(x.visit)}</figcaption></figure>`).join("")}</div>` : ""}`;
  panel.querySelector(".close").addEventListener("click", () => {
    panel.hidden = true;
    app.querySelectorAll("tr.sel").forEach((tr) => tr.classList.remove("sel"));
    history.replaceState(null, "", siteHash(site.id));
  });
  if (pageChart) { pageChart.destroy(); charts = charts.filter((c) => c !== pageChart); }
  const http = urlSeries(site.runs, m.url, "http"), browser = urlSeries(site.runs, m.url, "browser");
  pageChart = chart(panel.querySelector("#pageChart"), "line", http.map((p) => p.at.slice(5, 16).replace("T", " ")), [
    line("TTFB", http.map((p) => p.value), css("--s1")),
    line("time to content", browser.map((p) => p.value), css("--s2")),
  ], "seconds");
}

async function render() {
  charts.forEach((c) => c.destroy());
  charts = [];
  pageChart = null;
  try {
    const { sites, failed } = await loadSites();
    const params = new URLSearchParams(location.hash.slice(1));
    const site = params.get("site") && sites.find((s) => s.id === params.get("site"));
    site ? renderSite(site, params) : renderOverview(sites);
    if (failed) app.insertAdjacentHTML("afterbegin", `<p class="muted WARN">${failed} measurement run(s) could not be loaded and are left out.</p>`);
  } catch (err) {
    app.innerHTML = `<p class="FAIL">Could not load data: ${esc(err.message)}</p>`;
  }
}

window.addEventListener("hashchange", render);
daysSel.addEventListener("change", render);
bucketSel.addEventListener("change", render);
render();
