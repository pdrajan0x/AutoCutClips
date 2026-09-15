"""
clipping.metadata — Metadata normalisation, enrichment and QA preview.

Turns the raw AI clip list into the ``*_final`` fields the uploaders consume,
validates the clip timings, re-ranks clips by viral score, and prints a compact
QA report. All metadata is English-only.
"""

import bisect
import json
import re

from .engine.prompt import MAX_CLIP_DURATION, MIN_CLIP_DURATION

# Two clips sharing more than this fraction of their runtime are treated as
# duplicate coverage of the same moment, and the weaker one is dropped. At 0.6,
# two clips repeating half of each other's content were both published.
MAX_CLIP_OVERLAP_RATIO = 0.25

# Clips the AI itself scores below this are dropped, as long as a better clip remains.
MIN_VIRAL_SCORE = 60

# A clip up to this fraction under --min-duration is kept: dropping a strong
# 28-second clip over a 30-second rule lost more than it protected.
SHORT_CLIP_TOLERANCE = 0.9

# Cut ends are moved onto the end of their sentence when the transcript has
# punctuation: forward by up to SENTENCE_EXTEND_MAX, else back by up to
# SENTENCE_RETREAT_MAX (never below the minimum length).
SENTENCE_END_CHARS = (".", "?", "!", "…", "।", "॥", "؟", "。", "！", "？")
SENTENCE_EXTEND_MAX = 2.5
SENTENCE_RETREAT_MAX = 6.0

# Cut-point snapping: keep a sliver of room before the first word so its
# consonant is not clipped, and let the last word ring out before the cut.
WORD_LEAD_IN = 0.12
WORD_TAIL = 0.35
# The AI copies line timestamps, and a line's end often equals the next word's
# start; ignore words starting within this window when snapping an end point.
SNAP_EPSILON = 0.05

ON_SCREEN_HOOK_MAX_CHARS = 42


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


MAX_HASHTAGS = 15  # YouTube ignores ALL hashtags on a video that has more than 15
MIN_HASHTAGS = 10


def _normalize_hashtags(text, max_tags=MAX_HASHTAGS):
    parts = _normalize_spaces(text).split()
    clean = []
    seen = set()

    for p in parts:
        # A hashtag ends at the first space or punctuation mark, so "#Joe-Rogan"
        # would only link "#Joe" — keep letters, digits and underscores only.
        body = re.sub(r"[^\w]", "", p.lstrip("#"))
        if not body or body.isdigit():
            continue
        p = "#" + body
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


def _normalize_on_screen_hook(text, max_chars=ON_SCREEN_HOOK_MAX_CHARS):
    """Clean the overlay headline: no quotes/hashtags, trimmed at a word boundary."""
    text = _normalize_spaces(text).strip("\"'“”‘’")
    text = " ".join(w for w in text.split() if not w.startswith("#"))
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:-–— ")
    return cut or text[:max_chars]


def _merge_segments(segments):
    """Sort keep_segments and merge overlaps, which would otherwise repeat audio."""
    merged = []
    for seg in sorted(segments, key=lambda s: s["start_time"]):
        if merged and seg["start_time"] <= merged[-1]["end_time"]:
            merged[-1]["end_time"] = max(merged[-1]["end_time"], seg["end_time"])
        else:
            merged.append(dict(seg))
    return merged


def _format_timestamp(seconds):
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "?"
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes)}:{secs:04.1f}"


def _score(item):
    try:
        return int(float(item.get("viral_score") or 0))
    except (TypeError, ValueError):
        return 0


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

def normalize_and_validate(
    clips_json: list[dict],
    min_duration: float = MIN_CLIP_DURATION,
    max_duration: float = MAX_CLIP_DURATION,
) -> list[dict]:
    """
    Normalise and enrich the AI clip list, adding the ``*_final`` fields.

    Mutates items in place and returns them sorted by viral score, with
    duplicate/overlapping clips removed and timings sanity-checked against the
    run's clip length bounds (``--min-duration`` / ``--max-duration``).
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

        # --- duration is a hard limit, not a suggestion -------------------------
        # The prompt asks for MIN..MAX, but the model drifts, so enforce it here:
        # over-long clips are trimmed, too-short ones cannot be salvaged.
        duration = item["end_time"] - item["start_time"]

        if duration > max_duration:
            item["end_time"] = item["start_time"] + max_duration
            warnings.append(
                f"trimmed from {duration:.1f}s to the {max_duration:g}s limit"
            )
            duration = max_duration

        if duration < min_duration * SHORT_CLIP_TOLERANCE:
            print(
                f"   ⚠️ Dropped clip "
                f"{_format_timestamp(item['start_time'])}-{_format_timestamp(item['end_time'])}"
                f" — {duration:.1f}s is under the {min_duration:g}s minimum."
            )
            continue

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

        # Smart trim decides the *rendered* length, so it can undercut the
        # minimum even when the span is fine. Clamp the segments to the clip and
        # fall back to the full span rather than emit a too-short video.
        segments = item.get("keep_segments")
        if isinstance(segments, list) and segments:
            clamped = []
            for seg in segments:
                try:
                    seg_start = max(float(seg["start_time"]), item["start_time"])
                    seg_end = min(float(seg["end_time"]), item["end_time"])
                except (KeyError, TypeError, ValueError):
                    continue
                if seg_end > seg_start:
                    clamped.append({"start_time": seg_start, "end_time": seg_end})

            clamped = _merge_segments(clamped)
            kept = sum(s["end_time"] - s["start_time"] for s in clamped)
            if not clamped or kept < min_duration * SHORT_CLIP_TOLERANCE:
                item.pop("keep_segments", None)
                warnings.append(
                    f"smart trim would leave {kept:.1f}s; rendering the full clip instead"
                )
            else:
                item["keep_segments"] = clamped

        # --- metadata normalisation --------------------------------------------
        item["on_screen_hook"] = _normalize_on_screen_hook(item.get("on_screen_hook", ""))
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
        if hashtag_count < MIN_HASHTAGS:
            warnings.append(
                f"only {hashtag_count} hashtag(s), expected {MIN_HASHTAGS}-{MAX_HASHTAGS}"
            )
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
    valid_items.sort(key=lambda x: _score(x), reverse=True)
    valid_items = _drop_overlapping_clips(valid_items)

    strong = [item for item in valid_items if _score(item) >= MIN_VIRAL_SCORE]
    if strong and len(strong) < len(valid_items):
        for item in valid_items[len(strong):]:
            print(
                f"   ⚠️ Dropped weak clip {_format_timestamp(item['start_time'])} "
                f"(viral_score {_score(item)} < {MIN_VIRAL_SCORE})"
            )
        valid_items = strong

    for idx, item in enumerate(valid_items):
        item["rank"] = idx + 1
        item_warnings = item.pop("_warnings_temp", [])
        if item_warnings:
            print(f"   ⚠️ Clip {item['rank']}: {'; '.join(item_warnings)}")

    return valid_items


# ==============================================================================
# CUT-POINT SNAPPING
# ==============================================================================

def _flatten_words(segments: list[dict]) -> list[tuple[float, float, str]]:
    words = []
    for seg in segments or []:
        for w in seg.get("words", []):
            try:
                start, end = float(w["start"]), float(w["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if end > start:
                words.append((start, end, str(w.get("word", ""))))
    words.sort(key=lambda w: (w[0], w[1]))
    return words


def _ends_sentence(text) -> bool:
    return str(text).strip().rstrip("\"'”’»)]").endswith(SENTENCE_END_CHARS)


def _finish_sentence(end, words, starts, earliest_end):
    """
    Move a snapped end point onto the end of its sentence.

    Gemini copies line timestamps, and a line often holds more than one
    sentence, so clips stopped mid-sentence. Prefer finishing the sentence
    (within SENTENCE_EXTEND_MAX); otherwise fall back to the previous sentence
    end, but never earlier than *earliest_end*.
    """
    idx = bisect.bisect_right(starts, end - SNAP_EPSILON) - 1
    if idx < 0 or _ends_sentence(words[idx][2]):
        return end

    for j in range(idx + 1, len(words)):
        if words[j][1] - end > SENTENCE_EXTEND_MAX:
            break
        if _ends_sentence(words[j][2]):
            return _snap_end(words[j][1], words, starts)

    for j in range(idx - 1, -1, -1):
        if end - words[j][1] > SENTENCE_RETREAT_MAX or words[j][1] < earliest_end:
            break
        if _ends_sentence(words[j][2]):
            return _snap_end(words[j][1], words, starts)
    return end


def _snap_start(t, words, starts):
    """Move a start time to the beginning of the word it falls in (or the next word)."""
    idx = bisect.bisect_right(starts, t) - 1
    w = idx if idx >= 0 and words[idx][1] > t else idx + 1
    if w >= len(words):
        return t
    prev_end = words[w - 1][1] if w > 0 else 0.0
    return max(words[w][0] - WORD_LEAD_IN, min(prev_end, words[w][0]), 0.0)


def _snap_end(t, words, starts):
    """Move an end time to the end of the word it falls in (or the previous word)."""
    idx = bisect.bisect_right(starts, t - SNAP_EPSILON) - 1
    if idx < 0:
        return t
    word_end = words[idx][1]
    next_start = words[idx + 1][0] if idx + 1 < len(words) else float("inf")
    return max(word_end, min(word_end + WORD_TAIL, next_start - SNAP_EPSILON))


def _snap_span(start, end, words, starts):
    new_start = _snap_start(float(start), words, starts)
    new_end = _snap_end(float(end), words, starts)
    if new_end <= new_start:
        return float(start), float(end)
    return round(new_start, 3), round(new_end, 3)


def snap_clips_to_words(
    clips: list[dict], segments: list[dict], min_duration: float = MIN_CLIP_DURATION
) -> list[dict]:
    """
    Snap every cut point to the transcript's word boundaries (in place).

    The AI copies line-level timestamps, so its cuts land mid-word or clip the
    first consonant and the final syllable. This moves clip, keep-segment and
    hook boundaries onto real word edges with a little breathing room, and
    ends clips on a sentence end when the transcript is punctuated.
    """
    words = _flatten_words(segments)
    if not words:
        return clips
    starts = [w[0] for w in words]
    punctuated = any(_ends_sentence(w[2]) for w in words)

    for clip in clips:
        original_end = float(clip["end_time"])
        clip["start_time"], clip["end_time"] = _snap_span(
            clip["start_time"], clip["end_time"], words, starts
        )
        if punctuated:
            earliest_end = clip["start_time"] + min_duration * SHORT_CLIP_TOLERANCE
            clip["end_time"] = round(
                _finish_sentence(clip["end_time"], words, starts, earliest_end), 3
            )

        if clip.get("hook_start_time") is not None and clip.get("hook_end_time") is not None:
            hook_start, hook_end = _snap_span(
                clip["hook_start_time"], clip["hook_end_time"], words, starts
            )
            clip["hook_start_time"] = max(hook_start, clip["start_time"])
            clip["hook_end_time"] = min(hook_end, clip["end_time"])

        segs = clip.get("keep_segments")
        if isinstance(segs, list) and segs:
            snapped = []
            for seg in segs:
                seg_start, seg_end = _snap_span(seg["start_time"], seg["end_time"], words, starts)
                if abs(float(seg["end_time"]) - original_end) <= 1.0:
                    # The segment that ended the clip follows the clip's new end.
                    seg_end = clip["end_time"]
                seg_start = max(seg_start, clip["start_time"])
                seg_end = min(seg_end, clip["end_time"])
                if seg_end > seg_start:
                    snapped.append({"start_time": seg_start, "end_time": seg_end})
            clip["keep_segments"] = _merge_segments(snapped) if snapped else segs

    return clips


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
