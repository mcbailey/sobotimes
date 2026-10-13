# Southborough This Week

A small, automated website that turns [Southborough Access Media](https://www.youtube.com/c/SouthboroughAccessMedia)'s recordings of town meetings into plain-English weekly summaries.

- The home page lists each week with a short synopsis and its most important items.
- Each week's page covers every meeting: what was discussed, key numbers, outcomes, votes, public comment and upcoming dates, with a link to the exact moment in the video for every item.
- Important items are highlighted, and a strip under each meeting shows where they fall in the recording.
- Runs on a daily schedule in GitHub Actions and publishes to GitHub Pages. No server to maintain.

| Home | A week |
| --- | --- |
| ![Home page](docs/preview-home.png) | ![Week page](docs/preview-week.png) |

*Screenshots use fictional sample data.*

## How it works

Once a day, a GitHub Action:

1. **Finds new videos** on the channel, using the YouTube Data API (or the channel's RSS feed if you skip the API key). Titles that don't look like meetings (concerts, sports) are skipped.
2. **Summarizes each meeting** by passing its YouTube link to Gemini 3.8 Flash, which watches and listens to the recording itself. No transcript scraping, which YouTube blocks from cloud servers. Gemini's agentic video mode navigates long recordings and uses a fraction of the tokens of frame-by-frame processing.
3. **Writes a synopsis for each week** from that week's meeting summaries (a cheap, text-only call). A week is only rewritten when its meetings change.
4. **Commits the results** to `data/` in the repo. This is the pipeline's memory: each video is processed once.
5. **Builds and publishes the site** to GitHub Pages, along with an Atom feed for anyone who wants weekly updates.

The first run looks back 28 days. Backfilling those weeks takes a few daily runs because of the daily budget below.

## Cost and safeguards

The default setup costs nothing and needs no credit card.

- **Gemini free tier.** Gemini 3.8 Flash is free of charge on the free tier, which allows up to 8 hours of YouTube video per day. The pipeline budgets 7 hours (420 minutes) per day by default and keeps a ledger in `data/state.json`, so even manual extra runs can't go over.
- **Per-run caps.** At most 6 videos per run, a 60-minute run limit, and a 20-minute timeout on each Gemini call.
- **No retry loops.** A video that fails twice is marked failed and left alone (re-run it with `requeue`, below). Rate-limit errors stop the run for the day without counting against the video.
- **Long videos.** Anything over 5 hours is flagged instead of summarized.

If you later move to a paid Gemini tier, use prepaid credits and set a monthly **project spend cap** in Google AI Studio (Spend tab). Prepaid credits put a hard ceiling on what can be spent.

Note that on the free tier, Google may use the content you send to improve its products. These are public meeting recordings, so that is usually fine, but it's worth knowing.

## Setup (about 15 minutes)

1. **Create a public GitHub repository** and push these files to it. GitHub Pages is free for public repos.

2. **Get a Gemini API key.** In [Google AI Studio](https://aistudio.google.com/apikey), create an API key. Don't set up billing if you want to stay on the free tier.

3. **Get a YouTube Data API key** (recommended; free, no billing needed). Without it, the pipeline can only see the latest ~15 uploads and won't know video lengths, so budgeting is rougher and backfill is limited.
   - In the [Google Cloud console](https://console.cloud.google.com/), create a project.
   - Under *APIs & Services → Library*, enable **YouTube Data API v3**.
   - Under *Credentials*, create an **API key**, then restrict it to the YouTube Data API v3.
   - The pipeline uses a handful of quota units a day out of the default 10,000.

4. **Add the keys as repository secrets.** In the repo, go to *Settings → Secrets and variables → Actions → New repository secret*:
   - `GEMINI_API_KEY` (required)
   - `YOUTUBE_API_KEY` (recommended)

5. **Turn on GitHub Pages.** Go to *Settings → Pages* and set *Source* to **GitHub Actions**.

6. **Run it.** Open the *Actions* tab, choose **Meeting digest**, and click **Run workflow**. Tick *Dry run* the first time to see which videos it would summarize without calling Gemini. After that, it runs every morning on its own.

Your site will be at `https://<your-username>.github.io/<repo-name>/`. Put that URL in `site.base_url` in `config.toml` so the feed has absolute links.

## After the first run: tune the meeting filter

The run summary (click the run in the Actions tab) lists every video it **skipped** because the title didn't look like a meeting. If a real meeting was skipped, or a non-meeting got through, adjust `include_patterns` and `exclude_patterns` in `config.toml`. As a backstop, Gemini also flags videos that aren't public meetings, and those are hidden from the site.

## Configuration

Everything lives in `config.toml`:

| Setting | What it does |
| --- | --- |
| `discovery.backfill_days` | How far back to look for videos (default 28). |
| `discovery.min_age_hours` | Wait this long after upload before summarizing. |
| `budget.daily_video_minutes` | Daily video budget (default 420; the free tier allows 480). |
| `budget.max_videos_per_run` | Cap per run (default 6). |
| `gemini.model` | Model used for meetings (default `gemini-3.8-flash`). |
| `gemini.video_processing` | `agentic` (default) or `static`. |
| `gemini.thinking_level` | `low`, `medium` (default) or `high`. |
| `site.title`, `site.description` | Site name and tagline. |

The prompts, including the rubric for what counts as important, are in `digest/prompts.py`.

## Fixing a summary

If a summary looks wrong, have it redone on the next run:

```bash
python -m digest requeue VIDEO_ID
git commit -am "Requeue VIDEO_ID" && git push
```

`python -m digest status` lists every video the pipeline knows about and its status.

## Running locally

Requires Python 3.11 or newer.

```bash
pip install -r requirements.txt
python -m unittest discover -s tests          # tests use a fake Gemini, no keys needed
python scripts/build_sample_site.py           # build the site from fictional sample data
python -m http.server -d _sample_site         # then open http://localhost:8000

export GEMINI_API_KEY=... YOUTUBE_API_KEY=...
python -m digest run --dry-run                # see what would be summarized
python -m digest run --max-videos 1           # summarize one video
python -m digest build --out _site
```

## Things to know

- **Summaries can be wrong.** They're AI-generated; every item links to the moment in the video so readers can check. The site footer says this.
- **Timestamps are approximate.** They're usually within a minute of where an item starts.
- **Members of the public aren't named.** The prompt tells Gemini to describe public commenters generically and to name officials only when clearly identified.
- **Only public videos work.** Gemini can't read unlisted or private YouTube videos.
- **Preview features.** Gemini's YouTube URL input and agentic video mode are relatively new. If agentic mode returns errors, set `video_processing = "static"`.
- **Fonts are self-hosted** (Public Sans and Source Serif 4, SIL Open Font License), so visitors aren't tracked by a font service.
- **Scheduled workflows** in public repos pause after 60 days without repository activity. The data commits from new meetings keep it active; if it ever pauses, re-enable it from the Actions tab.

## Layout

```
config.toml                 settings
digest/                     the pipeline (standard library + Jinja2)
  youtube.py                find new uploads
  gemini.py                 Gemini Interactions API client (REST)
  prompts.py                prompts, JSON schemas, output cleaning
  pipeline.py               daily run: discover, budget, summarize, weekly synopses
  site.py                   build the static site
templates/, static/         site templates, CSS and fonts
data/                       the pipeline's memory (committed by the workflow)
.github/workflows/digest.yml
tests/                      unittest suite and fictional sample data
```
