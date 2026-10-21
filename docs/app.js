// Dashboard: loads data/manifest.json, fetches the runs in the chosen window, computes trends with trends.js.
import {
  STATUS_CLASSES, isEligible, latencyOf, latencyTrend, pageStatus, percentile, runsInWindow, statusCounts,
  statusTrend, trendSample, urlSeries,
} from "./trends.js";

const app = document.getElementById("app");
const daysSel = document.getElementById("days");
const bucketSel = document.getElementById("bucket");
const runCache = new Map();
// data/ and shots/ come from the R2 bucket in production; empty base = same origin for local preview.
const BASE = document.querySelector('meta[name="data-base"]')?.content || "";
let charts = [];

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const fmt = (v, digits = 2) => (v == null ? "–" : Number(v).toFixed(digits));
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

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
    return { ...site, runs: settled.filter((r) => r.status === "fulfilled").map((r) => r.value) };
  }));
  return { sites, failed };
}

function chart(canvas, type, labels, datasets, yTitle) {
  const grid = css("--line"), text = css("--muted");
  charts.push(new Chart(canvas, {
    type,
    data: { labels, datasets },
    options: {
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      spanGaps: true,
      scales: {
        x: { stacked: type === "bar", ticks: { color: text, maxRotation: 0, autoSkipPadding: 12 }, grid: { color: grid } },
        y: { stacked: type === "bar", beginAtZero: true, title: { display: !!yTitle, text: yTitle, color: text }, ticks: { color: text }, grid: { color: grid } },
      },
      plugins: { legend: { labels: { color: text, boxWidth: 12 } } },
    },
  }));
}

function latencyChart(canvas, trend, label) {
  chart(canvas, "line", trend.map((t) => t.key), [
    { label: "mean", data: trend.map((t) => t.mean), borderColor: css("--s1"), backgroundColor: css("--s1"), pointRadius: 2 },
    { label: "P90", data: trend.map((t) => t.p90), borderColor: css("--warn"), backgroundColor: css("--warn"), pointRadius: 2, borderDash: [4, 3] },
  ], `${label} (s)`);
}

function excludedNote(trend) {
  const total = trend.reduce((a, t) => a + t.total, 0), excluded = trend.reduce((a, t) => a + t.excluded, 0);
  return total ? `${excluded} of ${total} samples excluded (non-2xx, browser check, error) — ${Math.round((100 * excluded) / total)} %` : "no samples yet";
}

function renderOverview(sites) {
  const bucket = bucketSel.value;
  app.innerHTML = sites.length ? "" : '<p class="muted">No results yet.</p>';
  for (const site of sites) {
    const last = site.runs[site.runs.length - 1];
    const card = document.createElement("section");
    card.className = "card";
    if (!last) {
      card.innerHTML = `<h2>${esc(site.name)}</h2><p class="muted">No runs in this window.</p>`;
      app.append(card);
      continue;
    }
    const counts = statusCounts(last);
    const verdicts = Object.fromEntries(["OK", "WARN", "FAIL"].map((v) => [v, last.pages.filter((p) => p.verdict === v).length]));
    const http = latencyTrend(site.runs, "http", bucket), browser = latencyTrend(site.runs, "browser", bucket);
    card.innerHTML = `
      <h2>${esc(site.name)} <a href="#site=${encodeURIComponent(site.id)}" style="font-size:13px;font-weight:400">details →</a></h2>
      <p class="muted">${esc(site.domain || "ad-hoc URLs")} · last run ${esc(last.measured_at.slice(0, 16).replace("T", " "))} UTC · ${site.runs.length} runs in window</p>
      <div class="stats">
        <div class="stat"><b>${last.pages.length}</b><span>pages</span></div>
        ${["OK", "WARN", "FAIL"].map((v) => `<div class="stat"><b class="${v}">${verdicts[v]}</b><span>${v}</span></div>`).join("")}
        ${STATUS_CLASSES.map((c) => `<div class="stat"><b>${counts[c]}</b><span>${c}</span></div>`).join("")}
      </div>
      <div class="charts">
        <div><h3>Pages by status</h3><div class="chart"><canvas></canvas></div></div>
        <div><h3>HTTP TTFB</h3><div class="chart"><canvas></canvas></div><p class="muted">${esc(excludedNote(http))}</p></div>
        <div><h3>Browser time to real content (first visit)</h3><div class="chart"><canvas></canvas></div><p class="muted">${esc(excludedNote(browser))}</p></div>
      </div>`;
    app.append(card);
    const [statusCanvas, httpCanvas, browserCanvas] = card.querySelectorAll("canvas");
    const st = statusTrend(site.runs, bucket);
    const colors = { "2xx": css("--ok"), "3xx": css("--s2"), "4xx": css("--warn"), "5xx": css("--fail"), error: css("--s3") };
    chart(statusCanvas, "bar", st.map((t) => t.key), STATUS_CLASSES.map((c) => ({ label: c, data: st.map((t) => t[c]), backgroundColor: colors[c] })), "pages");
    latencyChart(httpCanvas, http, "TTFB");
    latencyChart(browserCanvas, browser, "content");
  }
}

function renderSite(site) {
  const last = site.runs[site.runs.length - 1];
  if (!last) {
    app.innerHTML = `<p><a href="#">← all sites</a></p><p class="muted">No runs for ${esc(site.name)} in this window.</p>`;
    return;
  }
  const p90Of = (url, kind) => percentile(urlSeries(site.runs, url, kind).map((p) => p.value).filter((v) => v != null), 90);
  const rows = last.pages.map((page, i) => {
    const h = trendSample(page, "http"), b = trendSample(page, "browser");
    const perf = b?.perf || {};
    return `<tr class="pick" data-i="${i}" title="${esc(page.reasons.join("\n"))}">
      <td class="url">${esc(page.url)}</td><td>${esc(page.tier)}</td><td class="b ${esc(page.verdict)}">${esc(page.verdict)}</td>
      <td>${esc(h?.status ?? pageStatus(page))}</td><td>${h && isEligible(h) ? fmt(latencyOf(h)) : "–"}</td><td>${fmt(p90Of(page.url, "http"))}</td>
      <td>${b && isEligible(b) ? fmt(latencyOf(b)) : "–"}</td><td>${fmt(p90Of(page.url, "browser"))}</td>
      <td>${fmt(perf.fcp_ms, 0)}</td><td>${fmt(perf.lcp_ms, 0)}</td><td>${fmt(perf.cls, 3)}</td>
      <td>${perf.page_bytes ? Math.round(perf.page_bytes / 1024) : "–"}</td><td>${fmt(perf.resource_count, 0)}</td><td>${esc(b?.console_errors ?? "–")}</td></tr>`;
  });
  const problems = last.pages.filter((p) => p.verdict !== "OK");
  const shots = last.pages.flatMap((p) => p.samples.flatMap((s) => (s.screenshots || []).map((src) => ({ src, s }))));
  const d = last.discovery;
  app.innerHTML = `
    <p><a href="#">← all sites</a></p>
    <section class="card">
      <h2>${esc(site.name)}</h2>
      <p class="muted">Last run ${esc(last.measured_at.slice(0, 16).replace("T", " "))} UTC${d ? ` · ${d.url_count} pages from ${d.sitemaps.length} sitemap(s)${d.capped ? " (capped)" : ""}` : ""}</p>
      ${d?.errors?.length ? `<ul class="WARN">${d.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>` : ""}
      ${problems.length ? `<h3>Problems in the last run</h3><ul>${problems.map((p) => `<li><span class="b ${esc(p.verdict)}">${esc(p.verdict)}</span> ${esc(p.url)}<ul>${p.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></li>`).join("")}</ul>` : '<p class="OK">No problems in the last run.</p>'}
    </section>
    <section class="card">
      <h3>Selected page over time</h3><p class="muted" id="sel">Click a row below.</p>
      <div class="chart"><canvas id="urlChart"></canvas></div>
    </section>
    <section class="card scroll">
      <table><thead><tr><th>URL</th><th>Tier</th><th>Verdict</th><th>Status</th><th>TTFB s</th><th>P90</th><th>Content s</th><th>P90</th>
        <th>FCP ms</th><th>LCP ms</th><th>CLS</th><th>KB</th><th>Requests</th><th>Console errors</th></tr></thead>
        <tbody>${rows.join("")}</tbody></table>
      <p class="muted">Latest values from chrome HTTP and the first chromium visit; P90 over the selected window. Excluded samples show as –.</p>
    </section>
    ${shots.length ? `<section class="card"><h3>Homepage screenshots (latest)</h3><div class="shots">${shots.map(({ src, s }) => `<figure><a href="${esc(BASE + src)}"><img src="${esc(BASE + src)}" alt="" loading="lazy"></a><figcaption>${esc(s.profile)} · ${esc(s.visit)}</figcaption></figure>`).join("")}</div></section>` : ""}`;

  const canvas = document.getElementById("urlChart");
  const select = (i) => {
    const url = last.pages[i].url;
    app.querySelectorAll("tr.sel").forEach((tr) => tr.classList.remove("sel"));
    app.querySelector(`tr[data-i="${i}"]`).classList.add("sel");
    document.getElementById("sel").textContent = url;
    charts.forEach((c) => c.destroy());
    charts = [];
    const http = urlSeries(site.runs, url, "http"), browser = urlSeries(site.runs, url, "browser");
    chart(canvas, "line", http.map((p) => p.at.slice(5, 16).replace("T", " ")), [
      { label: "HTTP TTFB", data: http.map((p) => p.value), borderColor: css("--s1"), backgroundColor: css("--s1"), pointRadius: 2 },
      { label: "Browser content", data: browser.map((p) => p.value), borderColor: css("--ok"), backgroundColor: css("--ok"), pointRadius: 2 },
    ], "seconds");
  };
  app.querySelectorAll("tr.pick").forEach((tr) => tr.addEventListener("click", () => select(Number(tr.dataset.i))));
  select(0);
}

async function render() {
  charts.forEach((c) => c.destroy());
  charts = [];
  try {
    const { sites, failed } = await loadSites();
    const id = new URLSearchParams(location.hash.slice(1)).get("site");
    const site = id && sites.find((s) => s.id === id);
    site ? renderSite(site) : renderOverview(sites);
    if (failed) app.insertAdjacentHTML("afterbegin", `<p class="muted WARN">${failed} measurement run(s) could not be loaded and are left out.</p>`);
  } catch (err) {
    app.innerHTML = `<p class="FAIL">Could not load data: ${esc(err.message)}</p>`;
  }
}

window.addEventListener("hashchange", render);
daysSel.addEventListener("change", render);
bucketSel.addEventListener("change", render);
render();
