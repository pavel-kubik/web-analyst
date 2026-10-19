"""Heuristics that recognise bot-protection / "checking your browser" interstitials."""
import re

# Phrases shown by hosting anti-bot / anti-DDoS interstitials (FORPSI, Cloudflare, SiteGround, Imunify, ...).
CHALLENGE_PATTERNS = [
    r"kontrol\w* (va[sš]eho |prohl[ií][zž]e[cč]e)",
    r"prob[ií]h[aá] kontrola",
    r"ov[eě][rř]ov[aá]n[ií] prohl[ií][zž]e[cč]e",
    r"ov[eě][rř]en[ií] (va[sš]eho )?prohl[ií][zž]e[cč]e",  # FORPSI: "Probíhá ověření vašeho prohlížeče"
    r"wait a moment",
    r"p[rř][ií]li[sš] mnoho po[zž]adavk[uů]",  # FORPSI 429 page
    r"too many requests",
    r"checking (your|the) browser",
    r"verify(ing)? (you are|that you are) (human|not a robot)",
    r"just a moment\.\.\.",
    r"ddos[- ]protection",
    r"cf-chl|challenge-platform|__cf_chl",
    r"sgcaptcha|sg-captcha",
    r"imunify360|bot-protection|botprotection",
    r"please (wait|enable javascript)",
]
_CHALLENGE_RE = re.compile("|".join(CHALLENGE_PATTERNS), re.IGNORECASE)
_META_REFRESH_RE = re.compile(r"<meta[^>]+http-equiv=[\"']?refresh", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def title_of(html: str) -> str:
    m = _TITLE_RE.search(html or "")
    return re.sub(r"\s+", " ", m.group(1)).strip()[:200] if m else ""


def analyse_html(html: str, status: int | None = None) -> dict:
    """Return which challenge signals the document shows."""
    html = html or ""
    matches = sorted({m.group(0).lower() for m in _CHALLENGE_RE.finditer(html)})
    meta_refresh = bool(_META_REFRESH_RE.search(html))
    # A tiny document that is mostly script and sets/reloads is typical of JS challenges.
    tiny_js_page = len(html) < 8000 and html.lower().count("<script") >= 1 and (
        "document.cookie" in html or "location.reload" in html or "location.href" in html
    )
    suspicious_status = status in (202, 403, 429, 503)
    is_challenge = bool(matches) or (tiny_js_page and (meta_refresh or suspicious_status))
    return {
        "is_challenge": is_challenge,
        "matches": matches,
        "meta_refresh": meta_refresh,
        "tiny_js_page": tiny_js_page,
        "mentions_forpsi": "forpsi" in html.lower(),
        "title": title_of(html),
        "html_bytes": len(html.encode("utf-8", "ignore")),
    }
