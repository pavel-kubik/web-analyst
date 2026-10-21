import pathlib
import tempfile
import unittest

from webanalyst import publish
from webanalyst.report import run_dir

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
            for rel in ("data/manifest.json", f"{run_dir()}/middex/old.json", f"{run_dir()}/middex/new.json",
                        "data/middex/legacy-unversioned.json", "shots/middex-0-chromium-cold-final.jpg",
                        "shots/adhoc-0-firefox-cold-final.jpg"):
                (docs / rel).parent.mkdir(parents=True, exist_ok=True)
                (docs / rel).write_text("x")
            keys = [k for k, *_ in publish.plan(docs, ["middex/new.json"])]
            self.assertEqual(keys, [f"{run_dir()}/middex/new.json", "shots/middex-0-chromium-cold-final.jpg", "data/manifest.json"])
            backfill = [k for k, *_ in publish.plan(docs, None)]
            self.assertIn(f"{run_dir()}/middex/old.json", backfill)
            self.assertNotIn("data/middex/legacy-unversioned.json", backfill)  # only the current format version
            self.assertNotIn("data/manifest.json", backfill[:-1])  # manifest is only uploaded once, last

    def test_cache_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = pathlib.Path(tmp)
            (docs / run_dir() / "s").mkdir(parents=True)
            (docs / run_dir() / "s" / "r.json").write_text("x")
            (docs / "data" / "manifest.json").write_text("x")
            by_key = {k: cache for k, _, _, cache in publish.plan(docs, None)}
            self.assertIn("immutable", by_key[f"{run_dir()}/s/r.json"])
            self.assertEqual(by_key["data/manifest.json"], "public, max-age=60")

    def test_legacy_keys_only_unversioned_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = pathlib.Path(tmp)
            for rel in ("middex/2026-10-19T1614Z.json", "middex/latest.json", "adhoc/2026-10-19T1844Z.json"):
                (results / rel).parent.mkdir(parents=True, exist_ok=True)
                (results / rel).write_text("{}")
            self.assertEqual(publish.legacy_keys(results), ["data/middex/2026-10-19T1614Z.json"])


if __name__ == "__main__":
    unittest.main()
