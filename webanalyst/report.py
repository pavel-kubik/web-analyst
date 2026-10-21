"""Export results/*.json into slim public data for the dashboard: docs/data/manifest.json + one file per run.

The slim files keep every sample (status, challenge flag, timings, perf) so trends are computed in the browser,
but drop headers, cookies and HTML snippets. `version` is the contract a future backend has to keep.
"""
import datetime as dt
import json
import pathlib
import shutil

VERSION = 1
PERF_KEYS = ("ttfb_ms", "fcp_ms", "dom_content_loaded_ms", "load_ms", "lcp_ms", "cls", "resource_count", "page_bytes")


def _slim_http(h: dict) -> dict:
    if "error" in h:
        return {"kind": "http", "profile": h["ua"], "error": h["error"]}
    return {
        "kind": "http",
        "profile": h["ua"],
        "status": h["status"],
        "challenge": h["is_challenge"],
        "ttfb_s": h["ttfb_s"],
        "total_s": h["total_s"],
        "redirects": len(h.get("redirects") or []),
    }


def _slim_browser(b: dict) -> list[dict]:
    if "error" in b:
        return [{"kind": "browser", "profile": b["label"], "visit": "cold", "error": b["error"]}]
    out = []
    for visit in ("cold", "warm"):
        v = b.get(visit) or {}
        if "error" in v:
            out.append({"kind": "browser", "profile": b["label"], "visit": visit, "error": v["error"]})
            continue
        perf = v.get("perf") or {}
        sample = {
            "kind": "browser",
            "profile": b["label"],
            "visit": visit,
            "status": v.get("final_status", v.get("first_status")),  # early runs only recorded first_status
            "challenge": v.get("challenge_seen"),
            "stuck": v.get("stuck_on_challenge"),
            "content_s": v.get("time_to_real_content_s"),
            "perf": {k: perf.get(k) for k in PERF_KEYS},
            "console_errors": v.get("console_error_count"),
        }
        shots = [v[k] for k in ("challenge_screenshot", "final_screenshot") if v.get(k)]
        if shots:
            sample["screenshots"] = shots
        out.append(sample)
    return out


def slim_run(raw: dict) -> dict:
    """Public, header-free view of one raw run. Runs from before tiers existed measured everything, i.e. "full"."""
    discovery = raw.get("discovery")
    return {
        "version": VERSION,
        "site": raw["site"],
        "name": raw.get("name", raw["site"]),
        "domain": raw.get("domain"),
        "measured_at": raw["measured_at"],
        "discovery": discovery and {k: discovery.get(k) for k in ("sitemaps", "capped", "errors")} | {"url_count": len(discovery.get("urls", []))},
        "pages": [
            {
                "url": p["url"],
                "tier": p.get("tier", "full"),
                "verdict": p["verdict"],
                "reasons": p["reasons"],
                "samples": [_slim_http(h) for h in p["http"]] + [s for b in p["browser"] for s in _slim_browser(b)],
            }
            for p in raw["pages"]
        ],
    }


def build(results: pathlib.Path, docs: pathlib.Path) -> None:
    data_dir = docs / "data"
    if data_dir.exists():
        shutil.rmtree(data_dir)  # regenerated from results/ every time, so a replay covers all history
    sites = []
    for site_dir in sorted(p for p in results.iterdir() if p.is_dir()) if results.exists() else []:
        runs = []
        for f in sorted(p for p in site_dir.glob("*.json") if p.name != "latest.json"):
            slim = slim_run(json.loads(f.read_text()))
            rel = f"data/{site_dir.name}/{f.name}"
            (docs / rel).parent.mkdir(parents=True, exist_ok=True)
            (docs / rel).write_text(json.dumps(slim, ensure_ascii=False, separators=(",", ":")))
            runs.append({"at": slim["measured_at"], "path": rel})
        if runs:
            last = json.loads((docs / runs[-1]["path"]).read_text())
            sites.append({"id": site_dir.name, "name": last["name"], "domain": last["domain"], "runs": runs})
    manifest = {"version": VERSION, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "sites": sites}
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
