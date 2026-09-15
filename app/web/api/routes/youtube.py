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
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ....uploaders import youtube_token
from ....uploaders.youtube import upload_manifest_to_youtube
from .. import store

router = APIRouter(prefix="/api/youtube", tags=["youtube"])

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
CREDENTIALS_DIR = os.path.join(PROJECT_ROOT, ".credentials")
CLIENT_SECRET_FILE = os.path.join(CREDENTIALS_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(CREDENTIALS_DIR, "youtube_token.json")

# Single-user local backend: one OAuth flow and one upload run in flight at a time.
_pending_flow: dict = {"flow": None}
_upload_status: dict[str, dict] = {}


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


@router.post("/client-secret")
async def save_client_secret(req: ClientSecretRequest):
    """Store the OAuth client JSON downloaded from Google Cloud Console."""
    try:
        parsed = json.loads(req.content)
    except json.JSONDecodeError:
        raise HTTPException(400, "Not valid JSON — paste the full client_secret.json content.")

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

    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRET_FILE, scopes=youtube_token.YOUTUBE_SCOPES
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
