"""
app.web.api.models — Pydantic schemas for request/response validation.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourcePlatform(str, enum.Enum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    GDRIVE = "gdrive"


class AspectRatio(str, enum.Enum):
    RATIO_9_16 = "9:16"
    RATIO_16_9 = "16:9"
    RATIO_1_1 = "1:1"
    RATIO_3_4 = "3:4"
    RATIO_4_5 = "4:5"


class FontStyle(str, enum.Enum):
    DEFAULT = "DEFAULT"
    STORYTELLER = "STORYTELLER"
    HORMOZI = "HORMOZI"
    CINEMATIC = "CINEMATIC"


class FaceDetector(str, enum.Enum):
    MEDIAPIPE = "mediapipe"
    YOLO = "yolo"


class AIProvider(str, enum.Enum):
    GEMINI = "gemini"
    NVIDIA = "nvidia"


class WhisperDevice(str, enum.Enum):
    CUDA = "cuda"
    CPU = "cpu"
    AUTO = "auto"


# ---------------------------------------------------------------------------
# Job Creation Request
# ---------------------------------------------------------------------------

class JobCreateRequest(BaseModel):
    """
    Payload to create a new clipping job.

    Every setting is optional: a field left out (None) uses the CLI default from
    ``clipping.config``, so the web API and the command line cannot drift apart.
    """

    # Source
    url: Optional[str] = Field(None, description="Video URL to process")
    upload_filename: Optional[str] = Field(None, description="Filename of an uploaded video")
    source: SourcePlatform = Field(SourcePlatform.YOUTUBE, description="Source platform")
    reuse_job_id: Optional[str] = Field(None, description="Existing Job ID to reuse its downloads and JSON")

    # Main settings
    clips: Optional[int] = Field(None, ge=1, le=30, description="Number of clips to generate")
    ratio: Optional[AspectRatio] = Field(None, description="Output aspect ratio")
    source_height: Optional[str] = Field(None, description="Source download max height")
    render_height: Optional[str] = Field(None, description="Target output height")
    min_duration: Optional[float] = Field(None, ge=5, le=180, description="Shortest clip length (seconds)")
    max_duration: Optional[float] = Field(None, ge=5, le=180, description="Longest clip length (seconds)")

    # Content & hook
    words_per_sub: Optional[int] = Field(None, ge=1, le=15)
    hook_duration: Optional[int] = Field(None, ge=1, le=10)
    hook_teaser: Optional[bool] = None
    use_hook_glitch: Optional[bool] = Field(None, description="Deprecated alias of hook_teaser")
    use_broll: Optional[bool] = None
    use_auto_bgm: Optional[bool] = None
    use_karaoke_effect: Optional[bool] = None
    use_split_screen: Optional[bool] = None
    use_camera_switch: Optional[bool] = None
    no_subs: Optional[bool] = None
    no_segment_trim: Optional[bool] = None
    silence_trim: Optional[bool] = None

    # Captions & framing
    font_style: Optional[FontStyle] = None
    caption_case: Optional[str] = Field(None, pattern="^(normal|upper)$")
    caption_font_size: Optional[int] = Field(None, ge=20, le=200, description="Override caption base font size")
    title_overlay: Optional[bool] = None
    layout: Optional[str] = Field(None, pattern="^(auto|crop|blur)$")
    speaker_tracking: Optional[bool] = None

    # Language
    language: Optional[str] = Field(None, description="Spoken language code, or 'auto'")
    caption_script: Optional[str] = Field(None, pattern="^(latin|native)$")

    # Whisper
    whisper_model: Optional[str] = None
    whisper_device: Optional[WhisperDevice] = None
    whisper_compute_type: Optional[str] = None
    use_dlp_subs: Optional[bool] = None

    # AI
    ai_provider: Optional[AIProvider] = None
    gemini_model: Optional[str] = None
    face_detector: Optional[FaceDetector] = None
    # Reuse the saved Gemini response for this job ID instead of calling the API.
    # Left as None when the caller says nothing, so "reuse a job" can default it
    # on while an explicit choice from the UI still wins.
    load_gemini_json: Optional[bool] = None


# ---------------------------------------------------------------------------
# Job Progress Event
# ---------------------------------------------------------------------------

class JobProgressEvent(BaseModel):
    """Single progress event for SSE streaming."""
    step: str
    step_number: int
    total_steps: int
    message: str
    percent: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Clip Detail
# ---------------------------------------------------------------------------

class ClipDetail(BaseModel):
    """Metadata for a single rendered clip."""
    rank: int
    viral_score: Optional[int] = None
    title: Optional[str] = None
    filename: str
    duration: Optional[float] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    download_url: str
    thumbnail_url: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Job Response
# ---------------------------------------------------------------------------

class JobResponse(BaseModel):
    """Full job detail for API responses."""
    id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    url: Optional[str] = None
    upload_filename: Optional[str] = None
    source: SourcePlatform = SourcePlatform.YOUTUBE
    config: dict = Field(default_factory=dict)
    progress: Optional[JobProgressEvent] = None
    clips: list[ClipDetail] = Field(default_factory=list)
    error: Optional[str] = None
    log: list[str] = Field(default_factory=list)


class JobListResponse(BaseModel):
    """Paginated job list."""
    jobs: list[JobResponse]
    total: int


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class SettingsRequest(BaseModel):
    """Settings update payload."""
    google_api_key: Optional[str] = None
    pexels_api_key: Optional[str] = None
    hf_token: Optional[str] = None
    nvidia_api_key: Optional[str] = None
    youtube_cookies: Optional[str] = Field(
        None, description="Raw Netscape-format cookies.txt content, to get past YouTube's bot check"
    )
    # Defaults
    default_clips: Optional[int] = None
    default_ratio: Optional[AspectRatio] = None
    default_font_style: Optional[FontStyle] = None
    default_whisper_model: Optional[str] = None
    default_whisper_device: Optional[WhisperDevice] = None
    default_ai_provider: Optional[AIProvider] = None


class SettingsResponse(BaseModel):
    """Current settings (keys are masked)."""
    google_api_key_set: bool = False
    pexels_api_key_set: bool = False
    hf_token_set: bool = False
    nvidia_api_key_set: bool = False
    youtube_cookies_set: bool = False
    default_clips: int = 7
    default_ratio: str = "9:16"
    default_font_style: str = "HORMOZI"
    default_whisper_model: str = "large-v3"
    default_whisper_device: str = "cuda"
    default_ai_provider: str = "gemini"
    gpu_available: bool = False


class SystemHealthResponse(BaseModel):
    """System health check."""
    status: str = "ok"
    version: str
    gpu_available: bool
    ffmpeg_available: bool
    jobs_running: int
    jobs_queued: int
