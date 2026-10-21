# Runbook: upgrading the dashboard data format

Run files are cached by browsers for a year (`immutable`), so a file at a given URL must never change.
Every format change therefore gets a new path prefix: `data/v<N>/<site>/<stamp>.json`.
`data/manifest.json` is the only fixed entry point; it carries `"version": N` and lists the versioned paths.

## When to bump the version

Bump when a **run file** changes in a way the dashboard could read wrongly from a stale cache:
fields added, removed, renamed or re-interpreted in `slim_run()` (`webanalyst/report.py`).

No bump needed for: frontend-only changes, new runs, manifest-only changes, screenshots.

## Upgrade steps (vN → vN+1)

Expect a short outage between steps 3 and 4: the deployed page may already expect vN+1 while R2 still serves vN
(the page then shows "data format … is not supported – an upgrade is probably in progress").

1. **Code**
   - `webanalyst/report.py`: change `slim_run()` and bump `VERSION`.
   - `docs/app.js`: set `SUPPORTED_VERSIONS` to the versions the page can read
     (keep the old one too if the frontend handles both – that removes the outage window).
   - `docs/trends.js`, fixtures (`tests/fixtures/slim-runs.json`) and tests for the new fields.
2. **Check locally**
   ```bash
   python -m pytest -q && npm test
   python -m webanalyst --report-only        # writes docs/data/manifest.json + docs/data/v<N+1>/…
   ```
   Preview with an empty `<meta name="data-base" content="">` (don't commit that) and
   `python -m http.server -d docs` → http://localhost:8000.
3. **Push** – runs the tests; Cloudflare Pages deploys the new frontend.
4. **Backfill R2 right away** (all history in the new format, manifest uploaded last): GitHub → Actions →
   **Backfill R2** → *Run workflow* (or `gh workflow run backfill.yml`). It runs in the `prod` environment,
   needs no local credentials and sends no requests to measured sites.
   Local alternative: `git pull`, set `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID`, then
   `python -m webanalyst --report-only && python -m webanalyst.publish --all`.
5. **Verify** in a private/incognito window (no cache) and on a phone: data loads, no
   "could not be loaded" note.
6. **Clean up after a few days**: delete the old prefix `data/v<N>/` in R2 – bucket `web-analyst-data` →
   Settings → *Object lifecycle rules* → add a rule for that prefix that deletes objects after 1 day,
   then remove the rule once the objects are gone.

## First migration (unversioned → v1, 2026-10-21)

Before versioning, run files lived at `data/<site>/<stamp>.json`. Done with **Backfill R2** and
`delete_legacy: true`, which uploads `data/v1/…` and then deletes exactly the old `data/<site>/<stamp>.json`
keys derived from `results/` (`publish.py --delete-legacy`).

## Rollback

Revert the commit and push (Pages redeploys the old frontend), then run step 4 again from the reverted code:
it uploads the old-format files (still present under `data/v<N>/` unless cleaned up) and the old manifest.
