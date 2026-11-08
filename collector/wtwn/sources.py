"""Collectors. Each returns a list of raw items and never raises; errors are
reported through the `status` dict so one blocked site doesn't kill the run.

Raw item shape:
    id, source, channel, kind, url, title, text, created (unix), engagement, rating
kind is one of: discussion | review | feature_request | job
"""
import html
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
                f"&title={quote(phrase)}&site={site}&fromdate={int(since)}&pagesize={cfg.get('pagesize', 50)}"
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


# -------------------------------------------------------------- Apple App Store
def app_store(cfg, since, http, status):
    name = "app_store"
    out, errors = {}, []
    country, max_rating = cfg.get("country", "us"), cfg.get("max_rating", 2)
    for app, app_id in cfg.get("apps", {}).items():
        url = f"https://itunes.apple.com/{country}/rss/customerreviews/page=1/id={app_id}/sortby=mostrecent/json"
        try:
            r = http.get(url)
            r.raise_for_status()
            entries = r.json().get("feed", {}).get("entry", [])
            if isinstance(entries, dict):
                entries = [entries]
            for e in entries:
                if "im:rating" not in e:
                    continue  # first entry can be the app itself
                rating = int(e["im:rating"]["label"])
                if rating > max_rating:
                    continue
                updated = e.get("updated", {}).get("label")
                ts = datetime.fromisoformat(updated).timestamp() if updated else time.time()
                if ts < since - 6 * 86400:  # app reviews are sparse; allow a week
                    continue
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
    return _ok(status, name, items, f"{len(errors)} apps failed" if errors else None)


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
                               f"https://apps.shopify.com/{handle}/reviews?ratings%5B%5D=1&ratings%5B%5D=2",
                               f"{handle}: {rating or '≤2'}★ review", text, ts, 0, rating))
    return found


def shopify_apps(cfg, since, http, status):
    name = "shopify_apps"
    out, errors = {}, []
    max_rating = cfg.get("max_rating", 2)
    for handle in cfg.get("apps", []):
        url = f"https://apps.shopify.com/{handle}/reviews?ratings%5B%5D=1&ratings%5B%5D=2&sort_by=newest"
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
    return _ok(status, name, items, f"{len(errors)} apps failed" if errors else None)


# ----------------------------------------------------------- WordPress plugins
def wordpress_plugins(cfg, since, http, status):
    name = "wordpress_plugins"
    out, errors = {}, []
    max_rating = cfg.get("max_rating", 2)
    for slug in cfg.get("plugins", []):
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
    """Job posts describing repetitive manual work = something people pay to have done."""
    name = "jobs"
    signals = [s.lower() for s in cfg.get("manual_work_signals", [])]
    out, errors = {}, []

    def keep(text):
        t = text.lower()
        hits = [s for s in signals if s in t]
        return hits if len(hits) >= 2 else None

    for term in cfg.get("remotive_searches", []):
        try:
            r = http.get(f"https://remotive.com/api/remote-jobs?search={quote_plus(term)}&limit=50")
            r.raise_for_status()
            for j in r.json().get("jobs", []):
                ts = datetime.fromisoformat(j["publication_date"]).replace(tzinfo=timezone.utc).timestamp() \
                    if j.get("publication_date") else time.time()
                if ts < since - 6 * 86400:
                    continue
                body = _strip_html(j.get("description", ""))
                if keep(body + " " + j.get("title", "")):
                    out[f"remotive-{j['id']}"] = _item(
                        name, f"Remotive · {j.get('company_name', '')}", "job", f"remotive-{j['id']}", j.get("url"),
                        j.get("title"), body, ts, 0)
        except Exception as e:  # noqa: BLE001
            errors.append(f"remotive/{term}: {e}")

    try:
        r = http.get("https://remoteok.com/api")
        r.raise_for_status()
        for j in r.json():
            if not isinstance(j, dict) or "id" not in j:
                continue
            ts = float(j.get("epoch") or time.time())
            if ts < since - 6 * 86400:
                continue
            body = _strip_html(j.get("description", ""))
            if keep(body + " " + j.get("position", "")):
                out[f"remoteok-{j['id']}"] = _item(
                    name, f"RemoteOK · {j.get('company', '')}", "job", f"remoteok-{j['id']}", j.get("url"),
                    j.get("position"), body, ts, 0)
    except Exception as e:  # noqa: BLE001
        errors.append(f"remoteok: {e}")

    items = list(out.values())
    if not items and errors:
        return _fail(status, name, "; ".join(errors[:3]))
    return _ok(status, name, items, f"{len(errors)} queries failed" if errors else None)


ALL = {
    "hackernews": hackernews,
    "reddit": reddit,
    "stackexchange": stackexchange,
    "github": github,
    "app_store": app_store,
    "shopify_apps": shopify_apps,
    "wordpress_plugins": wordpress_plugins,
    "jobs": jobs,
}
