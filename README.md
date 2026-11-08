# What the World Needs Now

A daily scan of the places where people complain, ask for tools that don't exist, leave 1-star reviews and pay
humans to do repetitive work. Each run scores what it finds, groups it into problems, and adds it to a history,
so you can see both **today's loudest unmet needs** and **which problems keep coming back over weeks**.

It is a private GitHub Pages site. The page asks for a passphrase, and every data file in this repo is
AES-256-GCM encrypted with a key derived from that passphrase, so reading the repo gets you nothing useful.
The passphrase itself is stored only as a GitHub Actions secret, never in the code.
Search engines are told not to index it (`noindex` meta tags and `robots.txt`).

## What it looks at, and why

| Source | What counts as a signal | Why it works |
| --- | --- | --- |
| Reddit (45 business and trade subreddits) | "is there a tool", "I wish there was", "would pay for", "manually … spreadsheet", "alternative to" | People describe their pain in their own words, in niche communities |
| Hacker News (Algolia API) | The same phrasing, plus "we built an internal tool" | Companies building it themselves = demand nobody sells to |
| Stack Exchange (Software Recs, Web Apps, Super User, PM, Money) | Titles like "is there…", "looking for…", "software for…" | Explicit requests for software that may not exist |
| Apple App Store | 1–2★ reviews of QuickBooks, Shopify, Square, Notion, Slack… | What incumbents get wrong for paying customers |
| Shopify App Store | 1–2★ reviews of popular apps | Merchants already paying and still unhappy |
| WordPress plugins | 1–2★ reviews of WooCommerce, Elementor, Yoast… | Same, for site owners |
| GitHub | Recently opened feature requests with many 👍 | Unmet needs inside tools people already use |
| Job boards (Remotive, RemoteOK) | Posts describing data entry, reconciliation, chasing, copy-paste | If a company pays a person to do it, software might do it cheaper |

These come from the usual playbooks (job-listing mining, 1-star review mining) plus a few more that tend to work:
cross-checking the same pain across several independent sources, watching marketplaces where people already pay
(Shopify and WordPress), and treating heavily upvoted feature requests as a backlog incumbents are ignoring.
Edit `collector/config.json` to change the subreddits, apps, plugins, search phrases or thresholds.

Problems that software can't fix (rent, staffing, regulation) are **kept** when lots of people share them.
They're labelled `SaaS fit: low` so you can filter them in or out.

## Pages

- **Today**: summary tiles, the day's top problems as cards (with links to every piece of evidence), the loudest
  individual complaints, and which sources responded.
- **Trends**: mentions per theme over time, volume by source, SaaS-fit mix, and the themes and phrases rising
  fastest (last 7 days vs the previous 7).
- **Problems**: every problem ever detected, with days seen, total mentions, a 30-day sparkline, and filters.
  A problem seen on many days from several sources is the strongest signal.
- **Browse**: every item from any day, searchable and filterable.

## Setup (one time)

1. **Add the passphrase secret.** In the repo go to *Settings → Secrets and variables → Actions → New repository
   secret*. Name it `SITE_PASSPHRASE` and set the value to the word you'll type on the site.
   This is the only place the passphrase lives. If you change it later, delete `docs/data` and `state` so the
   history is re-created with the new key (old data can't be read with a new passphrase).
2. **Turn on Pages.** *Settings → Pages → Build and deployment → Source: GitHub Actions.*
   (Pages on a private repo needs a paid GitHub plan. The data is encrypted, so a public repo is fine.)
3. **Run it once.** *Actions → Daily run + publish → Run workflow.* After about 5–10 minutes the site is at
   `https://<your-user>.github.io/<repo>/`. After that it runs every day at 11:17 UTC.

### Optional secrets (add the same way)

| Secret | What it adds |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude groups the day's items into named problems and writes who has the problem, why existing tools fail, and a solution idea. It also reuses names from earlier days so trends line up. Roughly one request per day. Without it, problems are grouped by shared phrases. |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Reddit often blocks anonymous requests from cloud servers. Create a free "script" app at reddit.com/prefs/apps and add its id and secret to make the Reddit source reliable. |
| `STACKEXCHANGE_KEY` | Raises the Stack Exchange quota (optional; the default is enough). |

## Running locally

```bash
pip install -r collector/requirements.txt
```

```bash
cd collector && SITE_PASSPHRASE='your-word' python -m wtwn.run
```

```bash
python -m unittest discover -s tests -v
```

To preview the site, serve `docs/` (for example `python -m http.server -d docs`) and open it in a browser.

## How the protection works

- `collector/wtwn/crypto.py` derives a 256-bit key from the passphrase with PBKDF2-SHA256 (310,000 rounds,
  random salt), then encrypts each gzipped JSON file with AES-GCM.
- `docs/data/meta.json` holds only the salt and a small encrypted check value, so the page can tell whether the
  passphrase is right without storing it.
- The browser does the same derivation with WebCrypto and decrypts in memory. The derived key (not the
  passphrase) is kept in `sessionStorage` until you close the tab or press the lock button.
- Search engines: `<meta name="robots" content="noindex, nofollow, …">` on the page and a `robots.txt` that
  disallows everything. Note that `robots.txt` is only honoured at a domain root, so on a project site
  (`user.github.io/repo/`) the meta tag is what does the work.

## Layout

```
collector/            Python daily job
  config.json         sources, phrases, thresholds
  wtwn/sources.py     one collector per source (each fails independently)
  wtwn/analyze.py     pain score, themes, SaaS fit, keyword clusters
  wtwn/ai.py          optional Claude grouping
  wtwn/run.py         orchestration + history/trend index
docs/                 the GitHub Pages site (static, no build step)
  data/               encrypted output (written by the workflow)
state/                encrypted de-duplication state
tests/                offline tests with synthetic data
```
