"""
app.web.api.routes.jobs — Job management endpoints.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..models import (
    ClipDetail,
    JobCreateRequest,
    JobListResponse,
    JobProgressEvent,
    JobResponse,
    JobStatus,
)
from .. import store
from .. import worker

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _job_to_response(job: dict) -> JobResponse:
    """Convert internal job dict to API response model."""
    clips = job.get("clips", [])
    clip_list = []
    for c in clips:
        if isinstance(c, ClipDetail):
            clip_list.append(c)
        elif isinstance(c, dict):
            clip_list.append(ClipDetail(**c))

    progress = job.get("progress")
    if progress and isinstance(progress, dict):
        # Convert timestamp strings back to datetime
        if isinstance(progress.get("timestamp"), str):
            progress["timestamp"] = datetime.fromisoformat(progress["timestamp"])
        progress = JobProgressEvent(**progress)

    return JobResponse(
        id=job["id"],
        status=job.get("status", JobStatus.QUEUED),
        created_at=job.get("created_at", datetime.utcnow()),
        updated_at=job.get("updated_at", datetime.utcnow()),
        url=job.get("url"),
        upload_filename=job.get("upload_filename"),
        source=job.get("source", "youtube"),
        config=job.get("config", {}),
        progress=progress,
        clips=clip_list,
        error=job.get("error"),
        log=job.get("log", []),
    )


@router.post("", status_code=201)
async def create_job(req: JobCreateRequest) -> JobResponse:
    """Create a new clipping job and submit it to the background queue."""
    if not req.url and not req.upload_filename and not req.reuse_job_id:
        raise HTTPException(
            status_code=400,
            detail="Either 'url', 'upload_filename', or 'reuse_job_id' must be provided.",
        )

    payload = req.model_dump(exclude={"playlist", "playlist_limit"})
    # Convert enums to string values for JSON serialization
    for key, value in payload.items():
        if hasattr(value, "value"):
            payload[key] = value.value

    reuse_job_id = payload.pop("reuse_job_id", None)

    # Reusing a job defaults to replaying its saved Gemini response, but an
    # explicit choice from the UI wins (the field is None when unspecified).
    if payload.get("load_gemini_json") is None:
        payload["load_gemini_json"] = bool(reuse_job_id)


    job_id = store.create_job(
        url=req.url,
        upload_filename=req.upload_filename,
        source=req.source.value if hasattr(req.source, "value") else req.source,
        config=payload,
        job_id=reuse_job_id
    )

    # Submit to background worker
    await worker.submit_job(job_id, payload)

    job = store.get_job(job_id)
    return _job_to_response(job)


def _playlist_url(url: str) -> str | None:
    """
    The canonical playlist URL for a YouTube link carrying ``list=``, else None.

    A "watch?v=...&list=..." link is rewritten to the playlist page so the whole
    list is expanded rather than the single video it happens to point at.
    """
    parsed = urlparse(url.strip())
    list_id = (parse_qs(parsed.query).get("list") or [None])[0]
    if list_id and ("youtube.com" in parsed.netloc or "youtu.be" in parsed.netloc):
        return f"https://www.youtube.com/playlist?list={list_id}"
    return None


def _expand_playlist(url: str, limit: int | None) -> tuple[str, list[str]]:
    """List the video URLs of a playlist (or channel page) without downloading anything."""
    import yt_dlp

    from ....clipping import ytdl

    cookies = worker.get_settings_env().get("YTDLP_COOKIES_FILE")
    opts = ytdl.base_opts(
        SimpleNamespace(cookies_file=cookies),
        extract_flat="in_playlist",
        skip_download=True,
        noplaylist=False,
    )
    if limit:
        opts["playlistend"] = limit

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(_playlist_url(url) or url, download=False) or {}

    urls: list[str] = []
    for entry in info.get("entries") or []:
        if not entry:
            continue
        # Private/deleted playlist entries have no usable ID.
        title = (entry.get("title") or "").strip().lower()
        if title in ("[private video]", "[deleted video]"):
            continue
        video_url = entry.get("url") or ""
        if entry.get("id") and not video_url.startswith("http"):
            video_url = f"https://www.youtube.com/watch?v={entry['id']}"
        if video_url and video_url not in urls:
            urls.append(video_url)
    return info.get("title") or "Playlist", urls[:limit] if limit else urls


@router.post("/playlist", status_code=201)
async def create_playlist_jobs(req: JobCreateRequest) -> dict:
    """
    Create one job per video in a playlist, all with the same settings.

    The jobs join the normal queue, so they run as many at a time as the
    concurrency setting allows, and each one auto-uploads on its own if asked.
    """
    if not req.url:
        raise HTTPException(status_code=400, detail="A playlist URL is required.")

    try:
        title, urls = await asyncio.get_running_loop().run_in_executor(
            None, _expand_playlist, req.url, req.playlist_limit
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read the playlist: {e}")
    if not urls:
        raise HTTPException(status_code=400, detail="No playable videos were found in that playlist.")

    base = req.model_dump(exclude={"reuse_job_id", "playlist", "playlist_limit", "upload_filename"})
    for key, value in base.items():
        if hasattr(value, "value"):
            base[key] = value.value
    if base.get("load_gemini_json") is None:
        base["load_gemini_json"] = False

    jobs = []
    for video_url in urls:
        payload = dict(base, url=video_url)
        job_id = store.create_job(url=video_url, source=base.get("source") or "youtube", config=payload)
        await worker.submit_job(job_id, payload)
        jobs.append(_job_to_response(store.get_job(job_id)))

    return {"playlist_title": title, "count": len(jobs), "jobs": jobs}


@router.get("")
async def list_jobs() -> JobListResponse:
    """List all jobs (newest first)."""
    jobs = store.list_jobs()
    return JobListResponse(
        jobs=[_job_to_response(j) for j in jobs],
        total=len(jobs),
    )


@router.get("/{job_id}")
async def get_job(job_id: str) -> JobResponse:
    """Get job detail."""
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


@router.delete("/{job_id}")
async def delete_job(job_id: str) -> dict:
    """Cancel/delete a job."""
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # If running, mark as cancelled first
    running_states = {
        JobStatus.QUEUED.value,
        JobStatus.DOWNLOADING.value,
        JobStatus.TRANSCRIBING.value,
        JobStatus.ANALYZING.value,
        JobStatus.RENDERING.value,
    }
    if job.get("status") in running_states:
        store.set_status(job_id, JobStatus.CANCELLED)

    store.delete_job(job_id)
    return {"message": "Job deleted", "id": job_id}


@router.get("/{job_id}/status")
async def job_status_sse(job_id: str):
    """
    Server-Sent Events endpoint for real-time job progress.

    The client connects to this endpoint and receives progress updates
    as SSE events until the job completes or fails.
    """
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_stream():
        last_progress = None
        terminal_states = {
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        }

        while True:
            current_job = store.get_job(job_id)
            if current_job is None:
                yield f"data: {json.dumps({'type': 'deleted'})}\n\n"
                break

            status = current_job.get("status", "")
            progress = current_job.get("progress")

            # Build event data
            progress_data = None
            if progress:
                if hasattr(progress, "model_dump"):
                    progress_data = progress.model_dump()
                    if isinstance(progress_data.get("timestamp"), datetime):
                        progress_data["timestamp"] = progress_data["timestamp"].isoformat()
                elif isinstance(progress, dict):
                    progress_data = progress

            event = {
                "type": "progress",
                "status": status,
                "progress": progress_data,
                "error": current_job.get("error"),
            }

            # Only send if something changed
            event_json = json.dumps(event, default=str)
            if event_json != last_progress:
                yield f"data: {event_json}\n\n"
                last_progress = event_json

            # Stop streaming on terminal states
            if status in terminal_states:
                # Send final event with clips if completed
                if status == JobStatus.COMPLETED.value:
                    clips = current_job.get("clips", [])
                    clip_data = []
                    for c in clips:
                        if hasattr(c, "model_dump"):
                            clip_data.append(c.model_dump())
                        elif isinstance(c, dict):
                            clip_data.append(c)
                    final_event = {
                        "type": "completed",
                        "status": status,
                        "clips": clip_data,
                    }
                    yield f"data: {json.dumps(final_event, default=str)}\n\n"
                break

            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
