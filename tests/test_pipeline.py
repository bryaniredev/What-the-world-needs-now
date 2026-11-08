import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "collector"))
sys.path.insert(0, str(ROOT / "tests"))

from wtwn import crypto, run, sources  # noqa: E402
import make_fixture  # noqa: E402

PASS = "test-passphrase"


class PipelineTest(unittest.TestCase):
    def test_three_days_and_wrong_passphrase(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            os.environ["SITE_PASSPHRASE"] = PASS
            for i, date in enumerate(["2026-01-01", "2026-01-02", "2026-01-03"], start=1):
                fx = d / f"fx{i}.json"
                fx.write_text(json.dumps(make_fixture.make(seed=i)))
                run.main(["--fixture", str(fx), "--date", date, "--data-dir", str(d / "data"), "--state-dir", str(d / "state")])

            meta = json.loads((d / "data" / "meta.json").read_text())
            key = crypto.derive_key(PASS, crypto.b64d(meta["salt"]), meta["iterations"])
            self.assertTrue(crypto.verify_meta(key, meta))
            index = crypto.decrypt_obj(key, json.loads((d / "data" / "index.json").read_text()))
            self.assertEqual([x["date"] for x in index["days"]], ["2026-01-01", "2026-01-02", "2026-01-03"])
            self.assertTrue(index["problems"])
            recurring = [p for p in index["problems"].values() if p["days_seen"] == 3]
            self.assertTrue(recurring, "same complaints on 3 days should form a recurring problem")
            day = crypto.decrypt_obj(key, json.loads((d / "data" / "days" / "2026-01-02.json").read_text()))
            self.assertTrue(day["items"])
            self.assertTrue(all("pain_score" in it for it in day["items"]))
            # nothing readable in plain text
            raw = (d / "data" / "index.json").read_text()
            self.assertNotIn("invoice", raw.lower())

            os.environ["SITE_PASSPHRASE"] = "wrong"
            with self.assertRaises(SystemExit):
                run.main(["--fixture", str(fx), "--date", "2026-01-04", "--data-dir", str(d / "data"), "--state-dir", str(d / "state")])

    def test_dedupe(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            os.environ["SITE_PASSPHRASE"] = PASS
            fx = d / "fx.json"
            fx.write_text(json.dumps(make_fixture.make(seed=7)))
            args = ["--fixture", str(fx), "--data-dir", str(d / "data"), "--state-dir", str(d / "state")]
            run.main(args + ["--date", "2026-02-01"])
            run.main(args + ["--date", "2026-02-02"])
            meta = json.loads((d / "data" / "meta.json").read_text())
            key = crypto.derive_key(PASS, crypto.b64d(meta["salt"]), meta["iterations"])
            day2 = crypto.decrypt_obj(key, json.loads((d / "data" / "days" / "2026-02-02.json").read_text()))
            self.assertEqual(day2["items"], [])


class ParserTest(unittest.TestCase):
    def test_shopify_parser(self):
        html = """<div data-merchant-review data-review-content-id="123">
          <div aria-label="1 out of 5 stars"></div><div>March 3, 2026</div>
          <p data-truncate-content-copy>The app broke our checkout and support never answered. Uninstalling.</p></div>
          <div data-merchant-review data-review-content-id="124"><div aria-label="5 out of 5 stars"></div>
          <p>Wonderful app, works great for our store and the team is helpful.</p></div>"""
        got = sources._parse_shopify_reviews("someapp", html, 2)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["rating"], 1)
        self.assertIn("checkout", got[0]["text"])


if __name__ == "__main__":
    unittest.main()
