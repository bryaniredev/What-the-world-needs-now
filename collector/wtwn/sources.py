"""Collectors. Each returns a list of raw items and never raises; errors are
reported through the `status` dict so one blocked site doesn't kill the run.

Raw item shape:
    id, source, channel, kind, url, title, text, created (unix), engagement, rating
kind is one of: discussion | review | feature_request | job
"""
import html
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, quote_plus

import requests
from bs4 import BeautifulSoup

UA = "what-the-world-needs-now/1.0 (daily pain-point research; +https://github.com)"
TIMEOUT = 25


class Http:
    def __init__(self, delay=1.0):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
        self.delay = delay
        self._last = 0.0

    def get(self, url, **kw):
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        kw.setdefault("timeout", TIMEOUT)
        for attempt in range(3):
            self._last = time.time()
            r = self.s.get(url, **kw)
            if r.status_code in (429, 502, 503, 504) and attempt < 2:
                time.sleep(4 * (attempt + 1))
                continue
            return r
        return r


def _strip_html(s):
    if not s:
        return ""
    return re.sub(r"\s+", " ", BeautifulSoup(html.unescape(s), "html.parser").get_text(" ")).strip()


def _item(source, channel, kind, id_, url, title, text, created, engagement=0, rating=None):
    return {
        "id": f"{source}:{id_}",
        "source": source,
        "channel": channel,
        "kind": kind,
        "url": url,
        "title": (title or "").strip()[:300],
        "text": (text or "").strip()[:2000],
        "created": int(created or time.time()),
        "engagement": int(engagement or 0),
        "rating": rating,
    }


def _ok(status, name, items, note=None):
    status[name] = {"ok": True, "count": len(items), **({"note": note} if note else {})}
    return items


def _fail(status, name, err, items=None):
    items = items or []
    status[name] = {"ok": False, "count": len(items), "error": str(err)[:300]}
    return items


# --------------------------------------------------------------------------- HN
def hackernews(cfg, since, http, status):
    name = "hackernews"
    out, errors = {}, []
    for phrase in cfg.get("phrases", []):
        url = (
            "https://hn.algolia.com/api/v1/search_by_date?query="
            + quote(f'"{phrase}"')
            + f"&tags=(story,comment)&numericFilters=created_at_i>{int(since)}"
            + f"&hitsPerPage={cfg.get('hits_per_phrase', 40)}"
        )
        try:
            r = http.get(url)
            r.raise_for_status()
            for h in r.json().get("hits", []):
                oid = h.get("objectID")
                is_comment = "comment" in (h.get("_tags") or [])
                title = h.get("title") or h.get("story_title") or ""
                text = _strip_html(h.get("comment_text") or h.get("story_text") or "")
                out[oid] = _item(
                    name, "Ask HN" if title.lower().startswith("ask hn") else "Hacker News",
                    "discussion", oid, f"https://news.ycombinator.com/item?id={oid}",
                    title if not is_comment else f"Comment on: {title}", text,
                    h.get("created_at_i"), (h.get("points") or 0) + (h.get("num_comments") or 0),
                )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{phrase}: {e}")
    items = list(out.values())
    if errors and not items:
        return _fail(status, name, "; ".join(errors[:3]))
    return _ok(status, name, items, f"{len(errors)} queries failed" if errors else None)


# ----------------------------------------------------------------------- Reddit
def _reddit_token(http):
    cid, secret = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        return None
    r = http.s.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(cid, secret), data={"grant_type": "client_credentials"}, timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json().get("access_token")


def reddit(cfg, since, http, status):
    name = "reddit"
    out, errors = {}, []
    try:
        token = _reddit_token(http)
    except Exception as e:  # noqa: BLE001
        token, errors = None, [f"oauth: {e}"]
    base = "https://oauth.reddit.com" if token else "https://www.reddit.com"
    headers = {"Authorization": f"bearer {token}"} if token else {}
    subs, queries = cfg.get("subreddits", []), cfg.get("queries", [])
    budget = cfg.get("max_requests", 120)
    # Combine queries with OR to keep request count = number of subreddits.
    q = " OR ".join(queries)
    blocked = 0
    for sub in subs[:budget]:
        url = f"{base}/r/{sub}/search.json?q={quote_plus(q)}&restrict_sr=1&sort=new&t=week&limit=100&raw_json=1"
        try:
            r = http.get(url, headers=headers)
            if r.status_code in (403, 429):
                blocked += 1
                errors.append(f"r/{sub}: HTTP {r.status_code}")
                if blocked >= 3 and not out:
                    break  # we're being blocked; stop hammering
                continue
            r.raise_for_status()
            for c in r.json().get("data", {}).get("children", []):
                d = c.get("data", {})
                if d.get("created_utc", 0) < since:
                    continue
                out[d["id"]] = _item(
                    name, f"r/{sub}", "discussion", d["id"], "https://www.reddit.com" + d.get("permalink", ""),
                    d.get("title"), d.get("selftext"), d.get("created_utc"),
                    (d.get("score") or 0) + (d.get("num_comments") or 0),
                )
        except Exception as e:  # noqa: BLE001
            errors.append(f"r/{sub}: {e}")
    items = list(out.values())
    if not items and errors:
        hint = "" if token else " (set REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET secrets; Reddit often blocks anonymous cloud traffic)"
        return _fail(status, name, "; ".join(errors[:3]) + hint)
    return _ok(status, name, items, f"{len(errors)} subreddits failed" if errors else None)


# ---------------------------------------------------------------- StackExchange
def stackexchange(cfg, since, http, status):
    name = "stackexchange"
    out, errors = {}, []
    key = os.environ.get("STACKEXCHANGE_KEY")
    for site in cfg.get("sites", []):
        for phrase in cfg.get("phrases", []):
            url = (
                "https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=creation"
                f"&title={quote(phrase)}&site={site}&fromdate={int(since) - cfg.get('extra_days', 6) * 86400}&pagesize={cfg.get('pagesize', 50)}"
                "&filter=withbody" + (f"&key={key}" if key else "")
            )
            try:
                r = http.get(url)
                r.raise_for_status()
                data = r.json()
                for q in data.get("items", []):
                    qid = f"{site}-{q['question_id']}"
                    out[qid] = _item(
                        name, site, "discussion", qid, q.get("link"), html.unescape(q.get("title", "")),
                        _strip_html(q.get("body", "")), q.get("creation_date"),
                        (q.get("score") or 0) + (q.get("answer_count") or 0) + (q.get("view_count") or 0) // 50,
                    )
                if data.get("backoff"):
                    time.sleep(int(data["backoff"]) + 1)
                if data.get("quota_remaining", 1) <= 0:
                    break
            except Exception as e:  # noqa: BLE001
                errors.append(f"{site}/{phrase}: {e}")
    items = list(out.values())
    if not items and errors:
        return _fail(status, name, "; ".join(errors[:3]))
    return _ok(status, name, items, f"{len(errors)} queries failed" if errors else None)


# ----------------------------------------------------------------------- GitHub
def github(cfg, since, http, status):
    name = "github"
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    created = (datetime.now(timezone.utc) - timedelta(days=cfg.get("created_within_days", 45))).strftime("%Y-%m-%d")
    out, errors = {}, []
    for q in cfg.get("queries", []):
        full = f"{q} created:>={created} reactions:>={cfg.get('min_reactions', 15)}"
        url = f"https://api.github.com/search/issues?q={quote_plus(full)}&sort=reactions-%2B1&order=desc&per_page=50"
        try:
            r = http.get(url, headers=headers)
            r.raise_for_status()
            for it in r.json().get("items", []):
                repo = it.get("repository_url", "").split("/repos/")[-1]
                reactions = (it.get("reactions") or {}).get("total_count", 0)
                created_ts = datetime.fromisoformat(it["created_at"].replace("Z", "+00:00")).timestamp()
                out[str(it["id"])] = _item(
                    name, repo, "feature_request", it["id"], it.get("html_url"), it.get("title"),
                    (it.get("body") or "")[:2000], created_ts, reactions + (it.get("comments") or 0),
                )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{q}: {e}")
    items = list(out.values())
    if not items and errors:
        return _fail(status, name, "; ".join(errors[:3]))
    return _ok(status, name, items)



# ------------------------------------------------- discovery of popular apps
def _discover_apple(cfg, http, errors):
    """Top-grossing apps per genre: categories where people already pay."""
    found = {}
    country = cfg.get("country", "us")
    for genre, gid in cfg.get("discover_top_grossing_genres", {}).items():
        url = f"https://itunes.apple.com/{country}/rss/topgrossingapplications/limit={cfg.get('discover_per_genre', 15)}/genre={gid}/json"
        try:
            r = http.get(url)
            r.raise_for_status()
            entries = r.json().get("feed", {}).get("entry", [])
            for e in entries if isinstance(entries, list) else [entries]:
                app_id = e.get("id", {}).get("attributes", {}).get("im:id")
                nm = e.get("im:name", {}).get("label")
                if app_id and nm:
                    found[nm] = app_id
        except Exception as ex:  # noqa: BLE001
            errors.append(f"discover {genre}: {ex}")
    return found


_SHOPIFY_RESERVED = {"categories", "collections", "partners", "search", "stories", "login", "sitemap", "browse",
                     "app-groups", "built-for-shopify", "logout", "signup", "pages", "blog", "compare", "apps"}


def _discover_shopify(cfg, http, errors):
    """Most popular apps in each Shopify App Store category, in page order."""
    handles = []
    for cat in cfg.get("discover_categories", []):
        try:
            r = http.get(f"https://apps.shopify.com/categories/{cat}", headers={"Accept": "text/html"})
            r.raise_for_status()
            got = []
            for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
                m = re.match(r"^(?:https://apps\.shopify\.com)?/([a-z0-9][a-z0-9-]+)(?:\?|/?$)", a["href"])
                if m and m.group(1) not in _SHOPIFY_RESERVED and m.group(1) not in got:
                    got.append(m.group(1))
            handles += got[: cfg.get("discover_per_category", 6)]
        except Exception as ex:  # noqa: BLE001
            errors.append(f"discover {cat}: {ex}")
    return handles


def _discover_wordpress(cfg, http, errors):
    n = cfg.get("discover_popular", 0)
    if not n:
        return []
    try:
        r = http.get("https://api.wordpress.org/plugins/info/1.2/?action=query_plugins"
                     f"&request%5Bbrowse%5D=popular&request%5Bper_page%5D={n}&request%5Bfields%5D%5Bdescription%5D=0")
        r.raise_for_status()
        return [p["slug"] for p in r.json().get("plugins", []) if p.get("slug")]
    except Exception as ex:  # noqa: BLE001
        errors.append(f"discover popular: {ex}")
        return []


# -------------------------------------------------------------- Apple App Store
def app_store(cfg, since, http, status):
    name = "app_store"
    out, errors = {}, []
    country, max_rating = cfg.get("country", "us"), cfg.get("max_rating", 2)
    apps = {**_discover_apple(cfg, http, errors), **cfg.get("apps", {})}
    seen = low = recent = empty = 0
    urls = [
        "https://itunes.apple.com/{c}/rss/customerreviews/page=1/id={i}/sortby=mostrecent/json",
        "https://itunes.apple.com/{c}/rss/customerreviews/id={i}/sortBy=mostRecent/json",
    ]
    for app, app_id in apps.items():
        try:
            entries = []
            for u in urls:  # Apple has served the feed under both spellings
                r = http.get(u.format(c=country, i=app_id))
                r.raise_for_status()
                entries = r.json().get("feed", {}).get("entry", [])
                if isinstance(entries, dict):
                    entries = [entries]
                if any("im:rating" in e for e in entries):
                    break
            if not any("im:rating" in e for e in entries):
                empty += 1
            for e in entries:
                if "im:rating" not in e:
                    continue  # first entry can be the app itself
                seen += 1
                rating = int(e["im:rating"]["label"])
                if rating > max_rating:
                    continue
                low += 1
                updated = e.get("updated", {}).get("label")
                ts = datetime.fromisoformat(updated).timestamp() if updated else time.time()
                if ts < since - 6 * 86400:  # app reviews are sparse; allow a week
                    continue
                recent += 1
                rid = e.get("id", {}).get("label")
                out[f"{app_id}-{rid}"] = _item(
                    name, app, "review", f"{app_id}-{rid}", f"https://apps.apple.com/{country}/app/id{app_id}?see-all=reviews",
                    e.get("title", {}).get("label"), e.get("content", {}).get("label"), ts,
                    int(e.get("im:voteCount", {}).get("label", 0) or 0), rating,
                )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{app}: {e}")
    items = list(out.values())
    if not items and errors:
        return _fail(status, name, "; ".join(errors[:3]))
    note = (f"{len(apps)} apps checked, {empty} returned no reviews; {seen} reviews seen, {low} at ≤{max_rating}★, "
            f"{recent} from the last week" + (f"; {len(errors)} errors: {'; '.join(errors[:2])}" if errors else ""))
    return _ok(status, name, items, note)


# ------------------------------------------------------------ Shopify App Store
def _parse_shopify_reviews(handle, html_text, max_rating):
    soup = BeautifulSoup(html_text, "html.parser")
    found = []
    for node in soup.select("[data-merchant-review]") or soup.select("[data-review-content-id]"):
        text_el = node.select_one("[data-truncate-content-copy]") or node.select_one("p")
        text = text_el.get_text(" ", strip=True) if text_el else node.get_text(" ", strip=True)
        rating = None
        star = node.select_one("[aria-label*='out of 5']")
        if star:
            m = re.search(r"(\d)\s*out of 5", star.get("aria-label", ""))
            rating = int(m.group(1)) if m else None
        if rating is not None and rating > max_rating:
            continue
        rid = node.get("data-review-content-id") or node.get("id") or str(abs(hash(text)) % 10**12)
        date_el = node.find(string=re.compile(r"[A-Z][a-z]+ \d{1,2}, \d{4}"))
        ts = time.time()
        if date_el:
            try:
                ts = datetime.strptime(re.search(r"[A-Z][a-z]+ \d{1,2}, \d{4}", date_el).group(0), "%B %d, %Y").replace(
                    tzinfo=timezone.utc).timestamp()
            except Exception:  # noqa: BLE001
                pass
        if len(text) > 30:
            found.append(_item("shopify_apps", handle, "review", f"{handle}-{rid}",
                               f"https://apps.shopify.com/{handle}/reviews",
                               f"{handle}: {rating or 'low'}★ review", text, ts, 0, rating))
    return found


def shopify_apps(cfg, since, http, status):
    name = "shopify_apps"
    out, errors = {}, []
    max_rating = cfg.get("max_rating", 2)
    handles = list(dict.fromkeys(_discover_shopify(cfg, http, errors) + cfg.get("apps", [])))
    ratings = "&".join(f"ratings%5B%5D={i}" for i in range(1, max_rating + 1))
    for handle in handles:
        url = f"https://apps.shopify.com/{handle}/reviews?{ratings}&sort_by=newest"
        try:
            r = http.get(url, headers={"Accept": "text/html"})
            r.raise_for_status()
            for it in _parse_shopify_reviews(handle, r.text, max_rating):
                if it["created"] >= since - 13 * 86400:
                    out[it["id"]] = it
        except Exception as e:  # noqa: BLE001
            errors.append(f"{handle}: {e}")
    items = list(out.values())
    if not items and errors:
        return _fail(status, name, "; ".join(errors[:3]))
    return _ok(status, name, items, f"{len(handles)} apps checked" + (f", {len(errors)} errors" if errors else ""))


# ----------------------------------------------------------- WordPress plugins
def wordpress_plugins(cfg, since, http, status):
    name = "wordpress_plugins"
    out, errors = {}, []
    max_rating = cfg.get("max_rating", 2)
    plugins = list(dict.fromkeys(cfg.get("plugins", []) + _discover_wordpress(cfg, http, errors)))
    for slug in plugins:
        url = f"https://wordpress.org/support/plugin/{slug}/reviews/feed/"
        try:
            r = http.get(url)
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "xml")
            for it in soup.find_all("item"):
                desc = it.find("description").get_text() if it.find("description") else ""
                body = _strip_html(desc)
                m = re.search(r"Rating:\s*(\d)", body)
                if not m or int(m.group(1)) > max_rating:
                    continue
                link = (it.find("link").get_text() or "").strip() if it.find("link") else ""
                if not link and it.find("guid"):
                    link = it.find("guid").get_text().strip()
                pub = it.find("pubDate").get_text() if it.find("pubDate") else None
                try:
                    ts = datetime.strptime(pub.strip(), "%a, %d %b %Y %H:%M:%S %z").timestamp() if pub else time.time()
                except Exception:  # noqa: BLE001
                    ts = time.time()
                if ts < since - 6 * 86400:
                    continue
                title = it.find("title").get_text() if it.find("title") else slug
                out[link or title] = _item(name, slug, "review", link or title, link, title,
                                           re.sub(r"Replies:\s*\d+\s*Rating:\s*\d\s*stars?", "", body), ts, 0, int(m.group(1)))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{slug}: {e}")
    items = list(out.values())
    if not items and errors:
        return _fail(status, name, "; ".join(errors[:3]))
    return _ok(status, name, items, f"{len(errors)} plugins failed" if errors else None)


# ------------------------------------------------------------------------- Jobs
def jobs(cfg, since, http, status):
    """Two uses of job posts (the "Job Search Method"):
    1. posts describing repetitive manual work become pain points (manual_hits >= 2);
    2. every post's listed duties are mined for "<duty> management software" ideas.
    Industry searches (Adzuna, The Muse) cover non-tech jobs; remote boards skew tech.
    """
    name = "jobs"
    signals = [s.lower() for s in cfg.get("manual_work_signals", [])]
    out, errors = {}, []
    recent = since - 6 * 86400

    def add(id_, where, url, title, body, ts, industry=None, require_manual=False):
        hits = sum(1 for sg in signals if sg in (body + " " + (title or "")).lower())
        if require_manual and hits < 2:
            return
        it = _item(name, where, "job", id_, url, title, body, ts, 0)
        it["manual_hits"] = hits
        it["industry"] = industry
        out[it["id"]] = it

    for term in cfg.get("remotive_searches", []):
        try:
            r = http.get(f"https://remotive.com/api/remote-jobs?search={quote_plus(term)}&limit=50")
            r.raise_for_status()
            for j in r.json().get("jobs", []):
                ts = datetime.fromisoformat(j["publication_date"]).replace(tzinfo=timezone.utc).timestamp() \
                    if j.get("publication_date") else time.time()
                if ts >= recent:
                    add(f"remotive-{j['id']}", f"Remotive · {j.get('company_name', '')}", j.get("url"), j.get("title"),
                        _strip_html(j.get("description", "")), ts, j.get("category"), require_manual=True)
        except Exception as e:  # noqa: BLE001
            errors.append(f"remotive/{term}: {e}")

    try:
        r = http.get("https://remoteok.com/api")
        r.raise_for_status()
        for j in r.json():
            if isinstance(j, dict) and "id" in j and float(j.get("epoch") or 0) >= recent:
                add(f"remoteok-{j['id']}", f"RemoteOK · {j.get('company', '')}", j.get("url"), j.get("position"),
                    _strip_html(j.get("description", "")), float(j["epoch"]), None, require_manual=True)
    except Exception as e:  # noqa: BLE001
        errors.append(f"remoteok: {e}")

    # The Muse: free, full job descriptions, browsable by job category.
    for cat in cfg.get("themuse_categories", []):
        try:
            r = http.get(f"https://www.themuse.com/api/public/jobs?page=0&descending=true&category={quote_plus(cat)}")
            r.raise_for_status()
            for j in r.json().get("results", []):
                ts = datetime.fromisoformat(j["publication_date"].replace("Z", "+00:00")).timestamp() \
                    if j.get("publication_date") else time.time()
                if ts >= recent:
                    add(f"muse-{j['id']}", f"The Muse · {(j.get('company') or {}).get('name', '')}",
                        (j.get("refs") or {}).get("landing_page"), j.get("name"), _strip_html(j.get("contents", "")), ts, cat)
        except Exception as e:  # noqa: BLE001
            errors.append(f"themuse/{cat}: {e}")

    # Adzuna: any industry ("car dealership", "dental office"...). Needs a free key.
    aid, akey = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if aid and akey:
        for ind in cfg.get("industries", []):
            try:
                r = http.get(f"https://api.adzuna.com/v1/api/jobs/{cfg.get('adzuna_country', 'us')}/search/1"
                             f"?app_id={aid}&app_key={akey}&what={quote_plus(ind)}&results_per_page=30&max_days_old=3")
                r.raise_for_status()
                for j in r.json().get("results", []):
                    ts = datetime.fromisoformat(j["created"].replace("Z", "+00:00")).timestamp() if j.get("created") else time.time()
                    add(f"adzuna-{j['id']}", f"Adzuna · {(j.get('company') or {}).get('display_name', '')}",
                        j.get("redirect_url"), j.get("title"), _strip_html(j.get("description", "")), ts, ind)
            except Exception as e:  # noqa: BLE001
                errors.append(f"adzuna/{ind}: {e}")

    items = list(out.values())
    if not items and errors:
        return _fail(status, name, "; ".join(errors[:3]))
    note = None if (aid and akey) else "add ADZUNA_APP_ID/ADZUNA_APP_KEY for industry job searches"
    if errors:
        note = f"{len(errors)} queries failed" + (f"; {note}" if note else "")
    return _ok(status, name, items, note)


# ------------------------------------------------------------- Job boards
def job_boards(cfg, since, http, status):
    """Reads what jobscrape.py (headless Playwright) gathered earlier in the same run."""
    name = "job_boards"
    path = os.environ.get("JOBS_SCRAPE_FILE")
    if not path or not os.path.exists(path):
        return _ok(status, name, [], "browser scrape didn't run (see the 'Scrape job boards' step)")
    data = json.loads(open(path, encoding="utf-8").read())
    for site, st in data.get("sites", {}).items():
        status[f"{name}:{site}"] = {k: v for k, v in st.items() if k in ("ok", "count", "error", "note", "seconds")}
    items = data.get("items", [])
    good = [st.get("label", k) for k, st in data.get("sites", {}).items() if st.get("count")]
    return _ok(status, name, items, f"searches: {', '.join(data.get('queries', []))}; results from: {', '.join(good) or 'none'}")


ALL = {
    "hackernews": hackernews,
    "reddit": reddit,
    "stackexchange": stackexchange,
    "github": github,
    "app_store": app_store,
    "shopify_apps": shopify_apps,
    "wordpress_plugins": wordpress_plugins,
    "jobs": jobs,
    "job_boards": job_boards,
}
