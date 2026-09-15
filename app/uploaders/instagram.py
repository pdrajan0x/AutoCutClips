"""
app.uploaders.instagram — Instagram Reels publishing via the Instagram Graph API.

Replaces the old Facebook Page Reels uploader. Publishing flow for an Instagram
Business/Creator account linked to a Facebook Page:

  1. POST /{ig-user-id}/media          -> create a media container
                                          (media_type=REELS, caption, share_to_feed)
     * Remote mode  : pass ``video_url`` and Instagram fetches the file.
     * Local mode   : create the container with ``upload_type=resumable`` and POST
                      the bytes to rupload.facebook.com (used when the clip only
                      exists on this machine).
  2. GET  /{container-id}?fields=status_code  -> poll until FINISHED
  3. POST /{ig-user-id}/media_publish  -> publish with creation_id

Required configuration (environment variables or .env):
  IG_USER_ID           Instagram *User* ID (not the Facebook Page ID).
  IG_ACCESS_TOKEN      Token with instagram_content_publish (falls back to
                       META_PAGE_ACCESS_TOKEN for backwards compatibility).
  IG_GRAPH_VERSION     Graph API version, default v25.0 (falls back to
                       META_GRAPH_VERSION).
  IG_PUBLIC_BASE_URL   Optional. Public base URL that serves the rendered clips;
                       when set, remote mode (``video_url``) is used instead of
                       the resumable upload.
  APP_TIMEZONE         Timezone used for the scheduling maths.

NOTE ON SCHEDULING: the Instagram Graph API has no scheduled-publish parameter —
a publish goes live immediately. The interval logic is therefore enforced
locally: clips whose slot is still in the future are recorded as ``deferred``
and published by a later run (e.g. from cron). Pass ``publish_now=True`` to
ignore the interval and publish the whole batch back to back.
"""

import os
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from .manifest import (
    get_clip_title_and_description,
    get_manifest_row,
    get_upload_candidates,
    load_json_file,
    save_json_file,
)

# ==============================================================================
# PLATFORM LIMITS
# ==============================================================================

# Instagram content publishing allows 50 API-published posts per 24 hours.
IG_PUBLISH_RATE_LIMIT_24H = 50

# Instagram truncates Reels captions at 2200 characters.
IG_CAPTION_MAX_CHARS = 2200

# A container can take a while to transcode; give up after this long.
CONTAINER_TIMEOUT_SECONDS = 300
CONTAINER_POLL_INTERVAL = 10

DEFAULT_TZ = "Asia/Kolkata"


# ==============================================================================
# CONFIG & AUTH
# ==============================================================================

def get_instagram_config() -> dict:
    """
    Read the Instagram Graph API configuration from the environment.

    Raises
    ------
    RuntimeError
        If the IG user ID or the access token is missing.
    """
    user_id = os.environ.get("IG_USER_ID", "").strip()
    token = (
        os.environ.get("IG_ACCESS_TOKEN", "").strip()
        # The Facebook-era variable holds the same Page token IG publishing uses.
        or os.environ.get("META_PAGE_ACCESS_TOKEN", "").strip()
    )
    version = (
        os.environ.get("IG_GRAPH_VERSION", "").strip()
        or os.environ.get("META_GRAPH_VERSION", "").strip()
        or "v25.0"
    )

    if not user_id:
        raise RuntimeError(
            "IG_USER_ID is not set. Add it to .env or export it as an "
            "environment variable (this is the Instagram User ID, not the Page ID)."
        )
    if not token:
        raise RuntimeError(
            "IG_ACCESS_TOKEN is not set. Add it to .env or export it as an "
            "environment variable (it needs the instagram_content_publish permission)."
        )

    return {
        "ig_user_id": user_id,
        "access_token": token,
        "graph_version": version,
        "base_url": f"https://graph.facebook.com/{version}",
        "upload_url": f"https://rupload.facebook.com/ig-api-upload/{version}",
        "public_base_url": os.environ.get("IG_PUBLIC_BASE_URL", "").strip().rstrip("/"),
    }


def _auth_headers(config: dict) -> dict:
    return {"Authorization": f"Bearer {config['access_token']}"}


def _graph_json(response: requests.Response, action: str) -> dict:
    """Parse a Graph API response, raising RuntimeError with its error payload."""
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(
            f"{action} failed: HTTP {response.status_code} with a non-JSON body: "
            f"{response.text[:300]}"
        ) from None

    if not response.ok or "error" in data:
        error = data.get("error", f"HTTP {response.status_code}")
        raise RuntimeError(f"{action} failed: {error}")

    return data


def validate_ig_account(config: dict) -> dict:
    """
    GET /{ig-user-id}?fields=id,username — verify the token can reach the account.

    Returns ``{"id": ..., "username": ...}``.
    """
    resp = requests.get(
        f"{config['base_url']}/{config['ig_user_id']}",
        headers=_auth_headers(config),
        params={"fields": "id,username"},
        timeout=30,
    )
    return _graph_json(resp, "Instagram account validation")


# ==============================================================================
# PUBLISHING FLOW
# ==============================================================================

def create_media_container(
    config: dict,
    caption: str,
    video_url: str | None = None,
    share_to_feed: bool = True,
) -> str:
    """
    POST /{ig-user-id}/media — create a REELS container and return its ID.

    With *video_url* Instagram fetches the file itself; without it the container
    is opened for a resumable upload and the bytes must be sent with
    :func:`upload_reel_binary`.
    """
    payload = {
        "media_type": "REELS",
        "caption": caption[:IG_CAPTION_MAX_CHARS],
        "share_to_feed": "true" if share_to_feed else "false",
    }
    if video_url:
        payload["video_url"] = video_url
    else:
        payload["upload_type"] = "resumable"

    resp = requests.post(
        f"{config['base_url']}/{config['ig_user_id']}/media",
        headers=_auth_headers(config),
        data=payload,
        timeout=60,
    )
    data = _graph_json(resp, "Create media container")

    container_id = data.get("id")
    if not container_id:
        raise RuntimeError(f"Unexpected create-container response: {data}")
    return container_id


def upload_reel_binary(config: dict, container_id: str, file_path: str) -> None:
    """
    POST the video bytes to the resumable upload endpoint for *container_id*.

    Instagram expects the "OAuth" authorization scheme here (not "Bearer").
    """
    file_size = os.path.getsize(file_path)
    headers = {
        "Authorization": f"OAuth {config['access_token']}",
        "offset": "0",
        "file_size": str(file_size),
    }

    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{config['upload_url']}/{container_id}",
            headers=headers,
            data=f,
            timeout=900,
        )

    data = _graph_json(resp, "Upload Reel binary")
    if not data.get("success", True):
        raise RuntimeError(f"Upload Reel binary failed: {data}")


def poll_container_status(
    config: dict,
    container_id: str,
    timeout_seconds: int = CONTAINER_TIMEOUT_SECONDS,
    poll_interval: int = CONTAINER_POLL_INTERVAL,
) -> dict:
    """
    GET /{container-id}?fields=status_code — poll until the container is FINISHED.

    Returns ``{"ready": bool, "status_code": str, "raw": dict}``. ``ERROR`` and
    ``EXPIRED`` raise; ``IN_PROGRESS`` past the timeout returns ready=False.
    """
    url = f"{config['base_url']}/{container_id}"
    params = {"fields": "status_code,status"}
    start_time = time.time()
    last_data: dict = {}

    while True:
        elapsed = time.time() - start_time

        try:
            resp = requests.get(url, headers=_auth_headers(config), params=params, timeout=30)
            last_data = _graph_json(resp, "Container status")
        except Exception as exc:
            print(f"   ⚠️ Could not read the container status: {exc}")
            if elapsed >= timeout_seconds:
                return {"ready": False, "status_code": None, "raw": last_data}
            time.sleep(poll_interval)
            continue

        status_code = last_data.get("status_code", "")
        print(f"   ... container status: {status_code or 'unknown'}")

        if status_code == "FINISHED":
            return {"ready": True, "status_code": status_code, "raw": last_data}

        if status_code in ("ERROR", "EXPIRED"):
            raise RuntimeError(
                f"Instagram container {status_code}: {last_data.get('status', last_data)}"
            )

        if elapsed >= timeout_seconds:
            print(f"   ℹ️ The container was still processing after {timeout_seconds} seconds.")
            return {"ready": False, "status_code": status_code, "raw": last_data}

        time.sleep(poll_interval)


def publish_media_container(config: dict, container_id: str) -> dict:
    """POST /{ig-user-id}/media_publish — publish a FINISHED container."""
    resp = requests.post(
        f"{config['base_url']}/{config['ig_user_id']}/media_publish",
        headers=_auth_headers(config),
        data={"creation_id": container_id},
        timeout=60,
    )
    data = _graph_json(resp, "Publish media")

    if not data.get("id"):
        raise RuntimeError(f"Unexpected media_publish response: {data}")
    return data


def refresh_existing_statuses(
    config: dict,
    manifest_rows: list[dict],
    updated_manifest_file: str,
) -> None:
    """
    Re-check any container that was left mid-flight by an earlier run.

    A row with ``ig_container_id`` but no ``ig_media_id`` is still unpublished;
    if its container has since finished it is published now, otherwise the row
    is marked ``expired`` so the next run re-uploads it.
    """
    pending = [
        row for row in manifest_rows
        if row.get("ig_container_id") and not row.get("ig_media_id")
    ]
    if not pending:
        return

    modified = False
    for row in pending:
        container_id = row["ig_container_id"]
        print(f"🔄 Re-checking the Instagram container {container_id} from an earlier run...")
        try:
            status = poll_container_status(config, container_id, timeout_seconds=0)
            if not status["ready"]:
                print(f"   ℹ️ Still {status['status_code'] or 'unknown'} — leaving it for later.")
                continue
            published = publish_media_container(config, container_id)
            row["ig_media_id"] = published["id"]
            row["ig_upload_status"] = "published"
            row["ig_published_at_utc"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            row["ig_upload_error"] = None
            print(f"   ✅ Published the pending container as media {published['id']}.")
        except Exception as e:
            row["ig_upload_status"] = "expired"
            row["ig_upload_error"] = str(e)
            print(f"   ⚠️ The container can no longer be published: {e}")
        modified = True

    if modified:
        save_json_file(updated_manifest_file, manifest_rows)
        print("💾 Updated manifest saved after the status sync.")


# ==============================================================================
# SCHEDULING (LOCAL — THE IG API HAS NO scheduled_publish_time)
# ==============================================================================

def get_last_publish_time(manifest_rows: list[dict], tz_name: str) -> datetime | None:
    """Return the most recent local publish time recorded in the manifest."""
    latest = None
    for row in manifest_rows:
        raw = row.get("ig_published_at_utc")
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if latest is None or dt > latest:
            latest = dt
    return latest.astimezone(ZoneInfo(tz_name)) if latest else None


def count_recent_publishes(manifest_rows: list[dict], hours: int = 24) -> int:
    """Count the clips published through the API within the last *hours* hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    count = 0
    for row in manifest_rows:
        raw = row.get("ig_published_at_utc")
        if not raw:
            continue
        try:
            if datetime.fromisoformat(raw.replace("Z", "+00:00")) >= cutoff:
                count += 1
        except (ValueError, TypeError):
            continue
    return count


def _public_video_url(config: dict, item: dict) -> str | None:
    """
    Resolve a publicly fetchable URL for a clip, or None for local upload mode.

    An explicit ``ig_video_url``/``public_video_url`` on the manifest row wins;
    otherwise ``IG_PUBLIC_BASE_URL`` is joined with the clip's filename.
    """
    explicit = item.get("ig_video_url") or item.get("public_video_url")
    if explicit:
        return explicit
    if config["public_base_url"]:
        return f"{config['public_base_url']}/{os.path.basename(item['video_path'])}"
    return None


# ==============================================================================
# MAIN PIPELINE
# ==============================================================================

def _select_pending(manifest_rows: list[dict], test_mode: bool) -> list[dict]:
    """Return the clips that have not been published to Instagram yet."""
    candidates = get_upload_candidates(manifest_rows)
    if not candidates:
        print("⚠️ No items are ready to upload.")
        return []

    pending = []
    for item in candidates:
        if item.get("ig_media_id"):
            print(
                f"⏭️ Skipping rank {item.get('rank')} — already published as "
                f"Instagram media {item['ig_media_id']}."
            )
            continue
        pending.append(item)

    if test_mode and pending:
        print("🧪 Test mode: uploading only the first item.")
        return pending[:1]

    return pending


def _publish_one(config: dict, item: dict, caption: str) -> dict:
    """Run the three-step publishing flow for a single clip."""
    video_path = item["video_path"]
    video_url = _public_video_url(config, item)

    if video_url:
        print(f"   📝 Creating the media container from {video_url}...")
        container_id = create_media_container(config, caption, video_url=video_url)
        print(f"   ✅ Container created: {container_id}")
    else:
        size_mb = os.path.getsize(video_path) / 1024 / 1024
        print("   📝 Creating a resumable media container...")
        container_id = create_media_container(config, caption)
        print(f"   ✅ Container created: {container_id}")
        print(f"   ⬆️ Uploading {os.path.basename(video_path)} ({size_mb:.1f} MB)...")
        upload_reel_binary(config, container_id, video_path)
        print("   ✅ Binary uploaded.")

    print("   ⏳ Waiting for Instagram to finish processing...")
    status = poll_container_status(config, container_id)

    if not status["ready"]:
        # The container stays valid for 24h, so record it and publish next run.
        return {
            "container_id": container_id,
            "media_id": None,
            "status": "processing",
            "status_code": status["status_code"],
        }

    print("   🚀 Publishing the container...")
    published = publish_media_container(config, container_id)

    return {
        "container_id": container_id,
        "media_id": published["id"],
        "status": "published",
        "status_code": status["status_code"],
    }


def upload_manifest_to_instagram(
    manifest_file: str = "outputs/render_manifest.json",
    result_file: str = "outputs/ig_upload_results.json",
    updated_manifest_file: str = "outputs/render_manifest_ig_uploaded.json",
    tz_name: str = DEFAULT_TZ,
    interval_hours: int = 5,
    test_mode: bool = False,
    publish_now: bool = False,
) -> list[dict]:
    """
    Publish every pending clip in the manifest as an Instagram Reel.

    The batch stops at the first failure rather than hammering the API, matching
    the previous uploader's behaviour.

    Parameters
    ----------
    interval_hours : int
        Minimum gap between publishes. Because the Instagram API publishes
        immediately, clips whose slot has not arrived yet are recorded as
        ``deferred`` for a later run.
    publish_now : bool
        Ignore the interval and publish the whole batch back to back.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    config = get_instagram_config()

    print("🔑 Validating the Instagram access token...")
    account = validate_ig_account(config)
    print(
        f"✅ Token valid for Instagram account @{account.get('username', '?')} "
        f"(ID: {account.get('id')})"
    )

    # Prefer a previous Instagram run's manifest so publish state is not lost.
    source_manifest_file = manifest_file
    if updated_manifest_file and os.path.exists(updated_manifest_file) and os.path.getsize(
        updated_manifest_file
    ):
        source_manifest_file = updated_manifest_file
        print(f"📂 Using the previous Instagram manifest: {source_manifest_file}")
    else:
        print(f"📂 Using the initial manifest: {source_manifest_file}")

    render_manifest = load_json_file(source_manifest_file, default=[])
    if not render_manifest:
        print(f"⚠️ {source_manifest_file} is empty or missing.")
        return []

    refresh_existing_statuses(config, render_manifest, updated_manifest_file)

    pending_items = _select_pending(render_manifest, test_mode)

    # --- Rate limit (50 API publishes / rolling 24 hours) ---
    recent_count = count_recent_publishes(render_manifest, hours=24)
    remaining_quota = max(0, IG_PUBLISH_RATE_LIMIT_24H - recent_count)
    print(
        f"\n📊 Rate limit: {recent_count}/{IG_PUBLISH_RATE_LIMIT_24H} Reels "
        "published in the last 24 hours."
    )

    if remaining_quota == 0:
        print("🛑 Rate limit reached! No more Reels can be published for now.")
        return []

    if len(pending_items) > remaining_quota:
        print(
            f"⚠️ Only {remaining_quota} of {len(pending_items)} clip(s) will be "
            "published (remaining 24h quota)."
        )
        pending_items = pending_items[:remaining_quota]

    if not pending_items:
        print("⚠️ Every successful item has already been published to Instagram.")
        return []

    tz = ZoneInfo(tz_name)
    interval = timedelta(hours=interval_hours)
    last_publish = None if publish_now else get_last_publish_time(render_manifest, tz_name)

    upload_results: list[dict] = []
    updated_manifest = deepcopy(render_manifest)

    print(f"\n🚀 Publishing {len(pending_items)} clip(s) to Instagram...")
    print(f"   Interval between clips: {interval_hours} hour(s)")
    print(f"   Timezone: {tz_name}")
    if publish_now:
        print("   Mode: PUBLISH NOW (the interval is ignored)")

    for idx, item in enumerate(pending_items, 1):
        rank = item.get("rank")
        manifest_row = get_manifest_row(updated_manifest, item)
        caption, _ = _instagram_caption(item)
        video_path = item.get("video_path", "")
        now = datetime.now(tz)

        # The IG API publishes immediately, so respect the interval by deferring.
        if last_publish is not None and now < last_publish + interval:
            next_slot = last_publish + interval
            print(
                f"\n⏸️ Rank {rank} deferred until "
                f"{next_slot.strftime('%Y-%m-%d %H:%M %Z')} (interval not elapsed)."
            )
            if manifest_row is not None:
                manifest_row["ig_upload_status"] = "deferred"
                manifest_row["ig_next_slot_local"] = next_slot.strftime(
                    "%Y-%m-%d %H:%M:%S %Z"
                )
            upload_results.append({
                "rank": rank,
                "status": "deferred",
                "filename": os.path.basename(video_path),
                "next_slot": next_slot.isoformat(),
            })
            continue

        print(f"\n{'=' * 60}")
        print(f"=== Clip {idx}/{len(pending_items)} — rank {rank} ===")
        print(f"Caption : {caption[:80]}{'...' if len(caption) > 80 else ''}")
        print(f"Video   : {os.path.basename(video_path)}")
        print(f"{'=' * 60}")

        try:
            result = _publish_one(config, item, caption)
            published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            if manifest_row is not None:
                manifest_row.update({
                    "ig_upload_status": result["status"],
                    "ig_container_id": result["container_id"],
                    "ig_media_id": result["media_id"],
                    "ig_container_status": result["status_code"],
                    "ig_caption": caption,
                    "ig_upload_error": None,
                })
                if result["media_id"]:
                    manifest_row["ig_published_at_utc"] = published_at

            upload_results.append({
                "rank": rank,
                "status": result["status"],
                "filename": os.path.basename(video_path),
                "container_id": result["container_id"],
                "media_id": result["media_id"],
            })

            if result["media_id"]:
                last_publish = datetime.now(tz)
                print(f"   ✅ Reel published. Media ID: {result['media_id']}")
            else:
                print(
                    "   ⏳ Instagram is still processing the container; the next "
                    "run will publish it."
                )

        except Exception as e:
            err = str(e)
            if manifest_row is not None:
                manifest_row["ig_upload_status"] = "failed"
                manifest_row["ig_upload_error"] = err

            upload_results.append({
                "rank": rank,
                "status": "failed",
                "filename": os.path.basename(video_path),
                "error": err,
            })
            print(f"   ❌ Upload failed for rank {rank}: {err}")
            print("   🛑 Batch stopped because a publish failed.")
            break

        save_json_file(result_file, upload_results)
        save_json_file(updated_manifest_file, updated_manifest)

    save_json_file(result_file, upload_results)
    save_json_file(updated_manifest_file, updated_manifest)

    print(f"\n💾 Upload results saved to: {result_file}")
    print(f"💾 Updated manifest saved to: {updated_manifest_file}")

    return upload_results


def _instagram_caption(item: dict) -> tuple[str, str]:
    """
    Build the Reel caption from a manifest row.

    Instagram has no separate title field, so the title and description are
    joined into one caption.
    """
    title, description = get_clip_title_and_description(item, title_limit=100)
    caption = f"{title}\n\n{description}".strip() if description else title
    return caption[:IG_CAPTION_MAX_CHARS], title
