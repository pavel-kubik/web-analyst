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
