"""Real-browser probe: first visit with an empty profile, like a new visitor or the Google Ads landing-page check."""
import base64
import os
import time

from .detect import analyse_html

_PERF_JS = """() => {
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const fcp = performance.getEntriesByName('first-contentful-paint')[0];
  const resources = performance.getEntriesByType('resource');
  // transferSize is 0 for cross-origin resources without Timing-Allow-Origin, so page weight is a lower bound.
  const resourceBytes = resources.reduce((sum, r) => sum + (r.transferSize || 0), 0);
  const lcp = (window.__lcp || 0);
  return {
    ttfb_ms: nav.responseStart ? Math.round(nav.responseStart) : null,
    fcp_ms: fcp ? Math.round(fcp.startTime) : null,
    dom_content_loaded_ms: nav.domContentLoadedEventEnd ? Math.round(nav.domContentLoadedEventEnd) : null,
    load_ms: nav.loadEventEnd ? Math.round(nav.loadEventEnd) : null,
    lcp_ms: lcp ? Math.round(lcp) : null,
    cls: window.__cls === null ? null : Math.round(window.__cls * 1000) / 1000,
    transfer_bytes: nav.transferSize || null,
    resource_count: resources.length,
    page_bytes: (nav.transferSize || 0) + resourceBytes,
  };
}"""

# Layout-shift entries are Chromium-only, so Firefox reports cls: null.
_LCP_INIT = """
window.__lcp = 0;
window.__cls = null;
try {
  new PerformanceObserver(list => {
    for (const e of list.getEntries()) window.__lcp = e.startTime;
  }).observe({type: 'largest-contentful-paint', buffered: true});
} catch (e) {}
try {
  if ((PerformanceObserver.supportedEntryTypes || []).includes('layout-shift')) {
    window.__cls = 0;
    new PerformanceObserver(list => {
      for (const e of list.getEntries()) if (!e.hadRecentInput) window.__cls += e.value;
    }).observe({type: 'layout-shift', buffered: true});
  }
} catch (e) {}
"""

MAX_CONSOLE_ERRORS = 5


def _screenshot(page) -> str:
    try:
        return base64.b64encode(page.screenshot(type="jpeg", quality=55)).decode()
    except Exception:
        return ""


def _visit(page, url: str, max_wait_s: float, screenshots: bool = True) -> dict:
    """Navigate and wait until any challenge interstitial is gone (or max_wait_s passes)."""
    statuses, console_errors = [], []
    page.on("console", lambda m: console_errors.append(m.text[:200]) if m.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(str(exc)[:200]))
    page.on("response", lambda r: statuses.append({"status": r.status, "url": r.url}) if r.request.resource_type == "document" and r.frame == page.main_frame else None)
    started = time.perf_counter()
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=max_wait_s * 1000)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "elapsed_s": round(time.perf_counter() - started, 3)}

    first = analyse_html(page.content(), resp.status if resp else None)
    first_shot = _screenshot(page) if screenshots and first["is_challenge"] else ""

    # Poll until the document no longer looks like a challenge page.
    content_at = None
    while time.perf_counter() - started < max_wait_s:
        try:
            page.wait_for_load_state("load", timeout=2000)
        except Exception:
            pass
        try:
            current = analyse_html(page.content())
        except Exception:  # page is navigating
            time.sleep(0.25)
            continue
        if not current["is_challenge"]:
            content_at = time.perf_counter() - started
            break
        time.sleep(0.25)

    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    final = analyse_html(page.content())
    final_status = statuses[-1]["status"] if statuses else (resp.status if resp else None)
    if final_status and final_status >= 400:
        content_at = None  # an error page is not real content
    return {
        "first_status": resp.status if resp else None,
        "document_responses": statuses,
        "first_document": {k: first[k] for k in ("is_challenge", "matches", "title", "mentions_forpsi")},
        "challenge_seen": first["is_challenge"],
        "time_to_real_content_s": round(content_at, 3) if content_at is not None else None,
        "stuck_on_challenge": content_at is None,
        "final_status": final_status,
        "final_url": page.url,
        "final_title": final["title"],
        "perf": page.evaluate(_PERF_JS),
        "console_error_count": len(console_errors),
        "console_errors": console_errors[:MAX_CONSOLE_ERRORS],
        "challenge_screenshot_jpeg_b64": first_shot,
        "final_screenshot_jpeg_b64": _screenshot(page) if screenshots else "",
    }


def probe(url: str, browser_name: str = "firefox", user_agent: str | None = None, max_wait_s: float = 30.0, screenshots: bool = True) -> dict:
    """Two visits in one fresh context: cold (no cookies) and warm (cookies from the first visit)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        # Optional override, e.g. a preinstalled Chromium when the bundled build is missing.
        exe = os.environ.get(f"WA_{browser_name.upper()}_EXECUTABLE")
        browser = getattr(pw, browser_name).launch(executable_path=exe or None)
        ctx = browser.new_context(user_agent=user_agent, locale="cs-CZ", viewport={"width": 1366, "height": 900})
        ctx.add_init_script(_LCP_INIT)
        cold = _visit(ctx.new_page(), url, max_wait_s, screenshots)
        cookies = sorted(c["name"] for c in ctx.cookies())
        warm = _visit(ctx.new_page(), url, max_wait_s, screenshots)
        browser.close()
    return {
        "browser": browser_name,
        "user_agent": user_agent or "default",
        "url": url,
        "cold": cold,
        "cookies_after_first_visit": cookies,
        "warm": warm,
    }
