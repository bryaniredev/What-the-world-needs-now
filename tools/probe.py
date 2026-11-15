"""Temporary: check which candidate sources answer from GitHub's servers."""
import json, sys, time
from datetime import datetime, timedelta, timezone
import requests

UA = {"User-Agent": "what-the-world-needs-now/2.0 (weekly unmet-needs research)"}
week = datetime.now(timezone.utc) - timedelta(days=7)
ep, iso = int(week.timestamp()), week.strftime("%Y-%m-%d")
T = [
 ("arctic posts", f"https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=smallbusiness&after={iso}&limit=5"),
 ("arctic query", f"https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=smallbusiness&after={iso}&limit=5&query=software"),
 ("arctic multi", f"https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=smallbusiness,landlord&after={iso}&limit=5"),
 ("pullpush", f"https://api.pullpush.io/reddit/search/submission/?subreddit=smallbusiness&size=5&after={ep}"),
 ("pullpush q", f"https://api.pullpush.io/reddit/search/submission/?q=%22is%20there%20a%20tool%22&size=5&after={ep}"),
 ("reddit rss", "https://www.reddit.com/r/smallbusiness/new/.rss"),
 ("reddit old json", "https://old.reddit.com/r/smallbusiness/new.json?limit=5"),
 ("hn ask threads", f"https://hn.algolia.com/api/v1/search?query=wish%20existed&tags=ask_hn&numericFilters=num_comments%3E20&hitsPerPage=5"),
 ("hn item", "https://hn.algolia.com/api/v1/items/1"),
 ("se softwarerecs", f"https://api.stackexchange.com/2.3/questions?order=desc&sort=creation&site=softwarerecs&fromdate={ep}&pagesize=5&filter=withbody"),
 ("se search", f"https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=creation&q=%22is%20there%20an%20app%22&site=lifehacks&fromdate={ep-86400*60}&pagesize=5"),
 ("freelancer", "https://www.freelancer.com/api/projects/0.1/projects/active/?query=automate%20spreadsheet&limit=5&full_description=true"),
 ("lemmy", "https://lemmy.world/api/v3/search?q=is%20there%20an%20app&type_=Posts&sort=New&limit=5"),
 ("bsky api", "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=%22is%20there%20an%20app%20that%22&limit=5&sort=latest"),
 ("bsky public", "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=%22is%20there%20an%20app%20that%22&limit=5&sort=latest"),
 ("askmefi rss", "https://ask.metafilter.com/rss"),
 ("askmefi tag", "https://ask.metafilter.com/tags/software/rss"),
 ("spiceworks", f"https://community.spiceworks.com/search.json?q=software%20recommendation%20after%3A{iso}"),
 ("make", f"https://community.make.com/search.json?q=is%20there%20a%20way%20after%3A{iso}"),
 ("macpowerusers", f"https://talk.macpowerusers.com/search.json?q=is%20there%20an%20app%20after%3A{iso}"),
 ("bubble", f"https://forum.bubble.io/search.json?q=looking%20for%20after%3A{iso}"),
 ("shopify community", f"https://community.shopify.com/search.json?q=is%20there%20an%20app%20after%3A{iso}"),
 ("google suggest", "https://suggestqueries.google.com/complete/search?client=firefox&q=is%20there%20an%20app%20for%20"),
 ("indiehackers", "https://www.indiehackers.com/"),
 ("producthunt", "https://www.producthunt.com/discussions"),
 ("quora", "https://www.quora.com/search?q=is%20there%20an%20app%20that"),
 ("mastodon tag", "https://mastodon.social/api/v1/timelines/tag/smallbusiness?limit=5"),
 ("lobsters ask", "https://lobste.rs/t/ask.json"),
 ("tildes", "https://tildes.net/~tech"),
 ("alternativeto", "https://alternativeto.net/"),
 ("biggerpockets", "https://www.biggerpockets.com/forums"),
 ("contractortalk", "https://www.contractortalk.com/"),
 ("dentaltown", "https://www.dentaltown.com/messageboard"),
]
for name, url in T:
    try:
        r = requests.get(url, headers=UA, timeout=25)
        body = r.text
        extra = ""
        try:
            j = r.json()
            if isinstance(j, dict):
                extra = "keys=" + ",".join(list(j.keys())[:8])
                for k in ("data", "hits", "items", "posts", "topics", "result"):
                    if isinstance(j.get(k), list):
                        extra += f" {k}={len(j[k])}"
                    elif isinstance(j.get(k), dict):
                        extra += f" {k}.keys=" + ",".join(list(j[k].keys())[:6])
            elif isinstance(j, list):
                extra = f"list={len(j)}"
        except Exception:
            pass
        print(f"{r.status_code} {name:18} {len(body):>8}b {r.headers.get('content-type','')[:30]:30} {extra}")
        print("      ", body[:260].replace("\n", " "))
    except Exception as e:
        print(f"ERR {name:18} {type(e).__name__}: {str(e)[:120]}")
    time.sleep(1)
