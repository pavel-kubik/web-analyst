import unittest

import yaml

from webanalyst.form_check import CONFIG, _fill_values, evaluate, summary


class EvaluateTest(unittest.TestCase):
    def test_mail_sent_with_redirect_is_ok(self):
        r = {"cf7_status": "mail_sent", "http_status": 200, "response_s": 2.1,
             "expected_redirect": "/dekujeme/", "redirected": True}
        self.assertEqual(evaluate(r), ("OK", []))

    def test_mail_failed_is_fail(self):
        verdict, reasons = evaluate({"cf7_status": "mail_failed", "cf7_message": "Během odesílání zprávy nastala chyba."})
        self.assertEqual(verdict, "FAIL")
        self.assertIn("mail_failed", reasons[0])
        self.assertIn("nastala chyba", reasons[0])

    def test_spam_is_fail(self):
        self.assertEqual(evaluate({"cf7_status": "spam"})[0], "FAIL")

    def test_timeout_is_fail(self):
        verdict, reasons = evaluate({"outcome": "timeout", "response_s": 90.0})
        self.assertEqual(verdict, "FAIL")
        self.assertIn("timeout", reasons[0])

    def test_slow_or_missing_redirect_is_warn(self):
        r = {"cf7_status": "mail_sent", "response_s": 20, "expected_redirect": "/dekujeme/", "redirected": False,
             "final_url": "https://www.middex.cz/kontakt/"}
        verdict, reasons = evaluate(r)
        self.assertEqual(verdict, "WARN")
        self.assertEqual(len(reasons), 2)


class ConfigTest(unittest.TestCase):
    def test_forms_yml_is_valid(self):
        forms = yaml.safe_load(CONFIG.read_text())["forms"]
        self.assertTrue(forms)
        for f in forms:
            for key in ("id", "url", "form_id", "fields"):
                self.assertIn(key, f)

    def test_placeholders_are_replaced(self):
        form = {"fields": {"email": "{email}", "zprava": "test ({run})"}}
        self.assertEqual(_fill_values(form, "2026-11-28T0623Z", "a@b.cz"),
                         {"email": "a@b.cz", "zprava": "test (2026-11-28T0623Z)"})


class SummaryTest(unittest.TestCase):
    def test_summary_row(self):
        text = summary([{"url": "https://x.cz/kontakt/", "verdict": "FAIL", "outcome": "timeout",
                         "response_s": 90.0, "reasons": ["timeout: …"]}])
        self.assertIn("❌ FAIL", text)
        self.assertIn("90.0 s", text)
