"""Weekly run: collect -> keep posts that state a need -> group -> merge into history -> encrypt.

    SITE_PASSPHRASE=... python -m wtwn.run            # normal weekly run
    SITE_PASSPHRASE=... python -m wtwn.run --fixture tests/fixtures/raw.json --date 2026-01-01
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ai, analyze, crypto, sources

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "collector" / "config.json"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


class Store:
    def __init__(self, data_dir: Path, state_dir: Path, passphrase: str):
        passphrase = passphrase.strip().lower()  # the site does the same, so capitalisation never matters
        self.data, self.state_dir = data_dir, state_dir
        (self.data / "days").mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        meta_p = self.data / "meta.json"
        if meta_p.exists():
            meta = json.loads(meta_p.read_text())
            self.key = crypto.derive_key(passphrase, crypto.b64d(meta["salt"]), meta["iterations"])
            if not crypto.verify_meta(self.key, meta):
                raise SystemExit("SITE_PASSPHRASE does not match the one used for existing data (docs/data/meta.json).")
        else:
            salt = os.urandom(16)
            self.key = crypto.derive_key(passphrase, salt)
            meta_p.write_text(json.dumps(crypto.new_meta(self.key, salt), indent=1))

    def _read(self, p: Path, default):
        if not p.exists():
            return default
        return crypto.decrypt_obj(self.key, json.loads(p.read_text()))

    def _write(self, p: Path, obj):
        p.write_text(json.dumps(crypto.encrypt_obj(self.key, obj)))

    def index(self):
        return self._read(self.data / "index.json", {"days": [], "problems": {}, "keywords": {}, "niches": {}, "products": {}, "spreadsheet_uses": {}, "events": {}})

    def day(self, date):
        return self._read(self.data / "days" / f"{date}.json", None)

    def state(self):
        return self._read(self.state_dir / "state.json", {"seen": {}})

    def save(self, day, index, state):
        self._write(self.data / "days" / f"{day['date']}.json", day)
        self._write(self.data / "index.json", index)
        self._write(self.state_dir / "state.json", state)


def collect(cfg, since, until=None, only=None):
    http = sources.Http(delay=1.0)
    status, items = {}, []
    for name, fn in sources.ALL.items():
        scfg = cfg.get(name, {})
        if not scfg.get("enabled", False) or (only and name not in only):
            continue
        t0 = time.time()
        log(f"[{name}] collecting...")
        try:
            got = fn(scfg, since, http, status, until)
        except Exception as e:  # noqa: BLE001  (a collector bug must not sink the run)
            got, status[name] = [], {"ok": False, "count": 0, "error": f"{type(e).__name__}: {e}"[:300]}
        status[name]["seconds"] = round(time.time() - t0, 1)
        log(f"[{name}] {status[name]}")
        items.extend(got)
    return items, status


_DROP_FIELDS = ("keep", "implied", "niche_hint", "dropped", "buyer_pts", "se_site", "se_qid", "budget_usd")


def build_run(date, raw, status, cfg, index, state, previous=None, fetch=True, reply_budget=None, backfilled=False):
    seen = state.setdefault("seen", {})
    fresh = [it for it in raw if it["id"] not in seen]
    min_strong = cfg.get("min_signal_strength", 3)

    kept, dropped, sheets, events, read_by_source = [], Counter(), {}, {}, Counter()
    for it in fresh:
        read_by_source[it["source"]] += 1
        analyze.score_item(it, min_strong)
        if it.get("dropped"):
            dropped[it["dropped"]] += 1
        full = f"{it['title']}\n{it['text']}"
        if it.get("dropped") != "promo":
            # What people use spreadsheets for: any post, whether or not it is a complaint.
            if analyze._SHEET.search(full):
                for u in analyze.spreadsheet_uses_for(full):
                    e = sheets.setdefault(u, {"phrase": u, "count": 0, "examples": []})
                    e["count"] += 1
                    if len(e["examples"]) < 3:
                        e["examples"].append({"title": analyze.short(it["title"] or it["text"], 80), "url": it["url"], "where": it["channel"]})
            # Forced changes: any post in a work community or about software.
            hint = it.get("niche_hint")
            if (hint and hint not in analyze.CONSUMER_NICHES) or analyze.SOFT.search(full):
                found = analyze.events_for(it["title"], it["text"], hint)
                for kind, subject in found:
                    key = f"{kind}|{hint}" if kind == "regulation" else f"{kind}|{subject.lower()}"
                    e = events.setdefault(key, {"key": key, "type": kind, "subject": hint if kind == "regulation" else subject,
                                                "count": 0, "weight": 0, "niches": {}, "examples": []})
                    e["count"] += 1
                    e["weight"] += it.get("engagement", 0)
                    niche = hint or analyze.detect_niche(full) or analyze.GENERAL
                    e["niches"][niche] = e["niches"].get(niche, 0) + 1
                    if len(e["examples"]) < 4:
                        e["examples"].append({"title": analyze.short(subject if kind == "regulation" else (it["title"] or it["text"]), 150),
                                              "url": it["url"], "where": it["channel"], "date": date})
                if found and it["keep"]:
                    it["events"] = [f"{analyze.EVENT_LABEL[k]}: {s_}" for k, s_ in found if k != "regulation"] or ["New rule"]
        if it["keep"]:
            kept.append(it)

    # A second run on the same date adds to the first instead of replacing it.
    if previous:
        have = {it["id"] for it in kept}
        kept += [it for it in previous.get("items", []) if it["id"] not in have]
        for r in previous.get("spreadsheet_uses", []):
            e = sheets.setdefault(r["phrase"], {"phrase": r["phrase"], "count": 0, "examples": []})
            e["count"] += r["count"]
            e["examples"] = (e["examples"] + r["examples"])[:3]
        for r in previous.get("events", []):
            if r["key"] not in events:
                events[r["key"]] = r
    kept.sort(key=lambda x: (-x["pain_score"], x["id"]))
    for it in kept:
        seen[it["id"]] = date  # including cross-posted copies, so they don't come back next week
    # The same post in several communities counts once (highest score wins).
    uniq, texts = [], set()
    for it in kept:
        fp = re.sub(r"\W+", "", (it["title"] + it["text"][:160]).lower())
        if fp not in texts:
            texts.add(fp)
            uniq.append(it)
    kept = uniq[: cfg.get("max_items_per_run", 600)]
    cutoff = (datetime.fromisoformat(date) - timedelta(days=200)).strftime("%Y-%m-%d")
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}

    # Read the replies: is anyone saying "same here", or did someone already name a tool that does it?
    if fetch:
        rcfg = dict(cfg.get("replies", {}))
        if reply_budget is not None:
            rcfg["max_per_run"] = reply_budget
        n, errs = sources.fetch_replies([it for it in kept if "replies" not in it], rcfg, sources.Http(delay=0.7), log)
        status["replies"] = {"ok": not errs or n > 0, "count": n, "note": f"reply threads read for {n} leads" + (f"; {len(errs)} failed ({errs[0][:80]})" if errs else "")}
        log(f"[replies] {status['replies']}")
    for it in kept:
        if "replies" not in it:
            analyze.reply_stats(it)
        if "opp" not in it:
            analyze.opportunity(it)
    kept.sort(key=lambda x: (-x["opp"], x["id"]))

    for name, n in read_by_source.items():
        if name in status:
            status[name]["read"] = n
            status[name]["count"] = sum(1 for it in kept if it["source"] == name)

    problems, ai_note = ai.refine(kept, index.get("problems", {}), cfg.get("ai", {}))
    if problems is None:
        log(f"[ai] {ai_note}; grouping by niche and problem area")
        problems = analyze.niche_clusters(kept)
    else:
        log(f"[ai] {ai_note}: {len(problems)} problems")
    by_id = {it["id"]: it for it in kept}
    known = index.get("problems", {})
    for p in problems:
        weeks = len(set(known.get(p["key"], {}).get("counts", {})) | {date})
        analyze.problem_stats(p, [by_id[i] for i in p["item_ids"]], weeks)
    analyze.rank_problems(problems)

    for it in kept:
        it["text"] = it["text"][:700]
        for f in _DROP_FIELDS:
            it.pop(f, None)
    return {
        "date": date,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backfilled": backfilled,
        "sources": status,
        "ai": ai_note,
        "raw_count": len(raw),
        "new_count": len(fresh),
        "filtered": dict(dropped),
        "problems": problems,
        "items": kept,
        "spreadsheet_uses": sorted(sheets.values(), key=lambda e: -e["count"])[:120],
        "events": sorted(events.values(), key=lambda e: (-e["count"], -e["weight"]))[:80],
    }


def _trim(d, n, weight):
    if len(d) > n:
        keep = sorted(d, key=weight, reverse=True)[:n]
        return {k: d[k] for k in keep}
    return d


def _summary(items):
    return {
        "total": len(items),
        "by_source": dict(Counter(it["source"] for it in items)),
        "by_niche": dict(Counter(it["niche"] for it in items)),
        "by_theme": dict(Counter(it["themes"][0] for it in items)),
        "by_fit": dict(Counter(it["saas_fit"] for it in items)),
        "by_reply": dict(Counter(it["replies"]["status"] for it in items)),
        "avg_opp": round(sum(it["opp"] for it in items) / len(items)) if items else 0,
    }


def merge_index(index, run):
    date, items = run["date"], run["items"]
    summary = {
        "date": date,
        "read": run.get("new_count", 0),
        "backfilled": bool(run.get("backfilled")),
        **_summary(items),
        "seg": {seg: _summary([it for it in items if it["segment"] == seg]) for seg in ("business", "consumer")},
        "top": [p["title"] for p in run["problems"][:5]],
    }
    index["days"] = sorted([d for d in index.get("days", []) if d["date"] != date] + [summary], key=lambda d: d["date"])

    by_id = {it["id"]: it for it in items}
    probs = index.setdefault("problems", {})
    for p in run["problems"]:
        e = probs.setdefault(p["key"], {"title": p["title"], "first_seen": date, "counts": {}, "scores": {}, "opps": {}, "leads": []})
        e.update({"title": p["title"], "theme": p.get("theme"), "niche": p.get("niche"), "saas_fit": p.get("saas_fit"),
                  "segment": p.get("segment"), "last_seen": max(e.get("last_seen", date), date), "summary": p.get("summary", ""),
                  "search_keyword": p.get("search_keyword")})
        e["first_seen"] = min(e["first_seen"], date)
        e["counts"][date] = len(p["item_ids"])
        e["scores"][date] = p["score"]
        e.setdefault("opps", {})[date] = p["opp"]
        e["days_seen"] = len(e["counts"])
        e["sources"] = sorted(set(e.get("sources", [])) | set(p.get("sources", [])))
        # Everyone who voiced it, newest first: the people to talk to.
        fresh = [{"date": date, "author": it.get("author"), "url": it["url"], "where": it["channel"], "source": it["source"],
                  "need": analyze.short(it["need"], 200), "opp": it["opp"], "reply": it["replies"]["status"]}
                 for it in (by_id[i] for i in p["item_ids"])]
        urls = {x["url"] for x in fresh}
        e["leads"] = (fresh + [x for x in e.get("leads", []) if x["url"] not in urls])[:40]
        e["tools"] = list(dict.fromkeys(p["replies"]["tools"] + e.get("tools", [])))[:8]
        e.setdefault("me_too_by", {})[date] = p["replies"]["me_too"]
        e["me_too"] = sum(e["me_too_by"].values())
        e.setdefault("unmet_by", {})[date] = p["replies"]["unmet"]
        e.setdefault("solved_by", {})[date] = p["replies"]["solved"]
        e["opp"] = e["opps"][max(e["opps"])]  # the most recent week's score, which already counts recurrence
        e["opp_parts"] = p["opp_parts"]
        if p.get("money_notes"):
            e["money_notes"] = p["money_notes"]

    # Who has problems: one row per niche, with what kind and a few examples in their words.
    niches = index.setdefault("niches", {})
    for n in niches.values():
        n["counts"].pop(date, None)
        for t in n["themes"].values():
            t.pop(date, None)
    for it in items:
        e = niches.setdefault(it["niche"], {"counts": {}, "themes": {}, "examples": []})
        e["segment"] = "consumer" if it["niche"] in analyze.CONSUMER_NICHES or it["niche"] == analyze.GENERAL else "business"
        e["counts"][date] = e["counts"].get(date, 0) + 1
        th = e["themes"].setdefault(it["themes"][0], {})
        th[date] = th.get(date, 0) + 1
    for niche, e in niches.items():
        top = [it for it in items if it["niche"] == niche][:4]
        fresh = [{"date": date, "need": it["need"], "url": it["url"], "where": it["channel"]} for it in top]
        urls = {x["url"] for x in fresh}
        e["examples"] = (fresh + [x for x in e["examples"] if x["url"] not in urls and x["date"] != date])[:6]

    # Products people say they want to leave, and why.
    products = index.setdefault("products", {})
    for e in products.values():
        e["counts"].pop(date, None)
        for t in e["types"].values():
            t.pop(date, None)
    for it in items:
        for name in it.get("products", []):
            e = products.setdefault(name.lower(), {"name": name, "counts": {}, "types": {}, "niches": {}, "quotes": []})
            e["counts"][date] = e["counts"].get(date, 0) + 1
            e["niches"][it["niche"]] = e["niches"].get(it["niche"], 0) + 1
            for t in it.get("complaints", []) or ["other"]:
                e["types"].setdefault(t, {})[date] = e["types"].get(t, {}).get(date, 0) + 1
            if all(q["url"] != it["url"] for q in e["quotes"]):
                e["quotes"] = ([{"date": date, "title": it["title"], "text": it["need"], "url": it["url"], "where": it["channel"]}] + e["quotes"])[:8]
    index["products"] = _trim(products, 500, lambda k: sum(products[k]["counts"].values()))

    # Forced changes: shutdowns, price rises, acquisitions, outages, new rules.
    events = index.setdefault("events", {})
    for r in run.get("events", []):
        e = events.setdefault(r["key"], {"type": r["type"], "subject": r["subject"], "counts": {}, "niches": {}, "examples": []})
        e["counts"][date] = r["count"]
        for n, c in r["niches"].items():
            e["niches"][n] = e["niches"].get(n, 0) + c
        urls = {x["url"] for x in r["examples"]}
        e["examples"] = (r["examples"] + [x for x in e["examples"] if x["url"] not in urls])[:6]
    index["events"] = _trim(events, 400, lambda k: (max(events[k]["counts"]), sum(events[k]["counts"].values())))

    sheets = index.setdefault("spreadsheet_uses", {})
    for r in run.get("spreadsheet_uses", []):
        e = sheets.setdefault(r["phrase"], {"counts": {}, "examples": []})
        e["counts"][date] = r["count"]
        urls, merged = set(), []
        for x in r["examples"] + e["examples"]:
            if x.get("url") not in urls:
                urls.add(x.get("url"))
                merged.append(x)
        e["examples"] = merged[:4]
    index["spreadsheet_uses"] = _trim(sheets, 600, lambda k: (len(sheets[k]["counts"]), sum(sheets[k]["counts"].values())))

    kws = index.setdefault("keywords", {})
    for k, n in Counter(k for it in items for k in it.get("keywords", [])).items():
        if n >= 2:
            kws.setdefault(k, {})[date] = n
    index["keywords"] = _trim(kws, 400, lambda k: sum(kws[k].values()))

    index["cadence"] = "weekly"
    index["updated"] = run["generated_at"]
    return index


def run_week(store, cfg, date, raw, status, fetch=True, reply_budget=None, backfilled=False):
    """Score, read replies, group, merge into the history and save. Used by the weekly run and the backfill."""
    index, state = store.index(), store.state()
    run = build_run(date, raw, status, cfg, index, state, previous=store.day(date), fetch=fetch,
                    reply_budget=reply_budget, backfilled=backfilled)
    index = merge_index(index, run)
    store.save(run, index, state)
    ok = sum(1 for s in status.values() if s.get("ok"))
    log(f"Done {date}: {len(raw)} posts read, {run['new_count']} not seen before, {len(run['items'])} kept as leads "
        f"(filtered out: {run['filtered']}), {len(run['problems'])} problems, {len(run['events'])} forced changes, "
        f"{ok}/{len(status)} sources ok")
    return run, ok


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", help="JSON file of raw items to use instead of fetching")
    ap.add_argument("--date", help="override run date (YYYY-MM-DD)")
    ap.add_argument("--data-dir", default=str(ROOT / "docs" / "data"))
    ap.add_argument("--state-dir", default=str(ROOT / "state"))
    args = ap.parse_args(argv)

    passphrase = os.environ.get("SITE_PASSPHRASE")
    if not passphrase:
        raise SystemExit("SITE_PASSPHRASE is not set. Add it as a repository secret (Settings > Secrets > Actions).")
    cfg = json.loads(CONFIG.read_text())
    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    store = Store(Path(args.data_dir), Path(args.state_dir), passphrase)

    if args.fixture:
        raw, status = json.loads(Path(args.fixture).read_text()), {"fixture": {"ok": True}}
        status["fixture"]["count"] = len(raw)
    else:
        since = time.time() - cfg.get("lookback_days", 8) * 86400
        raw, status = collect(cfg, since)

    _, ok = run_week(store, cfg, date, raw, status, fetch=not args.fixture)
    if ok == 0:
        raise SystemExit("Every source failed; check the log above.")


if __name__ == "__main__":
    main()
