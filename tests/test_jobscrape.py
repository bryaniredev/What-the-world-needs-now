import asyncio
import functools
import http.server
import os
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "collector"))
from wtwn import jobscrape  # noqa: E402

BOARD = ROOT / "tests" / "fixtures" / "board"


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        p = path.split("?")[0]
        name = "search.html" if p.startswith("/search") else p.rsplit("/", 1)[-1] + ".html"
        return str(BOARD / name)

    def log_message(self, *a):
        pass


@unittest.skipUnless(os.environ.get("RUN_BROWSER_TESTS"), "set RUN_BROWSER_TESTS=1 (needs Chromium)")
class ScrapeTest(unittest.TestCase):
    def test_fake_board(self):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_port}"
        jobscrape.SITES["fake"] = {"label": "Fake", "search": base + "/search?q={q}", "link": r"/job/\d+",
                                   "strip_query": True, "desc": [".desc"]}
        cfg = {"jobs": {"industries": ["car dealership"], "manual_work_signals": ["manually", "spreadsheet", "reconcil"]},
               "job_boards": {"sites": {"fake": True}, "queries_per_day": 1, "delay_seconds": [0, 0.1]}}
        out = asyncio.run(jobscrape.run(cfg, only=["fake"]))
        srv.shutdown()
        items = {it["title"]: it for it in out["items"]}
        self.assertEqual(set(items), {"Service Advisor", "Office Manager"})
        adv = items["Service Advisor"]
        self.assertIn("warranty claims", adv["text"])
        self.assertEqual(adv["url"], base + "/job/101")
        self.assertEqual(adv["channel"], "Fake · Metro Motors")
        self.assertGreaterEqual(adv["manual_hits"], 2)
        self.assertIn("blocked", out["sites"]["fake"].get("note", ""))  # 102 is a CAPTCHA page
        self.assertEqual(items["Office Manager"]["text"].split("\n")[0], "Office Manager")  # fell back to card text


class QueryRotationTest(unittest.TestCase):
    def test_rotation_covers_pool(self):
        from datetime import date, timedelta
        cfg = {"industries": [f"i{n}" for n in range(10)]}
        seen = set()
        for d in range(3):
            seen |= set(jobscrape.todays_queries(cfg, 4, date(2026, 1, 1) + timedelta(days=d)))
        self.assertEqual(len(seen), 10)

    def test_block_detection(self):
        self.assertTrue(jobscrape._blocked("Just a moment...", 200))
        self.assertTrue(jobscrape._blocked("", 403))
        self.assertIsNone(jobscrape._blocked("Senior Bookkeeper - Acme", 200))
