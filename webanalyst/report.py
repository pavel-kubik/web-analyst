"""Render results/*.json into a static, self-contained docs/index.html."""
import html
import json
import pathlib

HISTORY_ROWS = 30

CSS = """
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--card:#fff;--line:#e7e5e4;--ok:#15803d;--warn:#b45309;--fail:#b91c1c}
@media (prefers-color-scheme:dark){:root{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--card:#292524;--line:#44403c;--ok:#4ade80;--warn:#fbbf24;--fail:#f87171}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px}h1{font-size:22px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px}
h3{font-size:15px;margin:20px 0 6px;word-break:break-all}.muted{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:12px 0;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:4px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}.b{font-weight:700;border-radius:4px;padding:1px 6px;font-size:12px}
.OK{color:var(--ok)}.WARN{color:var(--warn)}.FAIL{color:var(--fail)}ul{margin:4px 0;padding-left:18px}
.shots{display:flex;gap:12px;flex-wrap:wrap}.shots figure{margin:0;max-width:340px}.shots img{width:100%;border:1px solid var(--line);border-radius:6px}
figcaption{font-size:12px;color:var(--muted)}code{font-size:12px}
"""


def e(v) -> str:
    return html.escape("" if v is None else str(v))


def badge(v: str) -> str:
    return f'<span class="b {e(v)}">{e(v)}</span>'


def _http_table(rows: list[dict]) -> str:
    out = ["<table><tr><th>User-Agent</th><th>Status</th><th>TTFB s</th><th>Total s</th><th>Redirects</th><th>Challenge</th><th>Title</th><th>Server</th></tr>"]
    for h in rows:
        if "error" in h:
            out.append(f"<tr><td>{e(h['ua'])}</td><td colspan=7 class=FAIL>{e(h['error'])}</td></tr>")
            continue
        redirects = " → ".join(f"{r['status']}" for r in h["redirects"]) or "–"
        chal = f"<span class=FAIL>YES</span> {e(', '.join(h['matches']))}" if h["is_challenge"] else "no"
        out.append(
            f"<tr><td>{e(h['ua'])}</td><td>{e(h['status'])}</td><td>{e(h['ttfb_s'])}</td><td>{e(h['total_s'])}</td>"
            f"<td>{e(redirects)}</td><td>{chal}</td><td>{e(h['title'])}</td><td>{e(h['headers'].get('server', ''))}</td></tr>"
        )
    return "".join(out) + "</table>"


def _browser_table(runs: list[dict]) -> tuple[str, str]:
    rows = ["<table><tr><th>Run</th><th>Visit</th><th>Status</th><th>Challenge</th><th>Real content after s</th><th>TTFB ms</th><th>LCP ms</th><th>Load ms</th><th>Final title</th></tr>"]
    shots = []
    for b in runs:
        if "error" in b:
            rows.append(f"<tr><td>{e(b['label'])}</td><td colspan=8 class=FAIL>{e(b['error'])}</td></tr>")
            continue
        for visit in ("cold", "warm"):
            v = b.get(visit) or {}
            if "error" in v:
                rows.append(f"<tr><td>{e(b['label'])}</td><td>{visit}</td><td colspan=7 class=FAIL>{e(v['error'])}</td></tr>")
                continue
            p = v.get("perf") or {}
            chal = "<span class=FAIL>stuck</span>" if v["stuck_on_challenge"] else ("<span class=WARN>yes</span>" if v["challenge_seen"] else "no")
            rows.append(
                f"<tr><td>{e(b['label'])}</td><td>{visit}</td><td>{e(v['first_status'])}</td><td>{chal}</td><td>{e(v['time_to_real_content_s'])}</td>"
                f"<td>{e(p.get('ttfb_ms'))}</td><td>{e(p.get('lcp_ms'))}</td><td>{e(p.get('load_ms'))}</td><td>{e(v['final_title'])}</td></tr>"
            )
            for key, label in (("challenge_screenshot", "browser-check page"), ("final_screenshot", "final page")):
                if v.get(key):
                    shots.append(f'<figure><a href="{e(v[key])}"><img src="{e(v[key])}" alt="{e(label)}" loading="lazy"></a><figcaption>{e(b["label"])} · {visit} · {label}</figcaption></figure>')
    return "".join(rows) + "</table>", ('<div class="shots">' + "".join(shots) + "</div>") if shots else ""


def _history(site_dir: pathlib.Path) -> str:
    files = sorted(p for p in site_dir.glob("*.json") if p.name != "latest.json")[-HISTORY_ROWS:]
    rows = ["<table><tr><th>Measured (UTC)</th><th>URL</th><th>Verdict</th><th>AdsBot status / TTFB</th><th>Firefox cold: challenge / content s</th></tr>"]
    for f in reversed(files):
        data = json.loads(f.read_text())
        for p in data["pages"]:
            ads = next((h for h in p["http"] if h["ua"] == "adsbot-google"), {})
            ff = next((b for b in p["browser"] if b.get("label") == "firefox"), {}).get("cold") or {}
            ads_s = e(ads.get("error")) if "error" in ads else f"{e(ads.get('status'))} / {e(ads.get('ttfb_s'))} s"
            ff_s = "–" if not ff or "error" in ff else f"{'yes' if ff['challenge_seen'] else 'no'} / {e(ff['time_to_real_content_s'])}"
            rows.append(f"<tr><td>{e(data['measured_at'][:16].replace('T', ' '))}</td><td>{e(p['url'])}</td><td>{badge(p['verdict'])}</td><td>{ads_s}</td><td>{ff_s}</td></tr>")
    return "".join(rows) + "</table>"


def build(results: pathlib.Path, docs: pathlib.Path) -> None:
    docs.mkdir(parents=True, exist_ok=True)
    sections, summary = [], []
    for site_dir in sorted(p for p in results.iterdir() if p.is_dir()) if results.exists() else []:
        latest = site_dir / "latest.json"
        if not latest.exists():
            continue
        data = json.loads(latest.read_text())
        parts = [f'<h2 id="{e(data["site"])}">{e(data["name"])}</h2><p class=muted>Last measured {e(data["measured_at"][:16].replace("T", " "))} UTC</p>']
        for p in data["pages"]:
            summary.append(f'<tr><td><a href="#{e(data["site"])}">{e(data["name"])}</a></td><td>{e(p["url"])}</td><td>{badge(p["verdict"])}</td><td>{e(p["reasons"][0] if p["reasons"] else "")}</td></tr>')
            reasons = "".join(f"<li>{e(r)}</li>" for r in p["reasons"]) or "<li>No problems detected.</li>"
            btable, shots = _browser_table(p["browser"])
            parts.append(
                f'<div class=card><h3>{badge(p["verdict"])} {e(p["url"])}</h3><ul>{reasons}</ul>'
                f"<h3>Plain HTTP (no JavaScript, fresh session)</h3>{_http_table(p['http'])}"
                + (f"<h3>Real browser (empty profile, then repeat visit)</h3>{btable}{shots}" if p["browser"] else "")
                + "</div>"
            )
        parts.append(f"<details class=card><summary>History</summary>{_history(site_dir)}</details>")
        sections.append("".join(parts))

    body = (
        "<main><h1>Web Analyst</h1><p class=muted>Landing-page reachability for Google Ads: browser-check interstitials, redirects, speed.</p>"
        "<div class=card><table><tr><th>Site</th><th>URL</th><th>Verdict</th><th>Main reason</th></tr>"
        + ("".join(summary) or "<tr><td colspan=4>No results yet.</td></tr>")
        + "</table></div>"
        + "".join(sections)
        + "</main>"
    )
    page = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Web Analyst</title><style>{CSS}</style></head><body>{body}</body></html>'
    (docs / "index.html").write_text(page)
