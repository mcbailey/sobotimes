"""Build the site from fictional sample data, with no API keys.

Useful for previewing design changes locally:
    python scripts/build_sample_site.py && python -m http.server -d _sample_site
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import sample_data  # noqa: E402
from test_digest import FakeClient, fake_discover  # noqa: E402

from digest.config import load_config  # noqa: E402
from digest.pipeline import Pipeline  # noqa: E402
from digest.site import build_site  # noqa: E402
from digest.store import Store  # noqa: E402

NOW = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)


def main(out: str = "_sample_site") -> None:
    cfg = load_config(ROOT / "config.toml")
    cfg.budget.daily_video_minutes = 10_000
    cfg.budget.max_videos_per_run = 50
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "data")
        Pipeline(
            cfg, store, client=FakeClient(), discover=fake_discover(sample_data.VIDEOS),
            now=lambda: NOW, log=lambda *_: None,
        ).run()
        site = build_site(
            cfg, store, ROOT / out,
            banner="Sample data for previewing the design. These are not real Southborough meetings.",
        )
    print(f"Sample site written to {site}")


if __name__ == "__main__":
    main(*sys.argv[1:])
