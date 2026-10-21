# TODO / later

- ⚠️ **Move dashboard data off `r2.dev`** (do first): r2.dev is rate-limited and not meant for production.
  Connect a custom domain to the `web-analyst-data` bucket, update CORS and `<meta name="data-base">` in `docs/index.html`.
- **Separate Cloudflare account from firmometr**: web-analyst shares account `584a900cab287c4bc9a4c681a6e808a4`.
  The R2 API token (*Workers R2 Storage → Edit*) can write to every bucket in the account, including firmometr's.
  Options: own Cloudflare account, or a bucket-scoped R2 S3 access key + S3 client in `webanalyst/publish.py`.
- **Revisit probe tiers** once real robots.txt / sitemap data is in: which pages deserve the full profile set,
  UA rotation per run, page sharding, more runs per day during an incident (`TIERS` in `webanalyst/__main__.py`).
- **HAR capture** – decide bodies vs metadata only and where to store it (not git).
- **Screenshot history** – latest screenshots are already in R2 (overwritten each run); keep dated copies if history is wanted.
- **Google Ads landing URLs** – Google Ads API (`ad_group_ad.ad.final_urls`) or exported list; Ads pages are often not in the sitemap.
- **Link crawl** – follow links on pages (with a cap) and compare discovered URLs with the sitemap.
- **RSS / Atom sitemaps** – robots.txt may list e.g. `sitemap.rss`; currently fetched but yields no pages.
- **Auth** for the dashboard – Cloudflare Access in front of the Pages project *and* the data domain (public R2 data is not covered by protecting the Pages site; or serve data through a Worker).
- **Next phase: SEO and AIO suggestions** generated from the collected page data.
