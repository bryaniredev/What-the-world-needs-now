"""Collectors. Each returns raw items and never raises; errors are reported through
the `status` dict so one unreachable site doesn't stop the run.

Raw item: id, source, channel, kind, url, title, text, created (unix), engagement,
plus optional niche_hint (who is talking, when the source tells us) and implied
(a signal carried by the source itself: "gig", "ask_tool" or "idea_thread").
kind is one of: discussion | gig
"""
import html
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, quote_plus

import requests
from bs4 import BeautifulSoup

UA = "what-the-world-needs-now/2.0 (weekly unmet-needs research)"
TIMEOUT = 30


class Http:
    def __init__(self, delay=1.0):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
        self.delay = delay
        self._last = 0.0

    def get(self, url, delay=None, **kw):
        wait = (self.delay if delay is None else delay) - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        kw.setdefault("timeout", TIMEOUT)
        r = None
        for attempt in range(3):
            self._last = time.time()
            try:
                r = self.s.get(url, **kw)
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code in (422, 429, 502, 503, 504) and attempt < 2:
                time.sleep(float(r.headers.get("retry-after") or 6 * (attempt + 1)))
                continue
            return r
        return r


def _strip_html(s):
    if not s:
        return ""
    return re.sub(r"[ \t]+", " ", BeautifulSoup(html.unescape(s), "html.parser").get_text("\n")).strip()


def _item(source, channel, kind, id_, url, title, text, created, engagement=0, **extra):
    it = {
        "id": f"{source}:{id_}",
        "source": source,
        "channel": channel,
        "kind": kind,
        "url": url,
        "title": html.unescape(title or "").strip()[:300],
        "text": (text or "").strip()[:2500],
        "created": int(created or time.time()),
        "engagement": int(engagement or 0),
    }
    it.update({k: v for k, v in extra.items() if v is not None})
    return it


def _done(status, name, items, errors, note=None):
    if errors and not items:
        status[name] = {"ok": False, "count": 0, "error": "; ".join(errors[:3])[:300]}
    else:
        bits = [b for b in (note, f"{len(errors)} requests failed ({errors[0][:80]})" if errors else None) if b]
        status[name] = {"ok": True, "count": len(items), **({"note": "; ".join(bits)} if bits else {})}
    return items


# ----------------------------------------------------------------------- Reddit
ARCTIC = "https://arctic-shift.photon-reddit.com/api/posts/search"
_REDDIT_SKIP = {"[removed]", "[deleted]", "[ Removed by Reddit ]"}


def _reddit_token(http):
    cid, secret = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        return None
    r = http.s.post("https://www.reddit.com/api/v1/access_token", auth=(cid, secret),
                    data={"grant_type": "client_credentials"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("access_token")


def _reddit_official(sub, since, http, token, max_pages):
    posts, after = [], None
    for _ in range(max_pages):
        r = http.get(f"https://oauth.reddit.com/r/{sub}/new?limit=100&raw_json=1" + (f"&after={after}" if after else ""),
                     headers={"Authorization": f"bearer {token}"})
        r.raise_for_status()
        data = r.json().get("data", {})
        page = [c["data"] for c in data.get("children", [])]
        posts += [p for p in page if p.get("created_utc", 0) >= since]
        after = data.get("after")
        if not after or not page or page[-1].get("created_utc", 0) < since:
            break
    return posts


def _reddit_archive(sub, since, http, max_pages):
    """Arctic Shift, a public archive of Reddit posts. Newest first; page back with `before`."""
    posts, before = [], None
    for _ in range(max_pages):
        url = (f"{ARCTIC}?subreddit={sub}&after={int(since)}&limit=100"
               "&fields=id,title,selftext,created_utc,subreddit,score,num_comments,link_flair_text,author"
               + (f"&before={before}" if before else ""))
        r = http.get(url)
        r.raise_for_status()
        page = r.json().get("data") or []
        posts += page
        if len(page) < 100:
            break
        before = int(min(p["created_utc"] for p in page))
    return posts


def reddit(cfg, since, http, status):
    """Whole week of posts from communities of practitioners; analyze.py keeps the ones stating a need."""
    name = "reddit"
    out, errors, fetched = {}, [], 0
    try:
        token = _reddit_token(http)
    except Exception as e:  # noqa: BLE001
        token, errors = None, [f"login: {e}"]
    max_pages = cfg.get("max_pages_per_community", 5)
    subs = [(s, niche) for niche, lst in cfg.get("communities", {}).items() for s in lst]
    failures = 0
    for sub, niche in subs:
        try:
            posts = _reddit_official(sub, since, http, token, max_pages) if token else _reddit_archive(sub, since, http, max_pages)
        except Exception as e:  # noqa: BLE001
            errors.append(f"r/{sub}: {e}")
            failures += 1
            if failures >= 8 and not out:
                break  # the source is down; stop asking
            continue
        fetched += len(posts)
        for p in posts:
            body = p.get("selftext") or ""
            if body in _REDDIT_SKIP or p.get("author") in ("AutoModerator", "[deleted]") or p.get("stickied"):
                continue
            out[p["id"]] = _item(
                name, f"r/{p.get('subreddit') or sub}", "discussion", p["id"],
                f"https://www.reddit.com/r/{p.get('subreddit') or sub}/comments/{p['id']}/",
                p.get("title"), body, p.get("created_utc"), (p.get("score") or 0) + (p.get("num_comments") or 0),
                niche_hint=None if niche.startswith("_") else niche)
    via = "Reddit API" if token else "Arctic Shift archive"
    return _done(status, name, list(out.values()), errors, f"{fetched} posts read from {len(subs) - failures}/{len(subs)} communities via {via}")


# --------------------------------------------------------------------------- HN
HN = "https://hn.algolia.com/api/v1"
_IDEA_TITLE = re.compile(
    r"\b(?:what|which)\b.*\b(?:problems?|pain|frustrat\w*|annoy\w*|tedious|wish|pay for|missing|should exist|unsolved|broken|struggl\w*|spreadsheets?|manual\w*|underserved)\b"
    r"|\bwish(?:ed)? (?:existed|there was)\b|\bwould you pay\b|\bwhat (?:would|do) you pay for\b|\bstartup ideas?\b|\bboring (?:business|software|problems?)\b"
    r"|\bwhat (?:software|tool|app|saas)s? (?:do you wish|is missing|doesn't exist|should exist)", re.I)


def hackernews(cfg, since, http, status):
    name = "hackernews"
    out, errors = {}, []

    def add(oid, title, text, created, engagement, channel, **extra):
        out[str(oid)] = _item(name, channel, "discussion", oid, f"https://news.ycombinator.com/item?id={oid}",
                              title, _strip_html(text), created, engagement, **extra)

    # 1. Every Ask HN post from the period; the filter decides which state a need.
    try:
        r = http.get(f"{HN}/search_by_date?tags=ask_hn&numericFilters=created_at_i>{int(since)}&hitsPerPage=1000")
        r.raise_for_status()
        for h in r.json().get("hits", []):
            add(h["objectID"], h.get("title"), h.get("story_text") or "", h.get("created_at_i"),
                (h.get("points") or 0) + (h.get("num_comments") or 0), "Ask HN")
    except Exception as e:  # noqa: BLE001
        errors.append(f"ask hn: {e}")

    # 2. Comments that use an unambiguous need phrase.
    for phrase in cfg.get("comment_phrases", []):
        try:
            r = http.get(f"{HN}/search_by_date?query={quote(chr(34) + phrase + chr(34))}&tags=comment"
                         f"&numericFilters=created_at_i>{int(since)}&hitsPerPage=100")
            r.raise_for_status()
            for h in r.json().get("hits", []):
                add(h["objectID"], "", h.get("comment_text") or "", h.get("created_at_i"), h.get("points") or 0,
                    "Hacker News · " + (h.get("story_title") or "comment")[:70])
        except Exception as e:  # noqa: BLE001
            errors.append(f"{phrase}: {e}")

    # 3. "What problem do you wish was solved?" threads: each top-level reply is a stated problem.
    threads = 0
    try:
        back = int(time.time()) - cfg.get("idea_thread_days", 180) * 86400
        r = http.get(f"{HN}/search_by_date?tags=ask_hn&numericFilters=created_at_i>{back},num_comments>{cfg.get('idea_thread_min_comments', 30)}&hitsPerPage=1000")
        r.raise_for_status()
        ideas = [h for h in r.json().get("hits", []) if _IDEA_TITLE.search(h.get("title") or "")]
        ideas.sort(key=lambda h: -(h.get("num_comments") or 0))
        for h in ideas[: cfg.get("idea_threads_max", 8)]:
            t = http.get(f"{HN}/items/{h['objectID']}")
            t.raise_for_status()
            threads += 1
            for c in (t.json().get("children") or [])[:200]:
                text = _strip_html(c.get("text") or "")
                if len(text) >= 120:
                    add(c["id"], "", text, c.get("created_at_i"), len(c.get("children") or []),
                        "Ask HN · " + (h.get("title") or "")[:70], implied="idea_thread")
    except Exception as e:  # noqa: BLE001
        errors.append(f"idea threads: {e}")
    return _done(status, name, list(out.values()), errors, f"{threads} idea threads read")


# ---------------------------------------------------------------- StackExchange
def stackexchange(cfg, since, http, status):
    name = "stackexchange"
    out, errors = {}, []
    key = os.environ.get("STACKEXCHANGE_KEY")
    back = int(time.time()) - cfg.get("lookback_days", 30) * 86400

    def fetch(url, site, label, implied=None):
        try:
            r = http.get(url + (f"&key={key}" if key else ""))
            r.raise_for_status()
            data = r.json()
            for q in data.get("items", []):
                qid = f"{site}-{q['question_id']}"
                out[qid] = _item(name, label, "discussion", qid, q.get("link"), q.get("title", ""), _strip_html(q.get("body", "")),
                                 q.get("creation_date"), (q.get("score") or 0) + (q.get("answer_count") or 0) + (q.get("view_count") or 0) // 50,
                                 implied=implied)
            if data.get("backoff"):
                time.sleep(int(data["backoff"]) + 1)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{site}: {e}")

    # Every question on a request site is someone who looked for software and couldn't find it.
    for site, label in cfg.get("request_sites", {}).items():
        fetch(f"https://api.stackexchange.com/2.3/questions?order=desc&sort=creation&site={site}&fromdate={back}&pagesize=100&filter=withbody",
              site, label, implied="ask_tool")
    for site, label in cfg.get("topic_sites", {}).items():
        fetch(f"https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=creation&title={quote('is there')}&site={site}"
              f"&fromdate={back}&pagesize=50&filter=withbody", site, label)
    return _done(status, name, list(out.values()), errors)


# ------------------------------------------------------------- Discourse forums
def forums(cfg, since, http, status):
    """Any Discourse forum: search recent topics for need phrases, read the opening post."""
    name = "forums"
    iso = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%d")
    out, errors, used = {}, [], []
    for f in cfg.get("sites", []):
        host, label = f["host"], f["name"]
        topics = {}
        for q in f.get("queries", cfg.get("queries", [])):
            try:
                r = http.get(f"https://{host}/search.json", params={"q": f"{q} after:{iso} order:latest"}, delay=2.0)
                r.raise_for_status()
                j = r.json()
                titles = {t["id"]: t for t in (j.get("topics") or [])}
                for p in j.get("posts") or []:
                    if p.get("post_number") == 1 and p.get("topic_id") in titles:
                        topics[p["topic_id"]] = titles[p["topic_id"]]
            except Exception as e:  # noqa: BLE001
                errors.append(f"{host}: {e}")
        got = 0
        for tid, t in list(topics.items())[: cfg.get("topics_per_site", 40)]:
            try:
                r = http.get(f"https://{host}/t/{tid}.json", delay=1.5)
                r.raise_for_status()
                j = r.json()
                first = j["post_stream"]["posts"][0]
                created = datetime.fromisoformat(first["created_at"].replace("Z", "+00:00")).timestamp()
                out[f"{host}-{tid}"] = _item(
                    name, label, "discussion", f"{host}-{tid}", f"https://{host}/t/{t.get('slug', 'topic')}/{tid}",
                    j.get("title") or t.get("title") or t.get("fancy_title"), _strip_html(first.get("cooked", "")), created,
                    (j.get("like_count") or 0) + (j.get("reply_count") or 0) + (j.get("views") or 0) // 25,
                    niche_hint=f.get("niche"))
                got += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"{host}/t/{tid}: {e}")
        if got:
            used.append(f"{label} {got}")
    return _done(status, name, list(out.values()), errors, ", ".join(used) or None)


# -------------------------------------------------------------- Freelance gigs
_GIG_NEED = re.compile(r"automat|spreadsheet|\bexcel\b|google sheets?|manual(?:ly)?\b|data entry|management system|internal tool|workflow|integrat|\bsync|"
                       r"dashboard|\bcrm\b|inventory|booking|scheduling|invoic|tracking system|reporting|copy(?:ing)? (?:and )?past", re.I)
_GIG_BUSINESS = re.compile(r"\b(?:my|our) (?:business|company|shop|store|clinic|practice|firm|agency|team|office|restaurant|warehouse|clients?|customers?|staff|"
                           r"employees|organi[sz]ation|school|church|nonprofit|operations?)\b|\bwe (?:are|run|have|need|currently|use|sell|manage|operate)\b"
                           r"|\bi (?:run|own|manage|operate)\b|\bsmall business\b", re.I)
_GIG_SKIP = re.compile(r"\blogo\b|\bseo\b|article|content writ|translat|video edit|social media (?:post|manag)|lead gen|cold call|backlink|"
                       r"\bnft\b|crypto|trading bot|forex|betting|casino|homework|assignment|thesis|essay|long[- ]term (?:developer|partner)|join our team", re.I)


def freelance(cfg, since, http, status):
    """Businesses paying for one-off custom tools and automation: demand with a budget attached."""
    name = "freelance"
    out, errors = {}, []
    for q in cfg.get("queries", []):
        try:
            r = http.get("https://www.freelancer.com/api/projects/0.1/projects/active/", params={
                "query": q, "limit": cfg.get("per_query", 50), "full_description": "true",
                "from_time": int(since), "languages[]": "en", "sort_field": "time_updated"})
            r.raise_for_status()
            for p in r.json().get("result", {}).get("projects", []):
                desc = (p.get("description") or p.get("preview_description") or "").strip()
                text = f"{p.get('title', '')}\n{desc}"
                if p.get("language") not in (None, "en") or len(desc) < 150:
                    continue
                if _GIG_SKIP.search(text) or not (_GIG_NEED.search(text) and _GIG_BUSINESS.search(text)):
                    continue
                b, cur = p.get("budget") or {}, (p.get("currency") or {}).get("code", "")
                lo, hi = b.get("minimum"), b.get("maximum")
                budget = f"{int(lo):,}–{int(hi):,} {cur}" if lo and hi else (f"{int(lo):,}+ {cur}" if lo else "")
                if p.get("type") == "hourly" and budget:
                    budget += "/hr"
                out[p["id"]] = _item(
                    name, "Freelancer" + (f" · budget {budget}" if budget else ""), "gig", p["id"],
                    f"https://www.freelancer.com/projects/{p.get('seo_url', '')}", p.get("title"), desc,
                    p.get("time_submitted"), (p.get("bid_stats") or {}).get("bid_count") or 0, implied="gig", budget=budget or None)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{q}: {e}")
    return _done(status, name, list(out.values()), errors)


# ---------------------------------------------------------------------- Bluesky
def bluesky(cfg, since, http, status):
    name = "bluesky"
    iso = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, errors = {}, []
    for phrase in cfg.get("phrases", []):
        try:
            r = http.get("https://api.bsky.app/xrpc/app.bsky.feed.searchPosts",
                         params={"q": f'"{phrase}"', "limit": 100, "sort": "latest", "lang": "en", "since": iso})
            r.raise_for_status()
            for p in r.json().get("posts", []):
                text = (p.get("record") or {}).get("text") or ""
                if len(text) < cfg.get("min_length", 90) or p.get("labels"):
                    continue
                handle, rkey = (p.get("author") or {}).get("handle", ""), p["uri"].rsplit("/", 1)[-1]
                created = (p.get("record") or {}).get("createdAt") or p.get("indexedAt")
                ts = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp() if created else time.time()
                out[p["uri"]] = _item(name, "Bluesky", "discussion", f"{handle}-{rkey}", f"https://bsky.app/profile/{handle}/post/{rkey}",
                                      "", text, ts, (p.get("likeCount") or 0) + (p.get("repostCount") or 0) + (p.get("replyCount") or 0))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{phrase}: {e}")
    return _done(status, name, list(out.values()), errors)


ALL = {
    "reddit": reddit,
    "forums": forums,
    "freelance": freelance,
    "hackernews": hackernews,
    "stackexchange": stackexchange,
    "bluesky": bluesky,
}
