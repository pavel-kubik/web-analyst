# 002 – Where to run the Measure job

Status: **open** (comparison only, no decision yet). Prices and limits checked 2026-10-24 – verify before acting.

## Context

Measure currently runs on a self-hosted runner on an OCI E2.1.Micro VM ([runbooks/self-hosted-runner.md](../runbooks/self-hosted-runner.md))
to save GitHub Actions minutes. That VM is too weak for trustworthy latency: 1 GB RAM, ~60 % CPU steal, a run
cancelled after ~40 min and false WARNs from slow first visits.

What any host has to provide:

1. Python + `requests` for the HTTP probes.
2. Playwright with **Firefox and Chromium** (cold + warm visits, screenshots).
3. A schedule (daily) plus on-demand runs.
4. Credentials for R2 upload and, today, a way to commit `results/` back to the repo.
5. A network position close to what Google Ads sees – anti-bot systems treat datacenter IP ranges differently.

Load to size against: a daily run on GitHub-hosted `ubuntu-latest` took **20–25 min** (runs on 2026-10-21…23),
i.e. ~600–750 min/month at the current `sites.yml`. It grows with the sitemap page count.

## Comparison

| | GitHub-hosted runner | Cloudflare Workers + Browser Rendering | Cloudflare Containers | Google Cloud Run Jobs | OCI VM (current) |
|---|---|---|---|---|---|
| Price | Public repo: free, unlimited. Private: 2,000 min/month on Free | Free plan | Workers Paid **$5/month** (no free tier) | Free tier, billing account (card) required | Always Free |
| Included | 2,000 min/month (private) | **10 browser-min/day**, 3 concurrent browsers, 60 s idle timeout | 375 vCPU-min, 25 GiB-h memory, 200 GB-h disk per month | 240,000 vCPU-s + 450,000 GiB-s per month (us-central1; lower in tier-2 regions); Cloud Scheduler: 3 free jobs | E2.1.Micro, or Ampere A1 up to 4 OCPU / 24 GB (Arm, capacity often scarce) |
| Fits our load? | Yes (~750 of 2,000 min) | **No** – a single run needs far more than 10 min | Mostly; small overage (memory) in cents | Yes – e.g. 2 vCPU / 4 GiB × 25 min × 30 days ≈ 90k vCPU-s, 180k GiB-s | Micro: no (latency). A1: likely yes |
| Current code as-is? | Yes | **No** – JS rewrite (Worker `fetch`, `@cloudflare/playwright`) | Yes, as a Docker image started by a cron Worker + Durable Object | Yes, as a Docker image (e.g. `mcr.microsoft.com/playwright/python`) | Yes |
| Firefox | Yes | **No, Chromium only** | Yes | Yes | Yes |
| Egress network | Azure datacenter | Cloudflare (Workers add `cf-worker` headers) | Cloudflare | Google Cloud – Google's network, but **not** Googlebot/AdsBot ranges or `googlebot.com` reverse DNS | Oracle |
| Latency reliability | Good: fresh dedicated VM per run | – | Good (dedicated instance size) | Good (dedicated CPU per task) | Micro: poor; A1: good |
| Results back to git | Built in (`GITHUB_TOKEN`) | Needs a GitHub token | Needs a GitHub token or results move to R2 only | Needs a GitHub token or results move to R2/GCS only | Built in (runner) |
| Extra setup | None | Rewrite + new deploy | Dockerfile, Worker, Durable Object, Wrangler deploy | GCP project, Artifact Registry (image ~2 GB, >0.5 GB free → cents/month), Scheduler, Secret Manager | Runner maintenance, OS updates |

### Notes

- **GitHub Actions**: the 2026-10-24 scheduled run failed in 4 s on billing, not on minutes for this repo alone –
  the free quota is per account, so other private repos (abeceda-hrou) and any $0 spending limit count. Check
  *Settings → Billing* first. The planned $0.002/min charge for self-hosted runners was postponed; public repos stay free.
- **Cloudflare Workers + Browser Rendering** fails on Firefox, the 10 min/day cap and a full rewrite. Useful at most
  for a tiny Chromium-only spot check.
- **Cloudflare Containers** is the Cloudflare option that keeps the code. Containers can be stopped or moved by
  the platform, so a 25-min batch job needs retry handling.
- **Google Cloud Run Jobs** stays within the free tier for our load and keeps the code. Default task timeout is
  10 min, set it higher (max 24 h). Being on Google's network does not make us AdsBot: anti-bot allow-lists usually
  verify Googlebot by reverse DNS, so results can still differ from Google Ads' own check.
- **Self-hosted on a stronger free VM** (OCI A1) fixes latency without changing the workflow, but stays our own
  machine to maintain and still runs from Oracle IPs.

## Open questions

- Will the repo become public (unlimited free hosted minutes)? Needs client consent and removing `.vibe-wise/`.
- Which matters most: zero cost, trustworthy latency, or network realism vs Google Ads?
- Should results keep being committed to git, or live only in R2? (Affects every non-GitHub host.)

## Sources

- [Cloudflare Browser Rendering limits](https://developers.cloudflare.com/browser-rendering/limits/)
- [Browser Rendering pricing changelog](https://developers.cloudflare.com/changelog/2025-07-28-br-pricing/)
- [Cloudflare Containers pricing](https://developers.cloudflare.com/containers/pricing/)
- [Cloud Run pricing](https://cloud.google.com/run/pricing)
- [GitHub Actions pricing update](https://github.blog/changelog/2025-12-16-coming-soon-simpler-pricing-and-a-better-experience-for-github-actions/)
- [GitHub 2026 Actions pricing changes](https://resources.github.com/actions/2026-pricing-changes-for-github-actions/)
