import pathlib
import tempfile
import unittest

from webanalyst import publish

PORCELAIN = """?? results/middex/2026-10-22T0417Z.json
 M results/middex/latest.json
?? results/adhoc/2026-10-22T0900Z.json
 M README.md
"""


class PublishTest(unittest.TestCase):
    def test_new_runs_from_git_status(self):
        self.assertEqual(publish.new_run_files(PORCELAIN), ["adhoc/2026-10-22T0900Z.json", "middex/2026-10-22T0417Z.json"])

    def test_plan_uploads_runs_shots_then_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = pathlib.Path(tmp)
            for rel in ("data/manifest.json", "data/middex/old.json", "data/middex/new.json", "shots/middex-0-chromium-cold-final.jpg",
                        "shots/adhoc-0-firefox-cold-final.jpg"):
                (docs / rel).parent.mkdir(parents=True, exist_ok=True)
                (docs / rel).write_text("x")
            keys = [k for k, *_ in publish.plan(docs, ["middex/new.json"])]
            self.assertEqual(keys, ["data/middex/new.json", "shots/middex-0-chromium-cold-final.jpg", "data/manifest.json"])
            backfill = [k for k, *_ in publish.plan(docs, None)]
            self.assertIn("data/middex/old.json", backfill)
            self.assertNotIn("data/manifest.json", backfill[:-1])  # manifest is only uploaded once, last

    def test_cache_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = pathlib.Path(tmp)
            (docs / "data" / "s").mkdir(parents=True)
            (docs / "data" / "s" / "r.json").write_text("x")
            (docs / "data" / "manifest.json").write_text("x")
            by_key = {k: cache for k, _, _, cache in publish.plan(docs, None)}
            self.assertIn("immutable", by_key["data/s/r.json"])
            self.assertEqual(by_key["data/manifest.json"], "public, max-age=60")


if __name__ == "__main__":
    unittest.main()
