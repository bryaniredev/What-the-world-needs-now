"""Daily run: collect -> score -> cluster -> merge into history -> encrypt.

    SITE_PASSPHRASE=... python -m wtwn.run            # normal daily run
    SITE_PASSPHRASE=... python -m wtwn.run --fixture tests/fixtures/raw.json --date 2026-01-01
"""
import argparse
import json
import os
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
        return self._read(self.data / "index.json", {"days": [], "problems": {}, "keywords": {}})

    def state(self):
        return self._read(self.state_dir / "state.json", {"seen": {}})

    def save(self, day, index, state):
        self._write(self.data / "days" / f"{day['date']}.json", day)
        self._write(self.data / "index.json", index)
        self._write(self.state_dir / "state.json", state)


def collect(cfg, since):
    http = sources.Http(delay=1.0)
    status, items = {}, []
    for name, fn in sources.ALL.items():
        scfg = cfg.get(name, {})
        if not scfg.get("enabled", False):
            continue
        t0 = time.time()
        log(f"[{name}] collecting...")
        got = fn(scfg, since, http, status)
        status[name]["seconds"] = round(time.time() - t0, 1)
        log(f"[{name}] {status[name]}")
        items.extend(got)
    return items, status


def build_day(date, raw, status, cfg, index, state):
    seen = state.setdefault("seen", {})
    fresh = [it for it in raw if it["id"] not in seen]
    scored = [analyze.score_item(it) for it in fresh]
    keep = [it for it in scored if it["pain_score"] >= cfg.get("min_pain_score", 3)
            and (it["signals"] or it["kind"] != "discussion")]  # engagement alone is not pain
    keep.sort(key=lambda x: -x["pain_score"])
    keep = keep[: cfg.get("max_items_per_day", 400)]
    for it in fresh:
        seen[it["id"]] = date
    cutoff = (datetime.fromisoformat(date) - timedelta(days=120)).strftime("%Y-%m-%d")
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}

    problems, ai_note = ai.refine(keep, index.get("problems", {}), cfg.get("ai", {}))
    if problems is None:
        log(f"[ai] {ai_note}; using keyword clusters")
        problems = analyze.heuristic_clusters(keep)
    else:
        log(f"[ai] {ai_note}: {len(problems)} problems")

    for it in keep:
        it["text"] = it["text"][:700]
    return {
        "date": date,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": status,
        "ai": ai_note,
        "raw_count": len(raw),
        "new_count": len(fresh),
        "problems": problems,
        "items": keep,
    }


def merge_index(index, day):
    date, items = day["date"], day["items"]
    summary = {
        "date": date,
        "total": len(items),
        "by_source": dict(Counter(it["source"] for it in items)),
        "by_theme": dict(Counter(t for it in items for t in it["themes"])),
        "by_fit": dict(Counter(it["saas_fit"] for it in items)),
        "by_kind": dict(Counter(it["kind"] for it in items)),
        "top": [p["title"] for p in day["problems"][:5]],
    }
    index["days"] = [d for d in index["days"] if d["date"] != date] + [summary]
    index["days"].sort(key=lambda d: d["date"])

    probs = index.setdefault("problems", {})
    for p in day["problems"]:
        e = probs.setdefault(p["key"], {"title": p["title"], "first_seen": date, "counts": {}, "scores": {}})
        e.update({"title": p["title"], "theme": p.get("theme"), "saas_fit": p.get("saas_fit"),
                  "last_seen": max(e.get("last_seen", date), date), "summary": p.get("summary", "")})
        e["first_seen"] = min(e["first_seen"], date)
        e["counts"][date] = len(p["item_ids"])
        e["scores"][date] = p["score"]
        e["sources"] = sorted(set(e.get("sources", [])) | set(p.get("sources", [])))
        e["days_seen"] = len(e["counts"])

    kws = index.setdefault("keywords", {})
    today = Counter(k for it in items for k in it["keywords"] if " " in k)
    for k, n in today.items():
        if n >= 2:
            kws.setdefault(k, {})[date] = n
    if len(kws) > 600:
        ranked = sorted(kws, key=lambda k: -sum(kws[k].values()))
        index["keywords"] = {k: kws[k] for k in ranked[:600]}
    index["updated"] = day["generated_at"]
    return index


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
        since = time.time() - cfg.get("lookback_hours", 30) * 3600
        raw, status = collect(cfg, since)

    index, state = store.index(), store.state()
    day = build_day(date, raw, status, cfg, index, state)
    index = merge_index(index, day)
    store.save(day, index, state)
    ok = sum(1 for s in status.values() if s.get("ok"))
    log(f"Done {date}: {len(raw)} raw, {day['new_count']} new, {len(day['items'])} kept, "
        f"{len(day['problems'])} problems, {ok}/{len(status)} sources ok")
    if ok == 0:
        raise SystemExit("Every source failed; check the log above.")


if __name__ == "__main__":
    main()
