import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  attention, bucketKey, isEligible, latencyTrend, pageMetrics, pageStatus, pathOf, percentile, rate, recentChanges,
  regressions, runsInWindow, siteSummary, statusCounts, statusTrend, topBy, urlSeries, verdictChanges,
} from "../../docs/trends.js";

const runs = JSON.parse(readFileSync(new URL("../fixtures/slim-runs.json", import.meta.url)));

test("latency rule B: only 2xx with real content counts", () => {
  const http = (o) => ({ kind: "http", status: 200, challenge: false, ttfb_s: 0.5, ...o });
  assert.equal(isEligible(http({})), true);
  assert.equal(isEligible(http({ status: 429 })), false, "fast FORPSI 429 must not lower latency");
  assert.equal(isEligible(http({ challenge: true })), false, "200 challenge page is not content");
  assert.equal(isEligible(http({ status: 301 })), false);
  assert.equal(isEligible({ kind: "http", error: "ConnectTimeout" }), false);
  const browser = (o) => ({ kind: "browser", status: 200, stuck: false, content_s: 2.1, ...o });
  assert.equal(isEligible(browser({})), true);
  assert.equal(isEligible(browser({ stuck: true, content_s: null })), false);
  assert.equal(isEligible(browser({ status: null })), false);
});

test("nearest-rank percentile returns a measured value", () => {
  assert.equal(percentile([], 90), null);
  assert.equal(percentile([5], 90), 5);
  assert.equal(percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90), 9);
  assert.equal(percentile([10, 1, 2], 90), 10);
});

test("day and ISO-week buckets in UTC", () => {
  assert.equal(bucketKey("2026-10-21T23:30:00+00:00", "day"), "2026-10-21");
  assert.equal(bucketKey("2026-10-22T01:30:00+02:00", "day"), "2026-10-21");
  assert.equal(bucketKey("2026-10-21T10:00:00+00:00", "week"), "2026-10-19"); // Wednesday -> Monday
  assert.equal(bucketKey("2026-10-25T10:00:00+00:00", "week"), "2026-10-19"); // Sunday -> same week
});

test("daily latency trend excludes blocked samples and reports the share", () => {
  const [blockedDay, okDay] = latencyTrend(runs, "http", "day");
  assert.equal(blockedDay.key, "2026-10-19");
  assert.equal(blockedDay.total, 3);
  assert.equal(blockedDay.used, 1, "only the clean 200 counts");
  assert.ok(Math.abs(blockedDay.excludedShare - 2 / 3) < 1e-9);
  assert.equal(blockedDay.mean, 1.2);
  assert.equal(okDay.used, 3);
  assert.equal(okDay.p90, 0.9);
});

test("browser trend uses the cold chromium visit only", () => {
  const [, okDay] = latencyTrend(runs, "browser", "day");
  assert.equal(okDay.total, 3);
  assert.equal(okDay.mean, 2);
});

test("status counts come from the chrome HTTP probe", () => {
  assert.deepEqual(statusCounts(runs[0]), { "2xx": 2, "3xx": 0, "4xx": 1, "5xx": 0, error: 0 });
  assert.equal(pageStatus({ samples: [] }), "error");
  const [day1, day2] = statusTrend(runs, "day");
  assert.equal(day1["4xx"], 1);
  assert.equal(day2["2xx"], 3);
});

test("weekly status trend is a snapshot of the last run, not a sum", () => {
  const [week] = statusTrend(runs, "week");
  assert.deepEqual({ ...week, key: undefined }, { key: undefined, "2xx": 3, "3xx": 0, "4xx": 0, "5xx": 0, error: 0 });
});

test("per-URL series keeps excluded runs as gaps", () => {
  const series = urlSeries(runs, "https://www.example.cz/", "http");
  assert.deepEqual(series.map((p) => p.value), [null, 0.3]);
});

test("window filter", () => {
  const manifestRuns = [{ at: "2026-07-01T00:00:00Z" }, { at: "2026-10-20T00:00:00Z" }];
  assert.equal(runsInWindow(manifestRuns, 30, new Date("2026-10-21T00:00:00Z")).length, 1);
});

test("paths drop scheme and host", () => {
  assert.equal(pathOf("https://www.example.cz/search/1?q=x"), "/search/1?q=x");
  assert.equal(pathOf("https://www.example.cz"), "/");
});

test("Google limits rate good / needs improvement / poor", () => {
  assert.equal(rate("cls", 0.05), "good");
  assert.equal(rate("cls", 0.1), "good", "the limit itself is still good");
  assert.equal(rate("cls", 0.2), "ni");
  assert.equal(rate("cls", 0.6), "poor");
  assert.equal(rate("lcp", 4.2), "poor");
  assert.equal(rate("content", 9), null, "no Google limit for time to content");
  assert.equal(rate("ttfb", null), null);
});

const browserPage = (url, o = {}, perf = {}) => ({
  url, tier: "light", verdict: "OK", reasons: [],
  samples: [
    { kind: "http", profile: "chrome", status: 200, challenge: false, ttfb_s: 0.4 },
    { kind: "browser", profile: "chromium", visit: "cold", status: 200, stuck: false, content_s: 2, console_errors: 0, perf: { lcp_ms: 1200, cls: 0.01, page_bytes: 2048, ...perf }, ...o },
  ],
});

test("page metrics and site summary", () => {
  const m = pageMetrics(browserPage("https://x.cz/a", {}, { lcp_ms: 4100, cls: 0.3 }));
  assert.equal(m.path, "/a");
  assert.equal(m.lcp, 4.1);
  assert.equal(m.kb, 2);
  const blocked = pageMetrics(runs[0].pages[0]);
  assert.equal(blocked.ttfb, null, "429 is excluded like in the trends");
  assert.equal(blocked.status, 429);
  const metrics = [m, pageMetrics(browserPage("https://x.cz/b", { console_errors: 2 })), blocked];
  const s = siteSummary(metrics);
  assert.deepEqual([s.pages, s.OK, s.FAIL], [3, 2, 1]);
  assert.deepEqual(s.over, { ttfb: 0, lcp: 1, cls: 1, clsPoor: 1 });
  assert.equal(s.errorPages, 1);
  assert.deepEqual(topBy(metrics, "lcp", 1).map((x) => x.path), ["/a"]);
  const first = attention(metrics, 2);
  assert.equal(first[0].m.verdict, "FAIL", "failing pages come before metric limits");
  assert.equal(first[1].label, "CLS 0.30", "poor CLS (3x limit) outranks poor LCP (1.6x)");
});

test("verdict changes match pages across runs, newest first", () => {
  assert.deepEqual(verdictChanges(runs[0], runs[1]).map((c) => [pathOf(c.url), c.from, c.to]), [["/", "FAIL", "OK"], ["/kontakt/", "WARN", "OK"]]);
  const grown = { ...runs[1], measured_at: "2026-10-22T04:00:00+00:00", pages: [...runs[1].pages, browserPage("https://www.example.cz/new")] };
  const events = recentChanges([runs[0], runs[1], grown]);
  assert.deepEqual(events[0], { at: grown.measured_at, type: "pages", from: 3, to: 4 });
  assert.equal(events.filter((e) => e.type === "verdict").length, 2);
});

test("regression needs history and a clear jump", () => {
  const run = (at, content) => ({ measured_at: at, pages: [browserPage("https://x.cz/", { content_s: content })] });
  const steady = ["2026-10-01", "2026-10-02", "2026-10-03"].map((d) => run(d, 1.0));
  assert.equal(regressions([...steady, run("2026-10-04", 1.4)], "browser").length, 0, "1.4 s vs 1.0 s is noise");
  const [r] = regressions([...steady, run("2026-10-04", 2.0)], "browser");
  assert.deepEqual([r.latest, r.baseline], [2.0, 1.0]);
  assert.equal(regressions([...steady.slice(1), run("2026-10-04", 9)], "browser").length, 0, "2 earlier values are not a history");
});
