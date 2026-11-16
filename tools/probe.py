"""Temporary: confirm how to read replies and past weeks from the archive (prints shapes only)."""
import time
from datetime import datetime, timedelta, timezone
import requests
UA = {"User-Agent": "what-the-world-needs-now/2.0 (weekly unmet-needs research)"}
A = "https://arctic-shift.photon-reddit.com/api"
now = datetime.now(timezone.utc)
def get(name, url):
    t = time.time()
    try:
        r = requests.get(url, headers=UA, timeout=40)
        j = r.json() if "json" in r.headers.get("content-type", "") else {}
        d = j.get("data")
        n = len(d) if isinstance(d, list) else None
        print(f"{name:28} HTTP {r.status_code} {time.time()-t:.1f}s n={n} err={j.get('error')} rl={ {k:v for k,v in r.headers.items() if 'ratelimit' in k.lower()} }")
        return d if isinstance(d, list) else j
    except Exception as e:
        print(f"{name:28} ERR {type(e).__name__} {e}")
        return []
week = int((now - timedelta(days=5)).timestamp())
posts = get("posts", f"{A}/posts/search?subreddit=smallbusiness&after={week}&limit=100&fields=id,title,num_comments,author,created_utc")
busy = sorted([p for p in posts if (p.get("num_comments") or 0) >= 8], key=lambda p: -p["num_comments"])[:2]
for p in busy:
    pid = p["id"]
    print("post", pid, "num_comments", p["num_comments"], "author set:", bool(p.get("author")))
    for name, url in [
        ("comments link_id bare", f"{A}/comments/search?link_id={pid}&limit=100"),
        ("comments link_id t3_", f"{A}/comments/search?link_id=t3_{pid}&limit=100"),
        ("comments fields", f"{A}/comments/search?link_id={pid}&limit=100&fields=id,author,body,score,parent_id,created_utc"),
        ("comments tree", f"{A}/comments/tree?link_id={pid}&limit=100"),
    ]:
        d = get(name, url); time.sleep(1.2)
        if isinstance(d, list) and d:
            x = d[0]
            x = x.get("data", x) if isinstance(x, dict) else x
            print("     keys:", sorted(x.keys())[:30] if isinstance(x, dict) else type(x), "| top-level:", sum(1 for c in d if str((c.get('data', c)).get('parent_id', '')).startswith('t3_')), "| is OP:", sum(1 for c in d if (c.get('data', c)).get('author') == p.get('author')), "| body len:", len((x.get('body') or '')) if isinstance(x, dict) else None)
    break
# history: how far back, and how fast
for wk in (4, 13, 26):
    a = int((now - timedelta(days=7 * wk + 7)).timestamp()); b = int((now - timedelta(days=7 * wk)).timestamp())
    d = get(f"posts {wk} weeks ago", f"{A}/posts/search?subreddit=Bookkeeping&after={a}&before={b}&limit=100&fields=id,title,selftext,created_utc,score,num_comments,author")
    if isinstance(d, list) and d:
        print("     span:", datetime.fromtimestamp(min(x['created_utc'] for x in d), timezone.utc).date(), "to", datetime.fromtimestamp(max(x['created_utc'] for x in d), timezone.utc).date(), "| removed:", sum(1 for x in d if x.get('selftext') in ('[removed]', '[deleted]')), "| scores:", [x.get('score') for x in d[:6]])
    time.sleep(1.2)
# 10 back-to-back requests: is 0.5s spacing tolerated?
t0 = time.time(); codes = []
for i in range(10):
    r = requests.get(f"{A}/posts/search?subreddit=Accounting&after={week}&limit=100&fields=id,created_utc", headers=UA, timeout=40); codes.append(r.status_code); time.sleep(0.5)
print("10 requests at 0.5s spacing:", codes, f"{time.time()-t0:.1f}s total")
hn = requests.get(f"https://hn.algolia.com/api/v1/search_by_date?tags=ask_hn&numericFilters=created_at_i>{int((now - timedelta(days=70)).timestamp())},created_at_i<{int((now - timedelta(days=63)).timestamp())}&hitsPerPage=1000", headers=UA, timeout=30).json()
print("hn ask_hn 10 weeks ago:", len(hn.get("hits", [])), "author key:", "author" in (hn.get("hits") or [{}])[0])
se = requests.get(f"https://api.stackexchange.com/2.3/questions?order=desc&sort=creation&site=softwarerecs&fromdate={int((now - timedelta(days=70)).timestamp())}&todate={int((now - timedelta(days=63)).timestamp())}&pagesize=100&filter=withbody", headers=UA, timeout=30).json()
its = se.get("items", [])
print("se softwarerecs 10 weeks ago:", len(its), "keys:", sorted(its[0].keys())[:20] if its else None)
if its:
    ids = ";".join(str(q["question_id"]) for q in its[:20])
    an = requests.get(f"https://api.stackexchange.com/2.3/questions/{ids}/answers?site=softwarerecs&pagesize=100&filter=withbody", headers=UA, timeout=30).json()
    print("se answers:", len(an.get("items", [])), "keys:", sorted(an["items"][0].keys()) if an.get("items") else None, "quota", an.get("quota_remaining"))
