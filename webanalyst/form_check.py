"""Submit contact forms from forms.yml in a real browser and check that the site really sends the message.

    python -m webanalyst.form_check                  # every form in forms.yml
    python -m webanalyst.form_check --form middex-kontakt
    python -m webanalyst.form_check --dry-run        # fill the form but do not submit (no e-mail is sent)

Contact Form 7 answers each submission with JSON from its REST endpoint (status mail_sent / mail_failed / spam /
validation_failed / aborted). The check records that answer, how long it took and whether the browser reached the
thank-you page. Results go to form-checks/<form id>/<timestamp>.json and latest.json; a Markdown summary is printed
for the GitHub Actions job summary. Exit code 1 when any form fails, so the scheduled run turns red and GitHub
notifies the repo owner.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import time

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "forms.yml"
OUT = ROOT / "form-checks"

DEFAULT_EMAIL = "web-analyst-test@middex.cz"
RESPONSE_TIMEOUT_S = 90       # the November 2026 outage left the request hanging for minutes
RECAPTCHA_SETTLE_S = 3        # give reCAPTCHA v3 time to load before submitting
SLOW_RESPONSE_S = 15

STATUS_TEXT = {
    "mail_sent": "e-mail odeslán",
    "mail_failed": "formulář hlásí chybu odeslání e-mailu (wp_mail selhal)",
    "spam": "formulář vyhodnotil zprávu jako spam (reCAPTCHA / antispam; je nastavený FORM_CHECK_TOKEN a zapnutý snippet na webu?)",
    "validation_failed": "validace polí selhala - změnil se formulář?",
    "acceptance_missing": "chybí souhlas se zpracováním údajů",
    "aborted": "odeslání přerušeno pluginem",
    "timeout": f"server neodpověděl do {RESPONSE_TIMEOUT_S} s (stejný příznak jako výpadek 18.-27. 11. 2026)",
    "no_response": "stránka neodeslala požadavek na CF7 REST API",
    "error": "chyba při práci s prohlížečem",
}


def evaluate(result: dict) -> tuple[str, list[str]]:
    """OK only when CF7 says mail_sent. WARN for a slow answer or a missing redirect, FAIL for anything else."""
    status = result.get("cf7_status") or result.get("outcome")
    if status != "mail_sent":
        reason = STATUS_TEXT.get(status, f"neznámý stav {status!r}")
        detail = (result.get("cf7_message") or result.get("error") or "").splitlines()[0] if (result.get("cf7_message") or result.get("error")) else ""
        return "FAIL", [f"{status}: {reason}" + (f" - „{detail}“" if detail else "")]
    warn = []
    if result.get("http_status") and result["http_status"] >= 400:
        warn.append(f"REST odpověď HTTP {result['http_status']}")
    if (result.get("response_s") or 0) > SLOW_RESPONSE_S:
        warn.append(f"pomalá odpověď {result['response_s']} s")
    if result.get("expected_redirect") and not result.get("redirected"):
        warn.append(f"nepřesměrovalo na {result['expected_redirect']} (final URL {result.get('final_url')})")
    return ("WARN" if warn else "OK"), warn


def _fill_values(form: dict, run: str, email: str) -> dict:
    return {name: str(v).replace("{run}", run).replace("{email}", email) for name, v in form["fields"].items()}


def check(form: dict, run: str, email: str, dry_run: bool = False, token: str = "") -> dict:
    from playwright.sync_api import sync_playwright

    url = f"{form['url']}?wa_form_check={run}"   # query string skips the page cache (WP Fastest Cache)
    feedback_path = f"/contact-form-7/v1/contact-forms/{form['form_id']}/feedback"
    result = {"form": form["id"], "url": form["url"], "run": run, "dry_run": dry_run, "token_used": bool(token),
              "expected_redirect": form.get("success_url_contains")}
    console_errors = []
    with sync_playwright() as pw:
        exe = os.environ.get("WA_CHROMIUM_EXECUTABLE")
        browser = pw.chromium.launch(executable_path=exe or None)
        page = browser.new_context(locale="cs-CZ", viewport={"width": 1366, "height": 900}).new_page()
        page.on("console", lambda m: console_errors.append(m.text[:200]) if m.type == "error" else None)
        try:
            page.goto(url, wait_until="load", timeout=60_000)
            scope = page.locator(f"form:has(input[name='_wpcf7'][value='{form['form_id']}'])")
            for name, value in _fill_values(form, run, email).items():
                scope.locator(f"[name='{name}']").fill(value)
            for name in form.get("checkboxes", []):
                # The theme hides the real checkbox (display:none) and styles its label, so tick it from JS.
                scope.locator(f"input[type=checkbox][name='{name}']").evaluate(
                    "el => { el.checked = true; el.dispatchEvent(new Event('change', {bubbles: true})); }")
            if token:
                # Lets the site skip its antispam check for this one submission (WPCode snippet on the site):
                # reCAPTCHA v3 scores a headless browser as a bot. The token is a GitHub secret, never stored here.
                scope.evaluate("(f, t) => { const i = document.createElement('input'); i.type = 'hidden';"
                               " i.name = '_wa_form_check'; i.value = t; f.appendChild(i); }", token)
            time.sleep(RECAPTCHA_SETTLE_S)
            if dry_run:
                result["outcome"] = "dry_run"
                result["verdict"], result["reasons"] = "OK", ["dry run - formulář vyplněn, neodesláno"]
                return result
            # Proxy the CF7 REST call through Playwright so the JSON answer is captured even when the theme
            # navigates to the thank-you page right after it (the browser would drop the response body).
            captured = {}

            def relay(route):
                try:
                    resp = route.fetch(timeout=RESPONSE_TIMEOUT_S * 1000)
                    captured.update(http_status=resp.status, body=resp.text())
                    route.fulfill(response=resp)
                except Exception as exc:
                    captured["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                    route.abort()
                captured["done"] = True

            page.route(f"**{feedback_path}*", relay)
            started = time.perf_counter()
            scope.locator("[type=submit]").click()
            while not captured.get("done") and time.perf_counter() - started < RESPONSE_TIMEOUT_S + 5:
                page.wait_for_timeout(250)
            result["response_s"] = round(time.perf_counter() - started, 2)
            if not captured.get("done"):
                result["outcome"] = "no_response"
            elif "error" in captured:
                result["outcome"] = "timeout" if "Timeout" in captured["error"] else "error"
                result["error"] = captured["error"]
            else:
                result["http_status"] = captured["http_status"]
                try:
                    body = json.loads(captured["body"])
                    result["cf7_status"] = body.get("status")
                    result["cf7_message"] = body.get("message")
                    result["site_token_check"] = body.get("wa_token")   # added by the WPCode snippet: ok / mismatch
                    result["invalid_fields"] = [f.get("field") for f in body.get("invalid_fields") or []]
                except ValueError:
                    result["outcome"] = "error"
                    result["error"] = f"odpověď není JSON: {captured['body'][:200]}"
            if result.get("cf7_status") == "mail_sent" and form.get("success_url_contains"):
                try:
                    page.wait_for_url(f"**{form['success_url_contains']}**", timeout=15_000)
                except Exception:
                    pass
            result["final_url"] = page.url
            result["redirected"] = bool(form.get("success_url_contains")) and form["success_url_contains"] in page.url
        except Exception as exc:
            result["outcome"] = "error"
            result["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        finally:
            result["console_errors"] = console_errors[:5]
            browser.close()
    result["verdict"], result["reasons"] = evaluate(result)
    return result


def save(result: dict) -> None:
    folder = OUT / result["form"]
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    (folder / f"{result['run']}.json").write_text(text)
    (folder / "latest.json").write_text(text)


def summary(results: list[dict]) -> str:
    icon = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌"}
    lines = ["### Kontaktní formuláře\n", "| Formulář | Výsledek | Stav CF7 | Odezva | Poznámka |", "|---|---|---|---|---|"]
    for r in results:
        status = r.get("cf7_status") or r.get("outcome") or "?"
        took = f"{r['response_s']} s" if r.get("response_s") is not None else "-"
        lines.append(f"| {r['url']} | {icon.get(r['verdict'], '')} {r['verdict']} | {status} | {took} | {'<br>'.join(r['reasons'])} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--form", action="append", help="form id from forms.yml (repeatable); default all")
    ap.add_argument("--dry-run", action="store_true", help="fill the form but do not submit")
    args = ap.parse_args()

    forms = yaml.safe_load(CONFIG.read_text())["forms"]
    if args.form:
        forms = [f for f in forms if f["id"] in args.form]
    run = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    email = os.environ.get("FORM_CHECK_EMAIL") or DEFAULT_EMAIL
    token = os.environ.get("FORM_CHECK_TOKEN", "")

    results = []
    for form in forms:
        r = check(form, run, email, dry_run=args.dry_run, token=token)
        results.append(r)
        if not args.dry_run:
            save(r)
    print(summary(results))
    return 1 if any(r["verdict"] == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
