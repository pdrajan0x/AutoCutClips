"""
app.web.api.routes.youtube — YouTube login + upload endpoints for the Studio.

The OAuth "manual" flow (no local browser callback) is reused from
``app.uploaders.youtube_token``: the user opens a login link, Google redirects
to a localhost URL that fails to load (expected), and they paste that URL (or
just the ``code`` param) back here to finish the exchange.

The resulting token file has a refresh_token, so once connected the Studio
stays logged in indefinitely — no need to repeat the login for future uploads
unless the token is revoked from the Google account or deleted here.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ....uploaders import youtube_token
from ....uploaders.youtube import get_youtube_service, upload_manifest_to_youtube, upload_video_to_youtube
from .. import store

router = APIRouter(prefix="/api/youtube", tags=["youtube"])

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
CREDENTIALS_DIR = os.path.join(PROJECT_ROOT, ".credentials")
CLIENT_SECRET_FILE = os.path.join(CREDENTIALS_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(CREDENTIALS_DIR, "youtube_token.json")
QUEUE_FILE = os.path.join(PROJECT_ROOT, "outputs", "youtube_queue.json")

# Single-user local backend: one OAuth flow and one upload run in flight at a time.
_pending_flow: dict = {"flow": None}
_upload_status: dict[str, dict] = {}
_queue_lock = threading.Lock()


class ClientSecretRequest(BaseModel):
    content: str  # raw text of the downloaded OAuth client_secret.json


class ExchangeCodeRequest(BaseModel):
    pasted_url_or_code: str


class UploadRequest(BaseModel):
    job_id: str
    interval_hours: float = 2.0
    tz_name: str = "Asia/Kolkata"
    test_mode: bool = False


# ---------------------------------------------------------------------------
# Connection status
# ---------------------------------------------------------------------------

@router.get("/status")
async def youtube_status():
    has_client_secret = os.path.exists(CLIENT_SECRET_FILE)
    has_token = os.path.exists(TOKEN_FILE)
    channel = None
    connected = False
    error = None

    if has_token:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials.from_authorized_user_file(TOKEN_FILE, youtube_token.YOUTUBE_SCOPES)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            yt = build("youtube", "v3", credentials=creds)
            items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
            if items:
                channel = {"title": items[0]["snippet"]["title"], "id": items[0]["id"]}
                connected = True
        except Exception as e:
            error = str(e)

    return {
        "has_client_secret": has_client_secret,
        "has_token": has_token,
        "connected": connected,
        "channel": channel,
        "error": error,
    }


_REQUIRED_CLIENT_FIELDS = ("client_id", "client_secret", "auth_uri", "token_uri")


@router.post("/client-secret")
async def save_client_secret(req: ClientSecretRequest):
    """Store the OAuth client JSON downloaded from Google Cloud Console."""
    try:
        parsed = json.loads(req.content)
    except json.JSONDecodeError:
        raise HTTPException(400, "Not valid JSON — paste the full client_secret.json content.")

    block = parsed.get("installed") or parsed.get("web") if isinstance(parsed, dict) else None
    missing = [f for f in _REQUIRED_CLIENT_FIELDS if not (block or {}).get(f)]
    if not block or missing:
        raise HTTPException(
            400,
            "This doesn't look like the full client_secret.json Google Cloud Console gives you "
            f"(missing: {', '.join(missing) or 'installed/web block'}). Download the file fresh "
            "from Credentials → your OAuth client → Download JSON, and paste it unmodified — "
            "don't retype or shorten it.",
        )

    os.makedirs(CREDENTIALS_DIR, exist_ok=True)
    with open(CLIENT_SECRET_FILE, "w", encoding="utf-8") as f:
        json.dump(parsed, f)
    return {"saved": True}


# ---------------------------------------------------------------------------
# OAuth login (manual / no local browser callback)
# ---------------------------------------------------------------------------

@router.post("/auth/start")
async def start_auth():
    if not os.path.exists(CLIENT_SECRET_FILE):
        raise HTTPException(400, "Upload your Google OAuth client_secret.json first.")

    from google_auth_oauthlib.flow import InstalledAppFlow

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            CLIENT_SECRET_FILE, scopes=youtube_token.YOUTUBE_SCOPES
        )
    except ValueError as e:
        raise HTTPException(
            400,
            f"The saved client_secret.json is invalid ({e}). Re-download it from Google Cloud "
            "Console (Credentials → your OAuth client → Download JSON) and save it again — "
            "don't retype or shorten it.",
        )
    flow.redirect_uri = "http://localhost:1"
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    _pending_flow["flow"] = flow
    return {"auth_url": auth_url}


@router.post("/auth/exchange")
async def exchange_auth(req: ExchangeCodeRequest):
    flow = _pending_flow.get("flow")
    if flow is None:
        raise HTTPException(400, "No login in progress — click 'Get Login Link' first.")

    raw = req.pasted_url_or_code.strip()
    code = parse_qs(urlparse(raw).query).get("code", [raw])[0]

    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise HTTPException(400, f"Could not exchange the code: {e}")

    os.makedirs(CREDENTIALS_DIR, exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(flow.credentials.to_json())
    _pending_flow["flow"] = None
    return {"connected": True}


@router.delete("/auth")
async def disconnect():
    """Forget the stored token (does not revoke it on Google's side)."""
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
    return {"connected": False}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@router.get("/uploadable-jobs")
async def uploadable_jobs():
    """Completed jobs with at least one successfully rendered clip."""
    results = []
    for job in store.list_jobs():
        if job.get("status") != "completed":
            continue
        outputs_dir = os.path.join(PROJECT_ROOT, "outputs", job["id"])
        manifest_path = os.path.join(outputs_dir, "render_manifest.json")
        if not os.path.exists(manifest_path):
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        successful = [r for r in manifest if r.get("status") == "success"]
        if not successful:
            continue
        uploaded = sum(1 for r in successful if r.get("youtube_upload_status") == "uploaded")
        results.append({
            "job_id": job["id"],
            "url": job.get("url"),
            "clip_count": len(successful),
            "uploaded_count": uploaded,
        })
    return {"jobs": results}


def _run_upload(job_id: str, req: UploadRequest) -> None:
    outputs_dir = os.path.join(PROJECT_ROOT, "outputs", job_id)
    manifest_file = os.path.join(outputs_dir, "render_manifest.json")
    result_file = os.path.join(outputs_dir, "youtube_upload_results.json")
    updated_manifest_file = os.path.join(outputs_dir, "render_manifest_uploaded.json")

    try:
        results = upload_manifest_to_youtube(
            token_file=TOKEN_FILE,
            manifest_file=manifest_file,
            result_file=result_file,
            updated_manifest_file=updated_manifest_file,
            tz_name=req.tz_name,
            interval_hours=req.interval_hours,
            test_mode=req.test_mode,
            skip_approval=True,  # no TTY in the web flow
        )
        _upload_status[job_id] = {"state": "done", "results": results, "error": None}
    except Exception as e:
        _upload_status[job_id] = {"state": "failed", "results": None, "error": str(e)}


@router.post("/upload")
async def upload_to_youtube(req: UploadRequest):
    if not os.path.exists(TOKEN_FILE):
        raise HTTPException(400, "Not connected — complete YouTube login first.")

    outputs_dir = os.path.join(PROJECT_ROOT, "outputs", req.job_id)
    if not os.path.exists(os.path.join(outputs_dir, "render_manifest.json")):
        raise HTTPException(404, "No render_manifest.json for this job.")

    if _upload_status.get(req.job_id, {}).get("state") == "running":
        raise HTTPException(409, "An upload for this job is already running.")

    _upload_status[req.job_id] = {"state": "running", "results": None, "error": None}
    thread = threading.Thread(target=_run_upload, args=(req.job_id, req), daemon=True)
    thread.start()
    return {"started": True, "job_id": req.job_id}


@router.get("/upload/{job_id}/status")
async def upload_status(job_id: str):
    return _upload_status.get(job_id, {"state": "idle", "results": None, "error": None})


# ---------------------------------------------------------------------------
# Channel dashboard (uploaded videos + stats)
# ---------------------------------------------------------------------------

def _youtube_client():
    if not os.path.exists(TOKEN_FILE):
        raise HTTPException(400, "Not connected — complete YouTube login first.")
    try:
        return get_youtube_service(TOKEN_FILE)
    except Exception as e:
        raise HTTPException(400, f"Could not use the stored YouTube login: {e}")


@router.get("/channel/stats")
async def channel_stats():
    yt = _youtube_client()
    items = yt.channels().list(part="snippet,statistics", mine=True).execute().get("items", [])
    if not items:
        raise HTTPException(404, "No YouTube channel found for this account.")
    ch = items[0]
    stats = ch.get("statistics", {})
    return {
        "title": ch["snippet"]["title"],
        "thumbnail": ch["snippet"].get("thumbnails", {}).get("default", {}).get("url"),
        "subscriber_count": int(stats.get("subscriberCount", 0)),
        "view_count": int(stats.get("viewCount", 0)),
        "video_count": int(stats.get("videoCount", 0)),
    }


@router.get("/channel/videos")
async def channel_videos(max_results: int = 25):
    yt = _youtube_client()

    channels = yt.channels().list(part="contentDetails", mine=True).execute().get("items", [])
    if not channels:
        raise HTTPException(404, "No YouTube channel found for this account.")
    uploads_playlist = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    playlist_items = yt.playlistItems().list(
        part="contentDetails", playlistId=uploads_playlist, maxResults=min(max_results, 50)
    ).execute().get("items", [])
    video_ids = [pi["contentDetails"]["videoId"] for pi in playlist_items]
    if not video_ids:
        return {"videos": []}

    videos = yt.videos().list(
        part="snippet,statistics,status", id=",".join(video_ids)
    ).execute().get("items", [])

    results = []
    for v in videos:
        snippet, stats, status = v["snippet"], v.get("statistics", {}), v.get("status", {})
        results.append({
            "video_id": v["id"],
            "title": snippet.get("title"),
            "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
            "published_at": snippet.get("publishedAt"),
            "privacy_status": status.get("privacyStatus"),
            "view_count": int(stats.get("viewCount", 0)),
            "like_count": int(stats.get("likeCount", 0)) if "likeCount" in stats else None,
            "comment_count": int(stats.get("commentCount", 0)) if "commentCount" in stats else None,
            "url": f"https://www.youtube.com/watch?v={v['id']}",
        })
    return {"videos": results}


# ---------------------------------------------------------------------------
# Ready-to-upload clips (across all completed jobs, clip-level)
# ---------------------------------------------------------------------------

def _manifest_rows(job_id: str) -> list[dict]:
    manifest_path = os.path.join(PROJECT_ROOT, "outputs", job_id, "render_manifest.json")
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _manifest_row(job_id: str, rank: int) -> Optional[dict]:
    for row in _manifest_rows(job_id):
        if row.get("rank") == rank:
            return row
    return None


@router.get("/uploadable-clips")
async def uploadable_clips():
    """Individual rendered clips (across all completed jobs) not yet uploaded or queued."""
    queued_keys = {(i["job_id"], i["rank"]) for i in _load_queue() if i["status"] in ("queued", "uploading")}

    results = []
    for job in store.list_jobs():
        if job.get("status") != "completed":
            continue
        for row in _manifest_rows(job["id"]):
            if row.get("status") != "success":
                continue
            if row.get("youtube_upload_status") == "uploaded":
                continue
            if (job["id"], row.get("rank")) in queued_keys:
                continue
            filename = os.path.basename(row.get("video_path", ""))
            results.append({
                "job_id": job["id"],
                "rank": row.get("rank"),
                "title": row.get("youtube_title_final") or row.get("title") or f"Clip {row.get('rank')}",
                "viral_score": row.get("viral_score"),
                "duration": row.get("duration"),
                "thumbnail_url": f"/api/outputs/{job['id']}/{os.path.basename(row.get('thumbnail_path') or '')}"
                if row.get("thumbnail_path") else None,
                "download_url": f"/api/outputs/{job['id']}/{filename}",
            })
    return {"clips": results}


# ---------------------------------------------------------------------------
# Upload queue — pick clips, space them by an interval, upload automatically
# ---------------------------------------------------------------------------

class QueueAddRequest(BaseModel):
    items: list[dict]  # [{"job_id": "...", "rank": 1}, ...]
    interval_hours: float = 2.0
    privacy_status: str = "public"  # "public" | "unlisted" | "private"
    start_at: Optional[str] = None  # ISO datetime; defaults to now


def _load_queue() -> list[dict]:
    if not os.path.exists(QUEUE_FILE):
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _save_queue(items: list[dict]) -> None:
    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    tmp = QUEUE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, QUEUE_FILE)


def _scheduled_at(entry: dict) -> datetime:
    """
    An entry's due time as an aware UTC datetime.

    A missing/corrupt value must not be able to stall the whole queue, and a
    naive timestamp must not blow up comparisons against an aware ``now``, so
    anything unparseable is treated as due immediately.
    """
    try:
        parsed = datetime.fromisoformat(str(entry.get("scheduled_at")))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _requeue_stranded_uploads() -> None:
    """A backend restart mid-upload leaves items stuck in 'uploading' forever."""
    with _queue_lock:
        items = _load_queue()
        stranded = [i for i in items if i.get("status") == "uploading"]
        if not stranded:
            return
        for item in stranded:
            item["status"] = "queued"
        _save_queue(items)
    print(f"[YouTube queue] Re-queued {len(stranded)} upload(s) interrupted by a restart.")


@router.get("/queue")
async def get_queue():
    with _queue_lock:
        items = _load_queue()
    return {"items": sorted(items, key=_scheduled_at)}


def enqueue_clips(
    refs: list[dict],
    interval_hours: float,
    privacy_status: str,
    start_at: datetime | None = None,
) -> list[dict]:
    """
    Add {"job_id", "rank"} references to the upload queue, spaced by *interval_hours*.

    New items are scheduled after anything already waiting, so queueing a second
    batch does not publish two clips at the same moment.
    """
    with _queue_lock:
        existing = _load_queue()
        pending_times = [_scheduled_at(i) for i in existing if i.get("status") == "queued"]
        start = start_at or datetime.now(timezone.utc)
        if not start.tzinfo:
            start = start.replace(tzinfo=timezone.utc)
        next_slot = max([start, *pending_times]) if pending_times else start

        already = {(i["job_id"], i["rank"]) for i in existing if i.get("status") != "failed"}

        added = []
        for ref in refs:
            job_id, rank = ref.get("job_id"), ref.get("rank")
            if (job_id, rank) in already:
                continue
            row = _manifest_row(job_id, rank)
            if not row or row.get("status") != "success":
                continue

            entry = {
                "id": uuid.uuid4().hex[:12],
                "job_id": job_id,
                "rank": rank,
                "title": row.get("youtube_title_final") or row.get("title") or f"Clip {rank}",
                "video_path": row.get("video_path"),
                "thumbnail_url": f"/api/outputs/{job_id}/{os.path.basename(row.get('thumbnail_path') or '')}"
                if row.get("thumbnail_path") else None,
                "privacy_status": privacy_status,
                "added_at": datetime.now(timezone.utc).isoformat(),
                "scheduled_at": next_slot.isoformat(),
                "status": "queued",
                "youtube_video_id": None,
                "youtube_url": None,
                "error": None,
            }
            existing.append(entry)
            added.append(entry)
            next_slot = next_slot + timedelta(hours=interval_hours)

        _save_queue(existing)

    return added


def enqueue_job_clips(job_id: str, interval_hours: float, privacy_status: str) -> list[dict]:
    """Queue every successfully rendered clip of *job_id*, best first."""
    rows = [r for r in _manifest_rows(job_id) if r.get("status") == "success"]
    rows.sort(key=lambda r: r.get("viral_score") or 0, reverse=True)
    return enqueue_clips(
        [{"job_id": job_id, "rank": r.get("rank")} for r in rows],
        interval_hours,
        privacy_status,
    )


@router.post("/queue")
async def add_to_queue(req: QueueAddRequest):
    if not req.items:
        raise HTTPException(400, "No clips selected.")
    if req.privacy_status not in ("public", "unlisted", "private"):
        raise HTTPException(400, "privacy_status must be public, unlisted or private.")

    start = None
    if req.start_at:
        try:
            start = datetime.fromisoformat(req.start_at)
        except ValueError:
            raise HTTPException(400, "start_at must be an ISO datetime, e.g. 2026-09-15T18:00:00Z")

    added = enqueue_clips(req.items, req.interval_hours, req.privacy_status, start)
    return {"added": added}


@router.delete("/queue/{item_id}")
async def remove_from_queue(item_id: str):
    with _queue_lock:
        items = _load_queue()
        remaining = [i for i in items if i["id"] != item_id]
        if len(remaining) == len(items):
            raise HTTPException(404, "Queue item not found.")
        _save_queue(remaining)
    return {"removed": item_id}


@router.post("/queue/{item_id}/upload-now")
async def upload_queue_item_now(item_id: str):
    with _queue_lock:
        items = _load_queue()
        found = next((i for i in items if i["id"] == item_id), None)
        if not found:
            raise HTTPException(404, "Queue item not found.")
        if found["status"] not in ("queued", "failed"):
            raise HTTPException(409, f"Item is already {found['status']}.")
        found["scheduled_at"] = datetime.now(timezone.utc).isoformat()
        found["status"] = "queued"
        _save_queue(items)
    return {"ok": True}


def _upload_one_queue_item(entry: dict) -> None:
    """Upload a single queued clip; mutates *entry* in place with the result."""
    try:
        youtube = get_youtube_service(TOKEN_FILE)
        row = _manifest_row(entry["job_id"], entry["rank"])
        if not row:
            raise RuntimeError("The source job's render_manifest.json is gone.")
        video_path = row.get("video_path") or entry.get("video_path")
        if not video_path or not os.path.exists(video_path):
            raise RuntimeError(f"The rendered clip is missing from disk: {video_path}")
        result = upload_video_to_youtube(
            youtube, row, publish_at_local=None, privacy_status=entry["privacy_status"]
        )
        entry.update(
            status="uploaded",
            youtube_video_id=result["video_id"],
            youtube_url=result["youtube_url"],
            error=None,
        )
        print(f"[YouTube queue] Uploaded {entry['title']!r} -> {result['youtube_url']}")
    except Exception as e:
        entry.update(status="failed", error=str(e))
        print(f"[YouTube queue] Upload failed for {entry['title']!r}: {e}")


def _scheduler_tick() -> None:
    """Upload at most one due item per tick, so uploads stay serialized."""
    # Without a token every claim would fail and burn the whole queue; the items
    # should simply wait until the account is connected again.
    if not os.path.exists(TOKEN_FILE):
        return

    with _queue_lock:
        items = _load_queue()
        now = datetime.now(timezone.utc)
        due = next(
            (
                i for i in sorted(items, key=_scheduled_at)
                if i.get("status") == "queued" and _scheduled_at(i) <= now
            ),
            None,
        )
        if due is None:
            return
        due["status"] = "uploading"
        _save_queue(items)

    _upload_one_queue_item(due)

    with _queue_lock:
        items = _load_queue()
        for i, item in enumerate(items):
            if item["id"] == due["id"]:
                items[i] = due
                break
        _save_queue(items)


def _scheduler_loop() -> None:
    while True:
        try:
            _scheduler_tick()
        except Exception as e:
            print(f"[YouTube queue] Scheduler tick failed: {e}")
        time.sleep(30)


_requeue_stranded_uploads()
threading.Thread(target=_scheduler_loop, daemon=True).start()
