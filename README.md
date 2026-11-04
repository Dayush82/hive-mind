# hive-mind

**The hive** is a daily GitHub Actions job (`.github/workflows/hive.yml`) that saves public YouTube stats for the channels in `hive/channels.txt` into CSVs under `data/`:

- `data/channels_daily.csv` — one row per channel per day
- `data/videos_daily.csv` — one row per video per day (latest 50 uploads)
- `data/videos_latest.csv` — today's snapshot, newest first

Runs every day at 05:17 UTC, or manually with `gh workflow run hive`. Needs the `YOUTUBE_API_KEY` repository secret.
