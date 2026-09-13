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
from .routes import files, jobs, settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    print("🚀 AutoCutClips Studio — backend starting...")
    yield
    print("👋 Backend shutting down...")


app = FastAPI(
    title="AutoCutClips Studio",
    description="AI Auto-Clipper & Teaser Generator — Web GUI API",
    version=VERSION,
    lifespan=lifespan,
)

# CORS — allow the frontend dev servers and the published dashboard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "https://naufalrizqullah.github.io",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(files.router)
app.include_router(settings.router)


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
