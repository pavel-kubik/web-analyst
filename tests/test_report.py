import json
import pathlib
import tempfile
import unittest

from webanalyst import report

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class SlimRunTest(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads((FIXTURES / "raw-forpsi-429.json").read_text())
        self.slim = report.slim_run(self.raw)

    def test_drops_headers_and_html(self):
        text = json.dumps(self.slim)
        for leaked in ("set-cookie", "snippet", "headers", "cookies_set"):
            self.assertNotIn(leaked, text)

    def test_keeps_every_sample(self):
        page = self.slim["pages"][0]
        self.assertEqual(page["tier"], "full")  # pre-tier runs measured everything
        http = [s for s in page["samples"] if s["kind"] == "http"]
        browser = [s for s in page["samples"] if s["kind"] == "browser"]
        self.assertEqual(len(http), 5)
        self.assertEqual(len(browser), 4)  # 2 browsers x cold/warm
        self.assertTrue(all(s["status"] == 429 for s in http))

    def test_old_browser_runs_fall_back_to_first_status(self):
        cold = next(s for s in self.slim["pages"][0]["samples"] if s["kind"] == "browser" and s["visit"] == "cold")
        self.assertEqual(cold["status"], 429)  # so latency rule B excludes this "content" (it was an error page)

    def test_build_writes_manifest_and_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            results, docs = pathlib.Path(tmp, "results"), pathlib.Path(tmp, "docs")
            (results / "middex").mkdir(parents=True)
            (results / "middex" / "2026-10-19T1614Z.json").write_text(json.dumps(self.raw))
            (results / "middex" / "latest.json").write_text(json.dumps(self.raw))
            report.build(results, docs)
            manifest = json.loads((docs / "data" / "manifest.json").read_text())
            self.assertEqual(manifest["version"], report.VERSION)
            runs = manifest["sites"][0]["runs"]
            self.assertEqual([r["path"] for r in runs], ["data/middex/2026-10-19T1614Z.json"])
            self.assertTrue((docs / runs[0]["path"]).exists())


if __name__ == "__main__":
    unittest.main()
