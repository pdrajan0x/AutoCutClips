"""
clipping.metadata — Metadata normalisation, enrichment and QA preview.

Turns the raw AI clip list into the ``*_final`` fields the uploaders consume,
validates the clip timings, re-ranks clips by viral score, and prints a compact
QA report. All metadata is English-only.
"""

import json

from .engine.prompt import MAX_CLIP_DURATION, MIN_CLIP_DURATION

# Two clips sharing more than this fraction of their runtime are treated as
# duplicate coverage of the same moment, and the weaker one is dropped.
MAX_CLIP_OVERLAP_RATIO = 0.6


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _normalize_spaces(text):
    return " ".join(str(text or "").split()).strip()


def _trim_title(text, max_len=100):
    text = _normalize_spaces(text)
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0].strip()
    return cut if cut else text[:max_len].strip()


def _normalize_hashtags(text, max_tags=3):
    parts = _normalize_spaces(text).split()
    clean = []
    seen = set()

    for p in parts:
        if not p:
            continue
        if not p.startswith("#"):
            p = "#" + p.lstrip("#")
        key = p.lower()
        if key not in seen:
            seen.add(key)
            clean.append(p)
        if len(clean) >= max_tags:
            break

    return " ".join(clean), len(clean)


def _normalize_keyword_tags(tags, max_items=8):
    if not isinstance(tags, list):
        tags = []
    out = []
    seen = set()

    for t in tags:
        x = _normalize_spaces(t)
        if not x:
            continue
        key = x.lower()
        if key not in seen:
            seen.add(key)
            out.append(x)
        if len(out) >= max_items:
            break

    return out


def _build_youtube_description(hook, context, hashtags, source_url=None):
    parts = [
        _normalize_spaces(hook),
        _normalize_spaces(context),
        _normalize_spaces(hashtags),
    ]
    desc = "\n\n".join([p for p in parts if p]).strip()

    if source_url:
        desc += f"\n\nSource: {source_url}"

    return desc


def _format_timestamp(seconds):
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "?"
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes)}:{secs:04.1f}"


def _overlap_ratio(a, b):
    """Fraction of the shorter clip's runtime that overlaps the other clip."""
    overlap = min(a["end_time"], b["end_time"]) - max(a["start_time"], b["start_time"])
    if overlap <= 0:
        return 0.0
    shortest = min(a["end_time"] - a["start_time"], b["end_time"] - b["start_time"])
    return overlap / shortest if shortest > 0 else 0.0


def _drop_overlapping_clips(items):
    """
    Remove clips that duplicate a higher-scoring clip's time range.

    The AI is told not to overlap, but still does on rambling transcripts, and
    keeping both produces two near-identical shorts.
    """
    kept = []
    for item in items:
        duplicate_of = next(
            (k for k in kept if _overlap_ratio(item, k) > MAX_CLIP_OVERLAP_RATIO),
            None,
        )
        if duplicate_of is None:
            kept.append(item)
            continue
        print(
            f"   ⚠️ Dropped overlapping clip "
            f"{_format_timestamp(item['start_time'])}-{_format_timestamp(item['end_time'])} "
            f"— duplicates "
            f"{_format_timestamp(duplicate_of['start_time'])}-"
            f"{_format_timestamp(duplicate_of['end_time'])}"
        )
    return kept


# ==============================================================================
# MAIN API
# ==============================================================================

def normalize_and_validate(clips_json: list[dict]) -> list[dict]:
    """
    Normalise and enrich the AI clip list, adding the ``*_final`` fields.

    Mutates items in place and returns them sorted by viral score, with
    duplicate/overlapping clips removed and timings sanity-checked.
    """
    valid_items = []
    for item in clips_json:
        if not isinstance(item, dict):
            print(f"   ⚠️ Skipping an invalid clip entry (not an object): {type(item)}")
            continue

        # Some models nest everything under a "metadata" key — lift it up.
        if isinstance(item.get("metadata"), dict):
            for k, v in item["metadata"].items():
                if k not in item:
                    item[k] = v

        item["rank"] = item.get("rank") or item.get("no") or "?"
        item["viral_score"] = item.get("viral_score", 0)

        start = item.get("start_time") or item.get("clip_start") or item.get("start")
        end = item.get("end_time") or item.get("clip_end") or item.get("end")
        item["start_time"] = float(start) if start is not None else 0.0
        item["end_time"] = float(end) if end is not None else 0.0

        warnings: list[str] = []

        # --- timing validation ------------------------------------------------
        duration = item["end_time"] - item["start_time"]
        if duration <= 0:
            warnings.append("zero or negative duration")
        elif duration < MIN_CLIP_DURATION:
            warnings.append(f"shorter than {MIN_CLIP_DURATION}s ({duration:.1f}s)")
        elif duration > MAX_CLIP_DURATION:
            warnings.append(f"longer than {MAX_CLIP_DURATION}s ({duration:.1f}s)")

        # Keep the hook inside its own clip — the renderer trusts these directly.
        hook_start = item.get("hook_start_time")
        hook_end = item.get("hook_end_time")
        if hook_start is not None and hook_end is not None:
            hook_start = min(max(float(hook_start), item["start_time"]), item["end_time"])
            hook_end = min(max(float(hook_end), hook_start), item["end_time"])
            if hook_end <= hook_start:
                # Drop the unusable values so the renderer falls back to its
                # own default window instead of seeking outside the clip.
                item.pop("hook_start_time", None)
                item.pop("hook_end_time", None)
                warnings.append("invalid hook timing; renderer will use its default")
            else:
                item["hook_start_time"] = hook_start
                item["hook_end_time"] = hook_end

        item["hook_text"] = _normalize_spaces(item.get("hook_text", ""))
        if not item["hook_text"]:
            warnings.append("hook_text is empty")

        # --- metadata normalisation --------------------------------------------
        item["title"] = _trim_title(item.get("title", ""))
        item["description_hook"] = _normalize_spaces(item.get("description_hook", ""))
        item["description_context"] = _normalize_spaces(item.get("description_context", ""))
        item["hashtags"] = _normalize_spaces(
            item.get("hashtags") or item.get("hashtag") or ""
        )
        item["keyword_tags"] = _normalize_keyword_tags(item.get("keyword_tags", []))

        hashtags_clean, hashtag_count = _normalize_hashtags(item["hashtags"])
        item["hashtags"] = hashtags_clean

        item["youtube_title_final"] = item["title"]
        item["youtube_description_final"] = _build_youtube_description(
            item.get("description_hook", ""),
            item.get("description_context", ""),
            item.get("hashtags", ""),
            source_url=item.get("source_url"),
        )
        item["youtube_tags_final"] = item.get("keyword_tags", [])

        # --- metadata QA --------------------------------------------------------
        if not item["title"]:
            warnings.append("title is empty")
        if hashtag_count < 2:
            warnings.append(f"only {hashtag_count} hashtag(s), expected 2-3")
        if not item["description_hook"]:
            warnings.append("description_hook is empty")
        if not item["description_context"]:
            warnings.append("description_context is empty")
        if len(item["keyword_tags"]) < 5:
            warnings.append(f"only {len(item['keyword_tags'])} keyword_tags, expected 5-8")
        if len(item.get("youtube_description_final", "")) < 30:
            warnings.append("youtube_description is very short (< 30 chars)")

        item["_warnings_temp"] = warnings
        valid_items.append(item)

    # Strongest clips first, then drop weaker clips covering the same moment.
    valid_items.sort(key=lambda x: x.get("viral_score", 0), reverse=True)
    valid_items = _drop_overlapping_clips(valid_items)

    for idx, item in enumerate(valid_items):
        item["rank"] = idx + 1
        item_warnings = item.pop("_warnings_temp", [])
        if item_warnings:
            print(f"   ⚠️ Clip {item['rank']}: {'; '.join(item_warnings)}")

    return valid_items


def print_preview(clips: list[dict]) -> None:
    """Print a compact one-line-per-clip summary; full detail goes to the JSON."""
    if not clips:
        print("⚠️ No clips survived validation.")
        return

    has_accounts = any(c.get("account_classification") for c in clips)

    header = f"{'#':>2}  {'SCORE':>5}  {'START':>7}  {'DUR':>6}  {'TITLE':<52}"
    if has_accounts:
        header += "  ACCOUNT"

    print(f"\n===== CLIP PREVIEW ({len(clips)} clips) =====")
    print(header)
    print("-" * len(header))

    for c in clips:
        duration = c["end_time"] - c["start_time"]
        title = c.get("title", "")
        title = title if len(title) <= 52 else title[:49] + "..."
        row = (
            f"{c['rank']:>2}  {c.get('viral_score', 0):>5}  "
            f"{_format_timestamp(c['start_time']):>7}  {duration:>5.1f}s  {title:<52}"
        )
        if has_accounts:
            row += f"  {c.get('account_classification', {}).get('account_type', '-')}"
        print(row)

    print()


def save_metadata_preview(clips: list[dict], path: str = "metadata_preview.json") -> None:
    """Save the normalised metadata to a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clips, f, ensure_ascii=False, indent=2)
    print(f"💾 Full metadata saved to {path}")
