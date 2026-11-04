"""The hive: daily public stats for the competition channels.

Reads handles from hive/channels.txt, calls the YouTube Data API v3
(public data only, API key from the YOUTUBE_API_KEY env var) and writes:

  data/channels_daily.csv  one row per channel per day (history)
  data/videos_daily.csv    one row per video per day for the latest 50 uploads (history)
  data/videos_latest.csv   today's snapshot of those videos, newest first

Quota: about 3 units per channel per run (10,000 free units/day).
Standard library only, so the workflow needs no pip install.
"""

import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANNELS_FILE = ROOT / "hive" / "channels.txt"
DATA = ROOT / "data"
API = "https://www.googleapis.com/youtube/v3/"

CHANNEL_FIELDS = ["date", "handle", "channel_id", "title", "subscribers",
                  "total_views", "video_count"]
VIDEO_FIELDS = ["date", "handle", "video_id", "title", "published_at",
                "duration", "views", "likes", "comments", "url"]


def api_get(endpoint, key, **params):
    params["key"] = key
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        # Never print the URL: it contains the key.
        raise RuntimeError(f"{endpoint} failed: HTTP {e.code}: {body[:500]}") from None


def read_handles():
    handles = []
    for line in CHANNELS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            handles.append(line if line.startswith("@") else "@" + line)
    return handles


def upsert_history(path, fields, new_rows, key_cols):
    """Append rows, replacing any existing row with the same key (re-runs on the same day)."""
    rows = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    new_keys = {tuple(r[c] for c in key_cols) for r in new_rows}
    rows = [r for r in rows if tuple(r.get(c, "") for c in key_cols) not in new_keys]
    rows.extend(new_rows)
    rows.sort(key=lambda r: tuple(r.get(c, "") for c in key_cols))
    write_csv(path, fields, rows)


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def fetch_channel(handle, key, today):
    res = api_get("channels", key, part="snippet,statistics,contentDetails",
                  forHandle=handle)
    items = res.get("items") or []
    if not items:
        raise RuntimeError(f"channel not found for {handle}")
    ch = items[0]
    st = ch.get("statistics", {})
    channel_row = {
        "date": today,
        "handle": handle,
        "channel_id": ch["id"],
        "title": ch["snippet"]["title"],
        # Public counts above 1,000 are rounded by YouTube.
        "subscribers": "" if st.get("hiddenSubscriberCount") else st.get("subscriberCount", ""),
        "total_views": st.get("viewCount", ""),
        "video_count": st.get("videoCount", ""),
    }

    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    pl = api_get("playlistItems", key, part="contentDetails",
                 playlistId=uploads, maxResults=50)
    ids = [it["contentDetails"]["videoId"] for it in pl.get("items", [])]

    video_rows = []
    if ids:
        vids = api_get("videos", key, part="snippet,statistics,contentDetails",
                       id=",".join(ids))
        for v in vids.get("items", []):
            vs = v.get("statistics", {})
            video_rows.append({
                "date": today,
                "handle": handle,
                "video_id": v["id"],
                "title": v["snippet"]["title"],
                "published_at": v["snippet"]["publishedAt"],
                "duration": v.get("contentDetails", {}).get("duration", ""),
                "views": vs.get("viewCount", ""),
                "likes": vs.get("likeCount", ""),
                "comments": vs.get("commentCount", ""),
                "url": f"https://www.youtube.com/shorts/{v['id']}",
            })
    return channel_row, video_rows


def main():
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        sys.exit("YOUTUBE_API_KEY is not set (add it as a repository secret).")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    channel_rows, video_rows, errors = [], [], []
    for handle in read_handles():
        try:
            c, vids = fetch_channel(handle, key, today)
            channel_rows.append(c)
            video_rows.extend(vids)
            print(f"{handle}: {c['subscribers']} subs, {c['total_views']} views, "
                  f"{len(vids)} recent videos")
        except Exception as e:  # keep going so one bad handle doesn't lose the others
            errors.append(f"{handle}: {e}")
            print(f"ERROR {handle}: {e}", file=sys.stderr)

    if channel_rows:
        upsert_history(DATA / "channels_daily.csv", CHANNEL_FIELDS, channel_rows,
                       ["date", "handle"])
        upsert_history(DATA / "videos_daily.csv", VIDEO_FIELDS, video_rows,
                       ["date", "handle", "video_id"])
        latest = sorted(video_rows, key=lambda r: r["published_at"], reverse=True)
        write_csv(DATA / "videos_latest.csv", VIDEO_FIELDS, latest)

    if errors:
        sys.exit("Some channels failed:\n" + "\n".join(errors))


if __name__ == "__main__":
    main()
