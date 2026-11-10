"""Daily job-board scrape with headless Playwright (the "Job Search Method" at scale).

For a rotating handful of industry searches it opens each enabled job board, reads
the result cards, then opens the top few postings to get the full description, whose
listed duties become "<duty> management software" ideas downstream.

Ground rules: low volume, a pause between page loads, an honest headless browser, and
no attempt to get around bot protection. If a site shows a CAPTCHA, a login wall or a
block page, that site is marked "blocked" for the day and skipped.

    python -m wtwn.jobscrape --out jobs.json            # daily run
    python -m wtwn.jobscrape --out jobs.json --test     # 1 search per site, verbose
"""
import argparse
import asyncio
import json
import os
import random
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote, quote_plus, urlsplit, urlunsplit

import requests

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "collector" / "config.json"

# Per-site recipe: where to search, which links are postings, where the description lives.
SITES = {
    "linkedin": {
        "label": "LinkedIn",
        "search": "https://www.linkedin.com/jobs/search?keywords={q}&location=United%20States&f_TPR=r86400",
        "link": r"linkedin\.com/jobs/view/",
        "strip_query": True,
        "delay": [10, 16],  # LinkedIn rate-limits quickly (HTTP 429)
        "desc": [".show-more-less-html__markup", ".description__text", "[class*=description]"],
    },
    "indeed": {
        "label": "Indeed",
        "search": "https://www.indeed.com/jobs?q={q}&l=United+States&fromage=1",
        "link": r"[?&]jk=[0-9a-f]+|/viewjob",
        "detail": "https://www.indeed.com/viewjob?jk={jk}",
        "desc": ["#jobDescriptionText", "[class*=jobDescription]"],
    },
    "ziprecruiter": {
        "label": "ZipRecruiter",
        "search": "https://www.ziprecruiter.com/jobs-search?search={q}&location=United+States&days=1",
        "link": r"ziprecruiter\.com/(?:c/[^/]+/Job/|jobs/|k/|ek/l/)",
        "desc": [".job_description", "[class*=job_description]", "[class*=jobDescription]", "[data-testid*=description]"],
    },
    "glassdoor": {
        "label": "Glassdoor",
        "search": "https://www.glassdoor.com/Job/jobs.htm?sc.keyword={q}&fromAge=1",
        "link": r"glassdoor\.com/(?:job-listing/|partner/jobListing)",
        "desc": ["[class*=JobDetails_jobDescription]", "#JobDescriptionContainer", "[class*=jobDescription]"],
    },
    "monster": {
        "label": "Monster",
        "search": "https://www.monster.com/jobs/search?q={q}&where=United+States&page=1",
        "link": r"monster\.com/job-openings/",
        "desc": ["[data-testid=svx-description-container-inner]", "#JobDescription", "[class*=description]"],
    },
    "dice": {
        "label": "Dice",
        "search": "https://www.dice.com/jobs?q={q}&location=United%20States&filters.postedDate=ONE",
        "link": r"dice\.com/job-detail/",
        "strip_query": True,
        "desc": ["[data-testid=jobDescriptionHtml]", "#jobDescription", "[class*=jobDescription]"],
    },
    "usajobs": {
        "label": "USAJOBS",
        "search": "https://www.usajobs.gov/search/results/?k={q}&p=1",
        "link": r"usajobs\.gov/job/\d+",
        "strip_query": True,
        "desc": ["#duties", "#summary", ".usajobs-joa-section"],
    },
    "google": {
        "label": "Google Jobs",
        "search": "https://www.google.com/search?q={q}+jobs&ibp=htl;jobs&hl=en&gl=us",
        "link": None,  # Google's job panel has no per-job links; cards are read in place
        "desc": [],
    },
}

BLOCK_MARKERS = [
    "captcha", "verify you are human", "are you a robot", "unusual traffic", "access denied",
    "just a moment", "pardon our interruption", "request blocked", "security check",
    "help us protect glassdoor", "please verify", "enable javascript and cookies", "sign in to view",
    "authwall", "bot detection",
]

CARD_JS = r"""
(linkRe) => {
  const re = new RegExp(linkRe);
  const keyOf = (h) => { const m = h.match(/[?&]jk=([0-9a-f]+)/); return m ? 'jk:' + m[1] : h.split('#')[0].split('?')[0]; };
  const isJob = (a) => re.test(a.href);
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    if (!isJob(a)) continue;
    const key = keyOf(a.href);
    if (seen.has(key)) continue;
    // The card is the largest ancestor that links to this job and no other.
    let card = a;
    while (card.parentElement && card.parentElement !== document.body) {
      const others = Array.from(card.parentElement.querySelectorAll('a[href]')).some((b) => isJob(b) && keyOf(b.href) !== key);
      if (others) break;
      card = card.parentElement;
    }
    const links = Array.from(card.querySelectorAll('a[href]')).filter((b) => isJob(b) && keyOf(b.href) === key);
    let title = '';
    for (const l of links) {
      const t = (l.innerText || '').trim().split('\n')[0].trim();
      if (t.length >= 3 && t.length <= 160) { title = t; break; }
    }
    if (!title) title = (a.getAttribute('aria-label') || a.title || '').trim();
    title = title.replace(/^View Details for\s+/i, '').replace(/\s*\([0-9a-f]{16,}\)\s*$/i, '').trim();
    if (!title || title.length < 3 || title.length > 160) continue;
    seen.add(key);
    const jk = a.dataset.jk || (a.href.match(/[?&]jk=([0-9a-f]+)/) || [])[1] || null;
    out.push({ href: a.href.split('#')[0], title, card: (card.innerText || '').slice(0, 800), jk });
  }
  return out;
}
"""

GOOGLE_CARDS_JS = r"""
() => Array.from(document.querySelectorAll('[role="treeitem"], li[data-ved]'))
  .map(e => (e.innerText || '').trim()).filter(t => t.split('\n').length >= 2 && t.length < 800).slice(0, 30)
"""

MAIN_TEXT_JS = r"""
() => {
  const m = document.querySelector('main, [role=main], article');
  return ((m && m.innerText) || document.body.innerText || '').slice(0, 8000);
}
"""


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _strip(url, strip_query):
    if not strip_query:
        return url
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def _blocked(text, status):
    if status in (401, 403, 407, 429, 451, 503):
        return f"HTTP {status}"
    t = (text or "").lower()[:4000]
    for m in BLOCK_MARKERS:
        if m in t:
            return f"page says “{m}”"
    return None


_NOISE = re.compile(r"^(?:new|easy apply|apply now|save|saved|promoted|actively hiring|\d+\s*(?:hours?|days?|minutes?) ago|just posted|today|view details.*)$", re.I)


def _card_fields(card, title):
    lines = [l.strip() for l in card.split("\n")
             if l.strip() and l.strip().lower() != title.lower() and not _NOISE.match(l.strip()) and title.lower() not in l.lower()]
    return (lines[0] if lines else ""), (lines[1] if len(lines) > 1 else "")


def todays_queries(cfg, n, day=None):
    pool = list(dict.fromkeys(cfg.get("industries", []) + cfg.get("remotive_searches", [])))
    if not pool:
        return []
    start = ((day or date.today()).toordinal() * n) % len(pool)
    return [pool[(start + i) % len(pool)] for i in range(min(n, len(pool)))]


def manual_hits(text, signals):
    t = text.lower()
    return sum(1 for s in signals if s in t)


def job_item(site, label, id_, url, title, company, location, text, industry, signals):
    return {
        "id": f"job_boards:{site}-{id_}",
        "source": "job_boards",
        "channel": f"{label} · {company}" if company else label,
        "kind": "job",
        "url": url,
        "title": (title or "").strip()[:300],
        "text": (text or "").strip()[:6000],
        "created": int(time.time()),
        "engagement": 0,
        "rating": None,
        "industry": industry,
        "location": location,
        "manual_hits": manual_hits(f"{title} {text}", signals),
    }


class Scraper:
    def __init__(self, bcfg, signals, verbose=False):
        self.cfg, self.signals, self.verbose = bcfg, signals, verbose
        self.deadline = time.time() + bcfg.get("max_minutes", 25) * 60

    async def pause(self, recipe=None):
        lo, hi = (recipe or {}).get("delay") or self.cfg.get("delay_seconds", [3, 6])
        await asyncio.sleep(random.uniform(lo, hi))

    async def goto(self, page, url):
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=35000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001  (busy pages never go idle; that's fine)
            pass
        return resp.status if resp else None

    async def description(self, page, recipe):
        for sel in recipe["desc"]:
            el = await page.query_selector(sel)
            if el:
                t = (await el.inner_text()).strip()
                if len(t) > 150:
                    return t
        return (await page.evaluate(MAIN_TEXT_JS)).strip()

    async def site(self, browser, key, queries):
        recipe = SITES[key]
        label = recipe["label"]
        st = {"ok": True, "count": 0, "searches": 0, "label": label}
        items = []
        details_blocked = False
        ctx = await browser.new_context(locale="en-US", viewport={"width": 1366, "height": 900})
        page = await ctx.new_page()
        try:
            for q in queries:
                if time.time() > self.deadline:
                    st["note"] = "stopped early: time budget used"
                    break
                url = recipe["search"].format(q=quote_plus(q))
                status = await self.goto(page, url)
                st["searches"] += 1
                body = await page.evaluate("() => document.title + '\\n' + (document.body ? document.body.innerText : '')")
                why = _blocked(body, status)
                if why:
                    st.update(ok=False, blocked=True, error=f"blocked on search: {why}")
                    if self.verbose:
                        log(f"  [{key}] BLOCKED ({why}) title={await page.title()!r} text={body[:200]!r}")
                    break
                if recipe["link"] is None:  # Google Jobs: read cards in place
                    cards = await page.evaluate(GOOGLE_CARDS_JS)
                    for i, c in enumerate(cards[: self.cfg.get("results_per_search", 15)]):
                        lines = c.split("\n")
                        items.append(job_item(key, label, f"{abs(hash(c)) % 10**12}", url, lines[0],
                                              lines[1] if len(lines) > 1 else "", lines[2] if len(lines) > 2 else "",
                                              c, q, self.signals))
                    if self.verbose:
                        log(f"  [{key}] {q!r}: {len(cards)} cards; first: {[c.split(chr(10))[0] for c in cards[:3]]}")
                    await self.pause(recipe)
                    continue

                cards = (await page.evaluate(CARD_JS, recipe["link"]))[: self.cfg.get("results_per_search", 15)]
                if self.verbose:
                    log(f"  [{key}] {q!r}: HTTP {status}, {len(cards)} cards; first: {[c['title'] for c in cards[:3]]}")
                    if not cards:
                        log(f"  [{key}] page title={await page.title()!r} text={body[:300]!r}")
                for i, c in enumerate(cards):
                    company, location = _card_fields(c["card"], c["title"])
                    detail = recipe.get("detail", "").format(jk=c["jk"]) if recipe.get("detail") and c["jk"] else c["href"]
                    detail = _strip(detail, recipe.get("strip_query"))
                    text = c["card"]
                    if i < self.cfg.get("details_per_search", 5) and time.time() < self.deadline and not details_blocked:
                        await self.pause(recipe)
                        try:
                            dstatus = await self.goto(page, detail)
                            dbody = await page.evaluate("() => document.title + '\\n' + (document.body ? document.body.innerText : '')")
                            why = _blocked(dbody, dstatus)
                            if why:  # back off: no more description pages from this site today
                                details_blocked = True
                                st["note"] = f"descriptions blocked after {i} ({why}); using card text for the rest"
                                if self.verbose:
                                    log(f"  [{key}] detail blocked ({why}) {detail}")
                            else:
                                text = await self.description(page, recipe)
                                if self.verbose and i == 0:
                                    log(f"  [{key}] detail ok: {len(text)} chars: {text[:160]!r}")
                        except Exception as e:  # noqa: BLE001
                            if self.verbose:
                                log(f"  [{key}] detail error {detail}: {e}")
                    jid = c["jk"] or re.sub(r"\W+", "-", urlsplit(detail).path.strip("/"))[-80:]
                    items.append(job_item(key, label, jid, detail, c["title"], company, location, text, q, self.signals))
                await self.pause(recipe)
        except Exception as e:  # noqa: BLE001
            st.update(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}")
        finally:
            await ctx.close()
        st["count"] = len(items)
        return items, st


def usajobs_api(queries, signals, cfg):
    """Official USAJOBS API (free key). Its MajorDuties field is ideal for duty mining."""
    key, email = os.environ.get("USAJOBS_API_KEY"), os.environ.get("USAJOBS_EMAIL")
    if not (key and email):
        return None, None
    items, errors = [], []
    for q in queries:
        try:
            r = requests.get(
                f"https://data.usajobs.gov/api/search?Keyword={quote(q)}&DatePosted=3&ResultsPerPage=25",
                headers={"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key}, timeout=30)
            r.raise_for_status()
            for m in r.json().get("SearchResult", {}).get("SearchResultItems", []):
                d = m.get("MatchedObjectDescriptor", {})
                det = (d.get("UserArea") or {}).get("Details") or {}
                duties = det.get("MajorDuties") or []
                text = "\n".join(duties if isinstance(duties, list) else [str(duties)]) + "\n" + (det.get("JobSummary") or "")
                loc = (d.get("PositionLocationDisplay") or "")
                items.append(job_item("usajobs", "USAJOBS", d.get("PositionID") or m.get("MatchedObjectId"),
                                      d.get("PositionURI"), d.get("PositionTitle"), d.get("OrganizationName"), loc,
                                      text, q, signals))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{q}: {e}")
    st = {"ok": bool(items) or not errors, "count": len(items), "searches": len(queries), "label": "USAJOBS (API)"}
    if errors:
        st["error" if not items else "note"] = "; ".join(errors[:2])
    return items, st


def serpapi_google(queries, signals, cfg):
    """Google Jobs through SerpApi (paid service with a free tier). Google blocks automated browsers."""
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        return None, None
    items, errors = [], []
    for q in queries[: cfg.get("serpapi_searches_per_day", 3)]:
        try:
            r = requests.get("https://serpapi.com/search.json", params={
                "engine": "google_jobs", "q": q, "hl": "en", "gl": "us", "api_key": key}, timeout=40)
            r.raise_for_status()
            for j in r.json().get("jobs_results", []):
                items.append(job_item("google", "Google Jobs", j.get("job_id", "")[:60] or abs(hash(j.get("title"))),
                                      (j.get("share_link") or j.get("apply_options", [{}])[0].get("link")),
                                      j.get("title"), j.get("company_name"), j.get("location"),
                                      j.get("description", ""), q, signals))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{q}: {e}")
    st = {"ok": bool(items) or not errors, "count": len(items), "searches": len(queries), "label": "Google Jobs (SerpApi)"}
    if errors:
        st["error" if not items else "note"] = "; ".join(errors[:2])
    return items, st


async def run(cfg, test=False, only=None, verbose=False):
    bcfg = dict(cfg.get("job_boards", {}))
    jcfg = cfg.get("jobs", {})
    signals = [s.lower() for s in jcfg.get("manual_work_signals", [])]
    if test:
        bcfg.update(queries_per_day=1, results_per_search=8, details_per_search=2, max_minutes=12)
    queries = todays_queries(jcfg, bcfg.get("queries_per_day", 4))
    enabled = [k for k, on in bcfg.get("sites", {}).items() if on and k in SITES and (not only or k in only)]
    log(f"[job_boards] searches today: {queries}; sites: {enabled}")

    items, sites = [], {}
    # Official APIs first; they replace the browser for that site when configured.
    for key, fn in (("usajobs", usajobs_api), ("google", serpapi_google)):
        if key in enabled:
            got, st = fn(queries, signals, bcfg)
            if st is not None:
                items += got
                sites[key] = st
                enabled.remove(key)
                log(f"[job_boards:{key}] {st}")

    if enabled:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            launch = {"headless": True}
            if os.environ.get("PW_CHROMIUM_PATH"):
                launch["executable_path"] = os.environ["PW_CHROMIUM_PATH"]
            browser = await p.chromium.launch(**launch)
            scraper = Scraper(bcfg, signals, verbose)
            for key in enabled:
                t0 = time.time()
                got, st = await scraper.site(browser, key, queries)
                st["seconds"] = round(time.time() - t0, 1)
                items += got
                sites[key] = st
                log(f"[job_boards:{key}] {st}")
            await browser.close()
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "queries": queries, "sites": sites, "items": items}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--test", action="store_true", help="1 search per site, extra logging")
    ap.add_argument("--only", nargs="*", help="limit to these site keys")
    ap.add_argument("--config", default=str(CONFIG))
    args = ap.parse_args(argv)
    cfg = json.loads(Path(args.config).read_text())
    result = asyncio.run(run(cfg, test=args.test, only=args.only, verbose=args.test))
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False))
    ok = [k for k, s in result["sites"].items() if s.get("count")]
    log(f"[job_boards] {len(result['items'])} postings; sites with results: {ok}")
    if args.test:
        for it in result["items"][:40]:
            if it.get("manual_hits") is not None:
                log(f"   - {it['channel']}: {it['title']} ({len(it['text'])} chars)")


if __name__ == "__main__":
    main()
