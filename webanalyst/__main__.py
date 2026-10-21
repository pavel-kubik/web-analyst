"""Run measurements and rebuild the public data for the dashboard.

    python -m webanalyst                     # all domains from sites.yml (pages from their sitemaps)
    python -m webanalyst --url https://...   # ad-hoc URL(s), full probe set, no discovery
    python -m webanalyst --max-urls 5        # cap discovered pages per domain (quick local runs)
    python -m webanalyst --no-browser        # HTTP probes only
    python -m webanalyst --report-only       # rebuild docs/data from results/
"""
import argparse
import base64
import datetime as dt
import json
import pathlib
import re
import time

import yaml

from . import browser_probe, http_probe, report, sitemap

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
DOCS = ROOT / "docs"

PAUSE_S = 1.0  # between pages, so one run never looks like a burst to the host's DoS filter

BROWSER_RUNS = {
    # label: (playwright browser, user agent override)
    "chromium": ("chromium", None),
    "firefox": ("firefox", None),
    "chromium-adsbot-mobile": ("chromium", http_probe.USER_AGENTS["adsbot-google-mobile"]),
}

# The light profiles are a subset of the full ones, so every page has the same trend series.
# TODO: revisit tiers once real robots.txt / sitemap data is in (see tasks/TODO.md).
TIERS = {
    "full": {"http": list(http_probe.USER_AGENTS), "browser": list(BROWSER_RUNS), "screenshots": True},
    "light": {"http": ["chrome"], "browser": ["chromium"], "screenshots": False},
}


def verdict(http: list[dict], browsers: list[dict]) -> tuple[str, list[str]]:
    """FAIL = Google Ads would likely see a broken destination, WARN = slow or challenge that clears, OK = clean."""
    fail, warn = [], []
    for h in http:
        tag = f"HTTP[{h['ua']}]"
        if "error" in h:
            fail.append(f"{tag} error: {h['error']}")
        elif h["status"] >= 400:
            fail.append(f"{tag} status {h['status']} ({h['title']})")
        elif h["is_challenge"]:
            (fail if h["ua"].startswith("adsbot") else warn).append(f"{tag} got a browser-check page ({', '.join(h['matches']) or 'JS reload'})")
        elif h["ttfb_s"] > 2:
            warn.append(f"{tag} slow TTFB {h['ttfb_s']} s")
    for b in browsers:
        tag = f"Browser[{b['label']}]"
        cold = b.get("cold", {})
        if "error" in b or "error" in cold:
            fail.append(f"{tag} error: {b.get('error') or cold.get('error')}")
            continue
        for visit in ("cold", "warm"):
            v = b.get(visit) or {}
            if (v.get("final_status") or 0) >= 400:
                fail.append(f"{tag} {visit} visit ended with status {v['final_status']} ({v.get('final_title', '')})")
        if any(r.startswith(f"{tag} ") for r in fail):
            continue
        if cold["stuck_on_challenge"]:
            fail.append(f"{tag} stuck on browser-check page")
        elif cold["challenge_seen"]:
            warn.append(f"{tag} browser-check on first visit, real content after {cold['time_to_real_content_s']} s")
        elif (cold["time_to_real_content_s"] or 0) > 5:
            warn.append(f"{tag} slow first visit {cold['time_to_real_content_s']} s")
    return ("FAIL" if fail else "WARN" if warn else "OK"), fail + warn


def _save_shots(site_id: str, idx: int, label: str, run: dict) -> None:
    """Move base64 screenshots out of the JSON into docs/shots (latest only, deployed but not committed)."""
    for visit in ("cold", "warm"):
        v = run.get(visit) or {}
        for key in ("challenge_screenshot_jpeg_b64", "final_screenshot_jpeg_b64"):
            data = v.pop(key, "")
            if data:
                name = f"{site_id}-{idx}-{label}-{visit}-{key.split('_')[0]}.jpg"
                path = DOCS / "shots" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(data))
                v[key.replace("_jpeg_b64", "")] = f"shots/{name}"


def measure_url(site_id: str, idx: int, url: str, tier: str, with_browser: bool) -> dict:
    print(f"  [{tier}] {url}")
    profile = TIERS[tier]
    http = http_probe.probe_all(url, profile["http"])
    browsers = []
    if with_browser:
        for label in profile["browser"]:
            engine, ua = BROWSER_RUNS[label]
            try:
                run = browser_probe.probe(url, engine, ua, screenshots=profile["screenshots"])
            except Exception as exc:  # browser missing, crash, ...
                run = {"error": f"{type(exc).__name__}: {str(exc).splitlines()[0]}"}
            run["label"] = label
            _save_shots(site_id, idx, label, run)
            browsers.append(run)
    status, reasons = verdict(http, browsers)
    print(f"    -> {status}" + "".join(f"\n       {r}" for r in reasons))
    return {"url": url, "tier": tier, "verdict": status, "reasons": reasons, "http": http, "browser": browsers}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", action="append", help="ad-hoc URL(s) instead of sites.yml")
    ap.add_argument("--max-urls", type=int, default=sitemap.MAX_URLS, help="pages per domain, homepage included")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()

    if not args.report_only:
        if args.url:
            sites = [{"id": "adhoc", "name": "Ad-hoc", "urls": args.url}]
        else:
            sites = yaml.safe_load((ROOT / "sites.yml").read_text())["sites"]
        now = dt.datetime.now(dt.timezone.utc)
        stamp = now.strftime("%Y-%m-%dT%H%MZ")
        for site in sites:
            site_id = re.sub(r"[^a-z0-9-]", "-", site["id"].lower())
            print(f"[{site_id}] {site.get('name', '')}")
            if site.get("domain"):
                discovery = sitemap.discover(site["domain"], max_urls=args.max_urls)
                print(f"  {len(discovery['urls'])} pages from {len(discovery['sitemaps'])} sitemap(s)"
                      + (" (capped)" if discovery["capped"] else "") + "".join(f"\n  ! {e}" for e in discovery["errors"]))
                targets = [(u, "full" if i == 0 else "light") for i, u in enumerate(discovery["urls"])]
            else:
                discovery = None
                targets = [(u, "full") for u in site["urls"]]
            pages = []
            for i, (url, tier) in enumerate(targets):
                if i:
                    time.sleep(PAUSE_S)
                pages.append(measure_url(site_id, i, url, tier, not args.no_browser))
            result = {"site": site_id, "name": site.get("name", site_id), "domain": site.get("domain"),
                      "measured_at": now.isoformat(), "discovery": discovery, "pages": pages}
            out = RESULTS / site_id
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{stamp}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
            (out / "latest.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    report.build(RESULTS, DOCS)
    print(f"Dashboard data: {DOCS / 'data' / 'manifest.json'}")


if __name__ == "__main__":
    main()
