"""
clipping.studio.transitions — Transition Asset Downloader & Manager

Downloads and caches transition overlay videos (film burn, light leak,
film grain, film leader) from YouTube sources (Think Make Push channel).

These assets have a ~5 second branding intro that must be skipped.
The usable transition content starts at the configured skip offset.
"""

import os
import random
import subprocess

from yt_dlp import YoutubeDL

from .utils import RATIO_MAP, _is_vertical_ratio, _get_render_dims
from .ffmpeg_utils import get_ts_encode_args


# ═══════════════════════════════════════════════════════════════════════
# TRANSITION POOL  (source: Think Make Push — YouTube)
#
# Each entry:
#   url         : YouTube watch URL
#   skip        : seconds to skip (branding/ad intro)
#   duration    : usable duration to extract (seconds, None = rest of video)
#   type        : category tag for future filtering
#   orientation : "landscape" or "vertical"
#   label       : human-readable label for logging
# ═══════════════════════════════════════════════════════════════════════

TMP_TRANSITION_POOL = [
    {
        "url": "https://www.youtube.com/watch?v=yfKv03nLaBE",
        "skip": 5,
        "duration": None,
        "type": "film_burn",
        "orientation": "landscape",
        "label": "GRUNGY Film Burn Transitions",
    },
    {
        "url": "https://www.youtube.com/watch?v=uYBcUpLxtEM",
        "skip": 5,
        "duration": None,
        "type": "film_burn",
        "orientation": "landscape",
        "label": "GRUNGE Film Overlay with Sound",
    },
    {
        "url": "https://www.youtube.com/watch?v=YFzGx0JuUUQ",
        "skip": 5,
        "duration": None,
        "type": "film_overlay",
        "orientation": "landscape",
        "label": "35mm Film Overlay",
    },
    {
        "url": "https://www.youtube.com/watch?v=iGvnBXS3pyM",
        "skip": 5,
        "duration": None,
        "type": "film_leader",
        "orientation": "landscape",
        "label": "Dirty Grainy Film Leader (Burns & Leaks)",
    },
    {
        "url": "https://www.youtube.com/watch?v=BsKj9iiimTE",
        "skip": 5,
        "duration": None,
        "type": "film_leader",
        "orientation": "landscape",
        "label": "Classic Film Leader Overlays",
    },
    {
        "url": "https://www.youtube.com/watch?v=OaK3jjBfOi0",
        "skip": 5,
        "duration": None,
        "type": "film_grain",
        "orientation": "landscape",
        "label": "Film Grain Overlay with Sound Effect",
    },
    # ── Vertical Variants ──
    {
        "url": "https://www.youtube.com/watch?v=k0BvSreLx5E",
        "skip": 5,
        "duration": None,
        "type": "film_burn",
        "orientation": "vertical",
        "label": "Vertical Vibrant Film Burn Overlay",
    },
    {
        "url": "https://www.youtube.com/watch?v=eiditSLUA3I",
        "skip": 5,
        "duration": None,
        "type": "film_burn",
        "orientation": "vertical",
        "label": "Vertical Rich and Vibrant Colors",
    },
]


def _get_cache_dir(cfg) -> str:
    """
    Return (and create) the directory where downloaded transition raw
    files are stored.  Located inside the project base directory under
    ``transitions_cache/``.
    """
    cache_dir = os.path.abspath(
        os.path.join(getattr(cfg, "base_dir", os.getcwd()), "transitions_cache")
    )
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _raw_filename(entry: dict) -> str:
    """Derive a deterministic raw filename from a pool entry's URL."""
    video_id = entry["url"].split("v=")[-1].split("&")[0]
    return f"tmp_raw_{video_id}.mp4"


def download_transition_raw(entry: dict, cfg) -> str | None:
    """
    Download a single transition video from YouTube if not already cached.

    Args:
        entry: A dict from ``TMP_TRANSITION_POOL``.
        cfg:   Runtime config (used for ``base_dir``).

    Returns:
        Absolute path to the downloaded raw MP4, or None on failure.
    """
    cache_dir = _get_cache_dir(cfg)
    raw_path = os.path.join(cache_dir, _raw_filename(entry))

    if os.path.exists(raw_path) and os.path.getsize(raw_path) > 10_000:
        return raw_path

    print(f"   📥 [Transition] Downloading: {entry['label']}...")

    try:
        YoutubeDL(
            {
                "format": "best[ext=mp4]",
                "outtmpl": raw_path,
                "quiet": True,
                "no_warnings": True,
                "extractor_args": {"youtube": ["player_client=android,web"]},
            }
        ).download([entry["url"]])
    except Exception as e:
        print(f"   ⚠️ [Transition] Download failed ({entry['label']}): {e}")
        return None

    if os.path.exists(raw_path) and os.path.getsize(raw_path) > 10_000:
        print(f"   ✅ [Transition] Saved: {raw_path}")
        return raw_path

    print(f"   ⚠️ [Transition] File too small / download failed: {raw_path}")
    return None


def download_all_transitions(cfg, types: list[str] | None = None) -> list[dict]:
    """
    Download all (or filtered) transition assets from the pool.

    Args:
        cfg:   Runtime config.
        types: Optional list of type tags to filter (e.g. ``["film_burn"]``).
               If None, downloads everything.

    Returns:
        List of dicts — each original pool entry augmented with
        ``"raw_path"`` pointing to the local file.  Entries that failed
        to download are excluded.
    """
    pool = TMP_TRANSITION_POOL
    if types:
        pool = [e for e in pool if e["type"] in types]

    results = []
    for entry in pool:
        path = download_transition_raw(entry, cfg)
        if path:
            enriched = dict(entry)
            enriched["raw_path"] = path
            results.append(enriched)

    print(
        f"   📦 [Transition] {len(results)}/{len(pool)} asset(s) downloaded."
    )
    return results


def get_random_transition(
    cfg,
    transition_type: str | None = None,
    orientation: str | None = None,
) -> dict | None:
    """
    Pick a random transition from the pool, downloading if necessary.

    Args:
        cfg:              Runtime config.
        transition_type:  Filter by type (``film_burn``, ``film_leader``,
                          ``film_grain``, ``film_overlay``).  None = any.
        orientation:      ``"landscape"`` or ``"vertical"``.  None = any.

    Returns:
        A pool entry dict with ``"raw_path"`` set, or None if nothing
        is available.
    """
    candidates = list(TMP_TRANSITION_POOL)

    if transition_type:
        candidates = [c for c in candidates if c["type"] == transition_type]
    if orientation:
        candidates = [c for c in candidates if c["orientation"] == orientation]

    if not candidates:
        return None

    random.shuffle(candidates)

    for entry in candidates:
        path = download_transition_raw(entry, cfg)
        if path:
            result = dict(entry)
            result["raw_path"] = path
            return result

    return None


def prepare_transition_clip(
    entry: dict,
    ratio: str,
    cfg,
    video_encoder: dict,
    source_h: int = 1080,
    clip_duration: float | None = None,
    custom_dims: tuple | None = None,
) -> str | None:
    """
    Extract the usable portion of a downloaded transition asset,
    crop/scale it to match the target output dimensions, and encode
    it as a ``.ts`` segment ready for concatenation or overlay.

    This skips the branding intro (``entry["skip"]`` seconds) and
    extracts ``clip_duration`` seconds of usable content.

    Args:
        entry:          Pool entry dict (must have ``"raw_path"``).
        ratio:          Target aspect ratio string.
        cfg:            Runtime config.
        video_encoder:  Encoder descriptor dict.
        source_h:       Source video height for dimension calculation.
        clip_duration:  How many seconds to extract.  None means the
                        entry's own ``duration`` field (or 3s fallback).
        custom_dims:    Optional ``(w, h)`` to override calculated dims.

    Returns:
        Path to the prepared ``.ts`` file, or None on failure.
    """
    raw_path = entry.get("raw_path")
    if not raw_path or not os.path.exists(raw_path):
        return None

    if custom_dims:
        out_w, out_h = custom_dims
    else:
        out_w, out_h = _get_render_dims(cfg, ratio, source_h=source_h)

    skip = entry.get("skip", 5)
    dur = clip_duration or entry.get("duration") or 3.0

    video_id = entry["url"].split("v=")[-1].split("&")[0]
    ts_path = f"transition_{video_id}_{out_w}x{out_h}.ts"

    if os.path.exists(ts_path):
        return ts_path

    algo = getattr(cfg, "video_scale_algo", "lanczos")

    if custom_dims:
        vf = f"scale={out_w}:{out_h}:flags={algo},setsar=1"
    elif _is_vertical_ratio(ratio):
        w_part, h_part = RATIO_MAP.get(ratio, (9, 16))
        vf = (
            f"crop=ih*{w_part}/{h_part}:ih:(iw-ih*{w_part}/{h_part})/2:0,"
            f"scale={out_w}:{out_h}:flags={algo},setsar=1"
        )
    else:
        vf = f"scale={out_w}:{out_h}:flags={algo},setsar=1"

    cmd = (
        [
            "ffmpeg",
            "-y",
            "-ss", str(skip),
            "-t", str(dur),
            "-i", raw_path,
            "-vf", vf,
            "-an",
        ]
        + get_ts_encode_args(video_encoder, fps=30)
        + [ts_path]
    )

    try:
        subprocess.run(
            cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return ts_path
    except subprocess.CalledProcessError as e:
        print(f"   ⚠️ [Transition] FFmpeg failed for {entry['label']}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════
# HOOK V2 SYNTHETIC TRANSITIONS
# Short (0.1-0.3s) clips generated with FFmpeg lavfi — no download needed —
# concatenated between micro-hook clips in the Hook V2 multi-intro pipeline.
# ═══════════════════════════════════════════════════════════════════════

def _render_lavfi_transition(output_path, color, duration, fps, width, height, vf=None):
    """Render a short lavfi-generated transition clip with silent stereo audio."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}:d={duration}:r={fps}",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", str(duration),
    ]
    if vf:
        cmd += ["-vf", vf]
    cmd += [
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path


def create_white_flash_transition(
    output_path: str,
    duration: float = 0.12,
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
) -> str:
    """Generate a solid white flash clip."""
    return _render_lavfi_transition(output_path, "white", duration, fps, width, height)


def create_glitch_transition(
    output_path: str,
    duration: float = 0.12,
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
) -> str:
    """Generate an RGB-shift glitch noise clip."""
    return _render_lavfi_transition(
        output_path, "black", duration, fps, width, height,
        vf="noise=alls=100:allf=t+u,rgbashift=rh=20:bv=20",
    )


# ═══════════════════════════════════════════════════════════════════════
# HOOK V2 SYNTHETIC TRANSITIONS (generated with FFmpeg lavfi, no download)
# Short 0.1-0.3s clips concatenated between micro-hook clips.
# ═══════════════════════════════════════════════════════════════════════

def create_white_flash_transition(
    output_path: str,
    duration: float = 0.12,
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
) -> str:
    """Generate a solid white flash clip."""
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c=white:s={width}x{height}:d={duration}:r={fps}",
        "-f", "lavfi",
        "-i", f"anullsrc=r=48000:cl=stereo",
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
    subprocess.run(
        cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return output_path


def create_glitch_transition(
    output_path: str,
    duration: float = 0.12,
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
) -> str:
    """Generate an RGB-shift glitch noise clip."""
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c=black:s={width}x{height}:d={duration}:r={fps}",
        "-f", "lavfi",
        "-i", f"anullsrc=r=48000:cl=stereo",
        "-t", str(duration),
        "-vf", "noise=alls=100:allf=t+u,rgbashift=rh=20:bv=20",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
    subprocess.run(
        cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return output_path
