# web-analyst

Automated measurement of web landing pages — mainly to catch problems that make
Google Ads reject ads as **"Destination not working" (nefunkční cíl)**:
anti-bot "checking your browser" interstitials, redirects, error codes and slow first loads.

## What it measures

For every URL in [`sites.yml`](sites.yml):

| Probe | What it simulates |
|---|---|
| Plain HTTP, fresh session, UAs `adsbot-google`, `adsbot-google-mobile`, `googlebot`, `firefox`, `chrome` | A crawler without JavaScript or cookies (how Google Ads checks the final URL). Records status, redirect chain, TTFB, title, `Server`/`Set-Cookie` headers and whether the HTML is a browser-check page. |
| Real Firefox, empty profile (cold) + repeat visit (warm) | A first-time visitor like the one in the client's complaint. Measures *time until real content replaces the challenge*, TTFB, LCP, load, and saves screenshots. |
| Real Chromium with AdsBot-Google-Mobile UA | Rendering crawler path. |

Verdict per URL: **FAIL** (AdsBot gets a challenge / error, or browser stays stuck),
**WARN** (challenge on first visit that clears, slow TTFB > 2 s or first content > 5 s), **OK**.

## Running

```bash
pip install -r requirements.txt
python -m playwright install --with-deps firefox chromium
python -m webanalyst                       # all sites from sites.yml
python -m webanalyst --url https://example.cz/landing   # ad-hoc
python -m webanalyst --no-browser          # HTTP probes only (fast)
```

Output: `results/<site>/<timestamp>.json` (history), `results/<site>/latest.json`,
and a static report `docs/index.html` with screenshots in `docs/shots/`.

## Automation

[`.github/workflows/measure.yml`](.github/workflows/measure.yml) runs every 3 hours and on demand
(*Actions → Measure → Run workflow*, optionally with an ad-hoc URL). It commits results back to the repo,
writes a verdict table to the job summary, and uploads `docs/` as the `report` artifact.

## Tasks

- [001 – FORPSI browser check breaks Google Ads](tasks/001-forpsi-browser-check.md)
