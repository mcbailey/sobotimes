"""Find recent uploads on the channel.

Two sources:
  * YouTube Data API v3 (when YOUTUBE_API_KEY is set) — full backfill window,
    durations, and live/upcoming status. Free; no billing account needed.
  * The channel's public RSS feed — no key needed, but only the latest ~15
    uploads and no durations.
"""
from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Iterable

from . import http
from .timeutil import iso, parse_duration, parse_iso

YT_API = "https://www.googleapis.com/youtube/v3"
RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


def discover(channel_id: str, since: datetime, api_key: str | None = None, log=print) -> list[dict]:
    """Return videos published at or after `since`, newest first.

    Each item: id, title, description, published_at (ISO UTC),
    duration_s (int|None), live ('none'|'live'|'upcoming'|None), source.
    """
    if api_key:
        videos = list(_via_data_api(channel_id, since, api_key))
    else:
        log("No YOUTUBE_API_KEY set: using the RSS feed (latest ~15 uploads, no durations).")
        videos = [v for v in _via_rss(channel_id) if parse_iso(v["published_at"]) >= since]
    videos.sort(key=lambda v: v["published_at"], reverse=True)
    return videos


# --- YouTube Data API --------------------------------------------------------

def _via_data_api(channel_id: str, since: datetime, api_key: str) -> Iterable[dict]:
    uploads = "UU" + channel_id[2:]
    found: dict[str, dict] = {}
    page_token = None
    for _ in range(20):  # 20 pages x 50 = far more than any backfill window needs
        params = {
            "part": "contentDetails,snippet",
            "playlistId": uploads,
            "maxResults": 50,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        data = http.get_json(f"{YT_API}/playlistItems?{urllib.parse.urlencode(params)}")
        oldest_on_page = None
        for item in data.get("items", []):
            cd = item.get("contentDetails", {})
            sn = item.get("snippet", {})
            vid = cd.get("videoId")
            published = cd.get("videoPublishedAt") or sn.get("publishedAt")
            if not vid or not published:
                continue  # private or deleted video
            pub_dt = parse_iso(published)
            oldest_on_page = pub_dt if oldest_on_page is None else min(oldest_on_page, pub_dt)
            if pub_dt < since:
                continue
            found[vid] = {
                "id": vid,
                "title": sn.get("title", "").strip(),
                "description": (sn.get("description") or "")[:3000],
                "published_at": iso(pub_dt),
                "duration_s": None,
                "live": None,
                "source": "youtube-api",
            }
        page_token = data.get("nextPageToken")
        if not page_token or (oldest_on_page is not None and oldest_on_page < since):
            break

    ids = list(found)
    for i in range(0, len(ids), 50):
        batch = ids[i : i + 50]
        params = {
            "part": "contentDetails,snippet,status",
            "id": ",".join(batch),
            "key": api_key,
        }
        data = http.get_json(f"{YT_API}/videos?{urllib.parse.urlencode(params)}")
        for item in data.get("items", []):
            v = found.get(item.get("id"))
            if not v:
                continue
            v["duration_s"] = parse_duration(item.get("contentDetails", {}).get("duration"))
            v["live"] = item.get("snippet", {}).get("liveBroadcastContent", "none")
            status = item.get("status", {})
            if status.get("privacyStatus") not in (None, "public"):
                v["live"] = "not_public"
    return found.values()


# --- RSS ---------------------------------------------------------------------

def _via_rss(channel_id: str) -> list[dict]:
    raw = http.request("GET", RSS_URL.format(channel_id=channel_id))
    return parse_rss(raw)


def parse_rss(raw: bytes | str) -> list[dict]:
    root = ET.fromstring(raw)
    out = []
    for entry in root.findall("atom:entry", _NS):
        vid = entry.findtext("yt:videoId", default="", namespaces=_NS)
        title = entry.findtext("atom:title", default="", namespaces=_NS)
        published = entry.findtext("atom:published", default="", namespaces=_NS)
        desc = entry.findtext("media:group/media:description", default="", namespaces=_NS)
        if not vid or not published:
            continue
        out.append(
            {
                "id": vid,
                "title": title.strip(),
                "description": (desc or "")[:3000],
                "published_at": iso(parse_iso(published)),
                "duration_s": None,
                "live": None,
                "source": "rss",
            }
        )
    return out


def watch_url(video_id: str, seconds: int | None = None) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    if seconds:
        url += f"&t={int(seconds)}s"
    return url
