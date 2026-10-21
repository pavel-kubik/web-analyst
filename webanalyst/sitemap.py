"""Discover a domain's pages: robots.txt -> sitemap index -> child sitemaps."""
import gzip
import time
import urllib.parse
import xml.etree.ElementTree as ET

import requests

from .http_probe import USER_AGENTS

MAX_URLS = 300  # per domain, homepage included
MAX_SITEMAPS = 50  # sitemap files fetched per domain
MAX_SITEMAP_BYTES = 20 * 1024 * 1024
PAUSE_S = 1.0  # between sitemap fetches, same pacing as page measurements


def _fetch(url: str) -> tuple[int, bytes]:
    resp = requests.get(url, headers={"User-Agent": USER_AGENTS["chrome"]}, timeout=30)
    return resp.status_code, resp.content[:MAX_SITEMAP_BYTES]


def _host(url: str) -> str:
    host = urllib.parse.urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def sitemaps_from_robots(text: str) -> list[str]:
    """`Sitemap:` lines of a robots.txt, in order."""
    out = []
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "sitemap" and value.strip():
            out.append(value.strip())
    return out


def parse_sitemap(data: bytes) -> tuple[list[str], list[str]]:
    """Return (child sitemaps, page URLs) from a sitemap index or urlset document (optionally gzipped)."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)[:MAX_SITEMAP_BYTES]
    root = ET.fromstring(data)
    kind = root.tag.rsplit("}", 1)[-1]
    locs = [el.text.strip() for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "loc" and el.text and el.text.strip()]
    # In a urlset, <loc> inside <image:image> etc. is not a page; keep only direct <url><loc>.
    if kind == "urlset":
        locs = [
            loc.text.strip()
            for url in root
            if url.tag.rsplit("}", 1)[-1] == "url"
            for loc in url
            if loc.tag.rsplit("}", 1)[-1] == "loc" and loc.text and loc.text.strip()
        ]
        return [], locs
    if kind == "sitemapindex":
        return locs, []
    return [], []


def discover(domain: str, fetch=_fetch, max_urls: int = MAX_URLS, pause_s: float = PAUSE_S) -> dict:
    """Homepage first, then same-host pages from the domain's sitemaps (www. and bare host are treated as one)."""
    home = domain.rstrip("/") + "/"
    host = _host(home)
    urls, errors, fetched = [home], [], []
    seen = {home}

    def add(url: str) -> bool:
        if len(urls) >= max_urls:
            return False
        if _host(url) == host and url not in seen:
            seen.add(url)
            urls.append(url)
        return True

    queue = []
    try:
        status, body = fetch(urllib.parse.urljoin(home, "/robots.txt"))
        if status == 200:
            queue = sitemaps_from_robots(body.decode("utf-8", "replace"))
    except Exception as exc:
        errors.append(f"robots.txt: {type(exc).__name__}: {exc}")
    if not queue:
        queue = [urllib.parse.urljoin(home, "/sitemap.xml")]

    capped = False
    while queue and len(fetched) < MAX_SITEMAPS and not capped:
        sm = queue.pop(0)
        if sm in fetched:
            continue
        if fetched and pause_s:
            time.sleep(pause_s)
        fetched.append(sm)
        try:
            status, body = fetch(sm)
            if status != 200:
                errors.append(f"{sm}: HTTP {status}")
                continue
            children, pages = parse_sitemap(body)
        except Exception as exc:
            errors.append(f"{sm}: {type(exc).__name__}: {exc}")
            continue
        queue.extend(c for c in children if c not in fetched)
        for page in pages:
            if not add(page):
                capped = True
                break
    return {"sitemaps": fetched, "urls": urls, "capped": capped, "errors": errors}
