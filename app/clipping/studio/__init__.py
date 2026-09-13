"""
clipping.studio — Video Rendering Engine.

Public surface of the Studio pipeline. The implementation lives in the
sibling modules (renderers, subtitles, typography, transitions, ...).
"""

from .audio_bgm import build_bgm_filter, get_local_bgm_file
from .broll import crop_center_broll, download_pexels_broll
from .core import process_clip
from .edge_glow import generate_edge_glow_video
from .effects import prepare_glitch_video
from .face_detection import estimate_speaker_count_from_video, get_face_detector
from .ffmpeg_utils import (
    build_ffmpeg_progress_cmd,
    detect_video_encoder,
    get_mp4_encode_args,
    get_ts_encode_args,
    open_ffmpeg_video_writer,
    run_ffmpeg_with_progress,
)
from .render_camera_switch import render_camera_switch_video
from .render_hybrid import render_hybrid_video
from .render_split_screen import render_split_screen_video
from .subtitles import build_ass_file
from .thumbnail import build_thumbnail
from .transitions import (
    TMP_TRANSITION_POOL,
    create_glitch_transition,
    create_white_flash_transition,
    download_all_transitions,
    download_transition_raw,
    get_random_transition,
    prepare_transition_clip,
)
from .typography import (
    download_google_font,
    register_fonts_for_libass,
    prepare_typography_fonts,
)
from .utils import (
    FIREFOX_UA,
    RATIO_MAP,
    VERTICAL_RATIOS,
    _get_render_dims,
    _is_vertical_ratio,
    escape_ffmpeg_filter_value,
    format_seconds,
)
from .watermark import apply_watermark

__all__ = [
    "FIREFOX_UA",
    "RATIO_MAP",
    "TMP_TRANSITION_POOL",
    "VERTICAL_RATIOS",
    "_get_render_dims",
    "_is_vertical_ratio",
    "apply_watermark",
    "build_ass_file",
    "build_bgm_filter",
    "build_ffmpeg_progress_cmd",
    "build_thumbnail",
    "create_glitch_transition",
    "create_white_flash_transition",
    "crop_center_broll",
    "detect_video_encoder",
    "download_all_transitions",
    "download_google_font",
    "download_pexels_broll",
    "download_transition_raw",
    "escape_ffmpeg_filter_value",
    "estimate_speaker_count_from_video",
    "format_seconds",
    "generate_edge_glow_video",
    "get_face_detector",
    "get_local_bgm_file",
    "get_mp4_encode_args",
    "get_random_transition",
    "get_ts_encode_args",
    "open_ffmpeg_video_writer",
    "prepare_glitch_video",
    "prepare_transition_clip",
    "prepare_typography_fonts",
    "process_clip",
    "register_fonts_for_libass",
    "render_camera_switch_video",
    "render_hybrid_video",
    "render_split_screen_video",
    "run_ffmpeg_with_progress",
]
