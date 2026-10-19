"""Print a Markdown summary of the latest results (used for the GitHub Actions job summary)."""
import json

from .__main__ import RESULTS

print("| Site | URL | Verdict | Reasons |\n|---|---|---|---|")
for latest in sorted(RESULTS.glob("*/latest.json")):
    data = json.loads(latest.read_text())
    for p in data["pages"]:
        icon = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌"}[p["verdict"]]
        print(f"| {data['name']} | {p['url']} | {icon} {p['verdict']} | {'<br>'.join(p['reasons']) or '–'} |")
