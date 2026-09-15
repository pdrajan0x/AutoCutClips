"""
app.uploaders.performance — Fetch results for uploaded clips (``learn-youtube``).

Reads the upload history the YouTube uploader writes, asks the YouTube Data API
for every video's views, likes and comments, and saves
``channel_performance.json``. The clip-selection prompt reads that file (see
``app.clipping.channel_learning``) to favour what works on this channel.

Uses the existing upload token (its ``youtube.readonly`` scope) and costs one
API quota unit per 50 videos.
"""

from datetime import datetime, timezone

from .manifest import load_json_file, save_json_file

DEFAULT_HISTORY_FILE = "outputs/upload_history.json"
DEFAULT_OUTPUT_FILE = "outputs/channel_performance.json"

# Clip details recorded at upload time and carried into the performance file.
CLIP_FIELDS = ("on_screen_hook", "hook_text", "duration", "viral_score", "reason", "language", "hashtags")


def refresh_channel_performance(
    token_file: str,
    history_file: str = DEFAULT_HISTORY_FILE,
    output_file: str = DEFAULT_OUTPUT_FILE,
) -> list[dict]:
    """Fetch statistics for every uploaded clip and save them to *output_file*."""
    from googleapiclient.errors import HttpError

    from .youtube import format_http_error, get_youtube_service

    history = load_json_file(history_file, default=[])
    by_id = {
        entry["video_id"]: entry
        for entry in (history if isinstance(history, list) else [])
        if isinstance(entry, dict) and entry.get("video_id")
    }
    if not by_id:
        print(f"⚠️ No uploads recorded in {history_file} yet — upload some clips first.")
        return []

    youtube = get_youtube_service(token_file)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    video_ids = list(by_id)
    rows: list[dict] = []

    print(f"📈 Fetching statistics for {len(video_ids)} uploaded clip(s)...")
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start:start + 50]
        try:
            response = youtube.videos().list(
                part="statistics,status,snippet", id=",".join(batch), maxResults=50
            ).execute()
        except HttpError as e:
            print(f"⚠️ Could not fetch statistics for a batch: {format_http_error(e)}")
            continue

        for video in response.get("items", []):
            entry = by_id.get(video["id"], {})
            stats = video.get("statistics", {})
            row = {
                "video_id": video["id"],
                "title": video.get("snippet", {}).get("title") or entry.get("title"),
                "published_at": video.get("snippet", {}).get("publishedAt"),
                "privacy": video.get("status", {}).get("privacyStatus"),
                "views": int(stats.get("viewCount", 0) or 0),
                "likes": int(stats.get("likeCount", 0) or 0),
                "comments": int(stats.get("commentCount", 0) or 0),
                "fetched_at": fetched_at,
            }
            row.update({k: entry[k] for k in CLIP_FIELDS if entry.get(k) is not None})
            rows.append(row)

    save_json_file(output_file, rows)

    public = sorted((r for r in rows if r["privacy"] == "public"), key=lambda r: r["views"], reverse=True)
    missing = len(video_ids) - len(rows)
    print(f"💾 Saved {len(rows)} clip(s) to {output_file} ({len(public)} public"
          + (f", {missing} no longer on YouTube" if missing else "") + ").")
    for row in public[:3]:
        print(f"   {row['views']:>9,} views · {row['title']}")
    return rows
