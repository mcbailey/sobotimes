"""Render the static site from data/ into an output folder."""
from __future__ import annotations

import shutil
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Config
from .pipeline import DONE, FAILED, QUEUED, TOO_LONG, week_key_for
from .store import Store
from .timeutil import (
    fmt_duration,
    fmt_hours,
    fmt_timestamp,
    local_date,
    long_date,
    parse_iso,
    short_date,
    utcnow,
    week_label,
)
from .youtube import watch_url

IMPORTANCE_RANK = {"high": 0, "medium": 1, "low": 2}
PKG_ROOT = Path(__file__).resolve().parent.parent


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def _watch_label(seconds: int | None) -> str | None:
    """Link text for a moment in a recording; 0:00 reads as 'from the start'."""
    if seconds is None:
        return None
    return "from the start" if seconds < 5 else f"at {fmt_timestamp(seconds)}"


def _topic_view(t: dict, vid: str, idx: int) -> dict:
    return {
        **t,
        "anchor": f"t-{vid}-{idx}",
        "ts": fmt_timestamp(t.get("start_seconds")),
        "watch": _watch_label(t.get("start_seconds")),
        "url": watch_url(vid, t.get("start_seconds")),
    }


def _significance(m: dict) -> tuple:
    """Sort key: meetings with more high-importance items and decisions first."""
    decided = sum(1 for v in m["votes"] if v.get("result") in ("passed", "failed"))
    score = 3 * m["high_count"] + m["medium_count"] + min(decided, 3)
    return (-score, -m["duration_s"], m["date"])


def _timeline(topics: list[dict], duration: int | None) -> dict | None:
    timed = [t for t in topics if t.get("start_seconds") is not None]
    if not timed:
        return None
    total = duration or (max(t["start_seconds"] for t in timed) + 600)
    segs = []
    for i, t in enumerate(timed):
        start = t["start_seconds"]
        nxt = timed[i + 1]["start_seconds"] if i + 1 < len(timed) else total
        end = t.get("end_seconds") or nxt
        end = max(start + 30, min(end, total))
        segs.append(
            {
                "left": round(100 * start / total, 3),
                "width": round(max(0.8, 100 * (end - start) / total), 3),
                "importance": t["importance"],
                "title": t["title"],
                "ts": t["ts"],
                "url": t["url"],
            }
        )
    return {"segments": segs, "end_label": fmt_timestamp(total)}


def _meeting_view(m: dict, tz: str) -> dict:
    v, s = m["video"], m["summary"]
    vid = v["id"]
    published = local_date(parse_iso(v["published_at"]), tz)
    mdate = date.fromisoformat(s["meeting_date"]) if s.get("meeting_date") else published
    topics = [_topic_view(t, vid, i) for i, t in enumerate(s.get("topics", []))]
    return {
        "id": vid,
        "anchor": f"m-{vid}",
        "title": v["title"],
        "body": s.get("body") or v["title"],
        "date": mdate,
        "date_long": long_date(mdate),
        "date_short": short_date(mdate),
        "date_known": bool(s.get("meeting_date")),
        "duration": fmt_duration(v.get("duration_s")),
        "duration_s": v.get("duration_s") or 0,
        "url": watch_url(vid),
        "headline": s.get("headline", ""),
        "summary": s.get("summary", ""),
        "main_topics": [t for t in topics if t["importance"] != "low"],
        "routine_topics": [t for t in topics if t["importance"] == "low"],
        "topics": topics,
        "timeline": _timeline(topics, v.get("duration_s")),
        "votes": [
            {**x, "ts": fmt_timestamp(x.get("start_seconds")), "url": watch_url(vid, x.get("start_seconds"))}
            for x in s.get("votes", [])
        ],
        "public_comment": [
            {**x, "ts": fmt_timestamp(x.get("start_seconds")), "url": watch_url(vid, x.get("start_seconds"))}
            for x in s.get("public_comment", [])
        ],
        "upcoming": s.get("upcoming", []),
        "caveats": s.get("caveats"),
        "high_count": sum(1 for t in topics if t["importance"] == "high"),
        "medium_count": sum(1 for t in topics if t["importance"] == "medium"),
    }


def collect_weeks(cfg: Config, store: Store) -> list[dict]:
    tz = cfg.channel.timezone
    state = store.load_state()
    weeks: dict[str, dict] = {}

    def week(key: str) -> dict:
        if key not in weeks:
            start = date.fromisoformat(key)
            weeks[key] = {
                "key": key,
                "start": start,
                "label": week_label(start),
                "meetings": [],
                "pending": [],
                "unavailable": [],
            }
        return weeks[key]

    for v in state["videos"].values():
        status = v["status"]
        key = v.get("week") or week_key_for(v, tz)
        published = local_date(parse_iso(v["published_at"]), tz)
        if status == DONE:
            m = store.read_meeting(v["id"])
            if m:
                week(key)["meetings"].append(_meeting_view(m, tz))
        elif status == QUEUED:
            week(key)["pending"].append({"title": v["title"], "url": watch_url(v["id"]), "date": short_date(published)})
        elif status in (FAILED, TOO_LONG):
            reason = (
                "This recording is longer than the automatic summarizer handles."
                if status == TOO_LONG
                else "The summarizer could not process this recording."
            )
            week(key)["unavailable"].append(
                {"title": v["title"], "url": watch_url(v["id"]), "date": short_date(published), "reason": reason}
            )

    out = []
    for key in sorted(weeks, reverse=True):
        w = weeks[key]
        stored = store.read_week(key) or {}
        current_ids = {m["id"] for m in w["meetings"]}
        w["synopsis"] = stored.get("synopsis") if stored else None
        w["looking_ahead"] = stored.get("looking_ahead", []) if stored else []
        highlights = [h for h in stored.get("highlights", []) if h.get("video_id") in current_ids] if stored else []
        if not highlights:  # fall back to the highest-importance topics
            pool = [
                {
                    "title": t["title"],
                    "why": t.get("why_it_matters") or t.get("summary", ""),
                    "body": m["body"],
                    "importance": t["importance"],
                    "video_id": m["id"],
                    "start_seconds": t.get("start_seconds"),
                }
                for m in w["meetings"]
                for t in m["topics"]
                if t["importance"] == "high"
            ]
            highlights = pool[:5]
        # Key meetings: the ones the week's highlights point to, plus any with
        # several high-importance items. Almost every meeting has one "high"
        # item, so a single one isn't enough to stand out.
        picked = {h["video_id"] for h in highlights}
        w["meetings"].sort(key=lambda m: (m["id"] not in picked, *_significance(m)))
        for m in w["meetings"]:
            m["key"] = m["id"] in picked or m["high_count"] >= 2
        w["key_meetings"] = [m for m in w["meetings"] if m["key"]]
        w["other_meetings"] = [m for m in w["meetings"] if not m["key"]]
        w["highlights"] = [
            {
                **h,
                "ts": fmt_timestamp(h.get("start_seconds")),
                "watch": _watch_label(h.get("start_seconds")),
                "url": watch_url(h["video_id"], h.get("start_seconds")),
            }
            for h in highlights
        ]
        total = sum(m["duration_s"] for m in w["meetings"])
        bodies: list[str] = []
        for m in w["meetings"]:
            if m["body"] not in bodies:
                bodies.append(m["body"])
        n = len(w["meetings"])
        w["count"] = n
        w["bodies"] = bodies
        if n:
            hours = f" · {fmt_hours(total)} of video" if total else ""
            w["stats"] = f"{n} meeting{'s' if n != 1 else ''}{hours}"
            w["bodies_text"] = _join(bodies)
        else:
            w["stats"] = ""
            w["bodies_text"] = ""
        w["generated_at"] = stored.get("generated_at") if stored else None
        out.append(w)
    return out


def build_site(cfg: Config, store: Store, out_dir: str | Path, *, banner: str | None = None, now: datetime | None = None) -> Path:
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    (out / "weeks").mkdir(parents=True)

    env = Environment(
        loader=FileSystemLoader(PKG_ROOT / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    weeks = collect_weeks(cfg, store)
    state = store.load_state()
    tz = ZoneInfo(cfg.channel.timezone)
    last = state.get("last_run") or {}
    updated = parse_iso(last["at"]).astimezone(tz) if last.get("at") else (now or utcnow()).astimezone(tz)
    updated_text = f"{updated:%A}, {updated:%B} {updated.day} at {updated:%-I:%M %p}"

    common = {
        "site": cfg.site,
        "site_base": (cfg.site.base_url.rstrip("/") + "/") if cfg.site.base_url else "/",
        "channel": cfg.channel,
        "channel_url": f"https://www.youtube.com/channel/{cfg.channel.id}",
        "sources": [{"name": cfg.channel.name, "url": f"https://www.youtube.com/channel/{cfg.channel.id}"}]
        + [{"name": c.name or c.id, "url": c.url} for c in cfg.extra_channels],
        "updated_text": updated_text,
        "banner": banner,
    }
    visible = [w for w in weeks if w["count"] or w["pending"] or w["unavailable"]]
    index_weeks = visible[: cfg.site.max_weeks_on_index]

    (out / "index.html").write_text(
        env.get_template("index.html").render(root="", weeks=index_weeks, **common), encoding="utf-8"
    )
    for i, w in enumerate(visible):
        newer = visible[i - 1] if i > 0 else None
        older = visible[i + 1] if i + 1 < len(visible) else None
        d = out / "weeks" / w["key"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(
            env.get_template("week.html").render(root="../../", week=w, newer=newer, older=older, **common),
            encoding="utf-8",
        )

    base = cfg.site.base_url.rstrip("/")
    feed_weeks = [w for w in visible if w["count"]][:20]
    (out / "feed.xml").write_text(
        env.get_template("feed.xml").render(
            base=base,
            weeks=feed_weeks,
            updated=updated.isoformat(),
            **common,
        ),
        encoding="utf-8",
    )
    shutil.copy(PKG_ROOT / "static" / "style.css", out / "style.css")
    shutil.copytree(PKG_ROOT / "static" / "fonts", out / "fonts")
    shutil.copytree(PKG_ROOT / "static" / "brand", out / "brand")
    (out / ".nojekyll").write_text("")
    return out
