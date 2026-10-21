// Trend math over slim run files (docs/data/<site>/<stamp>.json). Pure functions: no DOM, no fetch.

// Trends use only the profiles every page has (the "light" tier), so homepage extras don't skew the mix.
export const TREND_PROFILE = { http: "chrome", browser: "chromium" };

/** Latency rule B: only 2xx responses that delivered real content count. */
export function isEligible(s) {
  if (s.error || typeof s.status !== "number" || s.status < 200 || s.status >= 300) return false;
  if (s.kind === "http") return !s.challenge && typeof s.ttfb_s === "number";
  if (s.kind === "browser") return !s.stuck && typeof s.content_s === "number";
  return false;
}

export function latencyOf(s) {
  return s.kind === "http" ? s.ttfb_s : s.content_s;
}

/** The trend sample of one page for a kind: chrome HTTP, or the cold (first-visit) chromium load. */
export function trendSample(page, kind) {
  return page.samples.find(
    (s) => s.kind === kind && s.profile === TREND_PROFILE[kind] && (kind === "http" || s.visit === "cold"),
  );
}

export function mean(values) {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}

/** Nearest-rank percentile: always a value that was actually measured. */
export function percentile(values, p) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1))];
}

/** UTC day ("2026-10-21") or the Monday that starts the ISO week. */
export function bucketKey(iso, size) {
  const d = new Date(iso);
  const day = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  if (size === "week") day.setUTCDate(day.getUTCDate() - ((day.getUTCDay() + 6) % 7));
  return day.toISOString().slice(0, 10);
}

function groupByBucket(runs, size) {
  const groups = new Map();
  for (const run of [...runs].sort((a, b) => a.measured_at.localeCompare(b.measured_at))) {
    const key = bucketKey(run.measured_at, size);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(run);
  }
  return groups;
}

/** Per bucket: mean and P90 of eligible latencies, plus how many samples the rule excluded. */
export function latencyTrend(runs, kind, size = "day") {
  return [...groupByBucket(runs, size)].map(([key, group]) => {
    const samples = group.flatMap((r) => r.pages.map((p) => trendSample(p, kind)).filter(Boolean));
    const values = samples.filter(isEligible).map(latencyOf);
    return {
      key,
      total: samples.length,
      used: values.length,
      excluded: samples.length - values.length,
      excludedShare: samples.length ? (samples.length - values.length) / samples.length : 0,
      mean: mean(values),
      p90: percentile(values, 90),
    };
  });
}

export const STATUS_CLASSES = ["2xx", "3xx", "4xx", "5xx", "error"];

/** A page's status class, from its chrome HTTP probe (the one probe every page has). */
export function pageStatus(page) {
  const s = trendSample(page, "http");
  if (!s || s.error || typeof s.status !== "number") return "error";
  return `${Math.floor(s.status / 100)}xx`;
}

export function statusCounts(run) {
  const counts = Object.fromEntries(STATUS_CLASSES.map((c) => [c, 0]));
  for (const page of run.pages) {
    const c = pageStatus(page);
    counts[c in counts ? c : "error"] += 1;
  }
  return counts;
}

/** Per bucket: status counts of the last run in that bucket (a snapshot, not a sum over runs). */
export function statusTrend(runs, size = "day") {
  return [...groupByBucket(runs, size)].map(([key, group]) => ({ key, ...statusCounts(group[group.length - 1]) }));
}

/** Path shown in tables: the URL without scheme and host. */
export function pathOf(url) {
  const u = new URL(url);
  return u.pathname + u.search;
}

/** One URL over time: its eligible latency per run, or null when the rule excluded it. */
export function urlSeries(runs, url, kind) {
  return runs.flatMap((run) => {
    const page = run.pages.find((p) => p.url === url);
    if (!page) return [];
    const s = trendSample(page, kind);
    return [{ at: run.measured_at, value: s && isEligible(s) ? latencyOf(s) : null }];
  });
}

/** Manifest run entries measured within the last `days` days. */
export function runsInWindow(manifestRuns, days, now = new Date()) {
  const since = now.getTime() - days * 86400000;
  return manifestRuns.filter((r) => new Date(r.at).getTime() >= since);
}

/** Google's "good" / "poor" limits (web.dev Core Web Vitals; TTFB guidance). LCP in seconds. */
export const THRESHOLDS = { ttfb: [0.8, 1.8], lcp: [2.5, 4], cls: [0.1, 0.25] };

/** "good" | "ni" (needs improvement) | "poor", or null for metrics without a limit or missing values. */
export function rate(metric, value) {
  const t = THRESHOLDS[metric];
  if (!t || value == null) return null;
  return value > t[1] ? "poor" : value > t[0] ? "ni" : "good";
}

/** Flat numbers for one page: chrome HTTP and the cold chromium visit. Latencies are null when rule B excludes them. */
export function pageMetrics(page) {
  const h = trendSample(page, "http"), b = trendSample(page, "browser"), perf = b?.perf || {};
  return {
    url: page.url,
    path: pathOf(page.url),
    tier: page.tier,
    verdict: page.verdict,
    reasons: page.reasons,
    status: h && !h.error ? h.status : null,
    ttfb: h && isEligible(h) ? h.ttfb_s : null,
    content: b && isEligible(b) ? b.content_s : null,
    fcp: perf.fcp_ms ?? null,
    lcp: perf.lcp_ms != null ? perf.lcp_ms / 1000 : null,
    cls: perf.cls ?? null,
    kb: perf.page_bytes != null ? perf.page_bytes / 1024 : null,
    requests: perf.resource_count ?? null,
    errors: b?.console_errors ?? null,
  };
}

/** Headline numbers for one run's pages (as pageMetrics). */
export function siteSummary(metrics) {
  const vals = (k) => metrics.map((m) => m[k]).filter((v) => v != null);
  const over = (k, i) => metrics.filter((m) => m[k] != null && m[k] > THRESHOLDS[k][i]).length;
  const verdicts = Object.fromEntries(["OK", "WARN", "FAIL"].map((v) => [v, metrics.filter((m) => m.verdict === v).length]));
  return {
    pages: metrics.length,
    ...verdicts,
    p90: { ttfb: percentile(vals("ttfb"), 90), content: percentile(vals("content"), 90), lcp: percentile(vals("lcp"), 90) },
    over: { ttfb: over("ttfb", 0), lcp: over("lcp", 0), cls: over("cls", 0), clsPoor: over("cls", 1) },
    errorPages: metrics.filter((m) => m.errors > 0).length,
  };
}

/** The n pages with the highest value of a metric key (missing values left out). */
export function topBy(metrics, key, n = 5) {
  return metrics.filter((m) => m[key] != null).sort((a, b) => b[key] - a[key]).slice(0, n);
}

/** What to look at first: failing / warning pages, then metrics past Google's limits, worst first. */
export function attention(metrics, n = 3) {
  const items = [];
  for (const m of metrics) {
    if (m.verdict !== "OK") items.push({ m, score: m.verdict === "FAIL" ? 100 : 50, label: m.reasons[0] || m.verdict, rating: m.verdict === "FAIL" ? "poor" : "ni" });
    for (const k of Object.keys(THRESHOLDS)) {
      const r = rate(k, m[k]);
      if (r === "poor" || r === "ni") items.push({ m, score: (r === "poor" ? 10 : 0) + m[k] / THRESHOLDS[k][0], label: `${k.toUpperCase()} ${fmtMetric(k, m[k])}`, rating: r });
    }
  }
  return items.sort((a, b) => b.score - a.score).slice(0, n);
}

export function fmtMetric(key, v) {
  if (v == null) return "–";
  if (key === "cls") return v.toFixed(2);
  if (key === "kb") return `${Math.round(v)} KB`;
  return `${v.toFixed(2)} s`;
}

/** Pages whose verdict differs between two runs of a site (pages in only one run are skipped). */
export function verdictChanges(prev, last) {
  const before = new Map(prev.pages.map((p) => [p.url, p.verdict]));
  return last.pages
    .filter((p) => before.has(p.url) && before.get(p.url) !== p.verdict)
    .map((p) => ({ url: p.url, from: before.get(p.url), to: p.verdict }));
}

/** Verdict changes and page-count changes between consecutive runs, newest first. */
export function recentChanges(runs) {
  const sorted = [...runs].sort((a, b) => a.measured_at.localeCompare(b.measured_at));
  const events = [];
  for (let i = 1; i < sorted.length; i++) {
    const [prev, run] = [sorted[i - 1], sorted[i]];
    if (prev.pages.length !== run.pages.length) events.push({ at: run.measured_at, type: "pages", from: prev.pages.length, to: run.pages.length });
    for (const c of verdictChanges(prev, run)) events.push({ at: run.measured_at, type: "verdict", ...c });
  }
  return events.reverse();
}

/**
 * Pages whose latest latency is well above their own history: > 1.5 × P90 of earlier runs and at least 0.5 s worse.
 * Needs 3 earlier eligible values, so new pages and sparse history never count as regressed.
 */
export function regressions(runs, kind) {
  const last = runs[runs.length - 1];
  if (!last) return [];
  return last.pages.flatMap((page) => {
    const series = urlSeries(runs, page.url, kind);
    const latest = series.pop()?.value;
    const history = series.map((p) => p.value).filter((v) => v != null);
    const base = percentile(history, 90);
    if (latest == null || history.length < 3 || !(latest > 1.5 * base && latest - base >= 0.5)) return [];
    return [{ ...pageMetrics(page), latest, baseline: base }];
  });
}
