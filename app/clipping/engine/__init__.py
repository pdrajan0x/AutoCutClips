"""
clipping.engine — Source download, transcription and AI clip analysis.

Submodules are imported lazily through these re-exports so that importing
``engine`` does not pull in the heavy ML/network dependencies until the
corresponding step actually runs.
"""

from .analysis import analyze_with_ai, analyze_with_gemini, analyze_with_nvidia
from .download import download_video
from .transcribe import parse_youtube_json3_subs, transcribe_video

__all__ = [
    "analyze_with_ai",
    "analyze_with_gemini",
    "analyze_with_nvidia",
    "download_video",
    "parse_youtube_json3_subs",
    "transcribe_video",
]
