"""Plain HTTP probes: what a crawler without JavaScript (e.g. Google AdsBot) receives on a cold visit."""
import time

import requests

from .detect import analyse_html

USER_AGENTS = {
    "adsbot-google": "AdsBot-Google (+http://www.google.com/adsbot.html)",
    "adsbot-google-mobile": (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Mobile Safari/537.36 (compatible; AdsBot-Google-Mobile; +http://www.google.com/mobile/adsbot.html)"
    ),
    "googlebot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "chrome": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
}

INTERESTING_HEADERS = ("server", "x-powered-by", "set-cookie", "cache-control", "location", "via", "x-cache", "cf-ray", "retry-after")


def probe(url: str, ua_name: str, timeout: float = 30.0) -> dict:
    """Fetch url with a fresh session (no cookies) and record timing, redirects and challenge signals."""
    session = requests.Session()
    headers = {
        "User-Agent": USER_AGENTS[ua_name],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
    }
    started = time.perf_counter()
    try:
        resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=True)
        ttfb = time.perf_counter() - started
        body = resp.content.decode(resp.encoding or "utf-8", "replace")
        total = time.perf_counter() - started
    except requests.RequestException as exc:
        return {"ua": ua_name, "url": url, "error": f"{type(exc).__name__}: {exc}", "total_s": round(time.perf_counter() - started, 3)}

    chain = [{"status": r.status_code, "url": r.url, "location": r.headers.get("location")} for r in resp.history]
    return {
        "ua": ua_name,
        "url": url,
        "final_url": resp.url,
        "status": resp.status_code,
        "redirects": chain,
        "ttfb_s": round(ttfb, 3),
        "total_s": round(total, 3),
        "headers": {k.lower(): v for k, v in resp.headers.items() if k.lower() in INTERESTING_HEADERS},
        "cookies_set": sorted(session.cookies.keys()),
        **analyse_html(body, resp.status_code),
        "snippet": body[:1500] if len(body) < 20000 else "",
    }


def probe_all(url: str) -> list[dict]:
    return [probe(url, ua) for ua in USER_AGENTS]
