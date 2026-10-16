"""Load config.toml into typed settings."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ChannelConfig:
    id: str
    name: str = ""
    town: str = ""
    timezone: str = "America/New_York"


@dataclass
class ExtraChannel:
    """Another channel to pull from, limited to titles matching include_patterns."""

    id: str
    name: str = ""
    include_patterns: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.include_patterns:
            raise ValueError(f"extra channel {self.id} needs include_patterns")
        self._include = [re.compile(p, re.IGNORECASE) for p in self.include_patterns]

    def wants(self, title: str) -> bool:
        return any(rx.search(title) for rx in self._include)

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/channel/{self.id}"


@dataclass
class DiscoveryConfig:
    backfill_days: int = 28
    min_age_hours: float = 3
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._include = [re.compile(p, re.IGNORECASE) for p in self.include_patterns]
        self._exclude = [re.compile(p, re.IGNORECASE) for p in self.exclude_patterns]

    def classify(self, title: str) -> tuple[bool, str]:
        """Return (is_meeting_candidate, reason)."""
        for rx in self._exclude:
            if rx.search(title):
                return False, f"title matches exclude pattern {rx.pattern!r}"
        if not self._include:
            return True, "no include patterns configured"
        for rx in self._include:
            if rx.search(title):
                return True, f"title matches {rx.pattern!r}"
        return False, "title matches no include pattern"


@dataclass
class BudgetConfig:
    daily_video_minutes: int = 420
    max_videos_per_run: int = 6
    max_video_minutes: int = 300
    assumed_video_minutes: int = 150
    max_attempts: int = 2
    run_time_limit_minutes: int = 60
    max_week_summaries_per_run: int = 8
    max_link_weeks_per_run: int = 12
    max_month_summaries_per_run: int = 4
    max_issue_statuses_per_run: int = 100


@dataclass
class GeminiConfig:
    model: str = "gemini-3.8-flash"
    synthesis_model: str = "gemini-3.8-flash"
    fallback_models: list[str] = field(default_factory=lambda: ["gemini-3.5-flash-lite"])
    video_processing: str = "static"
    fallback_to_static: bool = True
    static_fps: float = 0.2
    thinking_level: str = "medium"
    meeting_max_output_tokens: int = 16000
    week_max_output_tokens: int = 6000
    link_max_output_tokens: int = 32000
    month_max_output_tokens: int = 16000
    issue_max_output_tokens: int = 16000
    call_timeout_minutes: int = 20
    api_revision: str = ""
    redo_outdated_summaries: bool = True


@dataclass
class SiteConfig:
    title: str = "Meeting Digest"
    description: str = ""
    base_url: str = ""
    max_weeks_on_index: int = 52
    # Other spellings of a board's name -> the name its page uses.
    board_aliases: dict = field(default_factory=dict)


@dataclass
class Config:
    channel: ChannelConfig
    discovery: DiscoveryConfig
    budget: BudgetConfig
    gemini: GeminiConfig
    site: SiteConfig
    root: Path
    extra_channels: list[ExtraChannel] = field(default_factory=list)


def load_config(path: str | Path = "config.toml") -> Config:
    path = Path(path).resolve()
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    cfg = Config(
        channel=ChannelConfig(**raw["channel"]),
        discovery=DiscoveryConfig(**raw.get("discovery", {})),
        budget=BudgetConfig(**raw.get("budget", {})),
        gemini=GeminiConfig(**raw.get("gemini", {})),
        site=SiteConfig(**raw.get("site", {})),
        root=path.parent,
        extra_channels=[ExtraChannel(**c) for c in raw.get("extra_channels", [])],
    )
    if cfg.gemini.video_processing not in ("agentic", "static"):
        raise ValueError("gemini.video_processing must be 'agentic' or 'static'")
    return cfg
