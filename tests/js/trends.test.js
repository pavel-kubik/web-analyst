import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  bucketKey, isEligible, latencyTrend, pageStatus, percentile, runsInWindow, statusCounts, statusTrend, urlSeries,
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
