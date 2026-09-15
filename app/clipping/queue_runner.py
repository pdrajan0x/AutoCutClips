"""
clipping.queue_runner — Process a list of video URLs one after another.

Each video gets its own folder under ``outputs/queue/<video-id>/`` so clips,
manifests and cached AI responses never overwrite each other. Progress is kept
in ``queue_state.json``: re-running the same links file (e.g. after a Colab
disconnect) skips every video that already finished.

All finished clips are also collected into ``queue_manifest.json``, sorted best
first, so a single ``upload-youtube --manifest-file`` run can publish the
strongest clips across every video.
"""

import hashlib
import json
import os
import re
import time
import traceback
from datetime import datetime, timezone

# Pause between consecutive downloads so a queue doesn't hammer YouTube back to
# back from the same (often shared Colab/Kaggle) IP and trigger a 403/rate-limit.
INTER_VIDEO_COOLDOWN_S = 8

QUEUE_DIR_NAME = "queue"
STATE_FILE = "queue_state.json"
QUEUE_MANIFEST_FILE = "queue_manifest.json"

_YOUTUBE_ID_PATTERNS = (
    r"(?:v=|/shorts/|/live/|/embed/|youtu\.be/)([A-Za-z0-9_-]{11})",
)


def read_links(path: str) -> list[str]:
    """
    Read one URL per line, ignoring blank lines, ``#`` comments and duplicates.

    Commas and whitespace also separate URLs, so a pasted list works as well.
    """
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    urls: list[str] = []
    seen = set()
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for token in re.split(r"[\s,]+", line.strip()):
            if not token.startswith(("http://", "https://")):
                continue
            key = video_key(token)
            if key in seen:
                continue
            seen.add(key)
            urls.append(token)
    return urls


def video_key(url: str) -> str:
    """A stable folder name per video: the YouTube ID, else a short URL hash."""
    for pattern in _YOUTUBE_ID_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return "v_" + hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:10]


def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rebuild_queue_manifest(queue_dir: str, state: dict) -> str:
    """
    Merge every finished video's render manifest into one list, best clip first.

    Rows keep their absolute ``video_path``, which is what the uploaders use to
    tell clips apart (ranks repeat across videos).
    """
    rows: list[dict] = []
    for key, entry in state.get("videos", {}).items():
        if entry.get("status") != "done":
            continue
        manifest = _load_json(os.path.join(queue_dir, key, "render_manifest.json"), [])
        for row in manifest:
            if row.get("status") == "success":
                rows.append(dict(row, queue_video_key=key, queue_source_url=entry.get("url")))

    rows.sort(key=lambda r: r.get("viral_score") or 0, reverse=True)
    path = os.path.join(queue_dir, QUEUE_MANIFEST_FILE)
    _save_json(path, rows)
    return path


def run_queue(
    links: list[str],
    clip_argv: list[str],
    *,
    outputs_root: str | None = None,
    retry_failed: bool = False,
    keep_source: bool = False,
) -> dict:
    """
    Run the clip pipeline for every URL in *links*, sequentially.

    Parameters
    ----------
    links : list[str]
        Video URLs, in processing order.
    clip_argv : list[str]
        Extra clip-pipeline flags (``--clips 5 --ratio 9:16 ...``), applied to every video.
    retry_failed : bool
        Also re-run videos whose previous attempt failed (done ones are always skipped).
    keep_source : bool
        Keep each downloaded source video; by default it is deleted once its
        clips are rendered, so a long queue does not fill the Colab disk.

    Returns
    -------
    dict
        The final queue state.
    """
    from .config import build_config
    from .runner import run_pipeline

    outputs_root = outputs_root or os.path.abspath(os.path.join(os.getcwd(), "outputs"))
    queue_dir = os.path.join(outputs_root, QUEUE_DIR_NAME)
    os.makedirs(queue_dir, exist_ok=True)
    state_path = os.path.join(queue_dir, STATE_FILE)
    state = _load_json(state_path, {"videos": {}})
    state.setdefault("videos", {})

    total = len(links)
    print(f"\n📋 Video queue: {total} link(s) — state file: {state_path}")

    for index, url in enumerate(links, 1):
        key = video_key(url)
        entry = state["videos"].get(key, {})
        status = entry.get("status")

        if status == "done" or (status == "failed" and not retry_failed):
            reason = "already done" if status == "done" else "failed before (use --retry-failed)"
            print(f"\n⏭️  [{index}/{total}] {url} — {reason}")
            continue

        print("\n" + "#" * 70)
        print(f"🎬 [{index}/{total}] {url}")
        print("#" * 70)

        if index > 1:
            print(f"   ⏳ Cooling down {INTER_VIDEO_COOLDOWN_S}s before the next download...")
            time.sleep(INTER_VIDEO_COOLDOWN_S)

        video_dir = os.path.join(queue_dir, key)
        os.makedirs(video_dir, exist_ok=True)

        entry = {"url": url, "status": "running", "started_at": _now()}
        state["videos"][key] = entry
        _save_json(state_path, state)

        cfg = build_config(["--url", url, *clip_argv])
        cfg.outputs_dir = video_dir
        cfg.source_video_path = os.path.join(video_dir, "source_video.mp4")

        if status == "failed" and os.path.exists(os.path.join(video_dir, "gemini_response.json")):
            # The source video and transcript are reused automatically; keep the
            # clips the AI already chose too, so a retry goes straight to rendering.
            print("   ♻️ Retrying with the saved download, transcript and AI clip selection.")
            cfg.load_gemini_json = True

        try:
            manifest = run_pipeline(cfg)
            succeeded = sum(1 for row in manifest if row.get("status") == "success")
            entry.update(status="done", clips=succeeded, finished_at=_now(), error=None)
            print(f"✅ [{index}/{total}] {succeeded} clip(s) rendered → {video_dir}")
            if not keep_source and os.path.exists(cfg.source_video_path):
                os.remove(cfg.source_video_path)
        except KeyboardInterrupt:
            entry.update(status="pending", error="interrupted")
            raise
        except Exception as e:
            traceback.print_exc()
            entry.update(status="failed", finished_at=_now(), error=str(e)[:2000])
            print(f"❌ [{index}/{total}] Failed: {e}")
            print("   The downloaded source was kept so --retry-failed can resume without re-downloading.")
        finally:
            _save_json(state_path, state)

        rebuild_queue_manifest(queue_dir, state)

    manifest_path = rebuild_queue_manifest(queue_dir, state)
    videos = state["videos"].values()
    done = sum(1 for v in videos if v.get("status") == "done")
    failed = sum(1 for v in videos if v.get("status") == "failed")
    clips = sum(v.get("clips", 0) for v in videos if v.get("status") == "done")

    print("\n" + "=" * 70)
    print(f"📋 Queue finished: {done} video(s) done, {failed} failed, {clips} clip(s) total")
    print(f"   Combined manifest (best clips first): {manifest_path}")
    print("=" * 70)
    return state
