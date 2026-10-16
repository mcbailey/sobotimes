"""Render the static site from data/ into an output folder.

Pages:
  /                       what's happening now: coming up, active issues, recent decisions, recent weeks
  /weeks/<monday>/        every meeting of one week, in full
  /months/                the archive, by month;  /months/<YYYY-MM>/  one month's roll-up
  /issues/                every tracked issue;    /issues/<id>/       one issue across boards and weeks
  /boards/                every board;            /boards/<slug>/     one board's meetings, issues, votes
  /decisions/             every vote, filterable
  /calendar/              dates mentioned in meetings, plus calendar.ics to subscribe
  /search/                full-text search (Pagefind index, built in CI)
  feed.xml, issues/<id>/feed.xml, boards/<slug>/feed.xml
"""
from __future__ import annotations

import hashlib
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import prompts
from .config import Config
from .pipeline import DONE, FAILED, QUEUED, TOO_LONG, week_key_for
from .store import Store
from .timeutil import (
    fmt_duration,
    fmt_hours,
    fmt_timestamp,
    local_date,
    long_date,
    month_label,
    parse_iso,
    resolve_when,
    short_date,
    utcnow,
    week_label,
)
from .youtube import watch_url

IMPORTANCE_RANK = {"high": 0, "medium": 1, "low": 2}
PKG_ROOT = Path(__file__).resolve().parent.parent

# How far the home page looks back and ahead.
RECENT_ISSUE_DAYS = 21
RECENT_DECISION_DAYS = 14
AHEAD_DAYS = 21
ACTIVE_ISSUE_DAYS = 45
# The event itself is a Town Meeting or an election ("Special Town Meeting at
# Trottier"), not something about one ("finalize the Town Meeting presentation",
# "Town Meeting warrant deadline").
BIG_EVENT = re.compile(
    r"^(?:the\s+)?(?:(?:fall|spring|special|annual|state|town|local|presidential|primary|\d{4})\s+)*"
    r"(?:town\s+meeting|election|primary)\b(?!\s+warrant)",
    re.IGNORECASE,
)


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


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def day_text(d: date) -> str:
    """'Sat, Oct 17'."""
    return short_date(d)


def day_long(d: date) -> str:
    """'Saturday, October 17'."""
    return f"{d:%A}, {d:%B} {d.day}"


# --------------------------------------------------------------------------
# Boards
# --------------------------------------------------------------------------

_BOARD_WORD = re.compile(r"\b(board|committee|commission|council|trust|trustees|department|authority|task force)\b", re.IGNORECASE)


def board_names(body: str, aliases: dict) -> list[str]:
    """Canonical board names for a meeting's body; a joint meeting gives several."""
    lower = {k.lower(): v for k, v in aliases.items()}

    def canon(name: str) -> str:
        n = re.sub(r"\s+", " ", name).strip(" .,;")
        n = re.sub(r"^(?:the\s+)?(?:town\s+of\s+)?southborough\s+", "", n, flags=re.IGNORECASE)
        n = re.sub(r"\s+meeting$", "", n, flags=re.IGNORECASE)
        return lower.get(n.lower(), n)

    body = (body or "").strip()
    if body.lower() in lower:
        return [lower[body.lower()]]
    parts = [p for p in re.split(r"\s*(?:,|&|\band\b)\s*(?=[A-Z])", body) if p.strip()]
    if len(parts) > 1 and all(_BOARD_WORD.search(p) for p in parts):
        names = [canon(p) for p in parts]
    else:
        names = [canon(body)]
    out: list[str] = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out or ["Town meeting"]


# --------------------------------------------------------------------------
# Meetings
# --------------------------------------------------------------------------

def _topic_view(t: dict, vid: str, idx: int, link: dict | None, issues: dict) -> dict:
    link = link or {}
    iid = link.get("issue")
    issue = issues.get(iid) if iid else None
    return {
        **t,
        "index": idx,
        "anchor": f"t-{vid}-{idx}",
        "ts": fmt_timestamp(t.get("start_seconds")),
        "watch": _watch_label(t.get("start_seconds")),
        "url": watch_url(vid, t.get("start_seconds")),
        "category": link.get("category") or prompts.CATEGORY_FALLBACK.get(t.get("category"), t.get("category") or "Other"),
        "issue": {"id": iid, "name": issue["name"]} if issue else None,
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


def _topic_at(topics: list[dict], seconds: int | None) -> dict | None:
    """The topic under discussion at a moment in the recording."""
    if seconds is None:
        return None
    best = None
    for t in topics:
        s = t.get("start_seconds")
        if s is not None and s <= seconds and (best is None or s >= best["start_seconds"]):
            best = t
    return best


def _meeting_view(m: dict, cfg: Config, links: dict, issues: dict) -> dict:
    tz = cfg.channel.timezone
    v, s = m["video"], m["summary"]
    vid = v["id"]
    published = local_date(parse_iso(v["published_at"]), tz)
    mdate = date.fromisoformat(s["meeting_date"]) if s.get("meeting_date") else published
    topic_links = links.get("topics") or {}
    topics = [
        _topic_view(t, vid, i, topic_links.get(prompts.topic_ref(vid, i)), issues)
        for i, t in enumerate(s.get("topics", []))
    ]
    boards = board_names(s.get("body") or v["title"], cfg.site.board_aliases)
    vote_links = links.get("votes")
    votes = []
    for i, x in enumerate(s.get("votes", [])):
        t = _topic_at(topics, x.get("start_seconds"))
        if vote_links is None:
            # Weeks linked before votes were tagged: use the topic under discussion.
            issue = t["issue"] if t else None
        else:
            iid = (vote_links.get(prompts.vote_ref(vid, i)) or {}).get("issue")
            issue = {"id": iid, "name": issues[iid]["name"]} if iid in issues else None
        if issue and issues.get(issue["id"], {}).get("category"):
            category = issues[issue["id"]]["category"]
        else:
            category = t["category"] if t else "Other"
        votes.append(
            {
                **x,
                "ts": fmt_timestamp(x.get("start_seconds")),
                "url": watch_url(vid, x.get("start_seconds")),
                "topic": t,
                "issue": issue,
                "category": category,
            }
        )
    events = []
    up_links = links.get("upcoming") or {}
    for i, u in enumerate(s.get("upcoming", [])):
        lk = up_links.get(prompts.upcoming_ref(vid, i)) or {}
        d = date.fromisoformat(lk["date"]) if lk.get("date") else resolve_when(u.get("when"), mdate)
        iid = lk.get("issue")
        events.append(
            {
                "what": u["what"],
                "when": u.get("when"),
                "date": d,
                "issue": {"id": iid, "name": issues[iid]["name"]} if iid in issues else None,
            }
        )
    return {
        "id": vid,
        "anchor": f"m-{vid}",
        "title": v["title"],
        "body": s.get("body") or v["title"],
        "boards": boards,
        "board_slugs": [prompts.slugify(b) for b in boards],
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
        "votes": votes,
        "public_comment": [
            {**x, "ts": fmt_timestamp(x.get("start_seconds")), "url": watch_url(vid, x.get("start_seconds"))}
            for x in s.get("public_comment", [])
        ],
        "upcoming": s.get("upcoming", []),
        "events": events,
        "caveats": s.get("caveats"),
        "high_count": sum(1 for t in topics if t["importance"] == "high"),
        "medium_count": sum(1 for t in topics if t["importance"] == "medium"),
    }


def _highlight_view(h: dict, meetings_by_id: dict, week_key: str) -> dict:
    m = meetings_by_id.get(h["video_id"])
    t = _topic_at(m["topics"], h.get("start_seconds")) if m else None
    if m and t is None and h.get("start_seconds") is None and m["topics"]:
        t = next((x for x in m["topics"] if x["title"] == h.get("title")), None)
    return {
        **h,
        "ts": fmt_timestamp(h.get("start_seconds")),
        "watch": _watch_label(h.get("start_seconds")),
        "url": watch_url(h["video_id"], h.get("start_seconds")),
        "week": week_key,
        "anchor": t["anchor"] if t else (m["anchor"] if m else None),
        "issue": t["issue"] if t else None,
    }


def collect_weeks(cfg: Config, store: Store, today: date | None = None) -> list[dict]:
    tz = cfg.channel.timezone
    state = store.load_state()
    issues = store.load_issues()
    all_links = store.all_links()
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
                mv = _meeting_view(m, cfg, all_links.get(key) or {}, issues)
                mv["week"] = key
                week(key)["meetings"].append(mv)
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
        by_id = {m["id"]: m for m in w["meetings"]}
        w["synopsis"] = stored.get("synopsis") or None
        w["headline"] = stored.get("headline") or prompts.first_sentence(stored.get("synopsis") or "")
        ahead = []
        for a in stored.get("looking_ahead", []):
            d = resolve_when(a.get("when"), w["start"] + timedelta(days=6)) if a.get("when") else None
            ahead.append({**a, "date": d, "past": bool(d and today and d < today)})
        w["looking_ahead"] = ahead
        highlights = [h for h in stored.get("highlights", []) if h.get("video_id") in by_id]
        if not highlights:  # fall back to the highest-importance topics
            highlights = [
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
            ][:5]
        # Key meetings: the ones the week's highlights point to, plus any with
        # several high-importance items. Almost every meeting has one "high"
        # item, so a single one isn't enough to stand out.
        picked = {h["video_id"] for h in highlights}
        w["meetings"].sort(key=lambda m: (m["id"] not in picked, *_significance(m)))
        for m in w["meetings"]:
            m["key"] = m["id"] in picked or m["high_count"] >= 2
        w["key_meetings"] = [m for m in w["meetings"] if m["key"]]
        w["other_meetings"] = [m for m in w["meetings"] if not m["key"]]
        w["highlights"] = [_highlight_view(h, by_id, key) for h in highlights]
        total = sum(m["duration_s"] for m in w["meetings"])
        bodies: list[str] = []
        for m in w["meetings"]:
            if m["body"] not in bodies:
                bodies.append(m["body"])
        n = len(w["meetings"])
        w["count"] = n
        w["hours_s"] = total
        w["bodies"] = bodies
        if n:
            hours = f" · {fmt_hours(total)} of video" if total else ""
            w["stats"] = f"{_plural(n, 'meeting')}{hours}"
            w["bodies_text"] = _join(bodies)
        else:
            w["stats"] = ""
            w["bodies_text"] = ""
        w["generated_at"] = stored.get("generated_at") if stored else None
        out.append(w)
    return out


# --------------------------------------------------------------------------
# Everything else is derived from the weeks
# --------------------------------------------------------------------------

def _words(text: str) -> set[str]:
    stop = {"the", "a", "an", "of", "for", "to", "on", "at", "and", "in", "meeting", "next", "with", "by"}
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in stop}


def _same_event(a: dict, b: dict) -> bool:
    if a["date"] != b["date"]:
        return False
    if a["big"] and b["big"]:
        return True
    wa, wb = _words(a["what"]), _words(b["what"])
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.5


def _clearer(a: str, b: str) -> bool:
    """For one Town Meeting mentioned several ways: prefer the wording that names the place, then the shortest."""
    return (" at " in a, -len(a)) > (" at " in b, -len(b))


def collect_events(meetings: list[dict]) -> list[dict]:
    """Every dated item mentioned in any meeting, with repeats folded together.

    The most recent mention wins, since it is the most current.
    """
    events: list[dict] = []
    for m in sorted(meetings, key=lambda m: m["date"], reverse=True):
        for e in m["events"]:
            if not e["date"]:
                continue
            mention = {"board": m["boards"][0], "date": m["date"], "week": m["week"], "anchor": m["anchor"]}
            item = {**e, "boards": list(m["boards"]), "mentions": [mention], "big": bool(BIG_EVENT.search(e["what"]))}
            for ex in events:
                if _same_event(ex, item):
                    if ex["big"] and _clearer(item["what"], ex["what"]):
                        ex["what"] = item["what"]
                    ex["mentions"].append(mention)
                    for b in item["boards"]:
                        if b not in ex["boards"]:
                            ex["boards"].append(b)
                    ex["issue"] = ex["issue"] or item["issue"]
                    break
            else:
                events.append(item)
    for e in events:
        e["day"] = day_text(e["date"])
        e["day_long"] = day_long(e["date"])
        e["board_slugs"] = [prompts.slugify(b) for b in e["boards"]]
    events.sort(key=lambda e: (e["date"], not e["big"], e["what"]))
    return events


def collect_decisions(meetings: list[dict]) -> list[dict]:
    rows = []
    for m in meetings:
        for v in m["votes"]:
            rows.append(
                {
                    **v,
                    "date": m["date"],
                    "day": short_date(m["date"]),
                    "month": m["date"].isoformat()[:7],
                    "board": m["boards"][0],
                    "boards": m["boards"],
                    "board_slug": m["board_slugs"][0],
                    "week": m["week"],
                    "meeting_anchor": m["anchor"],
                }
            )
    rows.sort(key=lambda r: (r["date"], r.get("start_seconds") or 0), reverse=True)
    return rows


def collect_issues(issues: dict, meetings: list[dict], events: list[dict], decisions: list[dict], today: date) -> list[dict]:
    views: dict[str, dict] = {}
    for iid, rec in issues.items():
        views[iid] = {**rec, "entries": [], "boards": [], "events": [], "votes": []}
    for m in meetings:
        for t in m["topics"]:
            if not t["issue"] or t["issue"]["id"] not in views:
                continue
            iv = views[t["issue"]["id"]]
            iv["entries"].append({"meeting": m, "topic": t})
            for b in m["boards"]:
                if b not in iv["boards"]:
                    iv["boards"].append(b)
    for e in events:
        if e["issue"] and e["issue"]["id"] in views and e["date"] >= today:
            views[e["issue"]["id"]]["events"].append(e)
    out = []
    for iv in views.values():
        if not iv["entries"]:
            continue  # tracked, but nothing on the site points at it any more
        iv["entries"].sort(key=lambda x: (x["meeting"]["date"], x["topic"].get("start_seconds") or 0), reverse=True)
        iv["votes"] = [d for d in decisions if d["issue"] and d["issue"]["id"] == iv["id"]]
        iv["meeting_count"] = len({x["meeting"]["id"] for x in iv["entries"]})
        iv["first_date"] = min(x["meeting"]["date"] for x in iv["entries"])
        iv["last_date"] = max(x["meeting"]["date"] for x in iv["entries"])
        iv["last_day"] = short_date(iv["last_date"])
        iv["first_day"] = short_date(iv["first_date"])
        iv["high_count"] = sum(1 for x in iv["entries"] if x["topic"]["importance"] == "high")
        iv["board_slugs"] = [prompts.slugify(b) for b in iv["boards"]]
        iv["next_event"] = iv["events"][0] if iv["events"] else None
        as_of = iv.get("status_as_of")
        iv["status_day"] = short_date(date.fromisoformat(as_of)) if as_of else None
        out.append(iv)
    out.sort(key=lambda i: (i["last_date"], i["high_count"]), reverse=True)
    return out


def collect_boards(meetings: list[dict], issues: list[dict], decisions: list[dict], events: list[dict], today: date) -> list[dict]:
    boards: dict[str, dict] = {}
    for m in sorted(meetings, key=lambda m: m["date"], reverse=True):
        for name, slug in zip(m["boards"], m["board_slugs"]):
            b = boards.setdefault(slug, {"name": name, "slug": slug, "meetings": [], "issues": [], "decisions": [], "events": []})
            b["meetings"].append(m)
    for iv in issues:
        for slug in iv["board_slugs"]:
            if slug in boards:
                boards[slug]["issues"].append(iv)
    for d in decisions:
        for name in d["boards"]:
            slug = prompts.slugify(name)
            if slug in boards:
                boards[slug]["decisions"].append(d)
    for e in events:
        if e["date"] < today:
            continue
        for slug in e["board_slugs"]:
            if slug in boards:
                boards[slug]["events"].append(e)
    out = []
    for b in boards.values():
        b["count"] = len(b["meetings"])
        b["hours_s"] = sum(m["duration_s"] for m in b["meetings"])
        b["hours"] = fmt_hours(b["hours_s"]) if b["hours_s"] else ""
        b["last_date"] = b["meetings"][0]["date"]
        b["last_day"] = short_date(b["last_date"])
        b["first_day"] = short_date(b["meetings"][-1]["date"])
        out.append(b)
    out.sort(key=lambda b: b["name"].lower())
    return out


def collect_months(store: Store, weeks: list[dict], meetings: list[dict], issues: list[dict], decisions: list[dict]) -> list[dict]:
    by_month: dict[str, dict] = {}
    for m in meetings:
        key = m["date"].isoformat()[:7]
        mo = by_month.setdefault(key, {"key": key, "label": month_label(key), "meetings": [], "weeks": []})
        mo["meetings"].append(m)
    for w in weeks:
        for key in sorted({m["date"].isoformat()[:7] for m in w["meetings"]}):
            by_month[key]["weeks"].append(w)
    out = []
    for key in sorted(by_month, reverse=True):
        mo = by_month[key]
        stored = store.read_month(key) or {}
        ids = {m["id"]: m for m in mo["meetings"]}
        mo["headline"] = stored.get("headline") or ""
        mo["synopsis"] = stored.get("synopsis") or ""
        items = [h for h in stored.get("top_items", []) if h.get("video_id") in ids]
        if not items:
            items = [
                {"title": t["title"], "why": t.get("why_it_matters") or t.get("summary", ""), "body": m["body"],
                 "importance": "high", "video_id": m["id"], "start_seconds": t.get("start_seconds")}
                for m in sorted(mo["meetings"], key=lambda m: m["date"]) for t in m["topics"] if t["importance"] == "high"
            ][:8]
        mo["top_items"] = [_highlight_view(h, ids, ids[h["video_id"]]["week"]) for h in items]
        mo["count"] = len(mo["meetings"])
        mo["hours_s"] = sum(m["duration_s"] for m in mo["meetings"])
        mo["stats"] = _plural(mo["count"], "meeting") + (f" · {fmt_hours(mo['hours_s'])} of video" if mo["hours_s"] else "")
        mo["decisions"] = [d for d in decisions if d["month"] == key]
        mo["issues"] = [
            iv for iv in issues
            if any(x["meeting"]["date"].isoformat()[:7] == key for x in iv["entries"])
        ]
        mo["weeks"].sort(key=lambda w: w["key"], reverse=True)
        out.append(mo)
    return out


# --------------------------------------------------------------------------
# Calendar file
# --------------------------------------------------------------------------

def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_fold(line: str) -> str:
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > 74:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    out.append(cur)
    return "\r\n".join(out)


def render_ics(events: list[dict], cfg: Config, base: str, stamp: datetime) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//{cfg.site.title}//Meeting calendar//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_ics_escape(cfg.site.title)}",
        f"X-WR-TIMEZONE:{cfg.channel.timezone}",
    ]
    dtstamp = stamp.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    for e in events:
        uid = hashlib.sha1(f"{e['date']}|{e['what']}".encode()).hexdigest()[:20]
        boards = ", ".join(e["boards"])
        first = e["mentions"][0]
        desc = f"Mentioned at the {first['board']} meeting on {long_date(first['date'])}."
        url = f"{base}/weeks/{first['week']}/#{first['anchor']}" if base else ""
        if e.get("when"):
            desc += f" As stated: {e['when']}."
        if url:
            desc += f" {url}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@{cfg.site.title}",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART;VALUE=DATE:{e['date']:%Y%m%d}",
            f"DTEND;VALUE=DATE:{e['date'] + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_ics_escape(e['what'] + (f' ({boards})' if boards else ''))}",
            f"DESCRIPTION:{_ics_escape(desc)}",
        ]
        if url:
            lines.append(f"URL:{url}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(line) for line in lines) + "\r\n"


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def build_site(cfg: Config, store: Store, out_dir: str | Path, *, banner: str | None = None, now: datetime | None = None) -> Path:
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    env = Environment(
        loader=FileSystemLoader(PKG_ROOT / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tz = ZoneInfo(cfg.channel.timezone)
    now = now or utcnow()
    today = now.astimezone(tz).date()
    state = store.load_state()

    weeks = collect_weeks(cfg, store, today)
    meetings = [m for w in weeks for m in w["meetings"]]
    events = collect_events(meetings)
    decisions = collect_decisions(meetings)
    issues = collect_issues(store.load_issues(), meetings, events, decisions, today)
    boards = collect_boards(meetings, issues, decisions, events, today)
    months = collect_months(store, weeks, meetings, issues, decisions)

    last = state.get("last_run") or {}
    updated = parse_iso(last["at"]).astimezone(tz) if last.get("at") else now.astimezone(tz)
    updated_text = f"{updated:%A}, {updated:%B} {updated.day} at {updated:%-I:%M %p}"
    base = cfg.site.base_url.rstrip("/")

    common = {
        "site": cfg.site,
        "site_base": (base + "/") if base else "/",
        "channel": cfg.channel,
        "channel_url": f"https://www.youtube.com/channel/{cfg.channel.id}",
        "sources": [{"name": cfg.channel.name, "url": f"https://www.youtube.com/channel/{cfg.channel.id}"}]
        + [{"name": c.name or c.id, "url": c.url} for c in cfg.extra_channels],
        "updated_text": updated_text,
        "banner": banner,
        "today": today,
        "categories": prompts.TOPIC_CATEGORIES,
        "has_issues": bool(issues),
    }

    def render(template: str, path: str, **ctx) -> None:
        depth = path.count("/")
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            env.get_template(template).render(root="../" * depth, **common, **ctx), encoding="utf-8"
        )

    visible = [w for w in weeks if w["count"] or w["pending"] or w["unavailable"]]

    # Home ----------------------------------------------------------------
    latest = max((m["date"] for m in meetings), default=today)
    upcoming = [e for e in events if today <= e["date"] <= today + timedelta(days=AHEAD_DAYS)]
    big = next((e for e in upcoming if e["big"] and e["date"] <= today + timedelta(days=14)), None)
    recent_issues = [i for i in issues if i["last_date"] >= latest - timedelta(days=RECENT_ISSUE_DAYS)]
    recent_issues.sort(key=lambda i: (-sum(1 for x in i["entries"] if x["meeting"]["date"] >= latest - timedelta(days=RECENT_ISSUE_DAYS) and x["topic"]["importance"] == "high"), -i["last_date"].toordinal()))
    recent_decisions = [
        d for d in decisions
        if d["date"] >= latest - timedelta(days=RECENT_DECISION_DAYS)
        and d["result"] in ("passed", "failed")
        and (d["topic"] is None or d["topic"]["importance"] != "low")
    ]
    render(
        "index.html", "index.html",
        weeks=visible[: min(cfg.site.max_weeks_on_index, 6)],
        more_weeks=len(visible) > 6,
        upcoming=upcoming[:8],
        more_upcoming=len([e for e in events if e["date"] >= today]) > 8,
        big_event=big,
        issues=recent_issues[:8],
        decisions=recent_decisions[:8],
        months=months[:6],
        has_content=bool(visible),
    )

    # Weeks ---------------------------------------------------------------
    for i, w in enumerate(visible):
        newer = visible[i - 1] if i > 0 else None
        older = visible[i + 1] if i + 1 < len(visible) else None
        render("week.html", f"weeks/{w['key']}/index.html", week=w, newer=newer, older=older,
               issue_counts={iv["id"]: iv["meeting_count"] for iv in issues})

    # Months --------------------------------------------------------------
    render("months.html", "months/index.html", months=months)
    for i, mo in enumerate(months):
        newer = months[i - 1] if i > 0 else None
        older = months[i + 1] if i + 1 < len(months) else None
        render("month.html", f"months/{mo['key']}/index.html", month=mo, newer=newer, older=older)

    # Issues --------------------------------------------------------------
    active_since = latest - timedelta(days=ACTIVE_ISSUE_DAYS)
    render(
        "issues.html", "issues/index.html",
        active=[i for i in issues if i["last_date"] >= active_since],
        earlier=[i for i in issues if i["last_date"] < active_since],
        used_categories=[c for c in prompts.TOPIC_CATEGORIES if any(i.get("category") == c for i in issues)],
    )
    for iv in issues:
        render("issue.html", f"issues/{iv['id']}/index.html", issue=iv)
        render_feed(env, out / "issues" / iv["id"] / "feed.xml", common, base,
                    title=f"{iv['name']} | {cfg.site.title}", rel=f"issues/{iv['id']}/",
                    items=[_topic_feed_item(x["meeting"], x["topic"], base) for x in iv["entries"][:30]],
                    updated=updated)

    # Boards --------------------------------------------------------------
    render("boards.html", "boards/index.html", boards=boards)
    for b in boards:
        render("board.html", f"boards/{b['slug']}/index.html", board=b)
        render_feed(env, out / "boards" / b["slug"] / "feed.xml", common, base,
                    title=f"{b['name']} | {cfg.site.title}", rel=f"boards/{b['slug']}/",
                    items=[_meeting_feed_item(m, base) for m in b["meetings"][:30]],
                    updated=updated)

    # Decisions, calendar, search -------------------------------------------
    dec_boards = sorted({d["board"] for d in decisions}, key=str.lower)
    render("decisions.html", "decisions/index.html", decisions=decisions, boards=dec_boards,
           used_categories=[c for c in prompts.TOPIC_CATEGORIES if any(d["category"] == c for d in decisions)])
    future = [e for e in events if e["date"] >= today]
    recent_past = [e for e in events if today - timedelta(days=14) <= e["date"] < today]
    by_month: list[dict] = []
    for e in future:
        key = e["date"].isoformat()[:7]
        if not by_month or by_month[-1]["key"] != key:
            by_month.append({"key": key, "label": month_label(key), "events": []})
        by_month[-1]["events"].append(e)
    render("calendar.html", "calendar/index.html", groups=by_month, recent_past=list(reversed(recent_past)))
    (out / "calendar.ics").write_text(render_ics(events[-300:], cfg, base, now), encoding="utf-8", newline="")
    render("search.html", "search/index.html")

    # Main feed -----------------------------------------------------------
    feed_weeks = [w for w in visible if w["count"]][:20]
    (out / "feed.xml").write_text(
        env.get_template("feed.xml").render(base=base, weeks=feed_weeks, updated=updated.isoformat(), **common),
        encoding="utf-8",
    )
    shutil.copy(PKG_ROOT / "static" / "style.css", out / "style.css")
    shutil.copy(PKG_ROOT / "static" / "site.js", out / "site.js")
    shutil.copytree(PKG_ROOT / "static" / "fonts", out / "fonts")
    shutil.copytree(PKG_ROOT / "static" / "brand", out / "brand")
    (out / ".nojekyll").write_text("")
    return out


def _meeting_time(m: dict) -> str:
    return datetime(m["date"].year, m["date"].month, m["date"].day, 12).isoformat() + "Z"


def _topic_feed_item(m: dict, t: dict, base: str) -> dict:
    text = t.get("summary") or ""
    if t.get("outcome"):
        text += f" Outcome: {t['outcome']}"
    return {
        "title": f"{m['boards'][0]}, {short_date(m['date'])}: {t['title']}",
        "url": f"{base}/weeks/{m['week']}/#{t['anchor']}",
        "id": f"{base or 'urn:meeting-digest'}/topics/{m['id']}/{t['index']}",
        "updated": _meeting_time(m),
        "summary": text,
    }


def _meeting_feed_item(m: dict, base: str) -> dict:
    return {
        "title": f"{m['body']}, {short_date(m['date'])}",
        "url": f"{base}/weeks/{m['week']}/#{m['anchor']}",
        "id": f"{base or 'urn:meeting-digest'}/meetings/{m['id']}",
        "updated": _meeting_time(m),
        "summary": m["headline"] + (" " + m["summary"] if m["summary"] else ""),
    }


def render_feed(env, target: Path, common: dict, base: str, *, title: str, rel: str, items: list[dict], updated: datetime) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        env.get_template("feed_items.xml").render(
            title=title, base=base, rel=rel, items=items, updated=updated.isoformat(), **common
        ),
        encoding="utf-8",
    )
