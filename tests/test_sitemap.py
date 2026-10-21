import pathlib
import unittest

from webanalyst import sitemap

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "sitemap"


def fake_fetch(pages: dict):
    """fetch() stand-in: url -> fixture file name, anything else is a 404."""
    def fetch(url):
        name = pages.get(url)
        return (200, (FIXTURES / name).read_bytes()) if name else (404, b"")
    return fetch


SITE = {
    "https://www.example.cz/robots.txt": "robots.txt",
    "https://www.example.cz/sitemap.xml": "index.xml",
    "https://www.example.cz/page-sitemap.xml": "pages.xml",
    "https://www.example.cz/post-sitemap.xml": "posts.xml",
}


class SitemapTest(unittest.TestCase):
    def test_robots_lines(self):
        text = (FIXTURES / "robots.txt").read_text()
        self.assertEqual(sitemap.sitemaps_from_robots(text), ["https://www.example.cz/sitemap.xml"])

    def test_index_to_pages(self):
        found = sitemap.discover("https://www.example.cz", fetch=fake_fetch(SITE), pause_s=0)
        self.assertEqual(found["urls"], [
            "https://www.example.cz/",
            "https://www.example.cz/kontakt/",
            "https://example.cz/sluzby/",  # bare host counts as the same site
            "https://www.example.cz/blog/prvni/",
        ])
        self.assertEqual(found["errors"], ["https://www.example.cz/missing-sitemap.xml: HTTP 404"])
        self.assertFalse(found["capped"])

    def test_image_locs_and_other_hosts_are_ignored(self):
        found = sitemap.discover("https://www.example.cz", fetch=fake_fetch(SITE), pause_s=0)
        self.assertFalse(any("uploads" in u or "cdn.other" in u for u in found["urls"]))

    def test_cap(self):
        found = sitemap.discover("https://www.example.cz", fetch=fake_fetch(SITE), max_urls=2, pause_s=0)
        self.assertEqual(len(found["urls"]), 2)
        self.assertTrue(found["capped"])

    def test_falls_back_to_sitemap_xml_without_robots(self):
        site = {k: v for k, v in SITE.items() if not k.endswith("robots.txt")}
        found = sitemap.discover("https://www.example.cz/", fetch=fake_fetch(site), pause_s=0)
        self.assertIn("https://www.example.cz/kontakt/", found["urls"])

    def test_gzipped_sitemap(self):
        import gzip
        _, pages = sitemap.parse_sitemap(gzip.compress((FIXTURES / "pages.xml").read_bytes()))
        self.assertIn("https://www.example.cz/kontakt/", pages)


HOME = "https://www.example.cz/"


class SafeUrlTest(unittest.TestCase):
    def test_accepts_same_site_and_rebuilds(self):
        self.assertEqual(sitemap.safe_url("https://example.cz/a?b=1#frag", HOME), "https://example.cz/a?b=1")
        self.assertEqual(sitemap.safe_url("HTTPS://WWW.EXAMPLE.CZ", HOME), "https://www.example.cz/")

    def test_rejects_hostile_urls(self):
        for url in (
            "https://evil.example\\@www.example.cz/",  # browser: host evil.example
            "https://evil.example\\www.example.cz/",
            "https://user@www.example.cz/",
            "https://www.example.cz:8443/",
            "https://www.example.cz.evil.example/",
            "javascript:alert(1)",
            "file:///etc/passwd",
            "http://169.254.169.254/latest/meta-data/",
            "https://www.example.cz/\tx",
            "https://www.example.cz/a b",
            "https://[::1/",
        ):
            self.assertIsNone(sitemap.safe_url(url, HOME), url)


class HostileSitemapTest(unittest.TestCase):
    def test_gzip_bomb_is_capped(self):
        import gzip
        bomb = gzip.compress(b"<urlset>" + b" " * (sitemap.MAX_SITEMAP_BYTES + 1024))
        self.assertLess(len(bomb), 100_000)
        with self.assertRaises(sitemap.SitemapError):
            sitemap.parse_sitemap(bomb)

    def test_dtd_rejected(self):
        with self.assertRaises(sitemap.SitemapError):
            sitemap.parse_sitemap(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><urlset/>')

    def test_off_site_sitemaps_are_not_fetched(self):
        requested = []
        files = {"https://www.example.cz/robots.txt": b"Sitemap: http://169.254.169.254/sitemap.xml\nSitemap: https://www.example.cz/s.xml",
                 "https://www.example.cz/s.xml": b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                                 b"<sitemap><loc>https://internal.corp/x.xml</loc></sitemap></sitemapindex>"}

        def fetch(url):
            requested.append(url)
            return (200, files[url]) if url in files else (404, b"")

        found = sitemap.discover(HOME, fetch=fetch, pause_s=0)
        self.assertEqual(requested, ["https://www.example.cz/robots.txt", "https://www.example.cz/s.xml"])
        self.assertEqual(len([e for e in found["errors"] if "not on this site" in e]), 2)

    def test_hostile_page_urls_dropped(self):
        files = {"https://www.example.cz/robots.txt": b"",
                 "https://www.example.cz/sitemap.xml": b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                 b"<url><loc>https://evil.example\\@www.example.cz/</loc></url>"
                 b"<url><loc>https://www.example.cz/ok/</loc></url></urlset>"}
        found = sitemap.discover(HOME, fetch=lambda u: (200, files[u]) if u in files else (404, b""), pause_s=0)
        self.assertEqual(found["urls"], [HOME, "https://www.example.cz/ok/"])

    def test_errors_hide_exception_text(self):
        def fetch(url):
            raise ConnectionError("secret internal detail")
        found = sitemap.discover(HOME, fetch=fetch, pause_s=0)
        self.assertTrue(found["errors"])
        self.assertFalse(any("secret" in e for e in found["errors"]))


class FakeResponse:
    def __init__(self, status, body=b"", location=None):
        self.status_code, self._body, self.headers = status, body, {"location": location} if location else {}

    def iter_content(self, size):
        for i in range(0, len(self._body), size):
            yield self._body[i:i + size]

    def close(self):
        pass


class FetchTest(unittest.TestCase):
    def test_follows_same_site_redirect_only(self):
        responses = {"https://example.cz/s.xml": FakeResponse(301, location="https://www.example.cz/s.xml"),
                     "https://www.example.cz/s.xml": FakeResponse(200, b"<urlset/>")}
        self.assertEqual(sitemap._fetch("https://example.cz/s.xml", HOME, get=lambda u, **kw: responses[u]), (200, b"<urlset/>"))
        evil = lambda u, **kw: FakeResponse(302, location="http://169.254.169.254/")  # noqa: E731
        with self.assertRaises(sitemap.SitemapError):
            sitemap._fetch("https://www.example.cz/s.xml", HOME, get=evil)

    def test_body_capped(self):
        big = FakeResponse(200, b"x" * (sitemap.MAX_SITEMAP_BYTES + 1))
        with self.assertRaises(sitemap.SitemapError):
            sitemap._fetch("https://www.example.cz/s.xml", HOME, get=lambda u, **kw: big)


if __name__ == "__main__":
    unittest.main()
