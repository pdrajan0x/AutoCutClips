"""
clipping.engine — Source download, transcription and AI clip analysis.

Submodules are imported lazily through these re-exports so that importing
``engine`` does not pull in the heavy ML/network dependencies until the
corresponding step actually runs.
"""

from .analysis import (
    analyze_with_ai,
    analyze_with_gemini,
    analyze_with_nvidia,
    merge_transcripts_with_ai,
)
from .download import download_video, source_info_path
from .romanize import romanize_clip_captions
from .transcribe import parse_youtube_json3_subs, transcribe_video

__all__ = [
    "analyze_with_ai",
    "analyze_with_gemini",
    "analyze_with_nvidia",
    "download_video",
    "merge_transcripts_with_ai",
    "romanize_clip_captions",
    "source_info_path",
    "parse_youtube_json3_subs",
    "transcribe_video",
]
