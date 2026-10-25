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
- Migration done 2026-10-21 via new Backfill R2 workflow (prod env, delete_legacy=true): data/v1/ filled, legacy data/middex/* deleted; verified on mobile without cache.

## Self-hosted runner (implemented 2026-10-24, pushed e693fb8)
- Learner decision: move all jobs (measure, test, backfill) to own VM to save Actions minutes; VM already has Playwright and system deps. No hosted fallback.
- Introduced (AI explained): hosted runners use Azure datacenter IPs, Google Ads checks from Google datacenter IPs, so a VM on a different network may see different anti-bot results; runners on a personal account are repo-scoped (the other service's runner can't serve this repo); runner can read the prod secret; `--with-deps` needs apt/sudo.
- Changes: runs-on [self-hosted, linux]; dropped `--with-deps` from the Playwright install.
- Runner `oci` on vm-tools, user `runner` (shared with abeceda-hrou; learner accepted since both repos private). Test run on push succeeded on `oci`.
- Context: the 2026-10-24 scheduled Measure on ubuntu-latest never started (billing/spending limit), confirming the minutes motive.
- Runner selection (2026-10-24, not committed): copied abeceda-hrou pattern on learner request: default self-hosted `[self-hosted, web-analyst]` (label added to `oci` via API), repo variable CI_RUNNER=github or manual `runner` input → ubuntu-latest; split Playwright install by runner.environment.
- Found: VM is OCI E2.1.Micro (1 GB RAM, 59.5% steal); 15:12 Measure run on VM was cancelled after ~40 min, slow-VM false WARNs (e.g. 6.5 s first visit). Learner asked for a reliable-latency plan (non-burstable machine, no overlap with other jobs, server vs render metrics, run health flag, control URL) — decision pending. Public-repo question pending (client consent, remove .vibe-wise).

## Where to run Measure (research 2026-10-24, decision pending)
- Learner asked to compare other services (Cloudflare focus) with GitHub Actions free tier.
- AI explained (facts): CF Workers Free + Browser Rendering = 10 browser-min/day, 3 concurrent, Chromium only, JS rewrite needed, CF egress IPs; CF Containers = Workers Paid $5/mo only (375 vCPU-min, 25 GiB-h incl.), runs existing Docker image via cron Worker; GH Actions: public repos free, private 2000 min/mo, self-hosted charge postponed.
- Google Cloud Run Jobs added; comparison saved to tasks/002-measure-hosting-options.md, linked from README (not committed).
- Open: learner to choose based on cost, latency reliability (links to pending latency plan) and network/IP realism vs Google Ads checks.
