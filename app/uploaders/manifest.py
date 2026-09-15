"""
app.uploaders.manifest — Shared render-manifest helpers.

Both uploaders read the same ``render_manifest.json`` and write their results
back as extra per-row fields, so the JSON/file/text plumbing lives here.
"""

import json
import os
import re

YOUTUBE_DESCRIPTION_MAX_CHARS = 5000
YOUTUBE_TAGS_MAX_CHARS = 500  # YouTube's limit for all tags combined


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


def normalize_description(text) -> str:
    """
    Tidy a description while keeping its line breaks.

    ``normalize_text`` flattens everything onto one line, which posted the hook,
    context, hashtags and source credit as a single run-on paragraph. ``<`` and
    ``>`` are removed because the YouTube API rejects descriptions containing them.
    """
    text = str(text or "").replace("\r\n", "\n").replace("<", "").replace(">", "")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text[:YOUTUBE_DESCRIPTION_MAX_CHARS]


def get_hashtags(item: dict) -> list[str]:
    """The clip's hashtags as a list (``#Tag`` strings), from the manifest row."""
    return [t for t in str(item.get("hashtags") or "").split() if t.startswith("#") and len(t) > 1]


def build_description(item: dict) -> str:
    """
    The publishable description, guaranteed to carry the clip's hashtags.

    Hashtags are placed before the source credit when the description does not
    already contain them (e.g. a manifest rendered before they were generated).
    """
    description = str(item.get("youtube_description_final") or "")
    hashtags = get_hashtags(item)
    missing = [t for t in hashtags if t.lower() not in description.lower()]
    if missing:
        line = " ".join(missing)
        marker = "\n\nSource:"
        if marker in description:
            head, tail = description.split(marker, 1)
            description = f"{head.rstrip()}\n\n{line}{marker}{tail}"
        else:
            description = f"{description.rstrip()}\n\n{line}"
    return normalize_description(description)


def build_youtube_tags(item: dict) -> list[str]:
    """
    Keyword tags followed by the hashtag words, within YouTube's 500-character budget.

    YouTube counts each tag's length, a comma between tags, and two extra
    characters for the quotes around any tag that contains a space.
    """
    candidates = list(item.get("youtube_tags_final") or item.get("keyword_tags") or [])
    candidates += [t.lstrip("#") for t in get_hashtags(item)]

    tags: list[str] = []
    seen = set()
    used = 0
    for tag in candidates:
        tag = normalize_text(tag).replace("<", "").replace(">", "")
        key = tag.lower().replace(" ", "")
        if not tag or key in seen:
            continue
        cost = len(tag) + (2 if " " in tag else 0) + (1 if tags else 0)
        if used + cost > YOUTUBE_TAGS_MAX_CHARS:
            continue
        seen.add(key)
        tags.append(tag)
        used += cost
    return tags


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


def _same_file(a, b) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def get_manifest_row(manifest_rows, item: dict):
    """
    Find the manifest row for *item*, matching on ``video_path`` first.

    Ranks repeat across videos in a combined queue manifest, so rank alone
    can update the wrong clip; it is only used when a row has no path.
    """
    video_path = item.get("video_path")
    if video_path:
        for row in manifest_rows:
            if _same_file(row.get("video_path"), video_path):
                return row
    return get_manifest_row_by_rank(manifest_rows, item.get("rank"))


def merge_previous_results(manifest_rows, previous_rows, prefix: str) -> int:
    """
    Copy ``<prefix>*`` fields from an earlier updated manifest onto *manifest_rows*.

    The uploaders read the render manifest but write results to a separate
    "updated" manifest, so without this every re-run saw no upload status and
    published the same clips again. Returns the number of rows restored.
    """
    restored = 0
    for prev in previous_rows or []:
        fields = {k: v for k, v in prev.items() if k.startswith(prefix)}
        if not fields:
            continue
        row = get_manifest_row(manifest_rows, prev)
        if row is not None:
            for k, v in fields.items():
                row.setdefault(k, v)
            restored += 1
    return restored


def get_clip_title_and_description(item: dict, title_limit: int = 100) -> tuple[str, str]:
    """
    Extract a publishable title and description from a manifest row.

    Prefers the enriched YouTube fields, falling back to the raw clip title.
    """
    title = (
        item.get("youtube_title_final")
        or item.get("title")
        or f"Clip Rank {item.get('rank', '?')}"
    )
    return normalize_text(title)[:title_limit], build_description(item)
