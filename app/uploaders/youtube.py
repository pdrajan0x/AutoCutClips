"""
app.uploaders.youtube — YouTube upload & scheduling.

Reads ``render_manifest.json``, uploads every successful clip as a private
video with a future ``publishAt``, and writes the results back into an updated
manifest. Safety rails live in ``youtube_safety``.
"""

import os
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from . import youtube_safety as safety
from .manifest import (
    get_manifest_row_by_rank,
    get_upload_candidates,
    is_nonempty_file,
    load_json_file,
    normalize_tags,
    normalize_text,
    save_json_file,
)

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

DEFAULT_TZ = "Asia/Kolkata"


# ==============================================================================
# AUTH
# ==============================================================================

def get_youtube_service(token_file: str):
    """Build an authenticated YouTube client, refreshing the token if needed."""
    if not os.path.exists(token_file):
        raise FileNotFoundError(
            f"{token_file} not found. Generate the token file in the credentials "
            "folder first (see: app.uploaders.youtube_token)."
        )

    creds = Credentials.from_authorized_user_file(token_file, YOUTUBE_SCOPES)

    if not creds.valid:
        if not (creds.expired and creds.refresh_token):
            raise RuntimeError(
                "The token is invalid and has no refresh_token. "
                "Re-create the token file by logging in from a desktop machine."
            )
        print("🔄 Access token expired, refreshing...")
        creds.refresh(Request())
        with open(token_file, "w", encoding="utf-8") as tf:
            tf.write(creds.to_json())
        print("✅ Token refreshed.")

    return build("youtube", "v3", credentials=creds)


# ==============================================================================
# TIME / SCHEDULING HELPERS
# ==============================================================================

def parse_local_datetime(dt_text, tz_name):
    """Parse ``YYYY-MM-DD HH:MM`` as a local time in *tz_name*."""
    return datetime.strptime(dt_text, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz_name))


def parse_rfc3339_to_local(dt_text, tz_name):
    """Convert an RFC3339 UTC timestamp to a local datetime (None on failure)."""
    if not dt_text:
        return None
    try:
        dt_utc = datetime.fromisoformat(dt_text.replace("Z", "+00:00"))
        return dt_utc.astimezone(ZoneInfo(tz_name))
    except (ValueError, TypeError):
        return None


def to_rfc3339_utc(dt_local):
    """Render a timezone-aware datetime as an RFC3339 UTC string."""
    return dt_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_uploads_playlist_id(youtube):
    """Return the channel's uploads playlist ID, or None."""
    resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        return None
    return (
        items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    )


def iter_future_scheduled(youtube, tz_name: str = DEFAULT_TZ, max_pages: int = 10):
    """
    Yield the local publish datetime of every video scheduled in the future.

    A video counts as scheduled when it is still ``private`` and carries a
    ``status.publishAt`` later than now — the state the uploader creates.
    """
    now_local = datetime.now(ZoneInfo(tz_name))

    uploads_playlist_id = _get_uploads_playlist_id(youtube)
    if not uploads_playlist_id:
        return

    page_token = None
    for _ in range(max_pages):
        playlist_resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()

        playlist_items = playlist_resp.get("items", [])
        if not playlist_items:
            return

        video_ids = [
            row["contentDetails"]["videoId"]
            for row in playlist_items
            if row.get("contentDetails", {}).get("videoId")
        ]

        if video_ids:
            videos_resp = youtube.videos().list(
                part="status", id=",".join(video_ids), maxResults=50
            ).execute()

            for video in videos_resp.get("items", []):
                status = video.get("status", {})
                if status.get("privacyStatus") != "private":
                    continue
                dt_local = parse_rfc3339_to_local(status.get("publishAt"), tz_name)
                if dt_local is not None and dt_local > now_local:
                    yield dt_local

        page_token = playlist_resp.get("nextPageToken")
        if not page_token:
            return


def count_future_scheduled(youtube, tz_name: str = DEFAULT_TZ, max_pages: int = 10) -> int:
    """Count the videos currently scheduled for a future publish."""
    return sum(1 for _ in iter_future_scheduled(youtube, tz_name, max_pages))


def get_latest_scheduled_publish_time(youtube, tz_name: str = DEFAULT_TZ, max_pages: int = 10):
    """Return the furthest-out scheduled publish time, or None."""
    print("🔎 Checking the latest scheduled video on the channel...")
    latest_dt = max(iter_future_scheduled(youtube, tz_name, max_pages), default=None)

    if latest_dt:
        print(f"✅ Latest schedule found: {latest_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    else:
        print("ℹ️ No future scheduled videos yet. Using the default fallback schedule.")
    return latest_dt


def get_first_publish_time(
    youtube=None,
    tz_name: str = DEFAULT_TZ,
    start_local: str | None = None,
    interval_hours: int = 8,
):
    """
    Decide when the first upload of this run should publish.

    Priority: an explicit ``start_local``, then one interval after the channel's
    last scheduled video, then the next full hour at least 30 minutes out.
    """
    if start_local:
        first_dt = parse_local_datetime(start_local, tz_name)
        print(f"🗓️ Using the manual start_local: {first_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        return first_dt

    if youtube is not None:
        latest_scheduled = get_latest_scheduled_publish_time(youtube, tz_name)
        if latest_scheduled is not None:
            first_dt = latest_scheduled + timedelta(hours=interval_hours)
            print(f"🗓️ First new slot after YouTube's queue: {first_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            return first_dt

    now_local = datetime.now(ZoneInfo(tz_name))
    first_dt = (now_local + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
    if first_dt <= now_local:
        first_dt += timedelta(hours=1)

    print(f"🗓️ Fallback first slot: {first_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    return first_dt


def build_schedule_times(
    count: int,
    youtube=None,
    tz_name: str = DEFAULT_TZ,
    interval_hours: int = 8,
    start_local: str | None = None,
) -> list:
    """Build *count* publish times spaced *interval_hours* apart."""
    if count <= 0:
        return []
    first_dt = get_first_publish_time(youtube, tz_name, start_local, interval_hours)
    return [first_dt + timedelta(hours=i * interval_hours) for i in range(count)]


# ==============================================================================
# YOUTUBE API HELPERS
# ==============================================================================

def format_http_error(e) -> str:
    """Render a googleapiclient HttpError as a readable single line."""
    status = getattr(getattr(e, "resp", None), "status", None)
    try:
        content = e.content.decode("utf-8") if getattr(e, "content", None) else str(e)
    except Exception:
        content = str(e)
    return f"HTTP {status or 'ERR'}: {content}"


def set_custom_thumbnail(youtube, video_id, thumbnail_path, max_retries=3) -> dict:
    """Upload a custom thumbnail for a video, retrying transient failures."""
    if not is_nonempty_file(thumbnail_path):
        return {"thumbnail_set": False, "thumbnail_error": "thumbnail file not found"}

    for attempt in range(1, max_retries + 1):
        try:
            media = MediaFileUpload(thumbnail_path, resumable=False)
            youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
            return {"thumbnail_set": True, "thumbnail_error": None}
        except Exception as e:
            err = format_http_error(e) if isinstance(e, HttpError) else str(e)
            if attempt == max_retries:
                return {"thumbnail_set": False, "thumbnail_error": err}
            print(f"   ⚠️ Thumbnail upload failed (attempt {attempt}/{max_retries}), retrying...")
            time.sleep(5)

    return {"thumbnail_set": False, "thumbnail_error": "unknown"}


def upload_video_to_youtube(
    youtube,
    item: dict,
    publish_at_local=None,
    category_id: str = "22",
    default_language: str = "en",
    privacy_status: str = "private",
    chunk_size: int = 8 * 1024 * 1024,
) -> dict:
    """Upload one manifest row as a (scheduled) YouTube video."""
    video_path = item["video_path"]

    title = normalize_text(
        item.get("youtube_title_final")
        or item.get("title")
        or f"Clip Rank {item.get('rank', '?')}"
    )[:100]
    description = normalize_text(item.get("youtube_description_final", ""))
    tags = normalize_tags(item.get("youtube_tags_final", []))

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
            "defaultLanguage": default_language,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    publish_at_rfc3339 = None
    if privacy_status == "private" and publish_at_local is not None:
        publish_at_rfc3339 = to_rfc3339_utc(publish_at_local)
        body["status"]["publishAt"] = publish_at_rfc3339

    media = MediaFileUpload(video_path, chunksize=chunk_size, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media, notifySubscribers=False
    )

    print(f"   ⬆️ Uploading: {os.path.basename(video_path)}")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"   ... {int(status.progress() * 100)}%")

    video_id = response["id"]

    # TODO: re-enable once the thumbnail generator produces good output.
    #   For now YouTube picks the thumbnail itself.
    #   thumb_result = set_custom_thumbnail(youtube, video_id, item.get("thumbnail_path"))
    thumb_result = {"thumbnail_set": False, "thumbnail_error": None}

    return {
        "video_id": video_id,
        "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
        "scheduled_publish_local": (
            publish_at_local.strftime("%Y-%m-%d %H:%M:%S %Z") if publish_at_local else None
        ),
        "scheduled_publish_utc": publish_at_rfc3339,
        "thumbnail_set": thumb_result["thumbnail_set"],
        "thumbnail_error": thumb_result["thumbnail_error"],
        "uploaded_title": title,
        "uploaded_description": description,
        "uploaded_tags": tags,
    }


# ==============================================================================
# MAIN PIPELINE
# ==============================================================================

def _collect_pending(render_manifest: list[dict], test_mode: bool) -> list[dict]:
    """Return the rows that still need uploading."""
    candidates = get_upload_candidates(render_manifest)
    if not candidates:
        print("⚠️ No items are ready to upload.")
        return []

    pending = []
    for item in candidates:
        if item.get("youtube_video_id") and item.get("youtube_upload_status") == "uploaded":
            print(f"⏭️ Skipping rank {item.get('rank')} — already uploaded.")
            continue
        pending.append(item)

    if test_mode and pending:
        print("🧪 Test mode: uploading only the first item.")
        return pending[:1]

    return pending


def upload_manifest_to_youtube(
    token_file: str,
    manifest_file: str = "render_manifest.json",
    result_file: str = "youtube_upload_results.json",
    updated_manifest_file: str = "render_manifest_uploaded.json",
    tz_name: str = DEFAULT_TZ,
    interval_hours: int = 2,
    start_local: str | None = None,
    test_mode: bool = False,
    safety_config: dict | None = None,
    skip_approval: bool = False,
) -> list[dict]:
    """
    Upload every pending clip in the manifest to YouTube on a schedule.

    Parameters
    ----------
    safety_config : dict, optional
        Safety rails from ``youtube_safety.load_safety_config()``. Loaded from
        the default path when omitted.
    skip_approval : bool
        Skip the interactive approval prompt (the other rails still apply).
    """
    if safety_config is None:
        safety_config = safety.load_safety_config()

    safety.print_safety_summary(safety_config, tz_name)

    allowed, uploads_today, max_per_day = safety.check_daily_limit(safety_config, tz_name)
    if not allowed:
        print(f"🚫 Upload cancelled — daily limit reached ({uploads_today}/{max_per_day}).")
        return []

    render_manifest = load_json_file(manifest_file, default=[])
    if not render_manifest:
        print(f"⚠️ {manifest_file} is empty or missing.")
        return []

    pending_items = _collect_pending(render_manifest, test_mode)
    if not pending_items:
        print("⚠️ Every successful item has already been uploaded.")
        return []

    if not test_mode:
        pending_items = safety.limit_pending_items(pending_items, safety_config)

    # Never schedule tighter than the configured minimum gap.
    interval_hours = safety.enforce_min_interval(interval_hours, safety_config)

    youtube = get_youtube_service(token_file)

    queue_ok, queue_count, queue_max = safety.check_queue_limit(
        youtube, safety_config, tz_name
    )
    if not queue_ok:
        print(f"🚫 Upload cancelled — the scheduled queue is full ({queue_count}/{queue_max}).")
        return []

    schedule_times = build_schedule_times(
        count=len(pending_items),
        youtube=youtube,
        tz_name=tz_name,
        interval_hours=interval_hours,
        start_local=start_local,
    )

    require_approval = (
        safety_config.get("require_manual_approval", True) and not skip_approval
    )

    upload_results: list[dict] = []
    updated_manifest = deepcopy(render_manifest)

    print(f"🚀 Uploading {len(pending_items)} clip(s) to YouTube...")

    for item, publish_at_local in zip(pending_items, schedule_times):
        rank = item.get("rank")
        manifest_row = get_manifest_row_by_rank(updated_manifest, rank)

        print(f"\n=== Upload rank {rank} ===")
        print(f"Title    : {item.get('youtube_title_final')}")
        print(f"Video    : {item.get('video_path')}")
        print(f"Schedule : {publish_at_local.strftime('%Y-%m-%d %H:%M:%S %Z')}")

        if require_approval and not safety.prompt_manual_approval(item, publish_at_local):
            print(f"⏭️ Rank {rank} skipped (not approved).")
            continue

        try:
            result = upload_video_to_youtube(youtube, item, publish_at_local)

            if manifest_row is not None:
                manifest_row.update({
                    "youtube_upload_status": "uploaded",
                    "youtube_video_id": result["video_id"],
                    "youtube_url": result["youtube_url"],
                    "youtube_scheduled_publish_local": result["scheduled_publish_local"],
                    "youtube_scheduled_publish_utc": result["scheduled_publish_utc"],
                    "youtube_thumbnail_set": result["thumbnail_set"],
                    "youtube_thumbnail_error": result["thumbnail_error"],
                    "youtube_uploaded_at_utc": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "youtube_upload_error": None,
                })

            upload_results.append({"rank": rank, "status": "uploaded", **result})
            safety.record_upload(
                safety_config["upload_log_file"],
                result["video_id"],
                result.get("uploaded_title", ""),
                tz_name,
            )

            print(f"✅ Upload succeeded. Video ID: {result['video_id']}")
            print(f"🔗 {result['youtube_url']}")

        except Exception as e:
            err = format_http_error(e) if isinstance(e, HttpError) else str(e)
            if manifest_row is not None:
                manifest_row["youtube_upload_status"] = "failed"
                manifest_row["youtube_upload_error"] = err
            upload_results.append({"rank": rank, "status": "failed", "error": err})
            print(f"❌ Upload failed for rank {rank}: {err}")

        save_json_file(result_file, upload_results)
        save_json_file(updated_manifest_file, updated_manifest)

    print(f"\n💾 Upload results saved to: {result_file}")
    print(f"💾 Updated manifest saved to: {updated_manifest_file}")

    return upload_results
