"""
clipping.story.source_manager — Multi-source download & cache manager.

Downloads videos from every supported platform (YouTube, TikTok, Instagram,
Google Drive) and caches them locally for reuse across the Story Clip pipeline.

Engine functions are imported lazily so the heavy dependencies
(faster-whisper, yt-dlp) are not pulled in at module import time.
"""

import json
import os
import shutil


def get_cache_dir(outputs_dir: str) -> str:
    """Return (and create) the story source cache directory."""
    cache_dir = os.path.join(outputs_dir, "story_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _size_mb(path: str) -> float:
    return os.path.getsize(path) / (1024 * 1024)


def _download_single_source(
    source: dict,
    cache_dir: str,
    download_source_height: str | int = "max",
) -> str:
    """
    Download one source video into the cache and return its path.

    Local sources are copied in; already-cached files are reused as-is.

    Raises
    ------
    RuntimeError
        If the download produced no file.
    """
    sid = source["id"]
    platform = source["platform"]
    cached_path = os.path.join(cache_dir, f"{sid}.mp4")

    if os.path.exists(cached_path):
        print(f"   ⏩ '{sid}' is already cached ({_size_mb(cached_path):.1f} MB), skipping download.")
        return cached_path

    if platform == "local":
        local_path = source["local_path"]
        print(f"   📁 [{sid}] Copying local file: {local_path}")
        shutil.copy2(local_path, cached_path)
        print(f"   ✅ '{sid}' copied into the cache.")
        return cached_path

    url = source["url"]
    print(f"   📥 [{sid}] Downloading from {platform}: {url}")

    # Lazy import to keep the heavy deps out of module import.
    from .. import engine

    engine.download_video(
        url=url,
        output_path=cached_path,
        use_dlp_subs=False,  # story sources never need subtitle files
        download_source_height=download_source_height,
        source_platform=platform,
    )

    if not os.path.exists(cached_path):
        raise RuntimeError(
            f"❌ Download failed for source '{sid}' — no file at {cached_path}"
        )

    print(f"   ✅ '{sid}' downloaded ({_size_mb(cached_path):.1f} MB)")
    return cached_path


def download_all_sources(
    source_registry: dict[str, dict],
    cache_dir: str,
    download_source_height: str | int = "max",
) -> dict[str, str]:
    """
    Download every source in the registry.

    Failures are reported and skipped rather than aborting the batch.

    Returns
    -------
    dict[str, str]
        Mapping of source_id -> cached file path, for the sources that succeeded.
    """
    total = len(source_registry)
    print(f"\n📦 Downloading {total} source video(s)...\n")

    paths: dict[str, str] = {}
    failed: list[str] = []

    for idx, (sid, source) in enumerate(source_registry.items(), 1):
        print(f"[{idx}/{total}] Source: {source.get('name', sid)}")
        try:
            paths[sid] = _download_single_source(source, cache_dir, download_source_height)
        except Exception as e:
            print(f"   ⚠️ FAILED to download '{sid}': {e}")
            failed.append(sid)

    print(f"\n{'=' * 50}")
    print(f"📦 Download summary: {len(paths)}/{total} succeeded")
    if failed:
        print(f"   ❌ Failed: {', '.join(failed)}")
    print(f"{'=' * 50}\n")

    return paths


def save_sources_status(
    source_registry: dict[str, dict],
    cached_paths: dict[str, str],
    outputs_dir: str,
) -> str:
    """Write ``sources_status.json`` documenting the download results."""
    status_entries = []
    for sid, src in source_registry.items():
        cached_path = cached_paths.get(sid)
        entry = {
            "id": sid,
            "name": src.get("name", sid),
            "platform": src["platform"],
            "url": src.get("url"),
            "local_path": src.get("local_path"),
            "cached_path": cached_path,
            "status": "ok" if sid in cached_paths else "failed",
        }
        if cached_path and os.path.exists(cached_path):
            entry["size_mb"] = round(_size_mb(cached_path), 2)
        status_entries.append(entry)

    status_path = os.path.join(outputs_dir, "sources_status.json")
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump({"sources": status_entries}, f, indent=2, ensure_ascii=False)

    print(f"💾 Sources status saved to: {status_path}")
    return status_path
