"""Small date/time helpers."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Gemini API daily quotas reset at midnight Pacific time.
QUOTA_TZ = ZoneInfo("America/Los_Angeles")

_DURATION_RX = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+(?:\.\d+)?)S)?)?$"
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp (YouTube/Atom style) into an aware datetime."""
    ts = ts.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_duration(value: str | None) -> int | None:
    """Parse a YouTube ISO-8601 duration like 'PT2H13M5S' into seconds."""
    if not value:
        return None
    m = _DURATION_RX.match(value.strip())
    if not m:
        return None
    days = int(m.group("days") or 0)
    hours = int(m.group("h") or 0)
    minutes = int(m.group("m") or 0)
    seconds = float(m.group("s") or 0)
    total = int(days * 86400 + hours * 3600 + minutes * 60 + seconds)
    return total or None


def fmt_timestamp(seconds: int | None) -> str:
    """1:23:40 or 23:40."""
    if seconds is None:
        return ""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_duration(seconds: int | None) -> str:
    """'2 hr 13 min', '47 min'."""
    if not seconds:
        return ""
    minutes = round(seconds / 60)
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} hr {m} min"
    if h:
        return f"{h} hr"
    return f"{m} min"


def fmt_hours(seconds: int) -> str:
    """Total video time for a week, e.g. '7½ hours'."""
    hours = seconds / 3600
    if hours < 1:
        return f"{round(seconds / 60)} minutes"
    halves = round(hours * 2) / 2
    whole = int(halves)
    frac = "½" if halves - whole else ""
    unit = "hour" if halves == 1 else "hours"
    return f"{whole}{frac} {unit}"


def local_date(dt: datetime, tz: str) -> date:
    return dt.astimezone(ZoneInfo(tz)).date()


def quota_day(dt: datetime) -> str:
    return dt.astimezone(QUOTA_TZ).date().isoformat()


def week_start(d: date) -> date:
    """Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def week_label(start: date) -> str:
    """'October 5–11, 2026' or 'September 28 – October 4, 2026'."""
    end = start + timedelta(days=6)
    if start.year != end.year:
        return f"{start:%B} {start.day}, {start.year} – {end:%B} {end.day}, {end.year}"
    if start.month == end.month:
        return f"{start:%B} {start.day}–{end.day}, {end.year}"
    return f"{start:%B} {start.day} – {end:%B} {end.day}, {end.year}"


def short_date(d: date) -> str:
    """'Tue, Oct 6'."""
    return f"{d:%a}, {d:%b} {d.day}"


def long_date(d: date) -> str:
    """'Tuesday, October 6, 2026'."""
    return f"{d:%A}, {d:%B} {d.day}, {d.year}"


_TITLE_DATE_PATTERNS = [
    # 10/6/2026, 10-06-26, 10.6.26
    re.compile(r"\b(?P<m>\d{1,2})[/.\-](?P<d>\d{1,2})[/.\-](?P<y>\d{2,4})\b"),
    # 2026-10-06
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"),
]
_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"),
            ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"),
            ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"),
            ("nov", "november"), ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_WORD_DATE = re.compile(
    r"\b(?P<mon>[A-Za-z]{3,9})\.?\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y>\d{4})\b"
)


def date_from_title(title: str) -> date | None:
    """Best-effort meeting date from a video title."""
    for rx in _TITLE_DATE_PATTERNS:
        m = rx.search(title)
        if m:
            y = int(m.group("y"))
            if y < 100:
                y += 2000
            try:
                return date(y, int(m.group("m")), int(m.group("d")))
            except ValueError:
                continue
    m = _WORD_DATE.search(title)
    if m and m.group("mon").lower() in _MONTHS:
        try:
            return date(int(m.group("y")), _MONTHS[m.group("mon").lower()], int(m.group("d")))
        except ValueError:
            return None
    return None
