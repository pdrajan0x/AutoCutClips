"""
Shared helpers for the Studio rendering pipeline: duration formatting,
FFmpeg value escaping, OpenCV scaling and aspect-ratio maths.
"""

import os

import cv2

FIREFOX_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0"
)

# Maps a ratio string to (width_part, height_part).
RATIO_MAP = {
    "9:16": (9, 16),
    "16:9": (16, 9),
    "1:1": (1, 1),
    "3:4": (3, 4),
    "4:5": (4, 5),
}

# Ratios that require a face-tracking crop (narrower than the source).
VERTICAL_RATIOS = {"9:16", "1:1", "3:4", "4:5"}


def format_seconds(seconds):
    """Format a duration in seconds as ``HH:MM:SS`` (clamped to non-negative)."""
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def escape_ffmpeg_filter_value(value: str) -> str:
    """Escape a value so it is safe inside an FFmpeg filter expression."""
    return str(value).replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")


def _get_cv2_interpolation(cfg=None):
    """Resolve the OpenCV interpolation mode from the runtime config."""
    algo = str(
        getattr(cfg, "video_scale_algo", os.environ.get("OSC_VIDEO_SCALE_ALGO", "lanczos"))
    ).lower()
    return {
        "lanczos": cv2.INTER_LANCZOS4,
        "bicubic": cv2.INTER_CUBIC,
        "bilinear": cv2.INTER_LINEAR,
        "area": cv2.INTER_AREA,
    }.get(algo, cv2.INTER_LANCZOS4)


def _resize_frame(frame, size, cfg=None):
    """Resize a frame to ``size`` using the configured interpolation algorithm."""
    return cv2.resize(frame, size, interpolation=_get_cv2_interpolation(cfg))


def _is_vertical_ratio(ratio: str) -> bool:
    """Return True when the ratio needs a face-tracked crop from the source."""
    return ratio in VERTICAL_RATIOS


def _get_render_dims(cfg, ratio, source_h=1080):
    """
    Calculate the target output resolution for a ratio.

    ``cfg.render_output_height`` may be ``"source"`` (use *source_h*) or a
    pixel height. For vertical ratios the value is treated as the short side.
    Dimensions are rounded up to even numbers for codec compatibility.
    """
    mode = str(getattr(cfg, "render_output_height", "1080")).lower()
    if mode == "source":
        target_h_base = source_h
    else:
        try:
            target_h_base = int(mode)
        except (ValueError, TypeError):
            target_h_base = 1080

    w_part, h_part = RATIO_MAP.get(ratio, (16, 9))

    if _is_vertical_ratio(ratio):
        out_w = target_h_base
        out_h = int(target_h_base * h_part / w_part)
    else:
        out_h = target_h_base
        out_w = int(target_h_base * w_part / h_part)

    if out_w % 2:
        out_w += 1
    if out_h % 2:
        out_h += 1

    return out_w, out_h
