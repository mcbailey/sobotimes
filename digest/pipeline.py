"""The daily run: discover -> pick within budget -> summarize -> weekly synopses."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from . import prompts
from .config import Config
from .gemini import GeminiError, RateLimited, TryLater, video_part
from .store import Store
from .timeutil import (
    date_from_title,
    fmt_duration,
    iso,
    local_date,
    parse_iso,
    quota_day,
    utcnow,
    week_label,
    week_start,
)
from .youtube import discover as youtube_discover

# Video statuses
QUEUED = "queued"          # waiting to be summarized
DONE = "done"              # summary written
SKIPPED = "skipped"        # title doesn't look like a meeting
NOT_MEETING = "not_meeting"  # Gemini said it isn't a government meeting
TOO_LONG = "too_long"      # longer than budget.max_video_minutes
FAILED = "failed"          # gave up after max_attempts

# Longest wait for a per-minute rate limit to clear before trying again.
MAX_LIMIT_WAIT_S = 120


class VideoDeferred(TryLater):
    """No model can take this particular video right now; move on to the next one."""


@dataclass
class RunReport:
    discovered: int = 0
    new: list[str] = field(default_factory=list)
    skipped_titles: list[str] = field(default_factory=list)
    summarized: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    refreshed: list[str] = field(default_factory=list)
    weeks_written: list[str] = field(default_factory=list)
    rate_limited: bool = False
    minutes_used: int = 0

    @property
    def had_errors(self) -> bool:
        return bool(self.errors)


def week_key_for(record: dict, tz: str) -> str:
    if record.get("meeting_date"):
        d = date.fromisoformat(record["meeting_date"])
    else:
        d = local_date(parse_iso(record["published_at"]), tz)
    return week_start(d).isoformat()


def _minutes(record: dict, cfg: Config) -> int:
    if record.get("duration_s"):
        return max(1, round(record["duration_s"] / 60))
    return cfg.budget.assumed_video_minutes


class Pipeline:
    def __init__(
        self,
        cfg: Config,
        store: Store,
        *,
        client=None,
        discover: Callable[..., list[dict]] | None = None,
        youtube_api_key: str | None = None,
        now: Callable[[], datetime] = utcnow,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        log: Callable[[str], None] = print,
    ):
        self.cfg = cfg
        self.store = store
        self.client = client
        self.discover_fn = discover or youtube_discover
        self.youtube_api_key = youtube_api_key
        self.now = now
        self.log = log
        import time

        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.exhausted: set[str] = set()  # models over their limit during this run

    # ------------------------------------------------------------------
    def run(self, *, dry_run: bool = False, max_videos: int | None = None, backfill_days: int | None = None) -> RunReport:
        cfg = self.cfg
        report = RunReport()
        state = self.store.load_state()
        started = self.clock()
        now = self.now()

        # 1. Discover --------------------------------------------------------
        days = backfill_days or cfg.discovery.backfill_days
        since = now - timedelta(days=days)
        try:
            found = self.discover_fn(cfg.channel.id, since, api_key=self.youtube_api_key, log=self.log)
        except Exception as e:  # discovery failure shouldn't stop the site from rebuilding
            report.errors.append(f"discovery failed: {e}")
            found = []
        report.discovered = len(found)
        self._register(state, [dict(f, channel=cfg.channel.id) for f in found], report)
        for extra in cfg.extra_channels:
            try:
                more = self.discover_fn(extra.id, since, api_key=self.youtube_api_key, log=self.log)
            except Exception as e:
                report.errors.append(f"discovery failed for {extra.name or extra.id}: {e}")
                continue
            # Only the titles we want from this channel; the rest never enter the state.
            wanted = [dict(f, channel=extra.id) for f in more if extra.wants(f["title"])]
            report.discovered += len(wanted)
            self._register(state, wanted, report)

        # 2. Pick what to summarize within today's budget --------------------
        day = quota_day(now)
        ledger = state["usage"].setdefault(day, {"video_minutes": 0, "calls": 0, "input_tokens": 0, "output_tokens": 0, "thought_tokens": 0, "tool_use_tokens": 0})
        remaining = cfg.budget.daily_video_minutes - ledger["video_minutes"]
        limit = max_videos if max_videos is not None else cfg.budget.max_videos_per_run
        min_age = timedelta(hours=cfg.discovery.min_age_hours)

        queue = sorted(
            (v for v in state["videos"].values() if v["status"] == QUEUED),
            key=lambda v: v["published_at"],
            reverse=True,
        )
        # Then refresh recent summaries written with older prompts, newest first.
        # The old summary stays on the site until the new one replaces it.
        if cfg.gemini.redo_outdated_summaries:
            queue += sorted(
                (
                    v for v in state["videos"].values()
                    if v["status"] == DONE
                    and v.get("prompt_version") != prompts.PROMPT_VERSION
                    and v.get("redo_skip") != prompts.PROMPT_VERSION
                    and parse_iso(v["published_at"]) >= since
                ),
                key=lambda v: v["published_at"],
                reverse=True,
            )
        picked = []
        for v in queue:
            tag = "refresh; " if v["status"] == DONE else ""
            if len(picked) >= limit:
                report.deferred.append(f"{v['title']} ({tag}run limit)")
                continue
            if v.get("live") in ("live", "upcoming", "not_public"):
                reason = "not public" if v["live"] == "not_public" else f"still {v['live']}"
                report.deferred.append(f"{v['title']} ({reason})")
                continue
            if now - parse_iso(v["published_at"]) < min_age:
                report.deferred.append(f"{v['title']} (published too recently)")
                continue
            mins = _minutes(v, cfg)
            if mins > remaining:
                report.deferred.append(
                    f"{v['title']} ({tag}needs {mins} min; only {max(0, remaining)} min of today's budget left after newer videos)"
                )
                continue
            picked.append(v)
            remaining -= mins

        if dry_run:
            for v in picked:
                verb = "refresh" if v["status"] == DONE else "summarize"
                self.log(f"[dry run] would {verb}: {v['title']} ({_minutes(v, cfg)} min)")
            for d in report.deferred:
                self.log(f"[dry run] deferred: {d}")
            return report

        # 3. Summarize ---------------------------------------------------------
        time_limit = cfg.budget.run_time_limit_minutes * 60
        for v in picked:
            if self.clock() - started > time_limit:
                report.deferred.append(f"{v['title']} (run time limit)")
                continue
            if self.client is None:
                raise RuntimeError("No Gemini client configured")
            mins = _minutes(v, cfg)
            refresh = v["status"] == DONE
            try:
                self._summarize(v, ledger)
                # Only successful work counts against the daily budget. If Google
                # counts failed attempts toward its own limit, it answers with a
                # 429, which stops the run below without penalizing any video.
                ledger["video_minutes"] += mins
                report.minutes_used += mins
                (report.refreshed if refresh else report.summarized).append(v["title"])
            except VideoDeferred as e:
                v["last_error"] = f"deferred: {e}"[:500]
                report.deferred.append(f"{v['title']} (too large for the models available right now; will retry next run)")
                self.log(f"  Deferring {v['id']}: {e}")
            except TryLater as e:
                report.rate_limited = True
                v["last_error"] = f"try later: {e}"[:500]
                remaining_titles = [p["title"] for p in picked[picked.index(v):]]
                report.deferred += [f"{t} (Gemini busy or limit reached; will retry next run)" for t in remaining_titles]
                self.log(f"Gemini asked us to try later; stopping this run. ({e})")
                self.store.save_state(state)
                break
            except (GeminiError, ValueError, KeyError) as e:
                v["last_error"] = str(e)[:500]
                if refresh:  # keep the existing summary; stop retrying after max_attempts
                    v["redo_attempts"] = v.get("redo_attempts", 0) + 1
                    if v["redo_attempts"] >= cfg.budget.max_attempts:
                        v["redo_skip"] = prompts.PROMPT_VERSION
                    self.log(f"Failed to refresh {v['id']} ({v['title']}); keeping the existing summary: {e}")
                    msg = f"{v['title']} (refresh): {e}"
                else:
                    v["attempts"] = v.get("attempts", 0) + 1
                    if v["attempts"] >= cfg.budget.max_attempts:
                        v["status"] = FAILED
                    self.log(f"Failed to summarize {v['id']} ({v['title']}): {e}")
                    msg = f"{v['title']}: {e}"
                report.errors.append(msg)
            self.store.save_state(state)  # keep progress even if the job is killed

        # 4. Weekly synopses ---------------------------------------------------
        if not report.rate_limited:
            self._update_weeks(state, report)

        state["last_run"] = {
            "at": iso(now),
            "discovered": report.discovered,
            "summarized": len(report.summarized),
            "refreshed": len(report.refreshed),
            "errors": len(report.errors),
        }
        self.store.save_state(state)
        return report

    # ------------------------------------------------------------------
    def _register(self, state: dict, found: list[dict], report: RunReport) -> None:
        cfg = self.cfg
        for f in found:
            rec = state["videos"].get(f["id"])
            if rec is None:
                ok, reason = cfg.discovery.classify(f["title"])
                dup = _duplicate_of(state, f, cfg.channel.id) if ok else None
                if dup:
                    ok, reason = False, f"same meeting as {dup['id']} ({dup['title']})"
                rec = {
                    "id": f["id"],
                    "title": f["title"],
                    "description": f.get("description", ""),
                    "published_at": f["published_at"],
                    "duration_s": f.get("duration_s"),
                    "live": f.get("live"),
                    "status": QUEUED if ok else SKIPPED,
                    "reason": reason,
                    "channel": f.get("channel", cfg.channel.id),
                    "attempts": 0,
                    "discovered_at": iso(self.now()),
                }
                title_date = date_from_title(f["title"])
                published = local_date(parse_iso(f["published_at"]), cfg.channel.timezone)
                if title_date and prompts.valid_meeting_date(title_date.isoformat(), published):
                    rec["meeting_date"] = title_date.isoformat()
                if ok and rec["duration_s"] and rec["duration_s"] > cfg.budget.max_video_minutes * 60:
                    rec["status"] = TOO_LONG
                    rec["reason"] = f"longer than {cfg.budget.max_video_minutes} minutes"
                rec["week"] = week_key_for(rec, cfg.channel.timezone)
                state["videos"][f["id"]] = rec
                report.new.append(f["title"])
                if rec["status"] == SKIPPED:
                    report.skipped_titles.append(f"{f['title']} ({reason})" if dup else f["title"])
            else:
                # Refresh fields that can change after upload.
                for k in ("title", "duration_s", "live"):
                    if f.get(k) is not None:
                        rec[k] = f[k]
                if (
                    rec["status"] == QUEUED
                    and rec.get("duration_s")
                    and rec["duration_s"] > cfg.budget.max_video_minutes * 60
                ):
                    rec["status"] = TOO_LONG
                    rec["reason"] = f"longer than {cfg.budget.max_video_minutes} minutes"

    # ------------------------------------------------------------------
    def _run_models(self, models: list[str], call):
        """Try each model in turn while Gemini says "busy" (503) or "over limit" (429).

        - Per-minute limit: wait for the window to clear (up to two minutes) and
          try the same model once more. If it still refuses, this request is too
          big for that model's per-minute allowance, so try the next model.
        - Daily limit: skip that model for the rest of the run, so we don't spend
          requests asking it again for every video.
        - Busy (503): try the next model.
        """
        candidates = [m for m in models if m not in self.exhausted]
        if not candidates:
            raise RateLimited("every configured model is over its daily limit for now")
        last: TryLater | None = None
        busy = too_big = False
        for i, model in enumerate(candidates):
            waited = False
            while True:
                try:
                    return model, call(model)
                except RateLimited as e:
                    last = e
                    if e.per_minute and not waited:
                        wait = min(MAX_LIMIT_WAIT_S, (e.retry_after or 60) + 3)
                        self.log(f"  {model} is over its per-minute limit; waiting {int(wait)}s and trying again")
                        self.sleep(wait)
                        waited = True
                        continue
                    if e.per_minute:
                        too_big = True
                        why = "still over its per-minute limit after waiting"
                    else:
                        self.exhausted.add(model)
                        why = "over its daily limit"
                except TryLater as e:
                    last = e
                    busy = True
                    why = "busy"
                break
            nxt = f"; trying {candidates[i + 1]}" if i + 1 < len(candidates) else ""
            self.log(f"  {model} is {why} ({last}){nxt}")
        if too_big and not busy:
            raise VideoDeferred(str(last))
        raise last

    # ------------------------------------------------------------------
    def _summarize(self, v: dict, ledger: dict) -> None:
        cfg = self.cfg
        g = cfg.gemini
        self.log(f"Summarizing {v['id']}: {v['title']}")
        modes = [g.video_processing]
        if g.video_processing == "agentic" and g.fallback_to_static:
            modes.append("static")
        models = [g.model] + [m for m in g.fallback_models if m != g.model]
        failures = []
        for mode in modes:
            try:
                used_model, result = self._run_models(models, lambda model: self.client.run(
                    model=model,
                    input=[
                        video_part(v["id"], mode, g.static_fps),
                        {"type": "text", "text": prompts.meeting_prompt(v, fmt_duration(v.get("duration_s")))},
                    ],
                    system_instruction=prompts.meeting_system(cfg.channel.town),
                    schema=prompts.MEETING_SCHEMA,
                    max_output_tokens=g.meeting_max_output_tokens,
                    thinking_level=g.thinking_level or None,
                    timeout_s=g.call_timeout_minutes * 60,
                ))
                _add_usage(ledger, result.usage)
                raw = result.json()
                break
            except TryLater:
                raise
            except GeminiError as e:
                failures.append(f"{mode} processing: {e}")
                if mode != modes[-1]:
                    self.log(f"  {mode} processing failed ({e}); retrying with {modes[-1]} processing")
        else:
            raise GeminiError(" | ".join(failures))
        summary = prompts.clean_meeting(raw, v.get("duration_s"))

        if not summary["is_public_meeting"]:
            v["status"] = NOT_MEETING
            v["reason"] = "Gemini reported this is not a public meeting"
            self.store.delete_meeting(v["id"])
            return
        if not summary["topics"] and not summary["summary"]:
            raise GeminiError("summary came back empty")

        published = local_date(parse_iso(v["published_at"]), cfg.channel.timezone)
        md = prompts.valid_meeting_date(summary.get("meeting_date"), published)
        if md:
            v["meeting_date"] = md.isoformat()
        summary["meeting_date"] = v.get("meeting_date")
        v["week"] = week_key_for(v, cfg.channel.timezone)

        self.store.write_meeting(
            v["id"],
            {
                "video": {
                    "id": v["id"],
                    "title": v["title"],
                    "published_at": v["published_at"],
                    "duration_s": v.get("duration_s"),
                },
                "summary": summary,
                "model": used_model,
                "processing": mode,
                "fallback_reason": failures[0] if failures else None,
                "prompt_version": prompts.PROMPT_VERSION,
                "processed_at": iso(self.now()),
                "usage": result.usage,
            },
        )
        v["status"] = DONE
        v["processed_at"] = iso(self.now())
        v["prompt_version"] = prompts.PROMPT_VERSION
        v["last_error"] = None
        v.pop("redo_attempts", None)

    # ------------------------------------------------------------------
    def _update_weeks(self, state: dict, report: RunReport) -> None:
        cfg = self.cfg
        if self.client is None:
            return
        by_week: dict[str, list[dict]] = {}
        for v in state["videos"].values():
            if v["status"] == DONE:
                v["week"] = week_key_for(v, cfg.channel.timezone)
                by_week.setdefault(v["week"], []).append(v)

        written = 0
        for week in sorted(by_week, reverse=True):
            vids = sorted(by_week[week], key=lambda r: r["id"])
            fingerprint = hashlib.sha256(
                json.dumps(
                    [prompts.PROMPT_VERSION, cfg.gemini.synthesis_model]
                    + [[r["id"], r.get("processed_at"), r.get("prompt_version")] for r in vids]
                ).encode()
            ).hexdigest()[:16]
            existing = self.store.read_week(week)
            if existing and existing.get("fingerprint") == fingerprint:
                continue
            if written >= cfg.budget.max_week_summaries_per_run:
                self.log(f"Week {week}: synopsis deferred (per-run cap)")
                continue
            meetings = [m for m in (self.store.read_meeting(r["id"]) for r in vids) if m]
            if not meetings:
                continue
            label = week_label(date.fromisoformat(week))
            self.log(f"Writing synopsis for week of {label} ({len(meetings)} meetings)")
            try:
                models = [cfg.gemini.synthesis_model] + [
                    m for m in cfg.gemini.fallback_models if m != cfg.gemini.synthesis_model
                ]
                used_model, result = self._run_models(models, lambda model: self.client.run(
                    model=model,
                    input=prompts.week_prompt(label, meetings),
                    system_instruction=prompts.week_system(cfg.channel.town),
                    schema=prompts.WEEK_SCHEMA,
                    max_output_tokens=cfg.gemini.week_max_output_tokens,
                    thinking_level=cfg.gemini.thinking_level or None,
                    timeout_s=cfg.gemini.call_timeout_minutes * 60,
                ))
                ledger = state["usage"].setdefault(quota_day(self.now()), {"video_minutes": 0, "calls": 0})
                _add_usage(ledger, result.usage)
                week_obj = prompts.clean_week(result.json(), meetings)
            except TryLater as e:
                report.rate_limited = True
                self.log(f"Rate limited while writing week synopses: {e}")
                return
            except (GeminiError, ValueError, KeyError) as e:
                report.errors.append(f"week {week}: {e}")
                self.log(f"Failed to write synopsis for week {week}: {e}")
                continue
            week_obj.update(
                {
                    "week": week,
                    "fingerprint": fingerprint,
                    "video_ids": [r["id"] for r in vids],
                    "model": used_model,
                    "generated_at": iso(self.now()),
                }
            )
            self.store.write_week(week, week_obj)
            report.weeks_written.append(week)
            written += 1


_NOISE = re.compile(r"\b(southborough|meeting|mtg|regular|special|remote|hybrid|of|the)\b|[^a-z ]", re.IGNORECASE)


def meeting_key(title: str) -> tuple | None:
    """(date in title, board name) so one meeting posted on two channels can be matched."""
    d = date_from_title(title)
    if not d:
        return None
    words = _NOISE.sub(" ", re.sub(r"\d+[/\-.]\d+[/\-.]\d+|\d{1,2},?\s*\d{4}", " ", title.lower()))
    for m in ("january", "february", "march", "april", "may", "june", "july", "august",
              "september", "october", "november", "december"):
        words = words.replace(m, " ")
    name = " ".join(words.split())
    return (d.isoformat(), name) if name else None


def _duplicate_of(state: dict, f: dict, primary: str) -> dict | None:
    """An already-known video from another channel that records the same meeting.

    Only compares across channels: one channel can legitimately post two
    recordings with the same title (for example, a mislabeled upload).
    """
    key = meeting_key(f["title"])
    if not key:
        return None
    channel = f.get("channel") or primary
    for v in state["videos"].values():
        if (v.get("channel") or primary) == channel or v["status"] == SKIPPED:
            continue
        if meeting_key(v["title"]) == key:
            return v
    return None


def _add_usage(ledger: dict, usage: dict) -> None:
    ledger["calls"] = ledger.get("calls", 0) + 1
    for src, dst in (
        ("total_input_tokens", "input_tokens"),
        ("total_output_tokens", "output_tokens"),
        ("total_thought_tokens", "thought_tokens"),
        ("total_tool_use_tokens", "tool_use_tokens"),
    ):
        try:
            ledger[dst] = ledger.get(dst, 0) + int(usage.get(src) or 0)
        except (TypeError, ValueError):
            pass
