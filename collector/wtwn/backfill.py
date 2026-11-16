"""Rebuild the history from past weeks, then run the current week.

    SITE_PASSPHRASE=... python -m wtwn.backfill --weeks 13 --reset

Past weeks end on Mondays. Reddit comes from the archive in one pass per community, Hacker News and
Stack Exchange by date range; forums, freelance gigs and Bluesky are only read for the current week.
Posts that were deleted or removed since they were written have lost their text, so past weeks hold
fewer leads than live ones. Weeks already on disk are skipped, so an interrupted backfill can resume.
"""
import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import run, sources

WEEK = 7 * 86400


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=13)
    ap.add_argument("--reset", action="store_true", help="delete existing history first (the passphrase salt is kept)")
    ap.add_argument("--no-current", action="store_true", help="only past weeks; skip the normal run for this week")
    ap.add_argument("--data-dir", default=str(run.ROOT / "docs" / "data"))
    ap.add_argument("--state-dir", default=str(run.ROOT / "state"))
    args = ap.parse_args(argv)

    passphrase = os.environ.get("SITE_PASSPHRASE")
    if not passphrase:
        raise SystemExit("SITE_PASSPHRASE is not set.")
    cfg = json.loads(run.CONFIG.read_text())
    bcfg = cfg.get("backfill", {})
    data, state = Path(args.data_dir), Path(args.state_dir)
    if args.reset:
        shutil.rmtree(data / "days", ignore_errors=True)
        (data / "index.json").unlink(missing_ok=True)
        (state / "state.json").unlink(missing_ok=True)
    store = run.Store(data, state, passphrase)

    # Week boundaries: Mondays 00:00 UTC. The last boundary is the most recent Monday at least a week old,
    # so the current week is left to the normal run with every source.
    now = datetime.now(timezone.utc)
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    last = monday - timedelta(days=7)
    edges = [int((last - timedelta(days=7 * i)).timestamp()) for i in range(args.weeks, -1, -1)]
    dates = [datetime.fromtimestamp(e, timezone.utc).strftime("%Y-%m-%d") for e in edges[1:]]
    todo = [i for i, d in enumerate(dates) if store.day(d) is None]
    run.log(f"[backfill] weeks ending {dates[0]} .. {dates[-1]}; {len(todo)} to do")

    if todo:
        lo = edges[todo[0]]
        sub_edges = edges[todo[0]:]
        http = sources.Http(delay=bcfg.get("delay_seconds", 0.7))
        t0 = time.time()
        weeks, note, errors = sources.reddit_history(cfg.get("reddit", {}), sub_edges, http, bcfg.get("pages_per_week", 2), run.log)
        run.log(f"[backfill] reddit: {note}; {len(errors)} errors; {round(time.time() - t0)}s")
        for k, i in enumerate(range(todo[0], len(dates))):
            if i not in todo:
                continue
            since, until, date = edges[i], edges[i + 1], dates[i]
            status = {"reddit": {"ok": bool(weeks[k]) or not errors, "count": len(weeks[k]),
                                 "note": "from the Arctic Shift archive; deleted and removed posts have no text"}}
            extra, st = run.collect(cfg, since, until, only={"hackernews", "stackexchange"})
            status.update(st)
            run.run_week(store, cfg, date, weeks[k] + extra, status, reply_budget=bcfg.get("replies_per_week", 40), backfilled=True)
            weeks[k] = None  # free memory

    if not args.no_current:
        run.log("[backfill] current week, all sources")
        since = time.time() - cfg.get("lookback_days", 8) * 86400
        raw, status = run.collect(cfg, since)
        run.run_week(store, cfg, now.strftime("%Y-%m-%d"), raw, status)


if __name__ == "__main__":
    main()
