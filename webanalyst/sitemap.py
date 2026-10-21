"""Discover a domain's pages: robots.txt -> sitemap index -> child sitemaps.

Everything here comes from the measured website, so it is untrusted: every URL (sitemaps, redirects, pages) must pass
`safe_url` (same site, http/https, no userinfo, backslashes or control characters) and is rebuilt from its parsed parts
before use; downloads, gzip output, sitemap count and error list are capped; documents with a DTD are rejected.
"""
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zlib

import requests

from .http_probe import USER_AGENTS

MAX_URLS = 300  # per domain, homepage included
MAX_SITEMAPS = 50  # sitemap files fetched per domain
MAX_SITEMAP_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_ERRORS = 50
PAUSE_S = 1.0  # between sitemap fetches, same pacing as page measurements


class SitemapError(Exception):
    """A problem worth showing in the public discovery errors (message contains no response data)."""


def _site(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def safe_url(url: str, home: str) -> str | None:
    """`url` rebuilt from its parts if it is an http(s) URL on the same site and port as `home`, else None."""
    url = (url or "").strip()
    if not url or "\\" in url or any(ord(c) < 0x21 or ord(c) == 0x7F for c in url):
        return None  # browsers read "\" as "/", so Python and the browser could disagree on the host
    try:
        parts, base = urllib.parse.urlsplit(url), urllib.parse.urlsplit(home)
        port, base_port = parts.port, base.port
    except ValueError:  # malformed port / IPv6 literal
        return None
    if parts.scheme not in ("http", "https") or "@" in parts.netloc or not parts.hostname:
        return None
    if _site(parts.hostname) != _site(base.hostname or "") or port != base_port:
        return None
    netloc = parts.hostname + (f":{port}" if port else "")
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def _fetch(url: str, home: str, get=requests.get) -> tuple[int, bytes]:
    """GET with redirects followed only to safe URLs and the body capped at MAX_SITEMAP_BYTES."""
    for _ in range(MAX_REDIRECTS + 1):
        resp = get(url, headers={"User-Agent": USER_AGENTS["chrome"]}, timeout=30, stream=True, allow_redirects=False)
        try:
            if resp.status_code in (301, 302, 303, 307, 308):
                target = safe_url(urllib.parse.urljoin(url, resp.headers.get("location", "")), home)
                if not target:
                    raise SitemapError("redirect to another site refused")
                url = target
                continue
            body = bytearray()
            for chunk in resp.iter_content(64 * 1024):
                body += chunk
                if len(body) > MAX_SITEMAP_BYTES:
                    raise SitemapError("larger than 20 MB")
            return resp.status_code, bytes(body)
        finally:
            resp.close()
    raise SitemapError("too many redirects")


def sitemaps_from_robots(text: str) -> list[str]:
    """`Sitemap:` lines of a robots.txt, in order."""
    out = []
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "sitemap" and value.strip():
            out.append(value.strip())
    return out


class _NoDoctype(ET.TreeBuilder):
    """Called by the XML parser on <!DOCTYPE>, i.e. after decoding, so encoding tricks or padding can't hide it."""

    def doctype(self, name, pubid, system):
        raise SitemapError("DTD not allowed")


def parse_sitemap(data: bytes) -> tuple[list[str], list[str]]:
    """Return (child sitemaps, page URLs) from a sitemap index or urlset document (optionally gzipped)."""
    if data[:2] == b"\x1f\x8b":
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        data = inflater.decompress(data, MAX_SITEMAP_BYTES + 1)  # output-capped: a gzip bomb stops here
        if len(data) > MAX_SITEMAP_BYTES or inflater.unconsumed_tail:
            raise SitemapError("larger than 20 MB unpacked")
    parser = ET.XMLParser(target=_NoDoctype())
    parser.feed(data)
    root = parser.close()
    name = lambda el: el.tag.rsplit("}", 1)[-1]  # noqa: E731
    text = lambda el: (el.text or "").strip()  # noqa: E731
    if name(root) == "urlset":
        # Only direct <url><loc>; <image:loc> etc. are not pages.
        return [], [text(loc) for url in root if name(url) == "url" for loc in url if name(loc) == "loc" and text(loc)]
    if name(root) == "sitemapindex":
        return [text(loc) for sm in root if name(sm) == "sitemap" for loc in sm if name(loc) == "loc" and text(loc)], []
    return [], []


def _error(where: str, exc: Exception) -> str:
    """Public error text: our own SitemapError message, otherwise only the exception type."""
    return f"{where[:200]}: {exc if isinstance(exc, SitemapError) else type(exc).__name__}"


def discover(domain: str, fetch=None, max_urls: int = MAX_URLS, pause_s: float = PAUSE_S) -> dict:
    """Homepage first, then same-site pages from the domain's sitemaps (www. and bare host are treated as one)."""
    home = domain.rstrip("/") + "/"
    fetch = fetch or (lambda url: _fetch(url, home))
    urls, errors, fetched = [home], [], []
    seen = {home}

    def add(url: str) -> bool:
        if len(urls) >= max_urls:
            return False
        safe = safe_url(url, home)
        if safe and safe not in seen:
            seen.add(safe)
            urls.append(safe)
        return True

    skipped = 0

    def enqueue(candidates: list[str], base: str) -> None:
        nonlocal skipped
        for c in candidates:
            if len(known) >= MAX_SITEMAPS:
                return
            safe = safe_url(urllib.parse.urljoin(base, c), home)
            if not safe:
                skipped += 1
                if skipped <= MAX_ERRORS:
                    errors.append(_error(c, SitemapError("skipped, not on this site")))
            elif safe not in known:
                known.add(safe)
                queue.append(safe)

    queue: list[str] = []
    known: set[str] = set()  # queued or fetched sitemaps
    robots = urllib.parse.urljoin(home, "/robots.txt")
    try:
        status, body = fetch(robots)
        if status == 200:
            enqueue(sitemaps_from_robots(body.decode("utf-8", "replace")), home)
    except Exception as exc:
        errors.append(_error("robots.txt", exc))
    if not queue:
        queue = [urllib.parse.urljoin(home, "/sitemap.xml")]
        known.add(queue[0])

    capped = False
    while queue and len(fetched) < MAX_SITEMAPS and not capped:
        sm = queue.pop(0)
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
            errors.append(_error(sm, exc))
            continue
        enqueue(children, sm)
        for page in pages:
            if not add(page):
                capped = True
                break
    if skipped > MAX_ERRORS:
        errors.append(f"…and {skipped - MAX_ERRORS} more sitemap URLs skipped, not on this site")
    return {"sitemaps": fetched, "urls": urls, "capped": capped, "errors": errors[:MAX_ERRORS + 1]}
