"""
clipping.engine.download — Source video download (yt-dlp / gdown).
"""

import glob
import os
import re
import sys

from .. import ytdl
from ..progress import render_bar

_BOT_CHECK_HINT = (
    "YouTube is asking this machine to sign in (common on Colab/Kaggle IPs).\n"
    "      Export cookies.txt from a browser logged in to YouTube and pass it with\n"
    "      --cookies /path/to/cookies.txt (or set YTDLP_COOKIES_FILE)."
)

_FORBIDDEN_HINT = (
    "YouTube returned 403 Forbidden — the cached video/signature URL likely expired\n"
    "      or the cookies session went stale between downloads (common when a queue\n"
    "      leaves several minutes between videos). Try:\n"
    "      1) Re-export a fresh cookies.txt and pass it with --cookies/--YTDLP_COOKIES_FILE\n"
    "      2) Update yt-dlp: pip install -U yt-dlp\n"
    "      3) Re-run the queue with --retry-failed — this video is skipped, not fatal."
)

PLATFORM_LABELS = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "gdrive": "Google Drive",
}


def _build_ydl_format_selector(download_source_height: str | int) -> str:
    """
    Build a yt-dlp format selector for the requested source quality.

    AV1 is excluded because it lacks hardware acceleration on many platforms
    (e.g. Colab T4) and makes the OpenCV/FFmpeg software fallbacks fail.
    """
    codec_filter = "[vcodec!*=av01]"

    if download_source_height == "max":
        return f"bestvideo{codec_filter}+bestaudio/best{codec_filter}"

    try:
        h_val = int(download_source_height)
    except (ValueError, TypeError):
        h_val = 0

    if 0 < h_val <= 1080:
        # At standard resolutions, strictly prefer native MP4 (H.264/AAC).
        return (
            f"bestvideo[height<=?{h_val}][ext=mp4]{codec_filter}+bestaudio[ext=m4a]/"
            f"bestvideo[height<=?{h_val}]{codec_filter}+bestaudio/"
            f"best[height<=?{h_val}][ext=mp4]{codec_filter}/"
            f"best[height<=?{h_val}]{codec_filter}"
        )

    return (
        f"bestvideo[height<=?{download_source_height}]{codec_filter}+bestaudio/"
        f"best[height<=?{download_source_height}]{codec_filter}"
    )


def source_info_path(video_path: str) -> str:
    """Where the trimmed source metadata for *video_path* is stored."""
    return os.path.splitext(video_path)[0] + ".info.json"


def _save_source_info(info: dict, video_path: str) -> None:
    """
    Keep the fields that tell the AI where a clip comes from (show, channel,
    guests in the title/description) — the transcript alone rarely names them.
    """
    import json

    trimmed = {
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "uploader": info.get("uploader"),
        "upload_date": info.get("upload_date"),
        "language": info.get("language"),
        "webpage_url": info.get("webpage_url"),
        "categories": info.get("categories") or [],
        "tags": (info.get("tags") or [])[:25],
        "description": (info.get("description") or "")[:1500],
        "chapters": [c.get("title") for c in (info.get("chapters") or []) if c.get("title")][:30],
    }
    try:
        with open(source_info_path(video_path), "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"      ⚠️ Could not save the source metadata: {e}", flush=True)


def _extract_gdrive_file_id(url: str) -> str | None:
    """Extract the Google Drive file ID from the supported URL formats."""
    for pattern in (r"/d/([a-zA-Z0-9_-]+)", r"[?&]id=([a-zA-Z0-9_-]+)"):
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _download_gdrive(url: str, output_path: str) -> None:
    """Download a video from Google Drive with gdown (more reliable than yt-dlp)."""
    import gdown

    file_id = _extract_gdrive_file_id(url)
    if not file_id:
        raise RuntimeError(
            f"Could not extract a file ID from the Google Drive URL: {url}\n"
            "      Supported formats:\n"
            "        - https://drive.google.com/file/d/FILE_ID/view\n"
            "        - https://drive.google.com/open?id=FILE_ID"
        )

    print(f"      📥 File ID: {file_id}")
    gdown.download(f"https://drive.google.com/uc?id={file_id}", output_path, quiet=False)


def _ydl_progress_hook(d: dict) -> None:
    """
    Render a one-line download progress bar from a yt-dlp hook payload.

    yt-dlp downloads the video and audio streams separately, so this hook
    fires for each; the newline on "finished" keeps every bar on its own line.
    """
    status = d.get("status")
    if status == "finished":
        print(flush=True)
        return
    if status != "downloading":
        return

    total = d.get("total_bytes") or d.get("total_bytes_estimate")
    downloaded = d.get("downloaded_bytes", 0)
    speed = d.get("speed")
    eta = d.get("eta")
    spd = f"{speed / 1024 / 1024:4.1f}MB/s" if speed else "  --MB/s"
    eta_s = f"{eta:>3}s" if eta is not None else " --s"

    if total:
        pct = downloaded / total * 100
        bar = render_bar(downloaded / total, 20, sys.stdout)
        print(
            f"\r      Download: {pct:3.0f}%|{bar}| "
            f"{downloaded / 1048576:.0f}/{total / 1048576:.0f}MB {spd} ETA {eta_s}   ",
            end="", flush=True,
        )
    else:
        # Unknown size (live/streamed manifest) — show bytes and speed only.
        print(f"\r      Download: {downloaded / 1048576:.0f}MB {spd}   ", end="", flush=True)


def _subtitle_languages(info: dict | None) -> list[str]:
    """
    Subtitle tracks in the language actually spoken, best first.

    Asking for "en" on a Hindi video returns YouTube's machine-*translated*
    English track, which is wrong for captions. Prefer uploaded subtitles in the
    video's language, then the original-language auto captions ("<lang>-orig").
    """
    if not info:
        return []

    base = str(info.get("language") or "").split("-")[0].lower()
    manual = list(info.get("subtitles") or {})
    auto = list(info.get("automatic_captions") or {})

    langs = []
    if base:
        langs += [k for k in manual if k.split("-")[0].lower() == base]
    langs += [k for k in auto if k.endswith("-orig")]
    if base:
        langs += [k for k in auto if k.lower() == base]
    return list(dict.fromkeys(langs))


def _download_subtitles(ydl_opts: dict, url: str, output_path: str, langs: list[str]) -> None:
    """Try to fetch YouTube subtitles as JSON3 in the spoken language."""
    from yt_dlp import YoutubeDL

    if not langs:
        print("      ℹ️ No original-language subtitles found. Whisper will transcribe instead.")
        return

    print(f"      Looking for subtitles in the spoken language ({' / '.join(langs)})...")
    for lang in langs:
        opts = dict(ydl_opts)
        opts.update({
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [lang],
            "subtitlesformat": "json3",
            "skip_download": True,
        })
        try:
            with YoutubeDL(opts) as ydl:
                ydl.download([url])
            if glob.glob(output_path.replace(".mp4", ".*.json3")):
                print(f"      ✅ Subtitle '{lang}' found. Continuing with the video...")
                return
        except Exception as e:
            print(f"      ⚠️ Could not fetch subtitle '{lang}' ({e}). Trying the next option...")


def download_video(
    url: str,
    output_path: str,
    use_dlp_subs: bool = False,
    download_source_height: str | int = "max",
    source_platform: str = "youtube",
    cfg=None,
) -> None:
    """
    Download a video to *output_path* at the requested source height.

    Parameters
    ----------
    source_platform : str
        One of ``"youtube"`` (default), ``"tiktok"``, ``"instagram"`` or ``"gdrive"``.
    cfg : SimpleNamespace, optional
        Runtime config; supplies the yt-dlp cookies file.
    """
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    platform_label = PLATFORM_LABELS.get(source_platform, source_platform)
    is_youtube = source_platform == "youtube"

    print(f"[1/3] Downloading video from {platform_label}...")
    if download_source_height == "max":
        print("      🎯 Source quality: highest available", flush=True)
    else:
        print(f"      🎯 Source quality: up to {download_source_height}p", flush=True)

    if source_platform == "gdrive":
        _download_gdrive(url, output_path)
        if not os.path.exists(output_path):
            raise RuntimeError(
                f"❌ Google Drive download failed — no file at {output_path}"
            )
        print("      ✅ Video downloaded from Google Drive.", flush=True)
        return

    if is_youtube:
        # No forced player_client: the old extractor_args value was a list, which
        # yt-dlp silently ignores, and forcing the android client would drop the
        # cookies (that client does not support them).
        ydl_opts = ytdl.base_opts(
            cfg,
            format=_build_ydl_format_selector(download_source_height),
            outtmpl=output_path,
            merge_output_format="mp4",
            remote_components=["ejs:github"],
            progress_hooks=[_ydl_progress_hook],
        )
    else:
        # TikTok / Instagram: make sure video and audio end up merged. Prefer
        # H.264 over H.265 (TikTok's bytevc1), which crashes PyAV/faster-whisper
        # with an IndexError on Kaggle/Colab.
        ydl_opts = ytdl.base_opts(
            cfg,
            format="bestvideo[vcodec^=h264]+bestaudio/best[vcodec^=h264]/best",
            outtmpl=output_path,
            merge_output_format="mp4",
            progress_hooks=[_ydl_progress_hook],
        )

    if is_youtube and "cookiefile" in ydl_opts:
        print(f"      🍪 Using cookies from {ydl_opts['cookiefile']}", flush=True)

    info = None
    with YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            print(
                f"      ✅ Downloading: {info.get('height', 'unknown')}p "
                f"(codec: {info.get('vcodec', 'unknown')}, language: {info.get('language') or 'unknown'})",
                flush=True,
            )
            _save_source_info(info, output_path)
        except Exception as e:
            print(f"      ⚠️ Could not read detailed info: {e}", flush=True)

    if use_dlp_subs:
        if is_youtube:
            _download_subtitles(ydl_opts, url, output_path, _subtitle_languages(info))
        else:
            print(
                f"      ℹ️ {platform_label} provides no automatic subtitles. "
                "Whisper will be used instead."
            )

    import time

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        with YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.download([url])
                break
            except DownloadError as e:
                msg = str(e)
                if "not a bot" in msg or "Sign in to confirm" in msg:
                    raise RuntimeError(f"{e}\n      {_BOT_CHECK_HINT}") from e
                is_forbidden = "403" in msg or "Forbidden" in msg
                if is_forbidden and attempt < max_attempts:
                    wait_s = 10 * attempt
                    print(
                        f"      ⚠️ 403 Forbidden (attempt {attempt}/{max_attempts}) — this is "
                        f"usually a stale cache/signature URL or brief rate-limiting. "
                        f"Retrying in {wait_s}s...",
                        flush=True,
                    )
                    time.sleep(wait_s)
                    continue
                if is_forbidden:
                    raise RuntimeError(f"{e}\n      {_FORBIDDEN_HINT}") from e
                raise

    if not os.path.exists(output_path):
        raise RuntimeError(
            f"❌ Download from {platform_label} failed — no video file at {output_path}.\n"
            "      Make sure the URL is valid and publicly accessible."
        )
