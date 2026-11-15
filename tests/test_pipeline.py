import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "collector"))
sys.path.insert(0, str(ROOT / "tests"))

from wtwn import analyze, crypto, run, sources  # noqa: E402
import make_fixture  # noqa: E402

PASS = "Test-Passphrase"


def _run(d, fx, date):
    run.main(["--fixture", str(fx), "--date", date, "--data-dir", str(d / "data"), "--state-dir", str(d / "state")])


def _key(d, passphrase):
    meta = json.loads((d / "data" / "meta.json").read_text())
    return crypto.derive_key(passphrase, crypto.b64d(meta["salt"]), meta["iterations"]), meta


class PipelineTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ["SITE_PASSPHRASE"] = PASS

    def test_three_weeks(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for i, date in enumerate(["2026-01-04", "2026-01-11", "2026-01-18"], start=1):
                fx = d / f"fx{i}.json"
                fx.write_text(json.dumps(make_fixture.make(seed=i)))
                _run(d, fx, date)

            key, meta = _key(d, PASS.lower())  # capitalisation of the passphrase never matters
            self.assertTrue(crypto.verify_meta(key, meta))
            index = crypto.decrypt_obj(key, json.loads((d / "data" / "index.json").read_text()))
            self.assertEqual([x["date"] for x in index["days"]], ["2026-01-04", "2026-01-11", "2026-01-18"])
            week = crypto.decrypt_obj(key, json.loads((d / "data" / "days" / "2026-01-11.json").read_text()))
            titles = {it["title"] for it in week["items"]}

            # only posts that state a need survive
            self.assertNotIn("I built an app for landlords", titles)
            self.assertNotIn("Yahoo mail won't load after the update", titles)
            self.assertNotIn("Rent keeps going up", titles)
            self.assertFalse(any("toilet" in it["text"] for it in week["items"]))
            self.assertGreaterEqual(week["filtered"].get("promo", 0), 1)
            self.assertIn("Trust accounting for solos", titles)

            by_title = {it["title"]: it for it in week["items"]}
            law = by_title["Trust accounting for solos"]
            self.assertEqual(law["niche"], "Lawyers & paralegals")
            self.assertIn("pay", law["signals"])
            self.assertIn("happily pay", law["need"])
            gig = by_title["Need automation for order intake"]
            self.assertEqual(gig["niche"], "Restaurants, bars & cafés")  # worked out from the text
            self.assertIn("money", gig["costs"])
            self.assertTrue(all("niche_hint" not in it and "keep" not in it for it in week["items"]))

            # problems are niche + problem area, stable across weeks
            keys = {p["key"] for p in week["problems"]}
            self.assertIn("landscaping-lawn-care--scheduling-booking", keys)
            recurring = [p for p in index["problems"].values() if p["days_seen"] == 3]
            self.assertTrue(recurring)
            self.assertIn("Lawyers & paralegals", index["niches"])
            self.assertEqual(len(index["niches"]["Lawyers & paralegals"]["counts"]), 3)
            self.assertIn("servicetitan", index["products"])
            self.assertIn("too_expensive", index["products"]["servicetitan"]["types"])
            self.assertIn("client retainers", index["spreadsheet_uses"])
            self.assertIn("by_niche", index["days"][0])

            # nothing readable in plain text
            self.assertNotIn("landlord", (d / "data" / "index.json").read_text().lower())

            os.environ["SITE_PASSPHRASE"] = "wrong"
            with self.assertRaises(SystemExit):
                _run(d, fx, "2026-01-25")

    def test_dedupe_and_same_date_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            fx = d / "fx.json"
            fx.write_text(json.dumps(make_fixture.make(seed=7)))
            _run(d, fx, "2026-02-01")
            key, _ = _key(d, PASS.lower())
            first = crypto.decrypt_obj(key, json.loads((d / "data" / "days" / "2026-02-01.json").read_text()))
            self.assertTrue(first["items"])
            _run(d, fx, "2026-02-01")  # same date again: keeps what it had
            again = crypto.decrypt_obj(key, json.loads((d / "data" / "days" / "2026-02-01.json").read_text()))
            self.assertEqual({i["id"] for i in again["items"]}, {i["id"] for i in first["items"]})
            _run(d, fx, "2026-02-08")  # next week, nothing new
            nxt = crypto.decrypt_obj(key, json.loads((d / "data" / "days" / "2026-02-08.json").read_text()))
            self.assertEqual(nxt["items"], [])


class AnalyzeTest(unittest.TestCase):
    def _score(self, title, text, hint=None, **kw):
        it = {"id": "x", "source": "t", "kind": "discussion", "engagement": 0, "title": title, "text": text, **kw}
        if hint:
            it["niche_hint"] = hint
        return analyze.score_item(it)

    def test_same_words_but_not_a_lead(self):
        for title, text, hint in [
            ("Construction worker gifts", "Looking for next level starter tools for my brother, he has a project coming up.", "Construction & contractors"),
            ("I'm at a loss with bed time", "I feel like I have really tried everything and nothing works. We've tried a bunch of things.", "Parents & families"),
            ("Overstay", "I'm completely willing to pay whatever official fine is required for the two days.", "Travelers"),
            ("Imposter syndrome", "How do you all manage this, especially when you've got a large caseload? It eats hours of my week.", "Therapists & counsellors"),
            ("Enzyme cleaner", "Hoping pet owners can recommend a pet safe solution for our problem. I looked online.", "Pet owners"),
            ("Question for sellers", "I'm researching a desktop tool for Amazon sellers who use spreadsheets. How do you track profit manually every week?", "E-commerce sellers"),
            ("Location access", "Is there any legitimate reason these apps would need background location access?", None),
            ("Construction accounting", "Not looking for a software sale here, just a general question about retainage and my clients.", "Accountants & bookkeepers"),
        ]:
            self.assertFalse(self._score(title, text, hint)["keep"], title)

    def test_real_leads(self):
        for title, text, hint in [
            ("Saving emails", "I'm wondering if anyone has recommendations on affordable apps/programs that make saving emails to the matter easier?", "Lawyers & paralegals"),
            ("Packing slip and shipping label separation", "Has anyone found a solution? We print 200 orders a day.", "E-commerce sellers"),
            ("Workpapers", "Does anyone else lose hours to capturing screenshots for workpapers and documentation?", "Accountants & bookkeepers"),
            ("Moving from SimplePractice to Clerie?", "Private practice therapists, advice please.", "Therapists & counsellors"),
            ("Budget app", "Is there an app that would help my aging father plan a monthly budget?", "Personal finance"),
            ("Quotes", "Landscapers: how do you handle customer quotes and estimates? Mine take all evening.", "Landscaping & lawn care"),
        ]:
            self.assertTrue(self._score(title, text, hint)["keep"], title)

    def test_need_statement_prefers_the_problem(self):
        it = analyze.score_item({"id": "x", "source": "t", "kind": "discussion", "engagement": 0, "title": "Scheduling crews", "niche_hint": "Landscaping & lawn care",
                                 "text": "Every week I spend hours manually moving jobs around a whiteboard and texting guys. There has to be a better way."})
        self.assertTrue(it["keep"])
        self.assertIn("whiteboard", it["need"])

    def test_products(self):
        self.assertEqual(analyze.products_for("Any alternatives to QuickBooks Online? We are moving away from Xero too."), ["QuickBooks Online", "Xero"])
        self.assertEqual(analyze.products_for("the alternative to a toilet app is switching from the old way"), [])


class SourceTest(unittest.TestCase):
    def test_reddit_archive_paging(self):
        calls = []

        class R:
            def __init__(self, data):
                self.status_code, self._d = 200, data

            def raise_for_status(self):
                pass

            def json(self):
                return {"data": self._d}

        class H:
            s = None

            def get(self, url, **k):
                calls.append(url)
                if "before=" in url:
                    return R([{"id": "b1", "title": "t", "selftext": "x", "created_utc": 50, "subreddit": "Dentistry"}])
                return R([{"id": f"a{i}", "title": "t", "selftext": "[removed]" if i == 0 else "x", "created_utc": 100 + i,
                           "subreddit": "Dentistry", "score": 2, "num_comments": 3} for i in range(100)])

        os.environ.pop("REDDIT_CLIENT_ID", None)
        st = {}
        items = sources.reddit({"communities": {"Dental practices": ["Dentistry"]}, "max_pages_per_community": 3}, 10, H(), st)
        self.assertEqual(len(calls), 2)
        self.assertIn("before=100", calls[1])
        self.assertEqual(len(items), 100)  # 99 + 1, the removed post is skipped
        self.assertEqual(sources._item("s", "c", "discussion", 1, "u", "I\u2019d pay", "can\u2019t", 0)["title"], "I'd pay")
        self.assertEqual(items[0]["niche_hint"], "Dental practices")
        self.assertEqual(items[1]["engagement"], 5)
        self.assertTrue(st["reddit"]["ok"])


if __name__ == "__main__":
    unittest.main()
