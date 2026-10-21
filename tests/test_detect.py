import unittest

from webanalyst.detect import analyse_html


class DetectTest(unittest.TestCase):
    def test_forpsi_browser_check(self):
        html = "<title>Wait a moment...</title><h1>Probíhá ověření vašeho prohlížeče. Počkejte prosím několik sekund.</h1>"
        self.assertTrue(analyse_html(html, 403)["is_challenge"])

    def test_forpsi_rate_limit(self):
        html = "<title>Technical Problems</title><h6>Chyba 429 - Příliš mnoho požadavků</h6>"
        self.assertTrue(analyse_html(html, 429)["is_challenge"])

    def test_normal_page(self):
        html = "<title>Middex</title><p>Hosting FORPSI</p>" + "<p>obsah</p>" * 1000
        result = analyse_html(html, 200)
        self.assertFalse(result["is_challenge"])
        self.assertTrue(result["mentions_forpsi"])

    def test_cloudflare_injected_script_is_not_a_challenge(self):
        html = ("<title>Firmometr</title>" + "<p>obsah</p>" * 1000
                + '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>')
        self.assertFalse(analyse_html(html, 200)["is_challenge"])

    def test_cloudflare_challenge(self):
        html = "<title>Just a moment...</title><script>window._cf_chl_opt={cvId:'3'}</script>"
        self.assertTrue(analyse_html(html, 403)["is_challenge"])


if __name__ == "__main__":
    unittest.main()
