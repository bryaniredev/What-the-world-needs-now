"""Temporary: settle Arctic Shift parameters and Discourse search form."""
import time
from datetime import datetime, timedelta, timezone
import requests
UA = {"User-Agent": "what-the-world-needs-now/2.0 (weekly unmet-needs research)"}
week = datetime.now(timezone.utc) - timedelta(days=7)
ep, iso = int(week.timestamp()), week.strftime("%Y-%m-%d")
B = "https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=Dentistry"
for name, q in [
    ("plain", f"&after={iso}&limit=100"),
    ("sort", f"&after={iso}&limit=100&sort=desc"),
    ("fields basic", f"&after={iso}&limit=100&fields=id,title,selftext,created_utc,subreddit,score,num_comments,author"),
    ("fields +flair", f"&after={iso}&limit=100&fields=id,title,selftext,created_utc,subreddit,score,num_comments,link_flair_text"),
    ("fields +permalink", f"&after={iso}&limit=100&fields=id,title,permalink"),
    ("epoch after", f"&after={ep}&limit=10&fields=id,title,created_utc"),
]:
    r = requests.get(B + q, headers=UA, timeout=30)
    try:
        d = r.json().get("data")
    except Exception:
        d = None
    n = len(d) if isinstance(d, list) else None
    info = ""
    if n:
        ts = [x.get("created_utc") for x in d]
        info = f"first={datetime.fromtimestamp(ts[0], timezone.utc):%m-%d %H:%M} last={datetime.fromtimestamp(ts[-1], timezone.utc):%m-%d %H:%M} keys={sorted(d[0].keys())[:14]} scores={[x.get('score') for x in d[:8]]} ncom={[x.get('num_comments') for x in d[:8]]}"
    print(f"arctic {name:18} HTTP {r.status_code} n={n} rl={r.headers.get('x-ratelimit-remaining')} {info} {'' if r.ok else r.text[:200]}")
    time.sleep(1.5)
# paging forward with after=last created_utc (default sort appears ascending?)
r = requests.get(B + f"&after={iso}&limit=100&fields=id,created_utc", headers=UA, timeout=30); d = r.json()["data"]
if d:
    nxt = max(x["created_utc"] for x in d)
    r2 = requests.get(B + f"&after={nxt}&limit=100&fields=id,created_utc", headers=UA, timeout=30)
    print("arctic page2 via after=max:", r2.status_code, len(r2.json().get("data") or []), "overlap", len({x['id'] for x in d} & {x['id'] for x in (r2.json().get('data') or [])}))
big = requests.get(f"https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=smallbusiness&after={iso}&limit=100&fields=id,created_utc,selftext,title", headers=UA, timeout=30)
bd = big.json().get("data") or []
print("smallbusiness:", big.status_code, len(bd), "removed/empty selftext:", sum(1 for x in bd if x.get("selftext") in ("[removed]", "[deleted]", "", None)), "span hours:", round((max(x['created_utc'] for x in bd) - min(x['created_utc'] for x in bd))/3600, 1) if bd else None)

for host, q in [("community.shopify.com", "is there an app that"), ("community.shopify.com", "looking for an app"), ("community.spiceworks.com", "looking for software"), ("talk.macpowerusers.com", "is there an app"), ("community.make.com", "is there a way to automate")]:
    r = requests.get(f"https://{host}/search.json", params={"q": f"{q} after:{iso} order:latest"}, headers=UA, timeout=30)
    j = r.json() if r.ok else {}
    posts, topics = j.get("posts") or [], j.get("topics") or []
    firsts = [p for p in posts if p.get("post_number") == 1]
    print(f"discourse {host} [{q}] HTTP {r.status_code} posts={len(posts)} first-posts={len(firsts)} topics={len(topics)} post keys={sorted(posts[0].keys()) if posts else None} topic keys={sorted(topics[0].keys())[:20] if topics else None} more={j.get('grouped_search_result',{}).get('more_full_page_results')}")
    if firsts:
        t = requests.get(f"https://{host}/t/{firsts[0]['topic_id']}.json", headers=UA, timeout=30)
        print("   topic fetch", t.status_code, "cooked", len(t.json()["post_stream"]["posts"][0].get("cooked", "")) if t.ok else t.text[:100], "views", t.json().get("views") if t.ok else None, "like", t.json().get("like_count") if t.ok else None)
    time.sleep(2)
r = requests.get(f"https://hn.algolia.com/api/v1/search_by_date?tags=ask_hn&numericFilters=created_at_i%3E{ep}&hitsPerPage=1000", headers=UA, timeout=30)
print("hn ask_hn this week:", r.status_code, len(r.json().get("hits", [])), "nbHits", r.json().get("nbHits"))
r = requests.get(f"https://hn.algolia.com/api/v1/search_by_date?tags=ask_hn&numericFilters=created_at_i%3E{ep-86400*200},num_comments%3E30&hitsPerPage=1000", headers=UA, timeout=30)
print("hn ask_hn 200d >30 comments:", r.status_code, len(r.json().get("hits", [])), "nbHits", r.json().get("nbHits"))
r = requests.get("https://www.reddit.com/r/Dentistry/new/.rss?limit=100", headers=UA, timeout=30)
print("reddit rss:", r.status_code, r.text.count("<entry>"), {k: v for k, v in r.headers.items() if "ratelimit" in k.lower()})
