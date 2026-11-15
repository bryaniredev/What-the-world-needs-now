# What the World Needs Now

A weekly scan of the places where people who do a job talk to each other. It keeps only the posts where someone
states a need that isn't being met, works out who they are (the niche) and what kind of problem it is, and adds
the result to a history, so you can see **this week's unmet needs by niche** and **which ones keep coming back**.

It is a private GitHub Pages site. The page asks for a passphrase, and every data file in this repo is
AES-256-GCM encrypted with a key derived from that passphrase, so reading the repo gets you nothing useful.
The passphrase itself is stored only as a GitHub Actions secret, never in the code.
Search engines are told not to index it (`noindex` meta tags and `robots.txt`).

## What it looks at, and why

| Source | What is read | Why it works |
| --- | --- | --- |
| Reddit communities of practitioners (about 160, grouped into some 50 niches) | The whole week of posts in each community | Dentists, landlords, HVAC contractors, bookkeepers, restaurant owners and so on describing their own workflow problems to peers |
| Merchant and professional forums (Shopify Community, Spiceworks, Mac Power Users, Make) | Opening posts matching need phrases | People who already pay for tools asking "is there an app that…" |
| Freelancer.com projects | Gigs where a business wants a custom tool or pays for repetitive manual work | Nothing off the shelf fit, and there is a budget attached |
| Hacker News | Ask HN posts, comments with an unambiguous need phrase, replies in "what problem do you wish was solved?" threads | Stated problems, often with detail about what was tried |
| Stack Exchange Software Recommendations | Every new question | Each is someone who looked for software and couldn't find it |
| Bluesky | Posts using "I wish there was an app that…" and similar | General-public wishes |

Reddit is read through the public [Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift) archive, so no
login is needed. If `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` secrets exist, Reddit's official API is used.

### What counts as a lead

A post is kept only if it does at least one of these: asks for a tool, wishes something existed, says they would
pay, says nothing on the market fits, asks how others cope, describes doing something by hand or in a
spreadsheet that has become painful, or wants to leave a named product. Removed on purpose:

- people promoting or validating their own product ("I built…", "would you use…");
- one-product support questions ("won't load after the update", "can't log in").

Each lead gets a **niche** (from the community it came from, or from the text: "I run a landscaping company"),
a **problem area** (scheduling, invoicing, inventory…), a **SaaS fit**, whether it costs **time or money**, and
the **sentence where the person states the need**. Problems that software can't fix are kept and labelled
`SaaS fit: low`.

Without an Anthropic key, problems are grouped as *niche + problem area* (for example "Dental practices:
scheduling & booking"), which stays stable from week to week so it can be tracked. With a key, Claude names
specific problems and writes up who has them, why existing tools fail, and a three-feature MVP.

Earlier versions also read App Store, Shopify app and WordPress plugin reviews, GitHub feature requests and job
boards. Those produced complaints about individual apps and noisy job-duty lists, not niche problems, and were
removed. They are in the git history if you want them back.

Edit `collector/config.json` to change the communities, forums, phrases or thresholds.

## Pages

- **This week**: summary tiles, the week's top problems as cards (with the quotes behind them and validation
  links), the strongest individual leads, and which sources responded.
- **Trends**: leads per week by niche and by problem area, the niches and problem areas rising fastest, volume
  by source and SaaS-fit mix.
- **Problems**: every problem ever detected, with weeks seen, total leads, a sparkline, and filters by niche
  and fit. A problem seen in many weeks from several sources is the strongest signal.
- **Idea mines**: niches with the most unmet needs (with examples in people's own words), products people say
  they want to leave and why, and what people use spreadsheets for.
- **Browse**: every lead from any week, searchable and filterable by niche, problem area, source and fit.

## Setup (one time)

1. **Add the passphrase secret.** In the repo go to *Settings → Secrets and variables → Actions → New repository
   secret*. Name it `SITE_PASSPHRASE` and set the value to the word you'll type on the site.
   This is the only place the passphrase lives. If you change it later, delete `docs/data` and `state` so the
   history is re-created with the new key (old data can't be read with a new passphrase).
2. **Turn on Pages.** *Settings → Pages → Build and deployment → Source: GitHub Actions.*
   (Pages on a private repo needs a paid GitHub plan. The data is encrypted, so a public repo is fine.)
3. **Run it once.** *Actions → Weekly run + publish → Run workflow.* After about 10–15 minutes the site is at
   `https://<your-user>.github.io/<repo>/`. After that it runs every Sunday at 00:00 UTC. To change the time,
   edit the `cron` line in `.github/workflows/weekly.yml` (GitHub schedules are always in UTC).

The passphrase is not case-sensitive: the collector and the page both lower-case it.

### Optional secrets (add the same way)

| Secret | What it adds |
| --- | --- |
| `ANTHROPIC_API_KEY` | The biggest quality gain. Claude turns the week's leads into named, specific problems and writes who has each one, why existing tools fail, what it costs them, and a three-feature MVP. It reuses names from earlier weeks so trends line up. One request per week. |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Use Reddit's official API instead of the archive. Create a free "script" app at reddit.com/prefs/apps. Optional: the archive works without it. |
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
collector/            Python weekly job
  config.json         communities, forums, phrases, thresholds
  wtwn/sources.py     one collector per source (each fails independently)
  wtwn/analyze.py     keeps posts that state a need; niche, problem area, SaaS fit, need sentence, grouping
  wtwn/ai.py          optional Claude write-up of named problems
  wtwn/run.py         orchestration + history/trend index
docs/                 the GitHub Pages site (static, no build step)
  data/               encrypted output (written by the workflow)
state/                encrypted de-duplication state
tests/                offline tests with synthetic data
```
