"""Command line: python -m digest {run,build,status,requeue}"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import load_config
from .gemini import InteractionsClient
from .pipeline import DONE, QUEUED, Pipeline, RunReport
from .site import build_site
from .store import Store


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="digest", description="Weekly summaries of town meeting videos.")
    p.add_argument("--config", default="config.toml", help="path to config.toml")
    p.add_argument("--data", default="data", help="data directory (default: data)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="discover new videos, summarize them, update weekly synopses")
    r.add_argument("--dry-run", action="store_true", help="show what would be summarized; no Gemini calls")
    r.add_argument("--max-videos", type=int, default=None, help="override budget.max_videos_per_run")
    r.add_argument("--backfill-days", type=int, default=None, help="override discovery.backfill_days")

    b = sub.add_parser("build", help="render the static site")
    b.add_argument("--out", default="_site")
    b.add_argument("--banner", default=None, help="optional notice shown at the top of every page")

    sub.add_parser("status", help="show what the pipeline knows")

    q = sub.add_parser("requeue", help="summarize these videos again on the next run")
    q.add_argument("video_ids", nargs="+")

    args = p.parse_args(argv)
    cfg = load_config(args.config)
    store = Store(args.data)

    if args.cmd == "run":
        return _run(cfg, store, args)
    if args.cmd == "build":
        out = build_site(cfg, store, args.out, banner=args.banner)
        print(f"Site written to {out}")
        return 0
    if args.cmd == "status":
        return _status(store)
    if args.cmd == "requeue":
        state = store.load_state()
        for vid in args.video_ids:
            rec = state["videos"].get(vid)
            if not rec:
                print(f"Unknown video id: {vid}")
                continue
            rec.update(status=QUEUED, attempts=0, last_error=None)
            print(f"Requeued {vid}: {rec['title']}")
        store.save_state(state)
        return 0
    return 2


def _run(cfg, store: Store, args) -> int:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    client = None
    if not args.dry_run:
        if not api_key:
            print("GEMINI_API_KEY is not set. Add it as a repository secret (see README).", file=sys.stderr)
            return 1
        client = InteractionsClient(api_key, api_revision=cfg.gemini.api_revision)
    pipeline = Pipeline(
        cfg,
        store,
        client=client,
        youtube_api_key=os.environ.get("YOUTUBE_API_KEY", "").strip() or None,
    )
    report = pipeline.run(dry_run=args.dry_run, max_videos=args.max_videos, backfill_days=args.backfill_days)
    text = format_report(report, store)
    print(text)
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 1 if report.had_errors else 0


def format_report(report: RunReport, store: Store) -> str:
    state = store.load_state()
    lines = ["## Meeting digest run", ""]
    lines.append(f"- Videos found in the lookback window: {report.discovered}")
    lines.append(f"- New this run: {len(report.new)}")
    lines.append(f"- Summarized: {len(report.summarized)} ({report.minutes_used} video minutes)")
    lines.append(f"- Weekly synopses written: {len(report.weeks_written)}")
    if report.rate_limited:
        lines.append("- Stopped early: Gemini rate limit or daily quota reached. Remaining videos will be picked up next run.")
    if state.get("usage"):
        day = sorted(state["usage"])[-1]
        u = state["usage"][day]
        lines.append(
            f"- Usage for {day} (Pacific): {u.get('video_minutes', 0)} video minutes, {u.get('calls', 0)} calls, "
            f"{u.get('input_tokens', 0):,} input / {u.get('tool_use_tokens', 0):,} tool-use / "
            f"{u.get('output_tokens', 0):,} output tokens"
        )
    for title, items in (
        ("Summarized", report.summarized),
        ("Deferred", report.deferred),
        ("Skipped (title did not look like a meeting; adjust include/exclude patterns in config.toml if wrong)", report.skipped_titles),
        ("Errors", report.errors),
    ):
        if items:
            lines += ["", f"### {title}", ""] + [f"- {i}" for i in items]
    return "\n".join(lines)


def _status(store: Store) -> int:
    state = store.load_state()
    counts: dict[str, int] = {}
    for v in state["videos"].values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    print("Videos by status:", ", ".join(f"{k}={n}" for k, n in sorted(counts.items())) or "none")
    print("Last run:", state.get("last_run"))
    for v in sorted(state["videos"].values(), key=lambda r: r["published_at"], reverse=True)[:40]:
        flag = "" if v["status"] == DONE else f"  [{v['status']}{': ' + v['last_error'] if v.get('last_error') else ''}]"
        print(f"{v['published_at'][:10]}  {v['id']}  {v['title']}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
