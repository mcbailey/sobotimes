"""Prompts, JSON schemas and output cleaning for the two Gemini calls."""
from __future__ import annotations

import json
import re
from datetime import date

from .timeutil import date_from_title

# Bump when prompts or schemas change. Meetings summarized with an older
# version are redone when gemini.redo_outdated_summaries is on.
PROMPT_VERSION = "2026-10-13b"

CATEGORIES = [
    "Budget & taxes",
    "Schools",
    "Development & zoning",
    "Roads & infrastructure",
    "Public safety",
    "Parks, recreation & open space",
    "Environment & conservation",
    "Health & human services",
    "Town administration",
    "Other",
]
IMPORTANCE = ["high", "medium", "low"]
VOTE_RESULTS = ["passed", "failed", "tabled", "continued", "withdrawn", "other"]

TS_FORMAT = "H:MM:SS measured from the start of this recording, e.g. '0:05:12' or '1:46:54'"

# --------------------------------------------------------------------------
# Per-meeting summary
# --------------------------------------------------------------------------

MEETING_SYSTEM = """\
You summarize recorded public meetings of {town} town government for residents \
who will not watch the video. You write like a careful local civic reporter: \
neutral, specific, plain English, no opinion, no speculation.

Rules:
- Cover every substantive agenda item, in the order discussed. Fold purely \
routine business (approving minutes, accepting gifts, signing warrants, routine \
appointments, adjournment) into a single low-importance topic called "Routine business".
- Be concrete so readers rarely need to click: dollar amounts, addresses, \
project names, vote counts, deadlines, who is asking for what, and what happens next.
- Only state what is said or shown in the video. If audio is unclear or the \
recording is cut off, say so in "caveats". Never invent numbers, names or dates.
- Keep everything consistent. A topic's outcome, the votes list, the headline \
and the summary must agree. Use the exact action taken: "nominated" is not \
"elected", "continued" is not "closed", "discussed" is not "approved". If a \
hearing was continued, do not list a vote closing it.
- Votes: list each motion that was actually voted on, except adjournment and \
approving minutes. If there were no substantive votes, return an empty list.
- Upcoming: only dates and next steps for this body's own business (hearings, \
deadlines, future agenda items, Town Meeting). Leave out unrelated community events.
- Timestamps: every topic, vote and public comment needs a start time in \
{ts_format}. Use the moment discussion of that item begins. Readers use these \
links to check your summary, so be accurate.
- Refer to officials by role (the chair, the town administrator, a member of \
the board) and name them only when clearly stated. Never name members of the \
public; describe them generically (for example, "a resident of Main Street").
- Plain text only in every field: no Markdown, asterisks, == marks or bullet symbols.

Importance rubric:
- high: affects residents' money or services (budgets, taxes, overrides, fees, \
borrowing, contracts over roughly $50,000), schools, decisions on land use or \
major development (including 40B projects, zoning changes, permits for large \
projects), public safety, anything headed to Town Meeting or a ballot, \
significant votes, or items drawing substantial public comment or disagreement.
- medium: notable updates, discussions or smaller decisions residents may care about.
- low: routine or procedural items.
"""

MEETING_PROMPT = """\
Summarize this meeting video for residents.

Video title: {title}
{date_hint}Published on YouTube: {published}
Video length: {length}
Video description (may be empty or boilerplate):
{description}

Return JSON matching the schema. The headline and summary must not be empty. \
If the video is not a public government meeting (for example a concert, sports \
event or promotional clip), set is_public_meeting to false and leave the lists empty.
"""

_TS = {"type": "string", "description": f"Start time, {TS_FORMAT}."}

_TOPIC = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short, specific title, e.g. 'FY28 operating budget preview' (max ~10 words)."},
        "category": {"type": "string", "enum": CATEGORIES},
        "importance": {"type": "string", "enum": IMPORTANCE},
        "start": _TS,
        "summary": {"type": "string", "description": "2-4 sentences: what was discussed and why it matters."},
        "key_details": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Up to 5 concrete facts: amounts, addresses, dates, positions taken.",
        },
        "outcome": {"type": ["string", "null"], "description": "Decision, vote result or next step, consistent with the votes list. null if none."},
        "why_it_matters": {"type": ["string", "null"], "description": "For high-importance items: one sentence on the impact on residents. Otherwise null."},
    },
    "required": ["title", "category", "importance", "start", "summary", "key_details", "outcome", "why_it_matters"],
}

MEETING_SCHEMA = {
    "type": "object",
    "properties": {
        "is_public_meeting": {"type": "boolean"},
        "body": {"type": "string", "description": "Board or committee holding the meeting, e.g. 'Select Board'. For joint meetings name each body."},
        "meeting_date": {"type": ["string", "null"], "format": "date", "description": "Date the meeting took place, YYYY-MM-DD, or null if unknown."},
        "headline": {"type": "string", "description": "One sentence (max ~25 words): the most consequential thing a resident should know."},
        "summary": {"type": "string", "description": "3-5 sentence plain-English overview of the meeting."},
        "topics": {"type": "array", "items": _TOPIC},
        "votes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "motion": {"type": "string", "description": "What was moved, in plain words."},
                    "result": {"type": "string", "enum": VOTE_RESULTS},
                    "tally": {"type": ["string", "null"], "description": "e.g. '4-1', 'unanimous', or null."},
                    "time": {"type": "string", "description": f"When the vote was taken, {TS_FORMAT}."},
                },
                "required": ["motion", "result", "tally", "time"],
            },
        },
        "public_comment": {
            "type": "array",
            "description": "Notable comments from members of the public (unnamed).",
            "items": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "time": {"type": "string", "description": f"When the comment starts, {TS_FORMAT}."},
                },
                "required": ["summary", "time"],
            },
        },
        "upcoming": {
            "type": "array",
            "description": "Future dates, hearings, deadlines or follow-ups for this body's business.",
            "items": {
                "type": "object",
                "properties": {
                    "what": {"type": "string"},
                    "when": {"type": ["string", "null"], "description": "Date or timeframe as stated, e.g. 'October 21' or 'next month'."},
                },
                "required": ["what", "when"],
            },
        },
        "caveats": {"type": ["string", "null"], "description": "Recording problems or gaps, or null."},
    },
    "required": ["is_public_meeting", "body", "meeting_date", "headline", "summary", "topics", "votes", "public_comment", "upcoming", "caveats"],
}


def meeting_system(town: str) -> str:
    return MEETING_SYSTEM.format(town=town, ts_format=TS_FORMAT)


def meeting_prompt(video: dict, length: str) -> str:
    title = video.get("title", "")
    title_date = date_from_title(title)
    hint = ""
    if title_date:
        hint = f"Meeting date from the title: {title_date:%A, %B} {title_date.day}, {title_date.year}\n"
    elif video.get("published_at"):
        hint = f"The meeting took place in or shortly before {video['published_at'][:4]}.\n"
    return MEETING_PROMPT.format(
        title=title,
        date_hint=hint,
        published=video.get("published_at", "")[:10],
        length=length or "unknown",
        description=(video.get("description") or "").strip()[:1500] or "(none)",
    )


# --------------------------------------------------------------------------
# Weekly synopsis
# --------------------------------------------------------------------------

WEEK_SYSTEM = """\
You write the weekly overview for a site that summarizes {town} public meetings. \
You receive structured summaries of every meeting from one week. Write for a \
busy resident who reads only this overview.

Rules:
- Use only facts from the provided summaries. Do not add outside knowledge.
- Say a body voted, approved, advanced or decided something only if its votes \
or outcomes show it. Otherwise say it discussed or reviewed it.
- Lead with what most affects residents. Connect related items across meetings.
- Plain, neutral language. No hype, no opinion. Plain text only: no Markdown, \
asterisks or == marks.
- Each highlight must point to a real item: copy its video_id and start time \
exactly from the input.
"""

WEEK_PROMPT = """\
Week of {label}. {count} meeting(s) summarized below as JSON.

{payload}

Return JSON matching the schema:
- synopsis: 3-5 sentences covering the week.
- highlights: the 3-6 most important items across all meetings, most important first.
- looking_ahead: upcoming dates, hearings and decisions residents should watch for (may be empty).
"""

WEEK_SCHEMA = {
    "type": "object",
    "properties": {
        "synopsis": {"type": "string"},
        "highlights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short title, max ~10 words."},
                    "why": {"type": "string", "description": "One or two sentences with the key facts and why it matters."},
                    "body": {"type": "string", "description": "Board or committee where this came up."},
                    "importance": {"type": "string", "enum": IMPORTANCE},
                    "video_id": {"type": "string"},
                    "start": {"type": "string", "description": "The item's start time, copied from the input."},
                },
                "required": ["title", "why", "body", "importance", "video_id", "start"],
            },
        },
        "looking_ahead": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "what": {"type": "string"},
                    "when": {"type": ["string", "null"]},
                    "body": {"type": ["string", "null"]},
                },
                "required": ["what", "when", "body"],
            },
        },
    },
    "required": ["synopsis", "highlights", "looking_ahead"],
}


def week_system(town: str) -> str:
    return WEEK_SYSTEM.format(town=town)


def _ts_or_none(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def week_prompt(label: str, meetings: list[dict]) -> str:
    compact = []
    for m in meetings:
        s = m["summary"]
        compact.append(
            {
                "video_id": m["video"]["id"],
                "body": s.get("body"),
                "meeting_date": s.get("meeting_date"),
                "headline": s.get("headline"),
                "summary": s.get("summary"),
                "topics": [
                    {
                        "title": t.get("title"),
                        "importance": t.get("importance"),
                        "category": t.get("category"),
                        "start": _ts_or_none(t.get("start_seconds")),
                        "summary": t.get("summary"),
                        "key_details": t.get("key_details"),
                        "outcome": t.get("outcome"),
                    }
                    for t in s.get("topics", [])
                ],
                "votes": [
                    {"motion": v.get("motion"), "result": v.get("result"), "tally": v.get("tally")}
                    for v in s.get("votes", [])
                ],
                "upcoming": s.get("upcoming", []),
            }
        )
    return WEEK_PROMPT.format(label=label, count=len(meetings), payload=json.dumps(compact, ensure_ascii=False, indent=1))


# --------------------------------------------------------------------------
# Cleaning: never trust model output blindly
# --------------------------------------------------------------------------

_MARKUP = re.compile(r"\*\*|__|==|`|^#+\s*|^\s*[-*•]\s+", re.MULTILINE)


def _str(v, default: str = "") -> str:
    if not isinstance(v, str):
        return default
    return _MARKUP.sub("", v).strip() or default


def _opt_str(v) -> str | None:
    s = _str(v)
    return s or None


_TS_RX = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:\.\d+)?\s*$")


def parse_timestamp(v) -> int | None:
    """'1:46:54', '46:54', '0:05:12', 125, '125' -> seconds."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if s.isdigit():
        return int(s)
    m = _TS_RX.match(s)
    if not m:
        return None
    h, mnt, sec = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
    if sec >= 60 or (m.group(1) is not None and mnt >= 60):
        return None
    return h * 3600 + mnt * 60 + sec


def _seconds(v, duration: int | None) -> int | None:
    n = parse_timestamp(v)
    if n is None or n < 0:
        return None
    if duration and n > duration:
        return None
    return n


def _time_of(item: dict, *keys: str):
    for k in keys:
        if item.get(k) not in (None, ""):
            return item.get(k)
    return None


def _enum(v, allowed: list[str], default: str) -> str:
    s = _str(v).lower()
    for a in allowed:
        if a.lower() == s:
            return a
    return default


def clean_meeting(raw: dict, duration_s: int | None) -> dict:
    topics = []
    for t in raw.get("topics") or []:
        if not isinstance(t, dict) or not _str(t.get("title")):
            continue
        start = _seconds(_time_of(t, "start", "start_seconds"), duration_s)
        end = _seconds(_time_of(t, "end", "end_seconds"), duration_s)
        if start is not None and end is not None and end <= start:
            end = None
        topics.append(
            {
                "title": _str(t.get("title")),
                "category": _enum(t.get("category"), CATEGORIES, "Other"),
                "importance": _enum(t.get("importance"), IMPORTANCE, "medium"),
                "summary": _str(t.get("summary")),
                "key_details": [_str(d) for d in (t.get("key_details") or []) if _str(d)][:6],
                "outcome": _opt_str(t.get("outcome")),
                "why_it_matters": _opt_str(t.get("why_it_matters")),
                "start_seconds": start,
                "end_seconds": end,
            }
        )
    topics.sort(key=lambda t: (t["start_seconds"] is None, t["start_seconds"] or 0))

    votes = []
    for v in raw.get("votes") or []:
        if isinstance(v, dict) and _str(v.get("motion")):
            votes.append(
                {
                    "motion": _str(v.get("motion")),
                    "result": _enum(v.get("result"), VOTE_RESULTS, "other"),
                    "tally": _opt_str(v.get("tally")),
                    "start_seconds": _seconds(_time_of(v, "time", "start", "start_seconds"), duration_s),
                }
            )
    comments = [
        {"summary": _str(c.get("summary")), "start_seconds": _seconds(_time_of(c, "time", "start", "start_seconds"), duration_s)}
        for c in raw.get("public_comment") or []
        if isinstance(c, dict) and _str(c.get("summary"))
    ]
    upcoming = [
        {"what": _str(u.get("what")), "when": _opt_str(u.get("when"))}
        for u in raw.get("upcoming") or []
        if isinstance(u, dict) and _str(u.get("what"))
    ]
    headline = _str(raw.get("headline"))
    summary = _str(raw.get("summary"))
    if not headline and summary:  # never leave a meeting without a headline
        headline = re.split(r"(?<=[.!?])\s", summary, maxsplit=1)[0]
    return {
        "is_public_meeting": raw.get("is_public_meeting") is not False,
        "body": _str(raw.get("body"), "Town meeting"),
        "meeting_date": _opt_str(raw.get("meeting_date")),
        "headline": headline,
        "summary": summary,
        "topics": topics,
        "votes": votes,
        "public_comment": comments,
        "upcoming": upcoming,
        "caveats": _opt_str(raw.get("caveats")),
    }


def clean_week(raw: dict, meetings: list[dict]) -> dict:
    by_id = {m["video"]["id"]: m for m in meetings}
    highlights = []
    for h in raw.get("highlights") or []:
        if not isinstance(h, dict):
            continue
        vid = _str(h.get("video_id"))
        if vid not in by_id or not _str(h.get("title")):
            continue  # drop anything that does not point at a real meeting
        duration = by_id[vid]["video"].get("duration_s")
        highlights.append(
            {
                "title": _str(h.get("title")),
                "why": _str(h.get("why")),
                "body": _str(h.get("body")) or by_id[vid]["summary"].get("body", ""),
                "importance": _enum(h.get("importance"), IMPORTANCE, "medium"),
                "video_id": vid,
                "start_seconds": _seconds(_time_of(h, "start", "start_seconds"), duration),
            }
        )
    ahead = [
        {"what": _str(a.get("what")), "when": _opt_str(a.get("when")), "body": _opt_str(a.get("body"))}
        for a in raw.get("looking_ahead") or []
        if isinstance(a, dict) and _str(a.get("what"))
    ]
    return {"synopsis": _str(raw.get("synopsis")), "highlights": highlights[:6], "looking_ahead": ahead[:8]}


def valid_meeting_date(value: str | None, published: date) -> date | None:
    """Accept the model's meeting date only if it is plausible."""
    if not value:
        return None
    try:
        d = date.fromisoformat(value[:10])
    except ValueError:
        return None
    delta = (published - d).days
    return d if -1 <= delta <= 90 else None

