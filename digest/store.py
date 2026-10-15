"""Everything the pipeline remembers lives in data/ as plain JSON, committed to git.

data/state.json            video registry, daily usage ledger, last run info
data/meetings/<id>.json    one summary per meeting video
data/weeks/<monday>.json   one synopsis per week
data/links/<monday>.json   that week's topics tagged with issues, categories and dates
data/issues.json           every tracked issue: name, description, latest status
data/months/<YYYY-MM>.json one roll-up per month
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

STATE_VERSION = 1


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8")
    if not text.strip():  # an emptied file means "start fresh"
        return default
    try:
        return json.loads(text)
    except ValueError as e:
        raise SystemExit(f"{path} is not valid JSON ({e}). Fix it, or replace its contents with {{}} to start fresh.")


def _write_json(path: Path, obj: Any) -> None:
    """Atomic write so a killed run never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=False, sort_keys=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class Store:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)
        self.state_path = self.dir / "state.json"
        self.meetings_dir = self.dir / "meetings"
        self.weeks_dir = self.dir / "weeks"
        self.links_dir = self.dir / "links"
        self.months_dir = self.dir / "months"
        self.issues_path = self.dir / "issues.json"

    # --- state -----------------------------------------------------------
    def load_state(self) -> dict:
        state = _read_json(self.state_path, None) or {}
        state.setdefault("version", STATE_VERSION)
        state.setdefault("videos", {})
        state.setdefault("usage", {})
        state.setdefault("last_run", None)
        return state

    def save_state(self, state: dict) -> None:
        # Keep the usage ledger small: the last 60 days is plenty.
        usage = state.get("usage", {})
        for day in sorted(usage)[:-60]:
            usage.pop(day, None)
        _write_json(self.state_path, state)

    # --- meetings ----------------------------------------------------------
    def meeting_path(self, video_id: str) -> Path:
        return self.meetings_dir / f"{video_id}.json"

    def read_meeting(self, video_id: str) -> dict | None:
        return _read_json(self.meeting_path(video_id))

    def write_meeting(self, video_id: str, obj: dict) -> None:
        _write_json(self.meeting_path(video_id), obj)

    def delete_meeting(self, video_id: str) -> None:
        p = self.meeting_path(video_id)
        if p.exists():
            p.unlink()

    # --- weeks -------------------------------------------------------------
    def week_path(self, week_key: str) -> Path:
        return self.weeks_dir / f"{week_key}.json"

    def read_week(self, week_key: str) -> dict | None:
        return _read_json(self.week_path(week_key))

    def write_week(self, week_key: str, obj: dict) -> None:
        _write_json(self.week_path(week_key), obj)

    # --- links (issues, categories, dates for one week) ---------------------
    def read_links(self, week_key: str) -> dict | None:
        return _read_json(self.links_dir / f"{week_key}.json")

    def write_links(self, week_key: str, obj: dict) -> None:
        _write_json(self.links_dir / f"{week_key}.json", obj)

    def all_links(self) -> dict[str, dict]:
        if not self.links_dir.exists():
            return {}
        return {p.stem: _read_json(p, {}) for p in sorted(self.links_dir.glob("*.json"))}

    # --- issues --------------------------------------------------------------
    def load_issues(self) -> dict:
        """{issue_id: {id, name, description, category, status, status_as_of, ...}}"""
        return (_read_json(self.issues_path, None) or {}).get("issues", {})

    def save_issues(self, issues: dict) -> None:
        _write_json(self.issues_path, {"version": 1, "issues": dict(sorted(issues.items()))})

    # --- months --------------------------------------------------------------
    def read_month(self, month_key: str) -> dict | None:
        return _read_json(self.months_dir / f"{month_key}.json")

    def write_month(self, month_key: str, obj: dict) -> None:
        _write_json(self.months_dir / f"{month_key}.json", obj)
