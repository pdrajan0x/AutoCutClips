"""
app.web.api.app — FastAPI application entry point.

AutoCutClips Studio — web GUI backend.

Run with:
    uvicorn app.web.api.app:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import os
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import VERSION
from .routes import files, jobs, settings, youtube


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    print("🚀 AutoCutClips Studio — backend starting...")
    # Printed so a browser blocked by CORS can be diagnosed from the server log.
    print(f"   Allowed origins: {', '.join(ALLOWED_ORIGINS)}")
    yield
    print("👋 Backend shutting down...")


app = FastAPI(
    title="AutoCutClips Studio",
    description="AI Auto-Clipper & Teaser Generator — Web GUI API",
    version=VERSION,
    lifespan=lifespan,
)

# CORS — the Studio pages (docs/studio) served locally or from GitHub Pages.
#
# The Pages origin depends on who forked the repo, so it is configurable rather
# than hardcoded: set STUDIO_ALLOWED_ORIGINS to a comma-separated list to add
# your own (e.g. "https://<user>.github.io"). The defaults below cover
# `python -m http.server 8080 --directory docs`, common editor live servers, and
# this repo's own Pages site.
DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "https://pdrajan0x.github.io",
]

_extra_origins = [
    origin.strip().rstrip("/")
    for origin in os.environ.get("STUDIO_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
ALLOWED_ORIGINS = DEFAULT_ALLOWED_ORIGINS + _extra_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(files.router)
app.include_router(settings.router)
app.include_router(youtube.router)


@app.get("/")
async def root():
    return {
        "name": "AutoCutClips Studio",
        "version": VERSION,
        "docs": "/docs",
        "health": "/api/health",
    }


@app.post("/api/shutdown")
async def shutdown_server():
    """Trigger a graceful shutdown of the server."""
    async def _shutdown():
        # Signal our own process so uvicorn shuts down gracefully.
        await asyncio.sleep(0.5)
        os.kill(os.getpid(), signal.SIGINT)

    asyncio.create_task(_shutdown())
    return {"status": "shutting down", "message": "Server is stopping..."}
