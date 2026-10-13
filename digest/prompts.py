"""Prompts, JSON schemas and output cleaning for the two Gemini calls."""
from __future__ import annotations

import json
from datetime import date

# Bump when prompts or schemas change in a way that should regenerate weeks.
PROMPT_VERSION = "2026-10-13"

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
appointments) into a single low-importance topic called "Routine business".
- Be concrete so readers rarely need to click: dollar amounts, addresses, \
project names, vote counts, deadlines, who is asking for what, and what happens next.
- Only state what is said or shown in the video. If audio is unclear or the \
recording is cut off, say so in "caveats". Never invent numbers or names.
- Refer to officials by role (the chair, the town administrator, a member of \
the board) and name them only when clearly stated. Never name members of the \
public; describe them generically (for example, "a resident of Main Street").
- start_seconds is the offset in the video, in whole seconds, where discussion \
of that item begins. It is used to deep-link readers into the video, so be accurate.

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
Published: {published}
Video length: {length}
Video description (may be empty or boilerplate):
{description}

Return JSON matching the schema. If the video is not a public government \
meeting (for example a concert, sports event or promotional clip), set \
is_public_meeting to false and leave the lists empty.
"""

_TOPIC = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short, specific title, e.g. 'FY28 operating budget preview' (max ~10 words)."},
        "category": {"type": "string", "enum": CATEGORIES},
        "importance": {"type": "string", "enum": IMPORTANCE},
        "summary": {"type": "string", "description": "2-4 sentences: what was discussed and why it matters."},
        "key_details": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Up to 5 concrete facts: amounts, addresses, dates, positions taken.",
        },
        "outcome": {"type": ["string", "null"], "description": "Decision, vote result or next step. null if none."},
        "why_it_matters": {"type": ["string", "null"], "description": "For high-importance items: one sentence on the impact on residents. Otherwise null."},
        "start_seconds": {"type": "integer", "description": "Offset in seconds where this item begins."},
        "end_seconds": {"type": ["integer", "null"], "description": "Offset in seconds where this item ends, if clear."},
    },
    "required": ["title", "category", "importance", "summary", "key_details", "outcome", "why_it_matters", "start_seconds", "end_seconds"],
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
                    "motion": {"type": "string"},
                    "result": {"type": "string", "enum": VOTE_RESULTS},
                    "tally": {"type": ["string", "null"], "description": "e.g. '4-1', 'unanimous', or null."},
                    "start_seconds": {"type": "integer"},
                },
                "required": ["motion", "result", "tally", "start_seconds"],
            },
        },
        "public_comment": {
            "type": "array",
            "description": "Notable comments from members of the public (unnamed).",
            "items": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "start_seconds": {"type": "integer"},
                },
                "required": ["summary", "start_seconds"],
            },
        },
        "upcoming": {
            "type": "array",
            "description": "Future dates, hearings, deadlines or follow-ups mentioned.",
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
    return MEETING_SYSTEM.format(town=town)


def meeting_prompt(video: dict, length: str) -> str:
    return MEETING_PROMPT.format(
        title=video.get("title", ""),
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
- Lead with what most affects residents. Connect related items across meetings.
- Plain, neutral language. No hype, no opinion.
- Each highlight must point to a real item: copy its video_id and start_seconds \
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
                    "start_seconds": {"type": "integer"},
                },
                "required": ["title", "why", "body", "importance", "video_id", "start_seconds"],
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
                        k: t.get(k)
                        for k in ("title", "importance", "category", "summary", "key_details", "outcome", "start_seconds")
                    }
                    for t in s.get("topics", [])
                ],
                "votes": s.get("votes", []),
                "upcoming": s.get("upcoming", []),
            }
        )
    return WEEK_PROMPT.format(label=label, count=len(meetings), payload=json.dumps(compact, ensure_ascii=False, indent=1))


# --------------------------------------------------------------------------
# Cleaning: never trust model output blindly
# --------------------------------------------------------------------------

def _str(v, default: str = "") -> str:
    return v.strip() if isinstance(v, str) else default


def _opt_str(v) -> str | None:
    s = _str(v)
    return s or None


def _seconds(v, duration: int | None) -> int | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    if duration and n > duration:
        return None
    return n


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
        start = _seconds(t.get("start_seconds"), duration_s)
        end = _seconds(t.get("end_seconds"), duration_s)
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
                    "start_seconds": _seconds(v.get("start_seconds"), duration_s),
                }
            )
    comments = [
        {"summary": _str(c.get("summary")), "start_seconds": _seconds(c.get("start_seconds"), duration_s)}
        for c in raw.get("public_comment") or []
        if isinstance(c, dict) and _str(c.get("summary"))
    ]
    upcoming = [
        {"what": _str(u.get("what")), "when": _opt_str(u.get("when"))}
        for u in raw.get("upcoming") or []
        if isinstance(u, dict) and _str(u.get("what"))
    ]
    return {
        "is_public_meeting": raw.get("is_public_meeting") is not False,
        "body": _str(raw.get("body"), "Town meeting"),
        "meeting_date": _opt_str(raw.get("meeting_date")),
        "headline": _str(raw.get("headline")),
        "summary": _str(raw.get("summary")),
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
                "start_seconds": _seconds(h.get("start_seconds"), duration),
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
