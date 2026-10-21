# Learning Progress

## Static hosting and report architecture
- Introduced (AI explained): static hosting means no server; logic runs either at build time (Python in Actions) or in the visitor's browser. Facts given on GitHub Pages limits (private repo needs paid plan, no auth outside Enterprise, 1 GB / 100 GB/mo) and repo growth (~100 MB/site/year JSON; screenshots re-committed each run).
- Introduced (AI explained): Cloudflare Pages Git integration vs direct upload; GitHub Actions free quota (2,000 min/month private); percentiles need sample volume (P99 of 10 samples = max); fast error/challenge responses skew latency down; static hosts have no directory listing; time_to_real_content is project-defined (HTML polling), Playwright exposes browser Performance APIs (FCP, CLS, resource timing, HAR).
- Learner reasoning: chose direct deploy because Actions already runs; proposed a manifest JSON for discovery, anticipating a future backend; proposed restricting latency to 2xx to avoid error skew.
- Clarified (AI explained): sites.yml is the repo's hand-written config; sitemap.xml is published by the website. Learner's mental model had assumed sitemap-based discovery.
- Learner reasoning: prioritises simplest architecture without many tools; accepts prototype-level scaling for now; wants auth in future.

## Dashboard and trends (implemented 2026-10-21)
- Introduced (AI explained): latency rule options and validation by replay; Playwright Performance API metrics vs project-defined time-to-real-content; Actions artifacts not public; R2 vs KV; sites.yml vs sitemap.xml; FORPSI rate-limit risk of crawling; tier/rotation/sharding tradeoffs.
- Learner reasoning: chose rule B for latency and slim public JSON; manifest JSON for discovery with a future backend in mind; tiered probing after the AdsBot-coverage challenge; daily/weekly percentile buckets for long-term trends; rejected git for binary artifacts.
- Needs reinforcement: request pacing was proposed by AI, not reasoned by learner; sampling frequency vs percentile sample size (learner chose daily anyway).
- Replay evidence: on 2026-10-19 unfiltered chrome TTFB mean ≈0.86 s vs rule-B 1.18 s (429s excluded).

## Deployment model (implemented 2026-10-21)
- Introduced (AI explained): Pages deployments are full snapshots; Git vs Direct Upload is permanent per project; wrangler pages deploy uploads only changed files (hash dedupe) — learner had assumed A re-uploads all history; R2 public access (r2.dev vs custom domain), CORS, cache headers; Access on Pages doesn't protect public R2 data.
- Learner reasoning: chose C because it matches the long-term direction (frontend and data independent, toward a Cloudflare backend) and to upload only per-run diffs; accepted r2.dev + public data for the prototype with a reminder.
- Needs reinforcement: the A-vs-C upload-volume reason rested on a misconception (corrected).

## Sitemap security hardening (implemented 2026-10-21, pushed 068677a)
- Introduced (AI explained): decompression bombs / output-capped inflate; SSRF via robots/sitemap/redirect targets from an untrusted site; URL parser differential (backslash, userinfo) between Python and browsers; keep raw exception text out of public data.
- Learner decision: fix all three now (no learner reasoning on mechanisms requested/given).

## Ad-hoc runs (implemented 2026-10-21, pushed 068677a)
- Learner asked for AI suggestion; accepted: ad-hoc runs are throwaway (job summary/artifact only), not committed, exported or uploaded. AI reasons given: mixed URLs make trends meaningless; public dashboard would leak checks of prospects/competitors.
- Open user action: delete orphaned R2 objects data/adhoc/* and shots/adhoc-*.

## CI triggers (implemented 2026-10-21, pushed ba98fd9)
- Learner asked for options; AI recommended and learner approved option C: test.yml on every push/PR (ignores results/**); measure.yml on schedule, manual dispatch and sites.yml changes only; ad-hoc dispatch serves as the smoke check. AI advised against capped manual runs (partial runs would enter trends).
- Also pushed: DTD rejection inside XML parser; bounded sitemap queue/errors.

## Caching and data versioning (implemented 2026-10-21, pushed 7a14b0f)
- Learner reasoning: diagnosed the cache masking with an incognito test; chose version-in-path over shorter max-age.
- Delegated to AI ("take defaults"): tolerant loader (skip missing runs with note), manifest version check, runbook in runbooks/ (not public docs/). Learner accepts outages for now (no customers).
- Open user action: run publish --all to fill data/v1/, then delete legacy data/middex/ prefix (runbook "First migration").
