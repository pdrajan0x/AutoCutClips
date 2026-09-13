"""
clipping.engine.download — Source video download (yt-dlp / gdown).
"""

import os
import re

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
        filled = int(20 * downloaded / total)
        bar = "█" * filled + " " * (20 - filled)
        print(
            f"\r      Download: {pct:3.0f}%|{bar}| "
            f"{downloaded / 1048576:.0f}/{total / 1048576:.0f}MB {spd} ETA {eta_s}   ",
            end="", flush=True,
        )
    else:
        # Unknown size (live/streamed manifest) — show bytes and speed only.
        print(f"\r      Download: {downloaded / 1048576:.0f}MB {spd}   ", end="", flush=True)


def _download_subtitles(ydl_opts: dict, url: str, output_path: str) -> None:
    """Try to fetch YouTube auto/manual subtitles as JSON3 (English, then Indonesian)."""
    import glob

    from yt_dlp import YoutubeDL

    print("      Looking for automatic subtitles (en / id)...")
    for lang in ("en", "id"):
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
) -> None:
    """
    Download a video to *output_path* at the requested source height.

    Parameters
    ----------
    source_platform : str
        One of ``"youtube"`` (default), ``"tiktok"``, ``"instagram"`` or ``"gdrive"``.
    """
    from yt_dlp import YoutubeDL

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
        ydl_opts = {
            "format": _build_ydl_format_selector(download_source_height),
            "outtmpl": output_path,
            "quiet": True,
            "merge_output_format": "mp4",
            "remote_components": ["ejs:github"],
            "progress_hooks": [_ydl_progress_hook],
            "extractor_args": {"youtube": ["player_client=android,web"]},
        }
    else:
        # TikTok / Instagram: make sure video and audio end up merged. Prefer
        # H.264 over H.265 (TikTok's bytevc1), which crashes PyAV/faster-whisper
        # with an IndexError on Kaggle/Colab.
        ydl_opts = {
            "format": "bestvideo[vcodec^=h264]+bestaudio/best[vcodec^=h264]/best",
            "outtmpl": output_path,
            "quiet": True,
            "merge_output_format": "mp4",
            "progress_hooks": [_ydl_progress_hook],
        }

    if use_dlp_subs:
        if is_youtube:
            _download_subtitles(ydl_opts, url, output_path)
        else:
            print(
                f"      ℹ️ {platform_label} provides no automatic subtitles. "
                "Whisper will be used instead."
            )

    with YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            print(
                f"      ✅ Downloading: {info.get('height', 'unknown')}p "
                f"(codec: {info.get('vcodec', 'unknown')})",
                flush=True,
            )
        except Exception as e:
            print(f"      ⚠️ Could not read detailed info: {e}", flush=True)

        ydl.download([url])

    if not os.path.exists(output_path):
        raise RuntimeError(
            f"❌ Download from {platform_label} failed — no video file at {output_path}.\n"
            "      Make sure the URL is valid and publicly accessible."
        )
