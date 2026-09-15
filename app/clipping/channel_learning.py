"""
clipping.channel_learning — Turn the channel's real results into prompt guidance.

``python -m app.cli learn-youtube`` saves view counts for published clips to
``channel_performance.json``. This module picks the strongest and weakest of
them so the clip-selection prompt can lean towards what has actually worked on
this channel. Pure standard library, so the prompt can import it freely.
"""

import json
import os
from datetime import datetime, timezone

MIN_VIDEOS = 6            # fewer published clips than this is noise, not a pattern
MIN_AGE_HOURS = 48        # younger clips have not had their distribution yet
EXAMPLES_PER_SIDE = 4
SCORE_WINDOW_DAYS = 7     # Shorts get most of their views in the first week


def _parse_time(text):
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def load_examples(path):
    """
    Return ``(best, worst)`` published clips, or None when there is not enough data.

    Clips are ranked by views per day over their first week, so an older clip
    is not favoured just for having been online longer.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            rows = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(rows, list):
        return None

    now = datetime.now(timezone.utc)
    scored = []
    for row in rows:
        if not isinstance(row, dict) or row.get("privacy") != "public":
            continue
        published = _parse_time(row.get("published_at"))
        if published is None:
            continue
        fetched = _parse_time(row.get("fetched_at")) or now
        age_hours = (fetched - published).total_seconds() / 3600
        if age_hours < MIN_AGE_HOURS:
            continue
        days = max(1.0, min(age_hours / 24, SCORE_WINDOW_DAYS))
        scored.append((int(row.get("views") or 0) / days, row))

    if len(scored) < MIN_VIDEOS:
        return None

    scored.sort(key=lambda item: item[0], reverse=True)
    count = min(EXAMPLES_PER_SIDE, len(scored) // 2)
    return [row for _, row in scored[:count]], [row for _, row in scored[-count:]]


def _describe(row):
    parts = [f"{int(row.get('views') or 0):,} views"]
    if row.get("duration"):
        parts.append(f"{float(row['duration']):.0f}s")
    if row.get("on_screen_hook"):
        parts.append(f'on-screen: "{row["on_screen_hook"]}"')
    opening = " ".join(str(row.get("hook_text") or "").split())[:140]
    if opening:
        parts.append(f'hook line: "{opening}"')
    elif row.get("title"):
        parts.append(f'title: "{row["title"]}"')
    return "- " + " · ".join(parts)


def build_learning_section(cfg) -> str:
    """The prompt block describing the channel's best and worst clips ("" when unavailable)."""
    if cfg is None or getattr(cfg, "no_channel_learning", False):
        return ""
    path = getattr(cfg, "performance_file", None)
    if not path or not os.path.exists(path):
        return ""
    examples = load_examples(path)
    if not examples:
        return ""

    best, worst = examples
    lines = [
        "",
        "WHAT HAS WORKED ON THIS CHANNEL (real results of clips already published here):",
        "Best performers:",
        *[_describe(row) for row in best],
        "Weakest performers:",
        *[_describe(row) for row in worst],
        "Learn the pattern, not the topics: when candidates pass the quality gate equally, prefer openings,",
        "lengths and angles like the best performers and avoid those like the weakest. The quality gate always wins.",
    ]
    return "\n".join(lines) + "\n"
