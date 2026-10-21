"""Print a Markdown summary of the latest results (used for the GitHub Actions job summary)."""
import json

from .__main__ import RESULTS

MAX_ROWS = 50

for latest in sorted(RESULTS.glob("*/latest.json")):
    data = json.loads(latest.read_text())
    counts = {v: sum(p["verdict"] == v for p in data["pages"]) for v in ("OK", "WARN", "FAIL")}
    print(f"### {data['name']}: {len(data['pages'])} pages · ✅ {counts['OK']} · ⚠️ {counts['WARN']} · ❌ {counts['FAIL']}\n")
    bad = [p for p in data["pages"] if p["verdict"] != "OK"]
    if bad:
        print("| URL | Verdict | Reasons |\n|---|---|---|")
        for p in bad[:MAX_ROWS]:
            icon = {"WARN": "⚠️", "FAIL": "❌"}[p["verdict"]]
            print(f"| {p['url']} | {icon} {p['verdict']} | {'<br>'.join(p['reasons'])} |")
        if len(bad) > MAX_ROWS:
            print(f"\n…and {len(bad) - MAX_ROWS} more.")
    print()
