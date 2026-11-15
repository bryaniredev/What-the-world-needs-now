"""Temporary: confirm response shapes (prints field names and counts only)."""
import json, time
from datetime import datetime, timedelta, timezone
import requests

UA = {"User-Agent": "what-the-world-needs-now/2.0 (weekly unmet-needs research)"}
week = datetime.now(timezone.utc) - timedelta(days=7)
ep, iso = int(week.timestamp()), week.strftime("%Y-%m-%d")

def get(name, url):
    try:
        r = requests.get(url, headers=UA, timeout=30)
        print(f"\n== {name}: HTTP {r.status_code}, {len(r.text)}b, ratelimit={ {k:v for k,v in r.headers.items() if 'rate' in k.lower()} }")
        return r
    except Exception as e:
        print(f"\n== {name}: ERR {e}")

def shape(o, depth=0, maxd=2):
    if isinstance(o, dict):
        return {k: (shape(v, depth+1, maxd) if depth < maxd else type(v).__name__) for k, v in list(o.items())[:40]}
    if isinstance(o, list):
        return [f"len={len(o)}", shape(o[0], depth+1, maxd) if o else None]
    if isinstance(o, str):
        return f"str[{len(o)}]"
    return o if isinstance(o, (int, float, bool)) or o is None else type(o).__name__

F = "id,title,selftext,created_utc,subreddit,score,num_comments,permalink,link_flair_text,removed_by_category,author"
r = get("arctic fields", f"https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=Dentistry&after={iso}&limit=100&sort=desc&fields={F}")
if r is not None and r.ok:
    d = r.json()["data"]; print(len(d), shape(d[0]) if d else None)
    if d:
        last = d[-1]["created_utc"]
        r2 = get("arctic page2", f"https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=Dentistry&after={iso}&before={last}&limit=100&sort=desc&fields={F}")
        if r2 is not None and r2.ok: print("page2", len(r2.json()["data"]))
time.sleep(1)
r = get("arctic big sub", f"https://arctic-shift.photon-reddit.com/api/posts/search?subreddit=smallbusiness&after={iso}&limit=100&sort=desc&fields={F}")
if r is not None and r.ok:
    d = r.json()["data"]; print(len(d), "oldest", datetime.fromtimestamp(d[-1]["created_utc"], timezone.utc) if d else None, "scores", [x.get("score") for x in d[:15]], "ncomm", [x.get("num_comments") for x in d[:15]])
time.sleep(1)
r = get("reddit rss search", "https://www.reddit.com/r/Dentistry/search.rss?q=software+OR+app&restrict_sr=1&sort=new&t=week&limit=100")
if r is not None: print(r.text.count("<entry>"), r.text[:200].replace("\n"," "))
time.sleep(2)
r = get("reddit rss new 100", "https://www.reddit.com/r/Dentistry/new/.rss?limit=100")
if r is not None: print(r.text.count("<entry>"))
time.sleep(1)
r = get("freelancer", f"https://www.freelancer.com/api/projects/0.1/projects/active/?query=automate&limit=5&full_description=true&job_details=true&from_time={ep}&languages[]=en&sort_field=time_updated")
if r is not None and r.ok:
    j = r.json()["result"]; print("total", j.get("total_count"), shape(j["projects"][0]) if j["projects"] else None)
time.sleep(1)
r = get("bsky", f"https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=%22is%20there%20an%20app%20that%22&limit=5&sort=latest&lang=en&since={iso}T00:00:00Z")
if r is not None and r.ok:
    j = r.json(); print("hitsTotal", j.get("hitsTotal"), "cursor", j.get("cursor"), shape(j["posts"][0], maxd=1) if j["posts"] else None)
time.sleep(1)
for host in ["community.shopify.com", "community.spiceworks.com"]:
    r = get(f"discourse {host}", f"https://{host}/search.json?q=%22is%20there%20an%20app%22%20after%3A{iso}%20in%3Afirst%20order%3Alatest")
    if r is not None and r.ok:
        j = r.json(); print(shape({"posts": j.get("posts"), "topics": j.get("topics"), "g": j.get("grouped_search_result")}, maxd=2))
        if j.get("topics"):
            t = j["topics"][0]
            r3 = get("topic", f"https://{host}/t/{t['id']}.json")
            if r3 is not None and r3.ok:
                p = r3.json()["post_stream"]["posts"][0]; print("first post keys", list(p.keys())[:25], "cooked len", len(p.get("cooked","")))
    time.sleep(1)
for host in ["community.n8n.io", "forum.obsidian.md", "community.airtable.com", "forum.manager.io", "discuss.erpnext.com", "community.quickfile.co.uk", "forum.asana.com", "community.monday.com", "community.glideapps.com", "community.retool.com", "forum.squarespace.com", "community.etsy.com", "community.wolfram.com", "community.jobber.com", "forum.zettelkasten.de", "community.smartthings.com", "talk.tidbits.com", "forum.ynab.com", "discourse.practicalecommerce.com", "community.klaviyo.com", "community.zapier.com", "forums.sellercentral.amazon.com", "community.openemr.org", "community.frappe.io", "forum.invoiceninja.com", "community.akaunting.com", "discuss.grocy.info", "forum.paperless.com", "community.revolut.com", "community.wise.com"]:
    try:
        r = requests.get(f"https://{host}/search.json?q=%22is%20there%22%20after%3A{iso}", headers=UA, timeout=15)
        n = None
        try: n = len(r.json().get("topics") or [])
        except Exception: pass
        print(f"   {host:38} HTTP {r.status_code} topics={n}")
    except Exception as e:
        print(f"   {host:38} ERR {type(e).__name__}")
    time.sleep(0.5)
r = get("hn ask need", f"https://hn.algolia.com/api/v1/search_by_date?query=%22is%20there%20a%20tool%22&tags=ask_hn&numericFilters=created_at_i%3E{ep}&hitsPerPage=20")
if r is not None and r.ok: print("hits", len(r.json()["hits"]))
r = get("hn idea threads", f"https://hn.algolia.com/api/v1/search?query=%22what%20problem%22&tags=ask_hn&numericFilters=created_at_i%3E{ep-86400*120},num_comments%3E15&hitsPerPage=20")
if r is not None and r.ok: print("hits", len(r.json()["hits"]), [h["title"][:60] for h in r.json()["hits"][:6]])
r = get("se softwarerecs week", f"https://api.stackexchange.com/2.3/questions?order=desc&sort=creation&site=softwarerecs&fromdate={ep}&pagesize=100")
if r is not None and r.ok: print("items", len(r.json()["items"]))
