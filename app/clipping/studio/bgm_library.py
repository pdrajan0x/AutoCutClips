"""
bgm_library.py — Download the curated background-music library.

``assets/bgm/library.json`` lists instrumental tracks from Mixkit, grouped by
mood. Mixkit's free license allows use in YouTube videos (monetized included)
with no attribution, and the list holds background tunes rather than songs.
The MP3s (~600 MB) are not kept in git; they are fetched into
``assets/bgm/<mood>/`` on first use, and files already present are skipped.

Run ``python -m app.clipping.studio.bgm_library`` to fetch everything up front.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor

LIBRARY_FILE = "library.json"
_UA = {"User-Agent": "Mozilla/5.0 (AutoCutClips BGM library)"}
_MIN_VALID_BYTES = 50_000
_lock = threading.Lock()


def load_library(bgm_dir: str) -> dict[str, list[dict]]:
    path = os.path.join(bgm_dir, LIBRARY_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def library_moods(bgm_dir: str) -> list[str]:
    return list(load_library(bgm_dir))


def _track_path(bgm_dir: str, mood: str, track: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(track.get("title", "")).lower()).strip("-") or "track"
    return os.path.join(bgm_dir, mood, f"mixkit-{track['id']}-{slug}.mp3")


def _download(url: str, dest: str) -> bool:
    tmp = dest + ".part"
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as f:
            while chunk := resp.read(1 << 16):
                f.write(chunk)
        if os.path.getsize(tmp) < _MIN_VALID_BYTES:
            raise ValueError("file too small to be a music track")
        os.replace(tmp, dest)
        return True
    except Exception as e:
        print(f"   ⚠️ BGM download failed ({os.path.basename(dest)}): {e}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


def ensure_bgm_library(bgm_dir: str, moods: list[str] | None = None, workers: int = 6) -> int:
    """
    Download any missing tracks for *moods* (all when None); returns how many were fetched.

    Safe to call from several jobs at once: the lock makes later callers wait
    for the first download instead of fetching the same files twice.
    """
    library = load_library(bgm_dir)
    wanted = [m for m in (moods or library) if m in library]

    with _lock:
        todo = []
        for mood in wanted:
            os.makedirs(os.path.join(bgm_dir, mood), exist_ok=True)
            for track in library[mood]:
                if not track.get("url") or "id" not in track:
                    continue
                dest = _track_path(bgm_dir, mood, track)
                if not os.path.exists(dest):
                    todo.append((track["url"], dest))
        if not todo:
            return 0

        print(f"   🎵 Downloading {len(todo)} background-music track(s)...")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fetched = sum(pool.map(lambda job: _download(*job), todo))
        print(f"   ✅ Background music ready ({fetched}/{len(todo)} downloaded).")
        return fetched


def main() -> None:
    bgm_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "bgm")
    )
    ensure_bgm_library(bgm_dir)


if __name__ == "__main__":
    main()
