"""Prompts, JSON schemas and output cleaning for the Gemini calls.

Four calls, one video call and three cheap text-only ones:
  meeting  watch one recording and summarize it
  week     write a week's synopsis from its meeting summaries
  links    tag a week's topics with ongoing issues, finer categories and real dates
  month    write a month's roll-up from its meetings and issues
"""
from __future__ import annotations

import json
import re
from datetime import date

from .timeutil import date_from_title

# Bump when prompts or schemas change. Meetings summarized with an older
# version are redone when gemini.redo_outdated_summaries is on.
PROMPT_VERSION = "2026-10-13b"
# The text-only calls have their own versions, so changing one doesn't mean
# re-watching any video.
WEEK_PROMPT_VERSION = "2026-10-15"
LINK_PROMPT_VERSION = "2026-10-16"
MONTH_PROMPT_VERSION = "2026-10-15"
ISSUE_PROMPT_VERSION = "2026-10-16"

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
# Finer categories, assigned by the links call. "Town administration" covered
# 40% of topics, too broad to filter by, so it is split up here.
TOPIC_CATEGORIES = [
    "Town Meeting & elections",
    "Budget & taxes",
    "Schools",
    "Zoning & development",
    "Housing",
    "Roads, water & infrastructure",
    "Buildings & facilities",
    "Public safety",
    "Parks, trails & recreation",
    "Environment & conservation",
    "Health & human services",
    "Library, arts & community",
    "Governance & committees",
    "Staffing & operations",
    "Other",
]
# Best guess for meetings that haven't been through the links call yet.
CATEGORY_FALLBACK = {
    "Budget & taxes": "Budget & taxes",
    "Schools": "Schools",
    "Development & zoning": "Zoning & development",
    "Roads & infrastructure": "Roads, water & infrastructure",
    "Public safety": "Public safety",
    "Parks, recreation & open space": "Parks, trails & recreation",
    "Environment & conservation": "Environment & conservation",
    "Health & human services": "Health & human services",
    "Town administration": "Governance & committees",
    "Other": "Other",
}
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
- headline: one sentence (max ~25 words), the single most important thing that happened.
- synopsis: 3-5 sentences covering the week.
- highlights: the 3-6 most important items across all meetings, most important first.
- looking_ahead: upcoming dates, hearings and decisions residents should watch for (may be empty).
"""

WEEK_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One sentence, max ~25 words."},
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
    "required": ["headline", "synopsis", "highlights", "looking_ahead"],
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


def clean_week(raw: dict, meetings: list[dict], limit: int = 6) -> dict:
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
    synopsis = _str(raw.get("synopsis"))
    headline = _str(raw.get("headline")) or first_sentence(synopsis)
    return {"headline": headline, "synopsis": synopsis, "highlights": highlights[:limit], "looking_ahead": ahead[:8]}


def first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s", text or "", maxsplit=1)[0]


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



# --------------------------------------------------------------------------
# Links: issues, categories and dates for one week's meetings (text only)
# --------------------------------------------------------------------------

LINK_SYSTEM = """\
You maintain the issue tracker for a site that summarizes {town} public \
meetings. Residents use it to follow one matter (a project, a property, a \
proposal, a budget item, a warrant article, a policy) across every board and \
week it comes up. You receive the list of issues already being tracked and \
the topics, votes and upcoming dates from one week's meetings.

For each topic:
- issue: the id of the tracked issue it belongs to. Reuse an existing issue \
whenever it is the same matter, even if it is worded differently or a \
different board is discussing it. If it is a substantive, specific matter that \
residents might follow and no issue fits, create one in new_issues. Use null \
for routine business, one-off administrative items and general updates.
- Keep issues specific: "Peninsula Trail pedestrian bridge" or "FY28 operating \
budget", never broad buckets like "Budget" or "Zoning". A single warrant \
article is its own issue, linked to the subject it funds or changes.
- category: the best fit from the allowed list.

For each vote, give the issue its motion is about, judged from the motion \
itself rather than from the topic it falls under: a block of votes on several \
warrant articles links each article's vote to that article's subject. Use null \
for procedural or routine motions (minutes, contracts for clerks, adjourning).

For each upcoming item, give its calendar date (YYYY-MM-DD) using the meeting \
date as the reference, or null if no specific day is stated ("next month", \
"in the spring"). Correct an obviously wrong year: a meeting in 2026 is not \
scheduling something in 2024. Link it to an issue when it clearly belongs to one.

For every issue that comes up this week, existing or new, write status: one \
or two plain sentences on where it stands after this week: the latest \
decision, where boards stand on it (which have recommended for or against, \
with tallies), and what happens next. Start from the issue's existing status \
and keep earlier positions that still hold unless this week changes them. \
Plain text, neutral, facts from the input only.
"""

LINK_PROMPT = """\
Week of {label}.

Issues already tracked (JSON):
{issues}

This week's meetings (JSON). Refer to topics, votes and upcoming items by their ref:
{payload}

Return JSON matching the schema. Every topic, vote and upcoming ref above \
must appear exactly once.
"""

_SLUG_DESC = "Lowercase words joined by hyphens, e.g. 'peninsula-trail-bridge'. Must be unique."

LINK_SCHEMA = {
    "type": "object",
    "properties": {
        "new_issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": _SLUG_DESC},
                    "name": {"type": "string", "description": "Short specific name, max ~7 words."},
                    "description": {"type": "string", "description": "One sentence: what this matter is."},
                    "category": {"type": "string", "enum": TOPIC_CATEGORIES},
                },
                "required": ["id", "name", "description", "category"],
            },
        },
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "issue": {"type": ["string", "null"], "description": "Issue id, existing or new, or null."},
                    "category": {"type": "string", "enum": TOPIC_CATEGORIES},
                },
                "required": ["ref", "issue", "category"],
            },
        },
        "votes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "issue": {"type": ["string", "null"], "description": "Issue id the motion is about, or null."},
                },
                "required": ["ref", "issue"],
            },
        },
        "upcoming": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "date": {"type": ["string", "null"], "format": "date", "description": "YYYY-MM-DD or null."},
                    "issue": {"type": ["string", "null"]},
                },
                "required": ["ref", "date", "issue"],
            },
        },
        "statuses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue": {"type": "string"},
                    "status": {"type": "string", "description": "One sentence: where it stands now and what is next."},
                },
                "required": ["issue", "status"],
            },
        },
    },
    "required": ["new_issues", "topics", "votes", "upcoming", "statuses"],
}


def link_system(town: str) -> str:
    return LINK_SYSTEM.format(town=town)


def topic_ref(video_id: str, index: int) -> str:
    return f"{video_id}#{index}"


def upcoming_ref(video_id: str, index: int) -> str:
    return f"{video_id}#u{index}"


def vote_ref(video_id: str, index: int) -> str:
    return f"{video_id}#v{index}"


def link_prompt(label: str, meetings: list[dict], issues: dict) -> str:
    tracked = [
        {"id": i["id"], "name": i["name"], "category": i.get("category"), "description": i.get("description"), "status": i.get("status")}
        for i in sorted(issues.values(), key=lambda i: i.get("last_seen") or "", reverse=True)
    ]
    compact = []
    for m in meetings:
        vid, s = m["video"]["id"], m["summary"]
        compact.append(
            {
                "body": s.get("body"),
                "meeting_date": s.get("meeting_date") or m["video"].get("published_at", "")[:10],
                "headline": s.get("headline"),
                "topics": [
                    {
                        "ref": topic_ref(vid, i),
                        "title": t.get("title"),
                        "category": t.get("category"),
                        "importance": t.get("importance"),
                        "summary": t.get("summary"),
                        "outcome": t.get("outcome"),
                    }
                    for i, t in enumerate(s.get("topics", []))
                ],
                "votes": [
                    {"ref": vote_ref(vid, i), "motion": x.get("motion"), "result": x.get("result"), "tally": x.get("tally")}
                    for i, x in enumerate(s.get("votes", []))
                ],
                "upcoming": [
                    {"ref": upcoming_ref(vid, i), "what": u.get("what"), "when": u.get("when")}
                    for i, u in enumerate(s.get("upcoming", []))
                ],
            }
        )
    return LINK_PROMPT.format(
        label=label,
        issues=json.dumps(tracked, ensure_ascii=False, indent=1) if tracked else "[] (none yet)",
        payload=json.dumps(compact, ensure_ascii=False, indent=1),
    )


_SLUG_BAD = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    slug = _SLUG_BAD.sub("-", (text or "").lower()).strip("-")
    return slug[:max_len].rstrip("-")


def clean_links(raw: dict, meetings: list[dict], issues: dict) -> dict:
    """Validate the links call. Returns {"topics", "votes", "upcoming", "new_issues", "statuses"}.

    Unknown refs are dropped, unknown issue ids become null, and dates outside
    what a meeting could plausibly point ahead to are dropped.
    """
    from .timeutil import plausible_ahead

    topic_refs, upcoming_refs, vote_refs = {}, {}, set()
    for m in meetings:
        vid, s = m["video"]["id"], m["summary"]
        ref_date = _meeting_date(m)
        for i, _ in enumerate(s.get("topics", [])):
            topic_refs[topic_ref(vid, i)] = ref_date
        for i, _ in enumerate(s.get("votes", [])):
            vote_refs.add(vote_ref(vid, i))
        for i, _ in enumerate(s.get("upcoming", [])):
            upcoming_refs[upcoming_ref(vid, i)] = ref_date

    new_issues: dict[str, dict] = {}
    renamed: dict[str, str] = {}
    for n in raw.get("new_issues") or []:
        if not isinstance(n, dict) or not _str(n.get("name")):
            continue
        given = _str(n.get("id"))
        slug = slugify(given) or slugify(n["name"])
        if not slug:
            continue
        if slug in issues:  # the model "created" one that already exists: reuse it
            renamed[given] = slug
            continue
        new_issues[slug] = {
            "id": slug,
            "name": _str(n.get("name")),
            "description": _str(n.get("description")),
            "category": _enum(n.get("category"), TOPIC_CATEGORIES, "Other"),
        }
        renamed[given] = slug
    known = set(issues) | set(new_issues)

    def issue_of(v) -> str | None:
        s = _str(v)
        if not s:
            return None
        s = renamed.get(s, s)
        s = s if s in known else slugify(s)
        return s if s in known else None

    topics = {}
    for t in raw.get("topics") or []:
        if isinstance(t, dict) and _str(t.get("ref")) in topic_refs:
            topics[_str(t["ref"])] = {
                "issue": issue_of(t.get("issue")),
                "category": _enum(t.get("category"), TOPIC_CATEGORIES, "Other"),
            }
    votes = {}
    for x in raw.get("votes") or []:
        if isinstance(x, dict) and _str(x.get("ref")) in vote_refs:
            votes[_str(x["ref"])] = {"issue": issue_of(x.get("issue"))}
    upcoming = {}
    for u in raw.get("upcoming") or []:
        if not isinstance(u, dict) or _str(u.get("ref")) not in upcoming_refs:
            continue
        ref = _str(u["ref"])
        d = None
        try:
            d = date.fromisoformat(_str(u.get("date"))[:10])
        except ValueError:
            pass
        if d and not plausible_ahead(d, upcoming_refs[ref]):
            d = None
        upcoming[ref] = {"date": d.isoformat() if d else None, "issue": issue_of(u.get("issue"))}

    used = {x["issue"] for part in (topics, votes, upcoming) for x in part.values() if x["issue"]}
    statuses = {}
    for st in raw.get("statuses") or []:
        if isinstance(st, dict):
            iid = issue_of(st.get("issue"))
            if iid and _str(st.get("status")):
                statuses[iid] = _str(st["status"])
    # Only keep new issues that something actually points at.
    new_issues = {k: v for k, v in new_issues.items() if k in used}
    return {"topics": topics, "votes": votes, "upcoming": upcoming, "new_issues": new_issues, "statuses": statuses}


def _meeting_date(m: dict) -> date:
    md = m["summary"].get("meeting_date") or m["video"].get("published_at", "")[:10]
    return date.fromisoformat(md[:10])


# --------------------------------------------------------------------------
# Where an issue stands (text only, one call per issue)
# --------------------------------------------------------------------------

ISSUE_SYSTEM = """\
You write the "Where it stands" box for one issue on a site that summarizes \
{town} public meetings. Residents read it to learn the current thinking on the \
matter from every board involved. Today is {today}.

You receive the issue's record grouped by board: each board's most recent \
discussions in full, its earlier ones in brief, every vote on the issue, \
public comment from those meetings, and dates mentioned for it.

Write about now, not the history:
- status: two to four plain sentences: where the matter stands today (for \
example approved, awaiting Town Meeting, under review, stalled), where the \
boards currently line up, the main open questions or concerns, and what \
happens next. Mention earlier events only when they explain the present, such \
as a board reversing itself or a plan changing substantially. A date that has \
passed is no longer "upcoming".
- positions: one entry for each board, committee or group whose current view \
the record shows, based on its most recent discussion or vote. stance is \
support, oppose, mixed, neutral or undecided. detail is one short sentence on \
its current thinking and the basis, such as "Voted 0-7 on Sep 16 to recommend \
against Article 4, citing the per-foot cost." If its view has shifted, say so \
briefly ("now opposes; supported the application in June"). Include residents \
as "Public comment" when comments on this matter were made, giving the range \
of views. Leave out boards that only heard updates without forming a view.
- next: the next scheduled step and its date, or an empty string if none is known.

Neutral tone. Facts from the input only: never infer a position that the \
record doesn't show. Comments listed as "other_comments_at_meeting" may be about \
other matters; use only those clearly about this issue.
"""

ISSUE_PROMPT = """\
Issue (JSON):
{issue}

Record (JSON):
{record}

Return JSON matching the schema.
"""

STANCES = ["support", "oppose", "mixed", "neutral", "undecided"]

ISSUE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "positions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "body": {"type": "string", "description": "Board, committee or group, e.g. 'Advisory Committee'."},
                    "stance": {"type": "string", "enum": STANCES},
                    "detail": {"type": "string"},
                },
                "required": ["body", "stance", "detail"],
            },
        },
        "next": {"type": "string"},
    },
    "required": ["status", "positions", "next"],
}


def issue_system(town: str, today: date) -> str:
    return ISSUE_SYSTEM.format(town=town, today=today.isoformat())


ISSUE_RECENT_PER_BOARD = 2


def issue_prompt(issue: dict, record: dict) -> str:
    """The record grouped by board: recent discussions in full, older ones in brief."""
    head = {k: issue.get(k) for k in ("name", "description", "category")}
    boards: dict[str, list[dict]] = {}
    for d in record["discussions"]:  # oldest first
        boards.setdefault(d["board"], []).append(d)
    by_board = []
    for board, ds in sorted(boards.items(), key=lambda kv: kv[1][-1]["date"], reverse=True):
        recent = ds[-ISSUE_RECENT_PER_BOARD:]
        earlier = [
            {k: d[k] for k in ("date", "title", "outcome") if d.get(k)}
            for d in ds[:-ISSUE_RECENT_PER_BOARD]
        ]
        entry = {"board": board, "latest": list(reversed([{k: v for k, v in d.items() if k != "board"} for d in recent]))}
        if earlier:
            entry["earlier"] = list(reversed(earlier))
        by_board.append(entry)
    shaped = {"by_board": by_board, "votes": list(reversed(record["votes"])), "dates": record["dates"]}
    return ISSUE_PROMPT.format(
        issue=json.dumps(head, ensure_ascii=False),
        record=json.dumps(shaped, ensure_ascii=False, indent=1),
    )


def clean_issue_status(raw: dict) -> dict:
    status = _str(raw.get("status"))
    if not status:
        raise ValueError("no status in response")
    positions = []
    for p in raw.get("positions") or []:
        if isinstance(p, dict) and _str(p.get("body")) and _str(p.get("detail")):
            positions.append(
                {"body": _str(p["body"]), "stance": _enum(p.get("stance"), STANCES, "undecided"), "detail": _str(p["detail"])}
            )
    return {"status": status, "positions": positions, "next": _str(raw.get("next"))}


# --------------------------------------------------------------------------
# Month roll-up (text only)
# --------------------------------------------------------------------------

MONTH_SYSTEM = """\
You write the monthly roll-up for a site that summarizes {town} public \
meetings, for residents who check in once a month. You receive one month's \
meeting summaries and the issues they touched.

Rules:
- Use only facts from the input. Say something was decided only if a vote or \
outcome shows it.
- Lead with what most affects residents: money, schools, development, Town \
Meeting, services. Follow an issue across boards rather than listing meetings.
- Plain, neutral language. Plain text only.
- Each top item must point to a real topic: copy its video_id and start time \
exactly from the input.
"""

MONTH_PROMPT = """\
{label}. {count} meeting(s), summarized below as JSON, with the issues they touched.

Issues:
{issues}

Meetings:
{payload}

Return JSON matching the schema:
- headline: one sentence (max ~25 words), the month's most important development.
- synopsis: 4-6 sentences covering the month.
- top_items: the 5-8 most important items of the month, most important first.
"""

MONTH_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "synopsis": {"type": "string"},
        "top_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short title, max ~10 words."},
                    "why": {"type": "string", "description": "One or two sentences with the key facts."},
                    "body": {"type": "string"},
                    "importance": {"type": "string", "enum": IMPORTANCE},
                    "issue": {"type": ["string", "null"], "description": "Issue id from the input, or null."},
                    "video_id": {"type": "string"},
                    "start": {"type": "string"},
                },
                "required": ["title", "why", "body", "importance", "issue", "video_id", "start"],
            },
        },
    },
    "required": ["headline", "synopsis", "top_items"],
}


def month_system(town: str) -> str:
    return MONTH_SYSTEM.format(town=town)


def month_prompt(label: str, meetings: list[dict], issues: dict, topic_issue: dict) -> str:
    """topic_issue maps topic refs to issue ids, from the links files."""
    touched = sorted({iid for iid in topic_issue.values() if iid and iid in issues})
    compact = []
    for m in sorted(meetings, key=lambda m: _meeting_date(m)):
        vid, s = m["video"]["id"], m["summary"]
        compact.append(
            {
                "video_id": vid,
                "body": s.get("body"),
                "meeting_date": _meeting_date(m).isoformat(),
                "headline": s.get("headline"),
                "topics": [
                    {
                        "title": t.get("title"),
                        "importance": t.get("importance"),
                        "issue": topic_issue.get(topic_ref(vid, i)),
                        "start": _ts_or_none(t.get("start_seconds")),
                        "summary": t.get("summary"),
                        "outcome": t.get("outcome"),
                    }
                    for i, t in enumerate(s.get("topics", []))
                    if t.get("importance") != "low"
                ],
                "votes": [
                    {"motion": v.get("motion"), "result": v.get("result"), "tally": v.get("tally")}
                    for v in s.get("votes", [])
                ],
            }
        )
    return MONTH_PROMPT.format(
        label=label,
        count=len(meetings),
        issues=json.dumps(
            [{"id": i, "name": issues[i]["name"], "status": issues[i].get("status")} for i in touched],
            ensure_ascii=False, indent=1,
        ),
        payload=json.dumps(compact, ensure_ascii=False, indent=1),
    )


def clean_month(raw: dict, meetings: list[dict], issues: dict) -> dict:
    week_like = clean_week({"highlights": raw.get("top_items")}, meetings, limit=8)
    items = []
    by_key = {}
    for h in raw.get("top_items") or []:
        if isinstance(h, dict):
            by_key[(_str(h.get("video_id")), _str(h.get("title")))] = h
    for h in week_like["highlights"]:
        src = by_key.get((h["video_id"], h["title"]), {})
        iid = _str(src.get("issue"))
        items.append({**h, "issue": iid if iid in issues else None})
    synopsis = _str(raw.get("synopsis"))
    return {
        "headline": _str(raw.get("headline")) or first_sentence(synopsis),
        "synopsis": synopsis,
        "top_items": items[:8],
    }
