"""
app.web.api.worker — Background task runner for the clipping pipeline.

Wraps ``app.clipping.runner.run_pipeline()`` in a thread-pool task and mirrors
its progress callback into the job store.
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import store
from .config_adapter import build_config_from_payload
from .models import ClipDetail, JobStatus

# Semaphore to cap the number of concurrently running jobs.
MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_JOBS", "1"))
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS)

# Runtime settings overrides (API keys etc.) held in memory.
_settings_env: dict[str, str] = {}

# Pipeline step -> job status shown in the dashboard.
_STEP_STATUS = {
    "download": JobStatus.DOWNLOADING,
    "transcribe": JobStatus.TRANSCRIBING,
    "analyze": JobStatus.ANALYZING,
    "render": JobStatus.RENDERING,
}


def set_settings_env(env: dict[str, str]) -> None:
    """Update the runtime settings environment."""
    _settings_env.update(env)


def get_settings_env() -> dict[str, str]:
    """Return a copy of the current settings environment."""
    return dict(_settings_env)


def _clip_details(job_id: str, render_manifest: list[dict]) -> list[ClipDetail]:
    """Convert manifest rows into the API's clip detail models."""
    clips: list[ClipDetail] = []
    for entry in render_manifest:
        filename = os.path.basename(
            entry.get("output_file") or entry.get("video_path") or ""
        )
        clips.append(
            ClipDetail(
                rank=entry.get("rank", 0),
                viral_score=entry.get("viral_score"),
                title=entry.get("title_indonesia", ""),
                title_en=entry.get("title_inggris", ""),
                filename=filename,
                duration=entry.get("duration"),
                start_time=entry.get("start_time"),
                end_time=entry.get("end_time"),
                download_url=f"/api/outputs/{job_id}/{filename}",
                metadata=entry,
            )
        )
    return clips


def _run_pipeline_sync(job_id: str, payload: dict) -> None:
    """Run the clipping pipeline on a worker thread, reporting into the job store."""
    from ...clipping.runner import run_pipeline

    def on_progress(step, step_number, total_steps, message, percent):
        status = _STEP_STATUS.get(step)
        if status is not None:
            store.set_status(job_id, status)
        store.update_progress(
            job_id,
            step=step,
            step_number=step_number,
            total_steps=total_steps,
            message=message,
            percent=percent,
        )

    try:
        cfg = build_config_from_payload(payload, job_id, env_overrides=_settings_env)

        if not cfg.api_key_gemini:
            store.set_error(
                job_id,
                "GOOGLE_API_KEY not found. Set it in Settings or in a .env file.",
            )
            return

        # An uploaded file replaces the download step; the config adapter already
        # points file_video_asli at it, so only existence needs checking here.
        if payload.get("upload_filename") and not os.path.exists(cfg.file_video_asli):
            store.set_error(
                job_id, f"Uploaded file not found: {payload['upload_filename']}"
            )
            return

        if not cfg.url_youtube and not os.path.exists(cfg.file_video_asli):
            store.set_error(
                job_id,
                "No source video for this job ID — the file may have been deleted.",
            )
            return

        render_manifest = run_pipeline(cfg, on_progress=on_progress)
        store.set_clips(job_id, _clip_details(job_id, render_manifest))

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        store.set_error(job_id, error_msg)
        store.update_progress(
            job_id,
            step="error",
            step_number=0,
            total_steps=7,
            message=f"Pipeline failed: {error_msg}",
            percent=0.0,
        )
        print(f"[Worker] Job {job_id} failed:\n{traceback.format_exc()}", file=sys.stderr)


async def submit_job(job_id: str, payload: dict) -> None:
    """
    Submit a job to the background worker queue.

    A semaphore limits concurrency and the pipeline runs in a thread pool so the
    asyncio event loop is never blocked.
    """
    async def _run():
        async with _semaphore:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(_executor, _run_pipeline_sync, job_id, payload)

    asyncio.create_task(_run())
