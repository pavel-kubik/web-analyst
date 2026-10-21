# web-analyst

Automated measurement of web landing pages — mainly to catch problems that make
Google Ads reject ads as **"Destination not working" (nefunkční cíl)**:
anti-bot "checking your browser" interstitials, redirects, error codes and slow first loads.

## What it measures

Each domain in [`sites.yml`](sites.yml) is expanded into pages via its `robots.txt` → sitemap index → child sitemaps
(same host only, max 300 pages, 1 s pause between pages). Probes are tiered:

| Tier | Pages | Probes |
|---|---|---|
| full | homepage | Plain HTTP with UAs `adsbot-google`, `adsbot-google-mobile`, `googlebot`, `firefox`, `chrome`; real Chromium, Firefox and Chromium with the AdsBot-Google-Mobile UA, each cold (empty profile) + warm (repeat visit), with screenshots |
| light | every other sitemap page | Plain HTTP with `chrome` UA; real Chromium cold + warm |

HTTP probes record status, redirect chain, TTFB, title and whether the HTML is a browser-check page.
Browser probes record time until real content replaces a challenge, TTFB, FCP, LCP, CLS (Chromium only),
load, request count, page weight and console errors.

Verdict per page: **FAIL** (AdsBot gets a challenge / error, or browser stays stuck),
**WARN** (challenge on first visit that clears, slow TTFB > 2 s or first content > 5 s), **OK**.

## Dashboard

The frontend in `docs/` (`index.html`, `app.js`, `trends.js`, Chart.js from cdnjs) is deployed by Cloudflare Pages
straight from the repo. Measurement data lives in the R2 bucket `web-analyst-data`; the page reads it from the URL
in `<meta name="data-base">`. Each run exports header-free data to `docs/data/` (`manifest.json` + one file per run,
regenerated from `results/`) and uploads only the new run, the manifest and the latest screenshots
(`python -m webanalyst.publish`; `--all` backfills history, `--dry-run` lists keys). Run files are versioned
(`data/v<N>/…`) and cached for a year; changing their format follows
[runbooks/data-version-upgrade.md](runbooks/data-version-upgrade.md).

The browser computes the trends:

- status counts per page (2xx / 3xx / 4xx / 5xx / error, from the `chrome` HTTP probe),
- HTTP TTFB and browser time-to-content: mean and P90 per day or week. Only 2xx responses with real content
  count (no browser-check pages, errors or stuck loads); the excluded share is shown under each chart.

Preview locally (empty `data-base` = same origin): `python -m webanalyst --report-only && python -m http.server -d docs`
→ http://localhost:8000.

## Running

```bash
pip install -r requirements.txt
python -m playwright install --with-deps firefox chromium
python -m webanalyst                       # all domains from sites.yml
python -m webanalyst --max-urls 5          # quick run: homepage + 4 sitemap pages
python -m webanalyst --url https://example.cz/landing   # ad-hoc check: full probes, not committed or published
python -m webanalyst --no-browser          # HTTP probes only (fast)
python -m webanalyst --report-only         # re-export docs/data from results/
```

Raw output: `results/<site>/<timestamp>.json` (history, committed) and `results/<site>/latest.json`.
`docs/data/` and `docs/shots/` are generated and not committed.

Tests: `python -m pytest` and `npm test` (Node's built-in test runner, no dependencies).

## Automation

[`.github/workflows/measure.yml`](.github/workflows/measure.yml) runs daily at 04:17 UTC, when `sites.yml` changes,
and on demand (*Actions → Measure → Run workflow*, optionally with an ad-hoc URL – a throwaway smoke check shown
only in the job summary). It runs the unit tests, measures, writes a verdict summary, uploads new data to R2 and
commits `results/` back to the repo.

[`.github/workflows/test.yml`](.github/workflows/test.yml) runs the unit tests on every push and pull request
(except the bot's `results/` commits) without touching any measured site.

### Cloudflare setup (once)

| | |
|---|---|
| Account ID | `584a900cab287c4bc9a4c681a6e808a4` – ⚠️ **shared with firmometr** (see [TODO](tasks/TODO.md)) |
| Dashboard | https://web-analyst.pages.dev/ (Pages project `web-analyst`, Git integration) |
| R2 bucket | `web-analyst-data`, public at `https://pub-55869ccb79434b3aa3a8ca444d75daba.r2.dev/` |

1. **R2 bucket**: R2 → Create bucket `web-analyst-data`. Settings → Public access → *R2.dev subdomain* → Allow; note the
   `https://pub-….r2.dev` URL. ⚠️ r2.dev is rate-limited and for prototypes only – see [TODO](tasks/TODO.md).
2. **CORS** (bucket Settings → CORS policy):
   ```json
   [{"AllowedOrigins": ["https://web-analyst.pages.dev", "http://localhost:8000"], "AllowedMethods": ["GET", "HEAD"], "AllowedHeaders": ["*"], "MaxAgeSeconds": 3600}]
   ```
3. **Data URL**: put the r2.dev URL with a trailing slash into `<meta name="data-base" content="…">` in `docs/index.html` and commit.
4. **API token**: My Profile → API Tokens → Create custom token: *Account → Workers R2 Storage → Edit*, limited to this
   account. Add repo secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. Until both exist the upload is skipped.
5. **Backfill** existing history once: run `python -m webanalyst.publish --all` locally with both variables set.
6. **Pages**: Workers & Pages → Create → Pages → *Connect to Git* → this repo only. Framework preset *None*, build command
   empty (or `exit 0`), output directory `docs`. Then Settings → Builds → *Build watch paths*: include `docs/*`, so the
   daily results commits don't trigger builds.

## Tasks

- [001 – FORPSI browser check breaks Google Ads](tasks/001-forpsi-browser-check.md) (resolved)
- [TODO / later](tasks/TODO.md)
