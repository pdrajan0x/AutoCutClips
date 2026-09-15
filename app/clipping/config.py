"""
clipping.config — Master configuration.

Holds every default value, the CLI parser, and ``config_from_args`` — the one
place that turns parsed options into the runtime config. The web API builds its
config through the same function, so a new option only has to be added here.
"""

import argparse
import os
from types import SimpleNamespace

from .engine.prompt import MAX_CLIP_DURATION, MIN_CLIP_DURATION

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ==============================================================================
# DEFAULT VALUES
# ==============================================================================

BASE_DIR = os.getcwd()
FONT_DIR = os.path.abspath(os.path.join(BASE_DIR, "custom_fonts"))

# 1. MAIN SETTINGS
CLIP_COUNT = 7
ASPECT_RATIO = "9:16"

# 2. CONTENT & HOOK SETTINGS
# 2-4 words per caption is what fast-reading short-form captions use; 5 words
# forced viewers to read ahead of the speaker.
MAX_WORDS_PER_SUBTITLE = 3
HOOK_DURATION = 3
USE_BROLL = True
# Off by default: clips open directly on their strongest line. The teaser
# (flash-forward to the peak line, then a clean cut to the clip) is opt-in.
HOOK_TEASER = False
USE_SPLIT_SCREEN = False
USE_CAMERA_SWITCH = False
DIARIZATION_NUM_SPEAKERS = "auto"
SWITCH_HOLD_DURATION = 2.0
SWITCH_BLEND_DURATION = 0.0  # 0 = instant snap, >0 = smooth blend in seconds

# Source Platform
SOURCE_PLATFORM = "youtube"

# 3. SUBTITLE & TYPOGRAPHY SETTINGS (ASS STYLE)
USE_ADVANCED_TEXT = True  # kinetic captions; --simple-captions turns them off
USE_KARAOKE_EFFECT = True

ACTIVE_FONT_STYLE = "DEFAULT"  # Montserrat Black — the heaviest, most readable preset

FONT_PRESETS = {
    "DEFAULT": {
        "main": {
            "name": "Montserrat Black",
            "file": "Montserrat-Black.ttf",
            "url": "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Black.ttf",
            "bold": 1,
        },
        "accent": {
            "name": "Montserrat Medium",
            "file": "Montserrat-Medium.ttf",
            "url": "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Medium.ttf",
            "bold": 0,
        },
    },
    "STORYTELLER": {
        "main": {
            "name": "Inter",
            "file": "Inter-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-400-normal.ttf",
            "bold": 0,
        },
        "accent": {
            "name": "Lora",
            "file": "Lora-Bold.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/lora@latest/latin-700-normal.ttf",
            "bold": 1,
        },
    },
    "HORMOZI": {
        "main": {
            "name": "Montserrat",
            "file": "Montserrat-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/montserrat@latest/latin-400-normal.ttf",
            "bold": 0,
        },
        "accent": {
            "name": "Anton",
            "file": "Anton-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/anton@latest/latin-400-normal.ttf",
            "bold": 0,
        },
    },
    "CINEMATIC": {
        "main": {
            "name": "Roboto",
            "file": "Roboto-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/roboto@latest/latin-400-normal.ttf",
            "bold": 0,
        },
        "accent": {
            "name": "Bebas Neue",
            "file": "BebasNeue-Regular.ttf",
            "url": "https://cdn.jsdelivr.net/fontsource/fonts/bebas-neue@latest/latin-400-normal.ttf",
            "bold": 0,
        },
    },
}

# 9:16 (vertical) only
ASS_ALIGN_916 = 2
ASS_MARGIN_916 = 450
ASS_FONT_916 = 90
ACCENT_WORD_SCALE_916 = 150  # percent size of the AI's most important keywords

# 16:9 (horizontal) only
ASS_ALIGN_169 = 2
ASS_MARGIN_169 = 70
ASS_FONT_169 = 80
ACCENT_WORD_SCALE_169 = 150

# Keyword / spoken-word highlight colour (ASS format is BGR: &H[Blue][Green][Red]&) — gold
ACCENT_WORD_COLOR = "&H00D7FF&"

# 4. EXTERNAL ASSET SETTINGS
THUMBNAIL_FONT_NAME = "Montserrat-Black.ttf"
URL_FONT_THUMBNAIL = (
    "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Black.ttf"
)

URL_MEDIAPIPE_MODEL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_full_range/float16/latest/blaze_face_full_range.tflite"

# 5. AUTO-BGM & AUDIO DUCKING SETTINGS
USE_AUTO_BGM = True
BGM_BASE_VOLUME = 0.12  # music should sit under the voice, not compete with it
BGM_MODE = "ducking"  # 'ducking' = sidechain compress, 'background' = constant volume mix

# Supported moods (these match the folder names under assets/bgm/)
BGM_MOODS = ["chill", "epic", "sad", "upbeat", "suspense"]
BGM_DIR = os.path.abspath(os.path.join(BASE_DIR, "assets", "bgm"))

# Whisper
WHISPER_MODEL = "large-v3"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE_TYPE = "float16"
DOWNLOAD_SOURCE_HEIGHT = "max"
VIDEO_QUALITY_CQ = 23
VIDEO_QUALITY_CRF = 20
VIDEO_PRESET = "auto"
VIDEO_SCALE_ALGO = "lanczos"
RENDER_OUTPUT_HEIGHT = 1080

# AI Provider
AI_PROVIDER = "gemini"
NVIDIA_MODEL = "deepseek-ai/deepseek-v4-pro"
GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_FALLBACK_MODEL = "gemini-2.5-flash"

# YouTube Shorts accept up to 3 minutes.
MAX_ALLOWED_CLIP_DURATION = 180
MIN_ALLOWED_CLIP_DURATION = 5


# ==============================================================================
# CLI PARSER
# ==============================================================================


def _parse_speakers(val: str) -> str | int:
    if val.lower() == "auto":
        return "auto"
    try:
        return int(val)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{val}' is not a valid integer or 'auto'")


def _parse_download_height(val: str) -> str | int:
    """
    Parse desired download source height.

    Accepts:
    - `max` to always prefer the highest available quality.
    - positive integers like 1080, 1440, 2160 to cap source resolution.
    """
    if str(val).lower() == "max":
        return "max"
    try:
        parsed = int(val)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"'{val}' is not valid. Use 'max' or an integer height (e.g. 1080, 1440, 2160)."
        ) from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Download source height must be a positive integer.")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="🎬 AutoCutClips — AI Auto-Clipper & Teaser Generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # --- Main settings ---
    p.add_argument(
        "--url", "-u", required=False, default=None,
        help="Video URL to process (supports YouTube, TikTok, Instagram, Google Drive). Required unless --story-mode is used.",
    )
    p.add_argument(
        "--source",
        choices=["youtube", "tiktok", "instagram", "gdrive"],
        default=SOURCE_PLATFORM,
        help="Video source platform. Determines download behavior and subtitle availability.",
    )
    p.add_argument(
        "--cookies",
        default=None,
        help="Netscape-format cookies.txt for yt-dlp (fixes YouTube's 'Sign in to confirm "
        "you're not a bot' on Colab/Kaggle). Also read from $YTDLP_COOKIES_FILE.",
    )
    p.add_argument(
        "--tiktok",
        action="store_true",
        default=False,
        help="[DEPRECATED] Use --source tiktok instead.",
    )
    p.add_argument(
        "--clips",
        "-n",
        type=int,
        default=CLIP_COUNT,
        help="Number of highlight clips to generate",
    )
    p.add_argument(
        "--ratio",
        "-r",
        default=ASPECT_RATIO,
        choices=["9:16", "16:9", "1:1", "3:4", "4:5"],
        help="Output aspect ratio",
    )
    p.add_argument(
        "--min-duration",
        type=float,
        default=MIN_CLIP_DURATION,
        help="Shortest clip length in seconds. Many strong moments are 15-30s.",
    )
    p.add_argument(
        "--max-duration",
        type=float,
        default=MAX_CLIP_DURATION,
        help="Longest clip length in seconds (YouTube Shorts allow up to 180).",
    )
    p.add_argument(
        "--source-height",
        type=_parse_download_height,
        default=DOWNLOAD_SOURCE_HEIGHT,
        help="Preferred source download max height. Use 'max' to fetch highest available quality.",
    )
    p.add_argument(
        "--render-height",
        default=str(RENDER_OUTPUT_HEIGHT),
        help="Target output height for the render. Use 'source' to match the source video height, or a number (e.g. 1080, 1440).",
    )

    # --- Content & hook ---
    p.add_argument(
        "--words-per-sub",
        type=int,
        default=MAX_WORDS_PER_SUBTITLE,
        help="Max words per caption group",
    )
    p.add_argument(
        "--hook-duration",
        type=int,
        default=HOOK_DURATION,
        help="Hook teaser duration in seconds",
    )
    p.add_argument(
        "--hook-teaser",
        action="store_true",
        default=HOOK_TEASER,
        help="Open each clip with a short flash-forward to its peak line, then cut to the clip. "
        "Off by default: clips open directly on their strongest line.",
    )
    p.add_argument("--no-hook", action="store_true", help=argparse.SUPPRESS)  # pre-1.15 flag; teaser is now off by default
    p.add_argument(
        "--hook-source",
        default=None,
        help="Google Drive URL or local path for a single custom hook video (.mp4); played as the teaser",
    )
    p.add_argument(
        "--hook-source-start",
        type=float,
        default=0.0,
        help="Start time in seconds for the custom hook video",
    )
    p.add_argument("--no-broll", action="store_true", help="Disable B-roll footage")
    p.add_argument("--no-bgm", action="store_true", help="Disable background music")
    p.add_argument(
        "--bgm-mode",
        choices=["ducking", "background"],
        default=BGM_MODE,
        help="BGM mixing mode: 'ducking' (sidechain compress — BGM auto-lowers during speech) or 'background' (constant low volume mix)",
    )
    p.add_argument(
        "--bgm-dir",
        default=None,
        help="Folder of your own music with chill/ epic/ sad/ upbeat/ suspense/ subfolders "
        "(default: assets/bgm). Handy for a Google Drive music folder on Colab.",
    )
    p.add_argument(
        "--bgm-volume",
        type=float,
        default=BGM_BASE_VOLUME,
        help="Background music volume before ducking (0.05 = barely there, 0.25 = prominent).",
    )
    p.add_argument(
        "--no-karaoke",
        action="store_true",
        help="Disable the spoken-word highlight (show the caption group without a moving highlight)",
    )
    p.add_argument(
        "--split-screen",
        action="store_true",
        default=USE_SPLIT_SCREEN,
        help="Enable split-screen mode for podcast with 2 speakers (vertical ratios only: 9:16, 1:1, 3:4, 4:5; requires HF_TOKEN for Pyannote)",
    )
    p.add_argument(
        "--diarization-speakers",
        type=_parse_speakers,
        default=DIARIZATION_NUM_SPEAKERS,
        help="Number of speakers for diarization, or 'auto' to auto-detect visually (used with --split-screen or --camera-switch)",
    )
    p.add_argument(
        "--camera-switch",
        action="store_true",
        default=USE_CAMERA_SWITCH,
        help="Enable camera-switch mode for podcast (vertical ratios only: 9:16, 1:1, 3:4, 4:5; requires HF_TOKEN). "
        "Mutually exclusive with --split-screen; split-screen takes precedence if both are set.",
    )
    p.add_argument(
        "--switch-hold-duration",
        type=float,
        default=SWITCH_HOLD_DURATION,
        help="Minimum seconds to hold on the current speaker before switching cameras (camera-switch mode only)",
    )
    p.add_argument(
        "--switch-blend-duration",
        type=float,
        default=SWITCH_BLEND_DURATION,
        help="Blend duration when switching speakers (0 = instant snap, 0.2 = smooth 200ms transition). Default is 0 (instant snap).",
    )
    p.add_argument(
        "--no-subs",
        action="store_true",
        help="Disable all subtitle rendering (useful if you only want the video without text)",
    )
    p.add_argument(
        "--dynamic-split",
        action="store_true",
        help="Automatically switch between full-screen (1 speaker) and split-screen (2 speakers) based on who is talking. Only active with --split-screen.",
    )
    p.add_argument(
        "--split-trigger",
        choices=["diarization", "face"],
        default="diarization",
        help="The trigger used to decide when to split the screen. 'diarization' uses audio (who is talking), 'face' uses video (how many faces are visible).",
    )

    # --- Split Screen Optimizations ---
    p.add_argument(
        "--split-zoom",
        type=float,
        default=1.0,
        help="Zoom factor for split-screen panels (e.g. 1.2, 1.5). Default is 1.0 (no zoom).",
    )
    p.add_argument(
        "--split-v-align",
        type=float,
        default=0.5,
        help="Vertical alignment for split-screen panels (0.0=top, 0.5=center, 1.0=bottom). Default is 0.5 (center).",
    )
    p.add_argument(
        "--split-auto-zoom",
        action="store_true",
        help="Automatically zoom in each split-screen panel until only one person is visible in each frame.",
    )
    p.add_argument(
        "--split-max-zoom",
        type=float,
        default=2.5,
        help="Maximum zoom factor allowed for auto-zoom (default: 2.5).",
    )

    # --- Subtitles & typography ---
    p.add_argument(
        "--font-style",
        default=ACTIVE_FONT_STYLE,
        choices=["DEFAULT", "STORYTELLER", "HORMOZI", "CINEMATIC"],
        help="Font style preset",
    )
    p.add_argument(
        "--caption-case",
        choices=["normal", "upper"],
        default="normal",
        help="Write captions as spoken ('normal') or in UPPERCASE ('upper').",
    )
    p.add_argument(
        "--simple-captions",
        action="store_true",
        help="Use the plain one-line karaoke captions instead of the default kinetic style "
        "(per-word pop, gold highlight, larger keywords).",
    )
    p.add_argument("--advanced-text", action="store_true", help=argparse.SUPPRESS)  # now the default
    p.add_argument("--advanced-text-hook", action="store_true", help=argparse.SUPPRESS)
    p.add_argument(
        "--no-title-overlay",
        action="store_true",
        help="Disable the AI headline boxed at the top of the frame for the first seconds "
        "(it keeps sound-off viewers from swiping away).",
    )

    # --- Whisper ---
    p.add_argument(
        "--use-dlp-subs",
        action="store_true",
        help="Use yt-dlp to download auto/manual subtitles to speed up process (skipping Whisper if found)",
    )
    p.add_argument(
        "--whisper-model", default=WHISPER_MODEL, help="Faster-Whisper model size"
    )
    p.add_argument(
        "--language",
        default="auto",
        help="Spoken language code for transcription (hi, en, ta, es, ...). 'auto' uses the language "
        "YouTube reports, then Whisper's detection. Speech is never translated.",
    )
    p.add_argument(
        "--caption-script",
        choices=["latin", "native"],
        default="latin",
        help="'latin': speech in a non-Latin script (Hindi, Tamil, Arabic, ...) keeps its language but is "
        "written in English letters, e.g. 'namaste, mera naam ... hai'. 'native': keep the original "
        "script (needs a caption font that supports it).",
    )
    p.add_argument(
        "--whisper-device",
        default=WHISPER_DEVICE,
        choices=["cuda", "cpu", "auto"],
        help="Device for Whisper inference",
    )
    p.add_argument(
        "--whisper-compute-type",
        default=WHISPER_COMPUTE_TYPE,
        help="Compute type for Whisper (float16, int8, etc.)",
    )

    # --- AI & face detection ---
    p.add_argument(
        "--face-detector",
        choices=["mediapipe", "yolo"],
        default="mediapipe",
        help="AI model for face tracking (mediapipe is CPU, yolo uses GPU if available)",
    )
    p.add_argument(
        "--yolo-size",
        choices=["8n", "8s", "8m", "8n_v2", "9c"],
        default="8m",
        help="YOLO face model version/size (8n, 8s, 8m, 8n_v2, 9c). Only active if --face-detector yolo",
    )
    p.add_argument(
        "--ai-provider",
        choices=["gemini", "nvidia"],
        default=AI_PROVIDER,
        help="AI provider for video analysis (gemini or nvidia).",
    )
    p.add_argument(
        "--nvidia-model",
        default=NVIDIA_MODEL,
        help="Model name for NVIDIA NIM API (e.g. deepseek-ai/deepseek-v3).",
    )
    p.add_argument("--gemini-model", default=GEMINI_MODEL, help="Gemini model name")
    p.add_argument(
        "--gemini-fallback-model",
        default=GEMINI_FALLBACK_MODEL,
        help="Gemini fallback model name if main model fails",
    )
    p.add_argument(
        "--load-gemini-json",
        action="store_true",
        help="Load the saved gemini_response.json from outputs dir to bypass the AI generation step (useful for debugging)",
    )
    p.add_argument(
        "--target-accounts",
        default=None,
        help="Path to the account routing JSON (default: target_accounts.json in the "
        "working directory). Falls back to built-in defaults when the file is missing.",
    )
    p.add_argument(
        "--no-account-routing",
        action="store_true",
        help="Skip target-account classification entirely; the AI then spends its "
        "effort on clip selection and metadata only.",
    )
    p.add_argument(
        "--performance-file",
        default=None,
        help="Channel results written by `learn-youtube` (default: outputs/channel_performance.json). "
        "When it holds enough published clips, the AI is shown the best and weakest performers.",
    )
    p.add_argument(
        "--no-channel-learning",
        action="store_true",
        help="Do not show the AI how earlier clips performed on the channel.",
    )

    # --- Framing ---
    p.add_argument(
        "--layout",
        choices=["auto", "crop", "blur"],
        default="auto",
        help="Vertical framing: 'auto' crops to the face, but fits the whole frame over a blurred "
        "background when the clip has few faces (slides, screen recordings); 'crop' always crops; "
        "'blur' always fits the whole frame.",
    )
    p.add_argument(
        "--no-speaker-tracking",
        action="store_true",
        help="With several people in frame, follow faces by position instead of by who is talking.",
    )
    p.add_argument(
        "--static-crop",
        action="store_true",
        help="Disable face tracking and use static center crop for 1:1, 3:4, and 4:5 ratios",
    )

    # --- Smart Auto-Framing / Tracking ---
    p.add_argument(
        "--track-step",
        type=float,
        default=None,
        help="Face detection frequency in seconds (default: 0.25)",
    )
    p.add_argument(
        "--track-deadzone",
        type=float,
        default=None,
        help="Camera deadzone ratio (default: 0.15)",
    )
    p.add_argument(
        "--track-smooth",
        type=float,
        default=None,
        help="Camera smoothing speed (default: 0.30)",
    )
    p.add_argument(
        "--track-jitter",
        type=int,
        default=None,
        help="Pixel jitter threshold (default: 5)",
    )
    p.add_argument(
        "--track-snap",
        type=float,
        default=None,
        help="Face jump snap threshold (default: 0.08 for the standard renderer)",
    )
    p.add_argument(
        "--track-conf",
        type=float,
        default=0.55,
        help="[Experimental] Higher confidence threshold for face detection to prevent ghosts (default: 0.55)",
    )
    p.add_argument(
        "--track-smooth-window",
        type=int,
        default=12,
        help="[Experimental] Majority-vote window for layout stability (default: 12 frames)",
    )
    p.add_argument(
        "--scene-cut-threshold",
        type=int,
        default=18,
        help="[Experimental] Visibility change threshold to detect camera cuts and reset layout history (default: 18)",
    )
    p.add_argument(
        "--track-iou-threshold",
        type=float,
        default=0.2,
        help="[Experimental] Box overlap threshold to merge duplicate detections (default: 0.2)",
    )
    p.add_argument(
        "--video-bitrate",
        default="auto",
        help="Target video bitrate (e.g. 8M, 12M, auto). 'auto' scales based on resolution.",
    )
    p.add_argument(
        "--video-sharpen",
        action="store_true",
        help="Apply a subtle sharpening filter for clearer output.",
    )
    p.add_argument(
        "--video-cq",
        type=int,
        default=VIDEO_QUALITY_CQ,
        help="NVENC constant quality value (lower is sharper, bigger file).",
    )
    p.add_argument(
        "--video-crf",
        type=int,
        default=VIDEO_QUALITY_CRF,
        help="libx264 CRF value (lower is sharper, bigger file).",
    )
    p.add_argument(
        "--video-preset",
        default=VIDEO_PRESET,
        help="Override encoder preset for NVENC/libx264, or 'auto' to keep defaults.",
    )
    p.add_argument(
        "--video-scale-algo",
        choices=["lanczos", "bicubic", "bilinear", "area"],
        default=VIDEO_SCALE_ALGO,
        help="Resize algorithm used when scaling frames during rendering.",
    )

    # --- Segment Trimming ---
    trim_group = p.add_argument_group("Segment Trimming")
    trim_group.add_argument(
        "--no-segment-trim",
        action="store_true",
        default=False,
        help="Disable AI segment trimming (render full start-to-end instead of keep_segments).",
    )
    trim_group.add_argument(
        "--silence-trim",
        action="store_true",
        default=False,
        help="Instruct AI to aggressively trim silence/dead air from clips.",
    )

    # --- Story Clip Mode ---
    story_group = p.add_argument_group("Story Clip Mode")
    story_group.add_argument(
        "--story-mode",
        action="store_true",
        default=False,
        help="Enable Story Clip mode: assemble clips from multiple video sources using a JSON recipe.",
    )
    story_group.add_argument(
        "--story-recipe",
        default="story_recipe.json",
        help="Path to the story recipe JSON file.",
    )
    story_group.add_argument(
        "--sources-json",
        default="sources.json",
        help="Path to the sources registry JSON file.",
    )
    story_group.add_argument(
        "--story-output-dir",
        default=None,
        help="Output directory for story clips (default: outputs/story_clips).",
    )
    story_group.add_argument(
        "--skip-download",
        action="store_true",
        default=False,
        help="Skip source downloads and use existing cached files.",
    )

    # --- Voice-Over Commentary Pipeline ---
    vo_group = p.add_argument_group("Voice-Over Commentary (TTS)")
    vo_group.add_argument(
        "--voiceover",
        action="store_true",
        default=False,
        help="Enable AI voice-over commentary mode using Gemini and edge-tts.",
    )
    vo_group.add_argument(
        "--voiceover-voice",
        default="en-GB-MaisieNeural",
        help="TTS voice for edge-tts (e.g. id-ID-ArdiNeural, en-US-AvaNeural).",
    )
    vo_group.add_argument(
        "--voiceover-lang",
        choices=["id", "en"],
        default="en",
        help="Language for the commentary script generation.",
    )
    vo_group.add_argument(
        "--voiceover-style",
        choices=["analysis", "reaction", "lesson", "summary"],
        default="analysis",
        help="Style of the generated commentary.",
    )
    vo_group.add_argument(
        "--voiceover-length",
        choices=["short", "normal", "long"],
        default="short",
        help="Length of the generated commentary (short: ~10s, normal: ~30s, long: ~50s).",
    )
    vo_group.add_argument(
        "--voiceover-volume",
        type=float,
        default=1.0,
        help="Volume of the voice-over audio (0.0 to 1.0+).",
    )
    vo_group.add_argument(
        "--original-volume",
        type=float,
        default=0.15,
        help="Volume of the original video audio when voice-over is active.",
    )

    # --- Watermark ---
    wm_group = p.add_argument_group("Watermark")
    wm_group.add_argument(
        "--watermark",
        action="store_true",
        default=False,
        help="Enable watermark overlay on rendered clips.",
    )
    wm_group.add_argument(
        "--text",
        default=None,
        help="Watermark text to overlay (e.g. 'Channel Name').",
    )
    wm_group.add_argument(
        "--image",
        default=None,
        help="Path to watermark image file (supports PNG, JPG, JPEG, WEBP). PNG with transparency recommended.",
    )
    wm_group.add_argument(
        "--opacity",
        type=int,
        default=70,
        help="Watermark opacity in percent (1-100). Default: 70.",
    )
    wm_group.add_argument(
        "--position",
        default="center-right",
        choices=[
            "top-left", "top-center", "top-right",
            "center-left", "center", "center-right",
            "bottom-left", "bottom-center", "bottom-right",
        ],
        help="Watermark position on the video frame.",
    )
    wm_group.add_argument(
        "--padding",
        type=int,
        default=0,
        help="Watermark padding from the nearest edge in pixels.",
    )
    wm_group.add_argument(
        "--watermark-font-size",
        type=int,
        default=0,
        help="Watermark font size in pixels. 0 = auto (3%% of frame height).",
    )
    wm_group.add_argument(
        "--watermark-scale",
        type=int,
        default=15,
        help="Watermark image height as %% of frame height (1-100). Default: 15.",
    )

    return p


# Kept for callers that imported the old private name.
_build_parser = build_parser


def validate_clip_durations(min_duration: float, max_duration: float) -> str | None:
    """Return an error message when the clip length bounds are unusable, else None."""
    if not (MIN_ALLOWED_CLIP_DURATION <= min_duration < max_duration <= MAX_ALLOWED_CLIP_DURATION):
        return (
            f"clip length must satisfy {MIN_ALLOWED_CLIP_DURATION} <= --min-duration < --max-duration "
            f"<= {MAX_ALLOWED_CLIP_DURATION} (got {min_duration:g} and {max_duration:g})."
        )
    return None


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not args.story_mode and not args.url:
        parser.error("--url is required unless --story-mode is used.")

    error = validate_clip_durations(args.min_duration, args.max_duration)
    if error:
        parser.error(error)

    if args.watermark:
        if not args.text and not args.image:
            parser.error("--watermark requires either --text or --image.")
        if not (1 <= args.opacity <= 100):
            parser.error(f"--opacity must be between 1 and 100, got: {args.opacity}")
        if args.padding < 0:
            parser.error(f"--padding cannot be negative, got: {args.padding}")
        if args.watermark_font_size < 0:
            parser.error(f"--watermark-font-size cannot be negative, got: {args.watermark_font_size}")
        if not (1 <= args.watermark_scale <= 100):
            parser.error(f"--watermark-scale must be between 1 and 100, got: {args.watermark_scale}")
        if args.image:
            if not os.path.exists(args.image):
                parser.error(f"Watermark image file not found: {args.image}")
            valid_exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")
            if not args.image.lower().endswith(valid_exts):
                parser.error(
                    f"Unsupported watermark image format: {args.image}. "
                    f"Supported formats: {', '.join(valid_exts)}"
                )


def config_from_args(
    args: argparse.Namespace,
    *,
    base_dir: str | None = None,
    outputs_dir: str | None = None,
    env=None,
) -> SimpleNamespace:
    """
    Build the runtime config from parsed options.

    Shared by the CLI (``build_config``) and the web API (which parses no
    arguments and then overrides the fields a job sets), so both always carry
    the same fields with the same defaults.
    """
    env = os.environ if env is None else env
    base_dir = os.path.abspath(base_dir or os.getcwd())
    base_outputs = os.path.join(base_dir, "outputs")
    outputs_dir = os.path.abspath(outputs_dir or base_outputs)
    os.makedirs(outputs_dir, exist_ok=True)
    font_dir = os.path.join(base_dir, "custom_fonts")
    os.makedirs(font_dir, exist_ok=True)

    def path_in_base(name):
        return os.path.join(base_dir, name)

    return SimpleNamespace(
        # Paths
        base_dir=base_dir,
        outputs_dir=outputs_dir,
        font_dir=font_dir,
        source_video_path=path_in_base("source_video.mp4"),
        file_font_thumbnail=path_in_base(THUMBNAIL_FONT_NAME),
        file_mediapipe_model=path_in_base("blaze_face_full_range.tflite"),
        file_face_landmarker=path_in_base("face_landmarker.task"),
        # YOLO configs
        face_detector=args.face_detector,
        yolo_size=args.yolo_size,
        url_yolo_model=f"https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov{args.yolo_size}.pt",
        file_yolo_model=path_in_base(f"face_yolov{args.yolo_size}.pt"),
        # API keys (from env)
        api_key_gemini=env.get("GOOGLE_API_KEY", ""),
        api_key_nvidia=env.get("NVIDIA_API_KEY", ""),
        hf_token=env.get("HF_TOKEN", ""),
        pexels_api_key=env.get("PEXELS_API_KEY", ""),
        # Main settings
        source_platform="tiktok" if args.tiktok else args.source,
        url_youtube=args.url,
        cookies_file=os.path.abspath(args.cookies) if args.cookies else env.get("YTDLP_COOKIES_FILE") or None,
        clip_count=args.clips,
        aspect_ratio=args.ratio,
        min_clip_duration=float(args.min_duration),
        max_clip_duration=float(args.max_duration),
        download_source_height=args.source_height,
        render_output_height=args.render_height,
        # Content & hook
        max_words_per_subtitle=args.words_per_sub,
        hook_duration=args.hook_duration,
        hook_teaser=args.hook_teaser,
        hook_source=args.hook_source,
        hook_source_start=args.hook_source_start,
        no_segment_trim=args.no_segment_trim,
        silence_trim=args.silence_trim,
        use_broll=not args.no_broll,
        use_auto_bgm=not args.no_bgm,
        use_karaoke_effect=not args.no_karaoke,
        use_split_screen=args.split_screen,
        use_dynamic_split=args.dynamic_split,
        split_trigger=args.split_trigger,
        use_camera_switch=args.camera_switch,
        diarization_num_speakers=args.diarization_speakers,
        switch_hold_duration=args.switch_hold_duration,
        switch_blend_duration=args.switch_blend_duration,
        split_zoom=args.split_zoom,
        split_v_align=args.split_v_align,
        split_auto_zoom=args.split_auto_zoom,
        split_max_zoom=args.split_max_zoom,
        # Framing
        layout=args.layout,
        speaker_tracking=not args.no_speaker_tracking,
        static_crop=args.static_crop,
        # Subtitles & typography
        no_subs=args.no_subs,
        active_font_style=args.font_style,
        font_presets=FONT_PRESETS,
        use_advanced_text=not args.simple_captions,
        caption_case=args.caption_case,
        title_overlay=not args.no_title_overlay,
        # ASS position values
        ass_align_916=ASS_ALIGN_916,
        ass_margin_916=ASS_MARGIN_916,
        ass_font_916=ASS_FONT_916,
        accent_word_scale_916=ACCENT_WORD_SCALE_916,
        ass_align_169=ASS_ALIGN_169,
        ass_margin_169=ASS_MARGIN_169,
        ass_font_169=ASS_FONT_169,
        accent_word_scale_169=ACCENT_WORD_SCALE_169,
        accent_word_color=ACCENT_WORD_COLOR,
        # Asset URLs
        url_font_thumbnail=URL_FONT_THUMBNAIL,
        url_mediapipe_model=URL_MEDIAPIPE_MODEL,
        # BGM
        bgm_base_volume=args.bgm_volume,
        bgm_mode=args.bgm_mode,
        bgm_moods=BGM_MOODS,
        bgm_dir=os.path.abspath(args.bgm_dir) if args.bgm_dir else os.path.join(base_dir, "assets", "bgm"),
        # Whisper & language
        use_dlp_subs=args.use_dlp_subs,
        whisper_model=args.whisper_model,
        whisper_language=args.language,
        caption_script=args.caption_script,
        whisper_device=args.whisper_device,
        whisper_compute_type=args.whisper_compute_type,
        # AI
        ai_provider=args.ai_provider,
        nvidia_model=args.nvidia_model,
        gemini_model=args.gemini_model,
        gemini_fallback_model=args.gemini_fallback_model,
        load_gemini_json=args.load_gemini_json,
        target_accounts_path=(
            os.path.abspath(args.target_accounts) if args.target_accounts else None
        ),
        no_account_routing=args.no_account_routing,
        performance_file=(
            os.path.abspath(args.performance_file)
            if args.performance_file
            else os.path.join(base_outputs, "channel_performance.json")
        ),
        no_channel_learning=args.no_channel_learning,
        # Tracking tuning
        track_step=args.track_step,
        track_deadzone=args.track_deadzone,
        track_smooth=args.track_smooth,
        track_jitter=args.track_jitter,
        track_snap=args.track_snap,
        track_conf=args.track_conf,
        track_smooth_window=args.track_smooth_window,
        scene_cut_threshold=args.scene_cut_threshold,
        track_iou_threshold=args.track_iou_threshold,
        # Video quality
        video_quality_cq=args.video_cq,
        video_quality_crf=args.video_crf,
        video_bitrate=args.video_bitrate,
        video_sharpen=args.video_sharpen,
        video_preset=args.video_preset,
        video_scale_algo=args.video_scale_algo,
        render_fps=None,  # set by the runner from the source video
        # Story Clip Mode
        story_mode=args.story_mode,
        story_recipe_path=os.path.abspath(args.story_recipe) if args.story_recipe else None,
        sources_json_path=os.path.abspath(args.sources_json) if args.sources_json else None,
        story_output_dir=(
            os.path.abspath(args.story_output_dir)
            if args.story_output_dir
            else os.path.join(outputs_dir, "story_clips")
        ),
        skip_download=args.skip_download,
        # Voice-Over Commentary
        voiceover=args.voiceover,
        voiceover_voice=args.voiceover_voice,
        voiceover_lang=args.voiceover_lang,
        voiceover_style=args.voiceover_style,
        voiceover_length=args.voiceover_length,
        voiceover_volume=args.voiceover_volume,
        original_volume=args.original_volume,
        # Watermark
        watermark_enabled=args.watermark,
        watermark_text=args.text,
        watermark_image=args.image,
        watermark_opacity=args.opacity,
        watermark_position=args.position,
        watermark_padding=args.padding,
        watermark_font_size=args.watermark_font_size,
        watermark_scale=args.watermark_scale,
    )


def build_config(argv: list[str] | None = None) -> SimpleNamespace:
    """Parse CLI args, validate them, and build the runtime config."""
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    return config_from_args(args)
