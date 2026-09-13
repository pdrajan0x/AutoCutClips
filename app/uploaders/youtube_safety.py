"""
app.uploaders.youtube_safety — Upload safety rails for the YouTube uploader.

Enforces a daily upload cap, a per-run cap, a minimum interval between
scheduled publishes, a maximum scheduled-queue length, and an optional manual
approval prompt. Configured by ``upload_safety.json`` (see DEFAULT_CONFIG).

These rails exist to reduce the risk of a channel being flagged for spam when
uploading in bulk; ``--no-approval`` skips only the interactive prompt.
"""

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_CONFIG = {
    "max_upload_per_day": 3,
    "max_upload_per_run": 2,
    "interval_hours_min": 2,
    "max_scheduled_queue": 15,
    "require_manual_approval": True,
    "upload_log_file": "outputs/upload_history.json",
}


# ==============================================================================
# CONFIG & HISTORY
# ==============================================================================

def load_safety_config(config_path: str = "upload_safety.json") -> dict:
    """
    Load the safety config, filling in defaults for anything missing.

    The merged config is written back so the file always documents every knob.
    """
    config = dict(DEFAULT_CONFIG)

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config.update(json.load(f))
        except (OSError, json.JSONDecodeError) as e:
            print(f"⚠️ Could not read {config_path}: {e}. Using defaults.")

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except OSError as e:
        print(f"⚠️ Could not write {config_path}: {e}")

    return config


def _load_history(log_file: str) -> list:
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            history = json.load(f)
        return history if isinstance(history, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def record_upload(log_file: str, video_id: str, title: str, tz_name: str) -> None:
    """Append one successful upload to the history log."""
    history = _load_history(log_file)
    now = datetime.now(ZoneInfo(tz_name))
    history.append({
        "video_id": video_id,
        "title": title,
        "uploaded_at": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "date": now.strftime("%Y-%m-%d"),
    })

    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def count_uploads_today(log_file: str, tz_name: str) -> int:
    """Count the uploads recorded for today in the configured timezone."""
    today = datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    return sum(1 for entry in _load_history(log_file) if entry.get("date") == today)


# ==============================================================================
# LIMIT CHECKS
# ==============================================================================

def check_daily_limit(safety_config: dict, tz_name: str) -> tuple[bool, int, int]:
    """Return (allowed, uploads_today, max_per_day)."""
    max_per_day = safety_config["max_upload_per_day"]
    uploads_today = count_uploads_today(safety_config["upload_log_file"], tz_name)
    return uploads_today < max_per_day, uploads_today, max_per_day


def enforce_min_interval(requested_hours: int, safety_config: dict) -> int:
    """Raise the requested interval to the configured minimum if needed."""
    effective = max(requested_hours, safety_config["interval_hours_min"])
    if effective != requested_hours:
        print(f"🛡️ Interval raised from {requested_hours}h to {effective}h")
    return effective


def limit_pending_items(items: list, safety_config: dict) -> list:
    """Trim the pending list to the per-run cap."""
    max_per_run = safety_config["max_upload_per_run"]
    if len(items) > max_per_run:
        print(f"🛡️ Limiting this run: {len(items)} item(s) -> {max_per_run} per run")
        return items[:max_per_run]
    return items


def check_queue_limit(youtube, safety_config: dict, tz_name: str) -> tuple[bool, int, int]:
    """
    Count the videos already scheduled in the future on the channel.

    Returns (allowed, scheduled_count, max_queue). On any API error the check
    passes (True, 0, max) so a transient failure cannot block every upload.
    """
    from .youtube import count_future_scheduled

    max_queue = safety_config["max_scheduled_queue"]
    try:
        scheduled_count = count_future_scheduled(youtube, tz_name, max_pages=5)
    except Exception as e:
        print(f"⚠️ Could not check the scheduled queue: {e}")
        return True, 0, max_queue
    return scheduled_count < max_queue, scheduled_count, max_queue


# ==============================================================================
# MANUAL APPROVAL
# ==============================================================================

def prompt_manual_approval(item: dict, publish_at_local=None) -> bool:
    """Ask the operator to confirm one upload. Returns False on skip/abort."""
    title = (
        item.get("youtube_title_final")
        or item.get("title_inggris")
        or f"Clip Rank {item.get('rank', '?')}"
    )

    print("\n" + "=" * 60)
    print("🛡️ MANUAL APPROVAL REQUIRED")
    print("=" * 60)
    print(f"  Title    : {title}")
    print(f"  File     : {os.path.basename(item.get('video_path', '?'))}")
    if publish_at_local:
        print(f"  Schedule : {publish_at_local.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("=" * 60)
    print("\n⚠️  CHECKLIST BEFORE APPROVING:")
    print("  [ ] Have you reviewed the video manually?")
    print("  [ ] Does it carry your own narration/analysis/voice-over?")
    print("  [ ] Do the title & thumbnail avoid imitating the original creator?")
    print()

    while True:
        try:
            answer = input("Upload this video? (y/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n⏹️ Upload cancelled by the user.")
            return False

        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            print("⏭️ Video skipped.")
            return False
        print("   Type 'y' to upload or 'n' to skip.")


def print_safety_summary(safety_config: dict, tz_name: str) -> None:
    """Print the active safety rails and today's usage."""
    is_allowed, uploads_today, max_per_day = check_daily_limit(safety_config, tz_name)

    print("\n" + "=" * 60)
    print("🛡️ UPLOAD SAFETY RULES")
    print("=" * 60)
    print(f"  Max per run        : {safety_config['max_upload_per_run']}")
    print(f"  Max per day        : {max_per_day} (today: {uploads_today})")
    print(f"  Min interval       : {safety_config['interval_hours_min']}h")
    print(f"  Max scheduled queue: {safety_config['max_scheduled_queue']}")
    print(
        "  Manual approval    : "
        + ("ON ✅" if safety_config["require_manual_approval"] else "OFF ⚠️")
    )
    print(f"  Upload log         : {safety_config['upload_log_file']}")
    print("=" * 60)

    if not is_allowed:
        print(f"\n🚫 DAILY LIMIT REACHED! Already {uploads_today}/{max_per_day} uploads today.")
