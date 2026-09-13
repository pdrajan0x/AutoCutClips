"""
app.uploaders.manifest — Shared render-manifest helpers.

Both uploaders read the same ``render_manifest.json`` and write their results
back as extra per-row fields, so the JSON/file/text plumbing lives here.
"""

import json
import os


def load_json_file(path, default=None):
    """Read a JSON file, returning *default* (or []) when it does not exist."""
    if not os.path.exists(path):
        return default if default is not None else []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json_file(path, data):
    """Write *data* as pretty UTF-8 JSON, creating the parent directory."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_nonempty_file(path) -> bool:
    """True when *path* points at an existing, non-empty regular file."""
    return bool(path) and os.path.isfile(path) and os.path.getsize(path) > 0


def normalize_text(text) -> str:
    """Collapse all whitespace runs in *text* into single spaces."""
    return " ".join(str(text or "").split()).strip()


def normalize_tags(tags, max_items=8) -> list[str]:
    """De-duplicate (case-insensitively) and trim a tag list."""
    if not isinstance(tags, list):
        return []

    out: list[str] = []
    seen = set()
    for tag in tags:
        t = normalize_text(tag)
        if not t or t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t)
        if len(out) >= max_items:
            break
    return out


def get_upload_candidates(render_manifest) -> list[dict]:
    """Return the manifest rows that rendered successfully and still have a file."""
    return [
        item
        for item in render_manifest
        if item.get("status") == "success" and is_nonempty_file(item.get("video_path"))
    ]


def get_manifest_row_by_rank(manifest_rows, rank):
    """Find a manifest row by its ``rank`` field."""
    for row in manifest_rows:
        if row.get("rank") == rank:
            return row
    return None


def get_clip_title_and_description(item: dict, title_limit: int = 100) -> tuple[str, str]:
    """
    Extract a publishable title and description from a manifest row.

    Prefers the English YouTube fields, falling back to the Indonesian title.
    """
    title = (
        item.get("youtube_title_final")
        or item.get("title_inggris")
        or item.get("title_indonesia")
        or f"Clip Rank {item.get('rank', '?')}"
    )
    description = (
        item.get("youtube_description_final")
        or item.get("tiktok_caption_final")
        or ""
    )
    return normalize_text(title)[:title_limit], normalize_text(description)
