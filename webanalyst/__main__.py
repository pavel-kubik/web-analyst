"""Run measurements and rebuild the report.

    python -m webanalyst                     # all sites from sites.yml
    python -m webanalyst --url https://...   # ad-hoc single URL
    python -m webanalyst --no-browser        # HTTP probes only
    python -m webanalyst --report-only       # rebuild docs/ from results/
"""
import argparse
import base64
import datetime as dt
import json
import pathlib
import re

import yaml

from . import browser_probe, http_probe, report

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
DOCS = ROOT / "docs"

BROWSER_RUNS = [
    # (label, playwright browser, user agent override)
    ("firefox", "firefox", None),
    ("chromium-adsbot-mobile", "chromium", http_probe.USER_AGENTS["adsbot-google-mobile"]),
]


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
    """Move base64 screenshots out of the JSON into docs/shots (latest only, to keep git small)."""
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


def measure_url(site_id: str, idx: int, url: str, with_browser: bool) -> dict:
    print(f"  {url}")
    http = http_probe.probe_all(url)
    browsers = []
    if with_browser:
        for label, engine, ua in BROWSER_RUNS:
            try:
                run = browser_probe.probe(url, engine, ua)
            except Exception as exc:  # browser missing, crash, ...
                run = {"error": f"{type(exc).__name__}: {str(exc).splitlines()[0]}"}
            run["label"] = label
            _save_shots(site_id, idx, label, run)
            browsers.append(run)
    status, reasons = verdict(http, browsers)
    print(f"    -> {status}" + "".join(f"\n       {r}" for r in reasons))
    return {"url": url, "verdict": status, "reasons": reasons, "http": http, "browser": browsers}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", action="append", help="ad-hoc URL(s) instead of sites.yml")
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
            pages = [measure_url(site_id, i, u, not args.no_browser) for i, u in enumerate(site["urls"])]
            result = {"site": site_id, "name": site.get("name", site_id), "measured_at": now.isoformat(), "pages": pages}
            out = RESULTS / site_id
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{stamp}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
            (out / "latest.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    report.build(RESULTS, DOCS)
    print(f"Report: {DOCS / 'index.html'}")


if __name__ == "__main__":
    main()
