"""Upload dashboard data to Cloudflare R2: new runs only (or --all), the manifest and the latest screenshots.

    python -m webanalyst.publish             # runs that are new in results/ since the last commit
    python -m webanalyst.publish --all       # backfill every run
    python -m webanalyst.publish --dry-run   # print what would be uploaded

R2 keys mirror docs/ (data/manifest.json, data/v<N>/<site>/<stamp>.json, shots/...), so the dashboard reads the same paths locally and from R2.
Needs CLOUDFLARE_API_TOKEN (R2 edit on the bucket) and CLOUDFLARE_ACCOUNT_ID; bucket from R2_BUCKET.
"""
import argparse
import os
import pathlib
import subprocess

from .__main__ import DOCS, ROOT
from .report import PRIVATE_SITES, run_dir

WRANGLER = "wrangler@4.144.0"
DEFAULT_BUCKET = "web-analyst-data"

CACHE = {
    "run": "public, max-age=31536000, immutable",  # a measured run never changes
    "manifest": "public, max-age=60",  # changes on every run
    "shot": "public, max-age=300",  # overwritten on every run
}


def new_run_files(porcelain: str) -> list[str]:
    """Run files (results/<site>/<stamp>.json) that `git status --porcelain` reports as new or changed."""
    out = []
    for line in porcelain.splitlines():
        path = line[3:].strip()
        parts = path.split("/")
        if len(parts) == 3 and parts[0] == "results" and parts[2].endswith(".json") and parts[2] != "latest.json":
            out.append(f"{parts[1]}/{parts[2]}")
    return sorted(out)


def plan(docs: pathlib.Path, runs: list[str] | None) -> list[tuple[str, pathlib.Path, str, str]]:
    """(key, local file, content type, cache control); runs=None means every run of the current format version."""
    data, run_root = docs / "data", docs / run_dir()
    run_files = sorted(p.relative_to(run_root).as_posix() for p in run_root.glob("*/*.json")) if runs is None else runs
    items = [(f"{run_dir()}/{r}", run_root / r, "application/json", CACHE["run"]) for r in run_files if (run_root / r).exists()]
    items += [(f"shots/{p.name}", p, "image/jpeg", CACHE["shot"]) for p in sorted((docs / "shots").glob("*.jpg"))
              if p.name.split("-", 1)[0] not in PRIVATE_SITES]
    # Manifest last: it only lists runs whose files are already uploaded.
    items.append(("data/manifest.json", data / "manifest.json", "application/json", CACHE["manifest"]))
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="upload every run (backfill)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    bucket = os.environ.get("R2_BUCKET", DEFAULT_BUCKET)
    runs = None
    if not args.all:
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", "results"],
                                cwd=ROOT, check=True, capture_output=True, text=True).stdout
        runs = new_run_files(status)
    for key, path, content_type, cache in plan(DOCS, runs):
        print(f"{bucket}/{key}")
        if not args.dry_run:
            subprocess.run(["npx", "--yes", WRANGLER, "r2", "object", "put", f"{bucket}/{key}", "--remote",
                            "--file", str(path), "--content-type", content_type, "--cache-control", cache], check=True)


if __name__ == "__main__":
    main()
