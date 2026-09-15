"""
app.web.api.config_adapter — Bridge between the API JSON payload and the CLI config.

The web job starts from the CLI's own defaults (``build_parser`` with no
arguments), applies the fields the request actually set, and builds the config
through the same ``config_from_args`` as the command line. Nothing is
duplicated here, so a new CLI option is available to the web API automatically.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

from ...clipping.config import build_parser, config_from_args, validate_clip_durations


def _negate(value):
    return not bool(value)


def _source_height(value):
    if str(value).lower() == "max":
        return "max"
    try:
        return int(value)
    except (TypeError, ValueError):
        return "max"


# JobCreateRequest field -> (argparse destination, transform)
PAYLOAD_TO_ARGS = {
    "url": ("url", None),
    "source": ("source", None),
    "clips": ("clips", int),
    "ratio": ("ratio", None),
    "min_duration": ("min_duration", float),
    "max_duration": ("max_duration", float),
    "source_height": ("source_height", _source_height),
    "render_height": ("render_height", str),
    "words_per_sub": ("words_per_sub", int),
    "hook_duration": ("hook_duration", int),
    "use_hook_glitch": ("hook_teaser", bool),  # pre-1.15 name
    "hook_teaser": ("hook_teaser", bool),
    "use_broll": ("no_broll", _negate),
    "use_auto_bgm": ("no_bgm", _negate),
    "use_karaoke_effect": ("no_karaoke", _negate),
    "use_split_screen": ("split_screen", bool),
    "use_camera_switch": ("camera_switch", bool),
    "no_subs": ("no_subs", bool),
    "no_segment_trim": ("no_segment_trim", bool),
    "silence_trim": ("silence_trim", bool),
    "font_style": ("font_style", None),
    "caption_case": ("caption_case", None),
    "title_overlay": ("no_title_overlay", _negate),
    "layout": ("layout", None),
    "speaker_tracking": ("no_speaker_tracking", _negate),
    "language": ("language", None),
    "caption_script": ("caption_script", None),
    "whisper_model": ("whisper_model", None),
    "whisper_device": ("whisper_device", None),
    "whisper_compute_type": ("whisper_compute_type", None),
    "use_dlp_subs": ("use_dlp_subs", bool),
    "ai_provider": ("ai_provider", None),
    "gemini_model": ("gemini_model", None),
    "face_detector": ("face_detector", None),
    "load_gemini_json": ("load_gemini_json", bool),
}


def build_config_from_payload(
    payload: dict,
    job_id: str,
    *,
    env_overrides: dict | None = None,
) -> SimpleNamespace:
    """
    Convert an API request payload into the pipeline config.

    Parameters
    ----------
    payload : dict
        The job creation payload (from ``JobCreateRequest.model_dump()``);
        ``None`` values mean "use the CLI default".
    job_id : str
        Unique job identifier — used for the per-job output directory.
    env_overrides : dict, optional
        Runtime overrides for API keys (e.g. from stored settings).

    Raises
    ------
    ValueError
        When the requested clip length bounds are unusable.
    """
    # Resolve the repository root (3 levels up from app/web/api).
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    outputs_dir = os.path.join(base_dir, "outputs", job_id)

    args = build_parser().parse_args([])
    for key, (dest, transform) in PAYLOAD_TO_ARGS.items():
        value = payload.get(key)
        if value is None:
            continue
        if hasattr(value, "value"):
            value = value.value
        setattr(args, dest, transform(value) if transform else value)

    error = validate_clip_durations(args.min_duration, args.max_duration)
    if error:
        raise ValueError(error)

    env = {**os.environ, **(env_overrides or {})}
    cfg = config_from_args(args, base_dir=base_dir, outputs_dir=outputs_dir, env=env)

    upload_filename = payload.get("upload_filename")
    if upload_filename:
        cfg.source_video_path = os.path.join(base_dir, "uploads", upload_filename)
    else:
        cfg.source_video_path = os.path.join(outputs_dir, "source_video.mp4")

    return cfg
