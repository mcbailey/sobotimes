"""End-to-end tests with a fake Gemini client and fake YouTube discovery.

Run with:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sample_data  # noqa: E402
from digest import gemini, http, prompts, timeutil, youtube  # noqa: E402
from digest.config import DiscoveryConfig, load_config  # noqa: E402
from digest.gemini import GeminiError, InteractionsClient, RateLimited, Result, TryLater  # noqa: E402
from digest.pipeline import DONE, FAILED, NOT_MEETING, QUEUED, SKIPPED, TOO_LONG, Pipeline  # noqa: E402
from digest.site import build_site  # noqa: E402
from digest.store import Store  # noqa: E402

NOW = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)  # Tue Oct 13, noon Eastern


class FakeClient:
    def __init__(self, fail_ids=(), ratelimit_ids=(), agentic_fail_ids=(), busy_ids=(), busy_models=()):
        self.busy_models = set(busy_models)
        self.calls = []
        self.modes = []
        self.fail_ids = set(fail_ids)
        self.ratelimit_ids = set(ratelimit_ids)
        self.agentic_fail_ids = set(agentic_fail_ids)
        self.busy_ids = set(busy_ids)

    def run(self, **kw):
        self.calls.append(kw)
        if kw["model"] in self.busy_models:
            raise TryLater("503: The model is currently experiencing high demand")
        inp = kw["input"]
        usage = {"total_input_tokens": 1000, "total_output_tokens": 500, "total_tool_use_tokens": 20000}
        if isinstance(inp, list):  # a video summary request
            vid = inp[0]["uri"].split("v=")[1]
            proc = inp[0]["processing"]
            mode = proc if isinstance(proc, str) else proc["type"]
            self.modes.append((vid, mode))
            assert kw["schema"] is prompts.MEETING_SCHEMA
            if vid in self.ratelimit_ids:
                raise RateLimited("quota exceeded")
            if vid in self.busy_ids:
                raise TryLater("503: The model is currently experiencing high demand")
            if vid in self.agentic_fail_ids and mode == "agentic":
                raise GeminiError("interaction failed: agentic processing unavailable")
            if vid in self.fail_ids:
                raise GeminiError("500: backend error")
            raw = sample_data.SUMMARIES.get(vid) or {
                "is_public_meeting": False, "body": "", "meeting_date": None, "headline": "", "summary": "",
                "topics": [], "votes": [], "public_comment": [], "upcoming": [], "caveats": None,
            }
            return Result(text=json.dumps(raw), usage=usage, interaction_id=f"i-{vid}")
        # a weekly synopsis request
        assert kw["schema"] is prompts.WEEK_SCHEMA
        for week in sample_data.WEEKS.values():
            if any(h["video_id"] in inp for h in week["highlights"]):
                return Result(text="```json\n" + json.dumps(week) + "\n```", usage=usage)
        return Result(text=json.dumps({"synopsis": "A quiet week.", "highlights": [], "looking_ahead": []}), usage=usage)


def fake_discover(videos):
    def _discover(channel_id, since, api_key=None, log=print):
        return [dict(v, source="test") for v in videos if timeutil.parse_iso(v["published_at"]) >= since]
    return _discover


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 1
        return self.t


MIXED_CHANNEL_PATTERNS = [r"\bboard\b", r"\bcommittee\b", r"\bcommission\b", r"\bmeeting\b", r"\bZBA\b"]


def make_pipeline(tmp, client, videos=None, **budget):
    cfg = load_config(ROOT / "config.toml")
    # Tests model a channel that mixes meetings with other videos.
    cfg.discovery = DiscoveryConfig(
        backfill_days=28, min_age_hours=3,
        include_patterns=MIXED_CHANNEL_PATTERNS, exclude_patterns=cfg.discovery.exclude_patterns,
    )
    for k, v in budget.items():
        setattr(cfg.budget, k, v)
    store = Store(Path(tmp) / "data")
    p = Pipeline(
        cfg, store, client=client,
        discover=fake_discover(videos if videos is not None else sample_data.VIDEOS),
        now=lambda: NOW, clock=Clock(), log=lambda *_: None,
    )
    return cfg, store, p


class PipelineTests(unittest.TestCase):
    def test_first_run_classifies_and_summarizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            cfg, store, p = make_pipeline(tmp, client, daily_video_minutes=10_000, max_videos_per_run=20)
            report = p.run()
            videos = store.load_state()["videos"]
            self.assertEqual(videos["sampleHF2026"]["status"], SKIPPED)        # title not a meeting
            self.assertEqual(videos["sampleBH0930"]["status"], TOO_LONG)       # 6 hours
            self.assertEqual(videos["sampleSB1013"]["status"], QUEUED)         # published 6h ago... see min_age
            for vid in sample_data.SUMMARIES:
                self.assertEqual(videos[vid]["status"], DONE, vid)
            self.assertEqual(len(report.summarized), len(sample_data.SUMMARIES))
            self.assertFalse(report.errors)
            self.assertIn("2026-10-05", report.weeks_written)
            self.assertIn("2026-09-28", report.weeks_written)
            self.assertEqual(videos["sampleSB1006"]["week"], "2026-10-05")
            self.assertEqual(videos["sampleSB0929"]["week"], "2026-09-28")

    def test_recent_upload_waits_for_min_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            cfg, store, p = make_pipeline(tmp, client, daily_video_minutes=10_000, max_videos_per_run=20)
            cfg.discovery.min_age_hours = 12
            report = p.run()
            self.assertTrue(any("published too recently" in d for d in report.deferred))
            self.assertEqual(store.load_state()["videos"]["sampleSB1013"]["status"], QUEUED)

    def test_daily_budget_and_run_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            cfg, store, p = make_pipeline(tmp, client, daily_video_minutes=300, max_videos_per_run=20)
            report = p.run()
            self.assertLessEqual(report.minutes_used, 300)
            state = store.load_state()
            day = timeutil.quota_day(NOW)
            self.assertLessEqual(state["usage"][day]["video_minutes"], 300)
            self.assertTrue(any("of today's budget left" in d for d in report.deferred))

            # A second run the same day must not exceed the budget either.
            report2 = p.run()
            self.assertLessEqual(store.load_state()["usage"][day]["video_minutes"], 300)
            self.assertEqual(report2.minutes_used + report.minutes_used, store.load_state()["usage"][day]["video_minutes"])

    def test_failures_retry_then_give_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(fail_ids={"samplePB1007"})
            cfg, store, p = make_pipeline(tmp, client, daily_video_minutes=10_000, max_videos_per_run=20, max_attempts=2)
            r1 = p.run()
            self.assertTrue(r1.had_errors)
            rec = store.load_state()["videos"]["samplePB1007"]
            self.assertEqual((rec["status"], rec["attempts"]), (QUEUED, 1))
            p.run()
            rec = store.load_state()["videos"]["samplePB1007"]
            self.assertEqual((rec["status"], rec["attempts"]), (FAILED, 2))
            calls_before = len(client.calls)
            p.run()
            self.assertFalse(any(
                isinstance(c["input"], list) and "samplePB1007" in c["input"][0]["uri"] for c in client.calls[calls_before:]
            ))

    def test_rate_limit_stops_without_penalty(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Newest eligible video is sampleSC1008; make it rate-limited.
            client = FakeClient(ratelimit_ids={"sampleSC1008"})
            cfg, store, p = make_pipeline(tmp, client, daily_video_minutes=10_000, max_videos_per_run=20)
            report = p.run()
            self.assertTrue(report.rate_limited)
            self.assertEqual(report.summarized, [])
            rec = store.load_state()["videos"]["sampleSC1008"]
            self.assertEqual((rec["status"], rec["attempts"]), (QUEUED, 0))
            self.assertEqual(store.load_state()["usage"][timeutil.quota_day(NOW)]["video_minutes"], 0)

    def test_agentic_failure_falls_back_to_static(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(agentic_fail_ids={"sampleSB1006"})
            cfg, store, p = make_pipeline(tmp, client, daily_video_minutes=10_000, max_videos_per_run=20)
            report = p.run()
            self.assertFalse(report.errors)
            self.assertEqual(store.load_state()["videos"]["sampleSB1006"]["status"], DONE)
            m = store.read_meeting("sampleSB1006")
            self.assertEqual(m["processing"], "static")
            self.assertIn("agentic", m["fallback_reason"])
            self.assertEqual([md for v, md in client.modes if v == "sampleSB1006"], ["agentic", "static"])
            self.assertEqual(store.read_meeting("samplePB1007")["processing"], "agentic")

    def test_busy_gemini_stops_without_penalty_or_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(busy_ids={"sampleSC1008"})
            cfg, store, p = make_pipeline(tmp, client, daily_video_minutes=10_000, max_videos_per_run=20)
            report = p.run()
            self.assertTrue(report.rate_limited)
            self.assertFalse(report.had_errors)
            state = store.load_state()
            rec = state["videos"]["sampleSC1008"]
            self.assertEqual((rec["status"], rec["attempts"]), (QUEUED, 0))
            self.assertEqual(state["usage"][timeutil.quota_day(NOW)]["video_minutes"], 0)
            self.assertTrue(any("will retry next run" in d for d in report.deferred))
            # Next run, Gemini is healthy again: everything gets done.
            client.busy_ids.clear()
            report2 = p.run()
            self.assertEqual(len(report2.summarized), len(sample_data.SUMMARIES))

    def test_busy_model_falls_back_to_next_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(busy_models={"gemini-3.8-flash"})
            cfg, store, p = make_pipeline(tmp, client, daily_video_minutes=10_000, max_videos_per_run=20)
            report = p.run()
            self.assertFalse(report.rate_limited)
            self.assertEqual(len(report.summarized), len(sample_data.SUMMARIES))
            self.assertEqual(store.read_meeting("sampleSB1006")["model"], "gemini-3.6-flash")
            self.assertIn("2026-10-05", report.weeks_written)

    def test_failures_do_not_use_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(fail_ids={"sampleSC1008"})
            cfg, store, p = make_pipeline(tmp, client, daily_video_minutes=10_000, max_videos_per_run=20)
            report = p.run()
            used = store.load_state()["usage"][timeutil.quota_day(NOW)]["video_minutes"]
            self.assertEqual(used, report.minutes_used)
            expected = sum(round(v["duration_s"] / 60) for v in sample_data.VIDEOS if v["id"] in sample_data.SUMMARIES and v["id"] != "sampleSC1008")
            self.assertEqual(used, expected)

    def test_weeks_only_regenerate_when_meetings_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            cfg, store, p = make_pipeline(tmp, client, daily_video_minutes=10_000, max_videos_per_run=20)
            p.run()
            n = len(client.calls)
            report = p.run()
            self.assertEqual(report.weeks_written, [])
            self.assertEqual(len(client.calls), n)  # nothing new: no calls at all

    def test_not_a_meeting(self):
        with tempfile.TemporaryDirectory() as tmp:
            odd = dict(sample_data.VIDEOS[0], id="sampleXX0001", title="Town Meeting Night Highlights Reel",
                       published_at="2026-10-10T10:00:00Z")
            client = FakeClient()
            cfg, store, p = make_pipeline(tmp, client, videos=[odd], daily_video_minutes=10_000)
            p.run()
            self.assertEqual(store.load_state()["videos"]["sampleXX0001"]["status"], NOT_MEETING)
            self.assertIsNone(store.read_meeting("sampleXX0001"))

    def test_dry_run_makes_no_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            cfg, store, p = make_pipeline(tmp, client, daily_video_minutes=10_000)
            p.run(dry_run=True)
            self.assertEqual(client.calls, [])


class SiteTests(unittest.TestCase):
    def test_build_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            cfg, store, p = make_pipeline(tmp, client, daily_video_minutes=10_000, max_videos_per_run=20)
            p.run()
            out = build_site(cfg, store, Path(tmp) / "_site", banner="Sample data")
            index = (out / "index.html").read_text()
            self.assertIn("October 5–11, 2026", index)
            self.assertIn("<mark>FY28 budget guidance adopted</mark>", index)
            self.assertIn("watch?v=sampleSB1006&amp;t=540s", index)
            self.assertIn("waiting to be summarized", index)           # sampleSB1013 pending
            self.assertNotIn("Harvest Fair", index)
            week = (out / "weeks" / "2026-10-05" / "index.html").read_text()
            self.assertIn("Route 85 sidewalk reconstruction contract", week)
            self.assertIn("Routine business (1 item)", week)
            self.assertIn('class="seg is-high"', week)
            older = (out / "weeks" / "2026-09-28" / "index.html").read_text()
            self.assertIn("longer than the automatic summarizer handles", older)   # Board of Health
            feed = (out / "feed.xml").read_text()
            import xml.etree.ElementTree as ET
            ET.fromstring(feed)  # well-formed
            self.assertIn("Week of October 5–11, 2026", feed)

    def test_empty_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(ROOT / "config.toml")
            out = build_site(cfg, Store(Path(tmp) / "data"), Path(tmp) / "_site")
            self.assertIn("No meetings summarized yet", (out / "index.html").read_text())


class UnitTests(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(timeutil.parse_duration("PT2H13M5S"), 7985)
        self.assertEqual(timeutil.parse_duration("PT45M"), 2700)
        self.assertIsNone(timeutil.parse_duration("P0D"))
        self.assertIsNone(timeutil.parse_duration("bogus"))

    def test_formatting(self):
        self.assertEqual(timeutil.fmt_timestamp(5025), "1:23:45")
        self.assertEqual(timeutil.fmt_timestamp(540), "9:00")
        self.assertEqual(timeutil.fmt_hours(27000), "7½ hours")
        self.assertEqual(timeutil.week_label(date(2026, 9, 28)), "September 28 – October 4, 2026")
        self.assertEqual(timeutil.week_label(date(2026, 10, 5)), "October 5–11, 2026")

    def test_date_from_title(self):
        self.assertEqual(timeutil.date_from_title("Select Board Meeting 10/6/2026"), date(2026, 10, 6))
        self.assertEqual(timeutil.date_from_title("Planning Board 10-7-26"), date(2026, 10, 7))
        self.assertEqual(timeutil.date_from_title("School Committee Meeting October 8, 2026"), date(2026, 10, 8))
        self.assertIsNone(timeutil.date_from_title("Planning Board"))

    def test_valid_meeting_date(self):
        pub = date(2026, 10, 9)
        self.assertEqual(prompts.valid_meeting_date("2026-10-07", pub), date(2026, 10, 7))
        self.assertIsNone(prompts.valid_meeting_date("2024-10-07", pub))   # implausible year
        self.assertIsNone(prompts.valid_meeting_date("2026-11-07", pub))   # in the future

    def test_classify(self):
        cfg = load_config(ROOT / "config.toml")
        # Default config: every title counts unless it hits an exclude pattern.
        self.assertTrue(cfg.discovery.classify("Advisory Committee 10/8/26")[0])
        self.assertTrue(cfg.discovery.classify("Housing Production Plan workshop")[0])
        self.assertFalse(cfg.discovery.classify("Algonquin Football vs Shrewsbury")[0])
        cfg.discovery = DiscoveryConfig(include_patterns=MIXED_CHANNEL_PATTERNS, exclude_patterns=cfg.discovery.exclude_patterns)
        self.assertFalse(cfg.discovery.classify("Southborough Harvest Fair 2026 Highlights")[0])
        self.assertTrue(cfg.discovery.classify("Select Board Meeting 10/6/2026")[0])
        self.assertTrue(cfg.discovery.classify("ZBA 10/1")[0])
        self.assertFalse(cfg.discovery.classify("Algonquin Football vs Shrewsbury")[0])
        self.assertFalse(cfg.discovery.classify("Holiday Concert 2026")[0])

    def test_clean_meeting_drops_bad_values(self):
        raw = dict(sample_data.SUMMARIES["samplePB1007"])
        raw["topics"] = [
            {"title": "Ok", "category": "Schools", "importance": "HIGH", "summary": "s", "key_details": [],
             "outcome": "", "why_it_matters": None, "start_seconds": 100, "end_seconds": 50},
            {"title": "Past the end", "category": "Nonsense", "importance": "urgent", "summary": "s",
             "key_details": ["a", ""], "start_seconds": 999999},
            {"title": "", "summary": "no title"},
        ]
        clean = prompts.clean_meeting(raw, duration_s=6720)
        self.assertEqual(len(clean["topics"]), 2)
        ok, bad = clean["topics"]
        self.assertEqual((ok["importance"], ok["end_seconds"], ok["outcome"]), ("high", None, None))
        self.assertEqual((bad["category"], bad["importance"], bad["start_seconds"]), ("Other", "medium", None))
        self.assertEqual(bad["key_details"], ["a"])

    def test_clean_week_drops_unknown_videos(self):
        meetings = [{"video": {"id": "sampleSB1006", "duration_s": 9660}, "summary": {"body": "Select Board"}}]
        raw = {"synopsis": "x", "highlights": [
            {"title": "real", "why": "w", "body": "", "importance": "high", "video_id": "sampleSB1006", "start_seconds": 540},
            {"title": "made up", "why": "w", "body": "", "importance": "high", "video_id": "nope", "start_seconds": 1},
        ], "looking_ahead": []}
        week = prompts.clean_week(raw, meetings)
        self.assertEqual([h["title"] for h in week["highlights"]], ["real"])
        self.assertEqual(week["highlights"][0]["body"], "Select Board")

    def test_parse_rss(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <id>yt:video:abc123def45</id>
  <yt:videoId>abc123def45</yt:videoId>
  <title>Select Board Meeting 10/6/2026</title>
  <published>2026-10-08T13:00:00+00:00</published>
  <media:group><media:description>Agenda items</media:description></media:group>
 </entry>
</feed>"""
        items = youtube.parse_rss(xml)
        self.assertEqual(items[0]["id"], "abc123def45")
        self.assertEqual(items[0]["published_at"], "2026-10-08T13:00:00Z")
        self.assertEqual(items[0]["description"], "Agenda items")


class GeminiClientTests(unittest.TestCase):
    def setUp(self):
        self._orig = http.request

    def tearDown(self):
        http.request = self._orig

    def test_background_polling_and_output_text(self):
        responses = [
            {"id": "int-1", "status": "in_progress"},
            {"id": "int-1", "status": "in_progress"},
            {"id": "int-1", "status": "completed",
             "steps": [
                 {"type": "thought", "summary": []},
                 {"type": "model_output", "content": [{"type": "text", "text": '{"a": '}, {"type": "text", "text": "1}"}]},
             ],
             "usage": {"total_input_tokens": 10, "total_output_tokens": 3}},
        ]
        sent = []

        def fake_request(method, url, headers=None, body=None, **kw):
            sent.append((method, url, headers, body))
            return json.dumps(responses.pop(0)).encode()

        http.request = fake_request
        sleeps = []
        client = InteractionsClient("k", sleep=sleeps.append, clock=lambda: 0)
        res = client.run(model="gemini-3.8-flash", input="hi", schema={"type": "object"},
                         max_output_tokens=100, thinking_level="low")
        self.assertEqual(res.json(), {"a": 1})
        self.assertEqual(res.usage["total_input_tokens"], 10)
        method, url, headers, body = sent[0]
        self.assertEqual((method, url.endswith("/interactions")), ("POST", True))
        self.assertEqual(headers["x-goog-api-key"], "k")
        self.assertTrue(body["background"])
        self.assertEqual(body["response_format"]["mime_type"], "application/json")
        self.assertEqual(body["generation_config"], {"max_output_tokens": 100, "thinking_level": "low"})
        self.assertTrue(sent[1][1].endswith("/interactions/int-1"))
        self.assertEqual(sleeps, [10.0, 15.0])

    def test_http_429_is_rate_limited(self):
        def fake_request(*a, **kw):
            raise http.HTTPError(429, "Resource exhausted")

        http.request = fake_request
        client = InteractionsClient("k", sleep=lambda s: None)
        with self.assertRaises(RateLimited):
            client.run(model="m", input="x")

    def test_failed_interaction(self):
        def fake_request(*a, **kw):
            return json.dumps({"id": "i", "status": "failed", "error": {"code": 400, "message": "bad video"}}).encode()

        http.request = fake_request
        client = InteractionsClient("k", sleep=lambda s: None)
        with self.assertRaisesRegex(GeminiError, "bad video"):
            client.run(model="m", input="x")

    def test_http_503_is_try_later(self):
        def fake_request(*a, **kw):
            raise http.HTTPError(503, "The model is currently experiencing high demand")

        http.request = fake_request
        client = InteractionsClient("k", sleep=lambda s: None)
        with self.assertRaises(TryLater):
            client.run(model="m", input="x")

    def test_failed_interaction_without_message_shows_response(self):
        def fake_request(*a, **kw):
            return json.dumps({"id": "i", "status": "failed", "steps": [{"type": "thought"}]}).encode()

        http.request = fake_request
        client = InteractionsClient("k", sleep=lambda s: None)
        with self.assertRaisesRegex(GeminiError, "no error message; response was .*thought"):
            client.run(model="m", input="x")

    def test_failed_interaction_unavailable_is_try_later(self):
        def fake_request(*a, **kw):
            return json.dumps({"id": "i", "status": "failed", "error": {"code": 503, "status": "UNAVAILABLE"}}).encode()

        http.request = fake_request
        client = InteractionsClient("k", sleep=lambda s: None)
        with self.assertRaises(TryLater):
            client.run(model="m", input="x")

    def test_timeout_cancels(self):
        calls = []

        def fake_request(method, url, **kw):
            calls.append((method, url))
            return json.dumps({"id": "i", "status": "in_progress"}).encode()

        http.request = fake_request
        t = iter(range(0, 10_000, 500))
        client = InteractionsClient("k", sleep=lambda s: None, clock=lambda: next(t))
        with self.assertRaisesRegex(GeminiError, "timed out"):
            client.run(model="m", input="x", timeout_s=1200)
        self.assertTrue(calls[-1][1].endswith("/interactions/i/cancel"))

    def test_video_part(self):
        self.assertEqual(gemini.video_part("abc")["processing"], "agentic")
        self.assertEqual(gemini.video_part("abc", "static", 0.5)["processing"], {"type": "static", "fps": 0.5})


if __name__ == "__main__":
    unittest.main()
