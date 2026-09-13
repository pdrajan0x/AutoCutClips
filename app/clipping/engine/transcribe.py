"""
clipping.engine.transcribe — Word-level transcription via Faster-Whisper,
with a YouTube JSON3 subtitle fast path.
"""

import json
import re

# YouTube subtitle artefacts to strip, applied in order.
_SUB_CLEANUP = [
    (re.compile(r"<[^>]+>"), ""),            # HTML tags (<i>, <font color=...>)
    (re.compile(r"\[[\w\s]+\]"), ""),        # annotations: [Music], [Applause], ...
    (re.compile(r">>\s*"), ""),              # speaker-change markers
    (re.compile(r"[♪♫♬♩]"), ""),             # music symbols
    (re.compile(r"^\s*-\s+"), ""),           # leading speaker dash
    (re.compile(r"\s{2,}"), " "),            # collapse runs of spaces
]


def _group_words(flat_words: list[dict], max_words_per_subtitle: int) -> tuple[str, list[dict]]:
    """Group a flat word list into subtitle chunks plus a timestamped transcript."""
    transcript = ""
    segments: list[dict] = []
    chunk: list[dict] = []
    chunk_start = 0.0

    for i, w in enumerate(flat_words):
        if not chunk:
            chunk_start = w["start"]
        chunk.append(w)

        if len(chunk) == max_words_per_subtitle or i == len(flat_words) - 1:
            text = " ".join(cw["word"] for cw in chunk)
            transcript += f"[{chunk_start:.1f} - {w['end']:.1f}] {text}\n"
            segments.append({"start": chunk_start, "end": w["end"], "words": chunk})
            chunk = []

    return transcript, segments


def parse_youtube_json3_subs(
    json_path: str, max_words_per_subtitle: int = 5
) -> tuple[str, list[dict]]:
    """
    Parse downloaded YouTube JSON3 subtitles into (transcript, segments).

    Returns empty values if parsing fails, so the caller can fall back to Whisper.
    """
    print("[2/3] Processing YouTube JSON3 subtitles...")

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            subs_data = json.load(f)

        flat_words: list[dict] = []

        for event in subs_data.get("events", []):
            # YouTube timestamps are in milliseconds.
            t_start = event.get("tStartMs", 0) / 1000.0
            event_end = t_start + event.get("dDurationMs", 0) / 1000.0
            segs = event.get("segs", [])

            for i, seg in enumerate(segs):
                text = seg.get("utf8", "")
                if not text.strip() or text == "\n":
                    continue

                seg_start = t_start + seg.get("tOffsetMs", 0) / 1000.0
                if i < len(segs) - 1:
                    seg_end = t_start + segs[i + 1].get("tOffsetMs", 0) / 1000.0
                else:
                    seg_end = event_end
                if seg_end <= seg_start:
                    seg_end = seg_start + 1.0  # fallback duration

                clean_text = text.replace("\n", " ").replace("\u200b", "").strip()
                for pattern, repl in _SUB_CLEANUP:
                    clean_text = pattern.sub(repl, clean_text)
                clean_text = clean_text.strip()
                if not clean_text:
                    continue

                # Split into single words so per-word karaoke works like Whisper.
                words_in_seg = clean_text.split()
                per_word = (seg_end - seg_start) / len(words_in_seg)
                for w_idx, w_text in enumerate(words_in_seg):
                    w_start = seg_start + w_idx * per_word
                    flat_words.append(
                        {"word": w_text, "start": w_start, "end": w_start + per_word}
                    )

        # Pull each word's end back to the next word's start to avoid overlaps.
        for i in range(len(flat_words) - 1):
            if flat_words[i]["end"] > flat_words[i + 1]["start"]:
                flat_words[i]["end"] = max(
                    flat_words[i]["start"] + 0.1, flat_words[i + 1]["start"]
                )

        return _group_words(flat_words, max_words_per_subtitle)

    except Exception as e:
        print(f"⚠️ Failed to parse JSON3: {e}")
        return "", []


def transcribe_video(
    video_path: str,
    max_words_per_subtitle: int = 5,
    model_size: str = "large-v3",
    device: str = "cuda",
    compute_type: str = "float16",
) -> tuple[str, list[dict]]:
    """
    Transcribe *video_path* with Faster-Whisper.

    Returns
    -------
    transcript : str
        Human-readable transcript with timestamps.
    segments : list[dict]
        Word-level segments grouped by *max_words_per_subtitle*.
    """
    from faster_whisper import WhisperModel
    from tqdm import tqdm

    print("[2/3] Starting transcription with Faster-Whisper (per-word level)...")

    # faster-whisper is silent until the first segment is produced, so announce
    # each phase — otherwise a first CPU run (model download + full audio
    # decode) looks like a hang.
    print(
        f"      ⏳ Loading Whisper model '{model_size}' ({device})"
        " — the first download can take a while...",
        flush=True,
    )
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    print("      ⏳ Decoding audio & extracting features (no output yet)...", flush=True)
    segments, info = model.transcribe(video_path, beam_size=5, word_timestamps=True)

    transcript = ""
    data_segments: list[dict] = []

    # Progress is tracked against audio timestamps: faster-whisper streams
    # segments lazily, so the bar advances to each segment's end time.
    total_dur = round(info.duration, 2)
    progress = tqdm(
        total=total_dur,
        unit="s",
        desc="      Transcription",
        bar_format="{desc}: {percentage:3.0f}%|{bar}| {n:.0f}/{total:.0f}s [{elapsed}<{remaining}]",
    )

    for segment in segments:
        # Clamp so floating-point drift past the duration does not overshoot.
        progress.update(min(segment.end, total_dur) - progress.n)
        transcript += f"[{segment.start:.1f} - {segment.end:.1f}] {segment.text}\n"

        if not segment.words:
            continue

        chunk: list[dict] = []
        chunk_start = 0.0
        for i, w in enumerate(segment.words):
            if not chunk:
                chunk_start = w.start
            chunk.append({"word": w.word.strip(), "start": w.start, "end": w.end})

            if len(chunk) == max_words_per_subtitle or i == len(segment.words) - 1:
                data_segments.append({"start": chunk_start, "end": w.end, "words": chunk})
                chunk = []

    progress.update(total_dur - progress.n)  # snap to 100% when done
    progress.close()
    return transcript, data_segments
