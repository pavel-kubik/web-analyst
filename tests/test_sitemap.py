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


if __name__ == "__main__":
    unittest.main()
