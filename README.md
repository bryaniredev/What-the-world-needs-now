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
| Apple App Store | 1–3★ reviews of the **top-grossing** Business, Productivity and Finance apps (found fresh each day) plus a fixed list | What incumbents get wrong for paying customers |
| Shopify App Store | 1–3★ reviews of the **most popular apps in each category** (found fresh each day) | Merchants already paying and still unhappy |
| WordPress plugins | 1–3★ reviews of the 25 most popular plugins | Same, for site owners |
| GitHub | Recently opened feature requests with many 👍 | Unmet needs inside tools people already use |
| Job boards via headless browser: LinkedIn, Indeed, ZipRecruiter, Glassdoor, Monster, Dice, USAJOBS, Google Jobs | Full job descriptions for a few rotating industry searches a day; their listed duties | The Job Search Method at scale (see below) |
| Job posts (The Muse, Remotive, RemoteOK, optional Adzuna by industry) | The duties listed in each post, plus posts describing data entry, reconciliation, chasing, copy-paste | If a company pays a person to do it, software might do it cheaper |

3-star reviews are kept only when they name a gap (a missing feature, the price, usability or integrations),
because "good, but…" reviews are often where the clearest gaps are.

### Job boards (headless browser)

`collector/wtwn/jobscrape.py` runs in the daily workflow before the main collector. Each day it takes 4
searches from `jobs.industries` + `jobs.remotive_searches` in `collector/config.json` (rotating, so every
industry comes round every few days), opens each enabled board, reads up to 15 result cards and opens the top
5 postings for the full description. With pauses between pages it takes 10–25 minutes.

It keeps volume low, uses an ordinary headless browser, and does not try to get past bot protection: if a site
shows a CAPTCHA, a login wall or a block page, that site is marked failed for the day under **Sources** and
skipped. LinkedIn, Indeed, Glassdoor, ZipRecruiter and Monster forbid automated access in their terms and
often block cloud servers, so expect some of them to fail on some or all days. Turn any site off under
`job_boards.sites` in the config. Two sites have proper APIs that are used instead of the browser when
their keys are set:

- **USAJOBS**: free key from developer.usajobs.gov. Save `USAJOBS_API_KEY` and `USAJOBS_EMAIL` (the email you
  registered with) as repository secrets. Its "major duties" field is ideal for this.
- **Google Jobs**: Google blocks automated browsers; SerpApi (serpapi.com, free tier) returns Google Jobs
  results. Save `SERPAPI_KEY`. Uses 3 searches a day.

To see what each site returns to GitHub's servers, run the **Job boards test** workflow (Actions tab); it does
one search per site with a detailed log and saves nothing.

### The idea-finding methods it automates

- **Job Search Method** (Tom Zaragoza): read job descriptions in an industry, take each responsibility and add
  "management software" ("ensure compliance with health and safety regulations" becomes
  *health and safety compliance management software*), then search it. The collector pulls duties out of every
  job post it sees and counts how often each shows up across posts and days.
- **App Store Method**: pick an app store category, sort by popularity, read the 1-star reviews of the top apps
  for what's badly missing. Done for the Apple App Store, Shopify App Store and WordPress plugins.
- **What-They're-Using-Excel-For Method**: phrases like "we track job costs in a spreadsheet" are pulled out and
  counted. Each is a workflow that might deserve real software.
- **Borrow it from 1-star reviews** (Aytekin Tank): mine reviews of tools in categories with recurring spend for
  repeated complaints, emotional language, "I wish it could…" and "too expensive for what it does", then have AI
  summarise the pain points and scope a minimal product. The *Idea mines* tab tallies complaint types per product
  (missing feature, hard to use, too expensive, unreliable, integrations, support, slow). With an Anthropic key,
  Claude writes each problem up with whether it costs people time or money and a 3-feature MVP.
- **Validation**: every problem card has links to check it the way both articles suggest: Google (are there ads
  and competitors?), "what is …" questions, Google Trends, G2, Capterra, Reddit and Keyword Planner.
- Also: Reddit, Hacker News and Stack Exchange "is there a tool…" posts, upvoted GitHub feature requests, and
  checking whether the same pain shows up in several unrelated sources.

Not covered: G2 and Capterra block scrapers, so they're only linked for manual checks; the Chrome Web Store,
Salesforce AppExchange and Google Play have no public review feed.

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
- **Idea mines**: incumbent gaps (complaints per product), jobs → software ideas (duties from job posts and their
  "management software" search), and what people use spreadsheets for. Each can be viewed over 7, 30, 90 days or all time.
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
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | Job searches by industry (car dealerships, dental offices, property management…, see `jobs.industries` in the config), the core of the Job Search Method. A free key is available at developer.adzuna.com. Without it, job posts come from The Muse and remote job boards only. |
| `USAJOBS_API_KEY` / `USAJOBS_EMAIL` | Official USAJOBS API instead of the browser (more reliable, includes listed duties). |
| `SERPAPI_KEY` | Google Jobs results via SerpApi (Google blocks automated browsers). |
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
  wtwn/jobscrape.py   headless-browser job board scrape (runs first, feeds sources.job_boards)
  wtwn/analyze.py     pain score, themes, SaaS fit, complaint types, job duties, spreadsheet uses, clusters
  wtwn/ai.py          optional Claude grouping
  wtwn/run.py         orchestration + history/trend index
docs/                 the GitHub Pages site (static, no build step)
  data/               encrypted output (written by the workflow)
state/                encrypted de-duplication state
tests/                offline tests with synthetic data
```
