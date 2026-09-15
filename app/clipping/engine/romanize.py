"""
clipping.engine.romanize — Captions in Latin letters for non-Latin speech.

When the speech is in a language written in another script (Hindi, Tamil,
Arabic, Russian, ...), the captions keep the spoken language but are written in
English letters, the way people type it on social media:

    नमस्ते, मेरा नाम प्रियदर्शनी राजन है  ->  namaste, mera naam priyadarshani rajan hai

This is transliteration, never translation. It also keeps captions renderable:
the caption fonts only cover Latin glyphs.

Only the words inside the selected clips are converted, word for word, so the
per-word timings used for karaoke captions stay untouched.
"""

import json
import string
import unicodedata

# Consecutive caption chunks are joined into lines of about this many words so
# the model sees enough context to spell words naturally.
MAX_WORDS_PER_LINE = 12
LINES_PER_REQUEST = 60
# Seconds of padding around each clip, so snapped cut points stay covered.
CLIP_PADDING = 1.0

_PROMPT = """You convert speech transcripts into Latin (English) letters for on-screen video captions.

Spoken language: {language}

RULES:
- Transliterate, NEVER translate. Keep exactly the same words, in the same language and order — only change the script.
- Spell words the way people casually type this language in English letters on WhatsApp, YouTube and Instagram
  (e.g. Hinglish), not academic transliteration: no diacritics (ā, ṣ, ṇ) and no ITRANS/IAST capital letters.
  Example (Hindi): ["नमस्ते,", "मेरा", "नाम", "प्रियदर्शनी", "राजन", "है।"] -> ["namaste,", "mera", "naam", "priyadarshani", "rajan", "hai."]
- English words written in the native script go back to their normal English spelling:
  "मोटिवेशन" -> "motivation", "बिज़नेस" -> "business".
- Words already in Latin letters stay unchanged. Numbers stay as digits.
- Keep punctuation on the same word; turn native marks into Latin ones ("।" -> ".", "؟" -> "?", "،" -> ",").
- Lowercase, except acronyms and brand/English proper nouns that are normally capitalised (AI, iPhone, Google).
- Return EXACTLY one output word for every input word in each line: same count, same order.
  Never merge, split, add or drop words.

Return JSON {{"lines": [{{"id": <same id>, "words": [...]}}]}} with every input line.

INPUT:
{payload}
"""

_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "lines": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "INTEGER"},
                    "words": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": ["id", "words"],
            },
        }
    },
    "required": ["lines"],
}


def needs_romanization(text) -> bool:
    """True when *text* contains a letter from a non-Latin script."""
    for ch in str(text or ""):
        if not ch.isalpha():
            continue
        try:
            if not unicodedata.name(ch).startswith("LATIN"):
                return True
        except ValueError:
            return True
    return False


def _clean_key(word) -> str:
    """Lowercase a word and strip surrounding punctuation, native marks included."""
    w = str(word or "").strip().lower()

    def is_punct(ch):
        return ch in string.punctuation or unicodedata.category(ch).startswith("P")

    start, end = 0, len(w)
    while start < end and is_punct(w[start]):
        start += 1
    while end > start and is_punct(w[end - 1]):
        end -= 1
    return w[start:end]


def _collect_lines(clips, segments, max_words=MAX_WORDS_PER_LINE):
    """Group the non-Latin caption chunks inside the clips into lines of word references."""
    spans = [
        (float(c["start_time"]) - CLIP_PADDING, float(c["end_time"]) + CLIP_PADDING)
        for c in clips
    ]
    lines: list[list[tuple[int, int]]] = []
    current: list[tuple[int, int]] = []
    last_seg = None

    for si, seg in enumerate(segments):
        words = seg.get("words") or []
        start, end = float(seg.get("start", 0)), float(seg.get("end", 0))
        in_clip = any(end > a and start < b for a, b in spans)
        if not in_clip or not any(needs_romanization(w.get("word")) for w in words):
            continue
        if current and (last_seg != si - 1 or len(current) + len(words) > max_words):
            lines.append(current)
            current = []
        current += [(si, wi) for wi in range(len(words))]
        last_seg = si

    if current:
        lines.append(current)
    return lines


def _gemini_request(texts, ids, language, cfg):
    """One Gemini call; returns {id: words} for the lines it answered."""
    import google.genai as genai
    from google.genai import types

    from .analysis import REQUEST_TIMEOUT_MS, _generate_json_with_retry

    client = genai.Client(
        api_key=cfg.api_key_gemini,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    payload = json.dumps(
        {"lines": [{"id": i, "words": texts[i]} for i in ids]}, ensure_ascii=False
    )
    parsed = _generate_json_with_retry(
        client=client,
        model=cfg.gemini_model,
        fallback_model=getattr(cfg, "gemini_fallback_model", None),
        contents=_PROMPT.format(language=language or "detect it from the text", payload=payload),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_SCHEMA,
        ),
    )
    out = {}
    for item in (parsed or {}).get("lines", []) if isinstance(parsed, dict) else []:
        if isinstance(item, dict) and isinstance(item.get("id"), int):
            out[item["id"]] = item.get("words")
    return out


def transliterate_lines(texts, language, cfg):
    """
    Transliterate each word list in *texts* with Gemini.

    Returns a list aligned with *texts*; an entry is None when the model did not
    return a same-length word list for it, even after a second attempt.
    """
    results = [None] * len(texts)
    pending = list(range(len(texts)))

    for attempt in (1, 2):
        if not pending:
            break
        for batch_start in range(0, len(pending), LINES_PER_REQUEST):
            ids = pending[batch_start:batch_start + LINES_PER_REQUEST]
            try:
                answered = _gemini_request(texts, ids, language, cfg)
            except Exception as e:
                print(f"   ⚠️ Caption transliteration request failed (attempt {attempt}): {e}")
                continue
            for i in ids:
                words = answered.get(i)
                if (
                    isinstance(words, list)
                    and len(words) == len(texts[i])
                    and all(isinstance(w, str) and w.strip() for w in words)
                ):
                    results[i] = [w.strip() for w in words]
        pending = [i for i in pending if results[i] is None]

    return results


def romanize_clip_captions(clips, segments, cfg, transliterate=None) -> int:
    """
    Rewrite the caption words inside *clips* in Latin letters (in place).

    Also converts each clip's on-screen headline if the AI wrote it in a
    non-Latin script, and remaps ``typography_plan`` words and ``hook_text`` so
    the emphasis styling still finds its words. Returns the number of caption
    words changed. ``transliterate(texts, language)`` can be injected for tests.
    """
    if not clips or not segments:
        return 0

    word_lines = _collect_lines(clips, segments)
    overlays = [
        ci for ci, clip in enumerate(clips) if needs_romanization(clip.get("on_screen_hook"))
    ]

    texts = [[segments[si]["words"][wi]["word"] for si, wi in line] for line in word_lines]
    texts += [str(clips[ci]["on_screen_hook"]).split() for ci in overlays]
    if not texts:
        return 0

    language = getattr(cfg, "transcript_language", None)
    total_words = sum(len(t) for t in texts)
    print(
        f"🔤 Writing {total_words} caption word(s) in English letters "
        f"(language: {language or 'auto'}) — transliterated, not translated..."
    )

    if transliterate is None:
        def transliterate(t, lang):
            return transliterate_lines(t, lang, cfg)

    results = list(transliterate(texts, language) or [])
    results += [None] * (len(texts) - len(results))

    mapping: dict[str, str] = {}
    changed = 0
    failed = 0

    for line, text, out in zip(word_lines, texts, results):
        if not isinstance(out, list) or len(out) != len(text):
            failed += len(line)
            continue
        for (si, wi), new_word in zip(line, out):
            word = segments[si]["words"][wi]
            if new_word and new_word != word["word"]:
                mapping.setdefault(_clean_key(word["word"]), new_word)
                word["word"] = new_word
                changed += 1

    for ci, text, out in zip(overlays, texts[len(word_lines):], results[len(word_lines):]):
        if isinstance(out, list) and len(out) == len(text):
            clips[ci]["on_screen_hook"] = " ".join(out)

    for clip in clips:
        for plan in clip.get("typography_plan") or []:
            new_word = mapping.get(_clean_key(plan.get("word")))
            if new_word:
                plan["word"] = new_word
        if needs_romanization(clip.get("hook_text")):
            clip["hook_text"] = " ".join(
                mapping.get(_clean_key(token), token) for token in clip["hook_text"].split()
            )

    if failed:
        print(
            f"   ⚠️ {failed} caption word(s) could not be transliterated and keep their original "
            "script — the caption font may not display them."
        )
    print(f"   ✅ {changed} caption word(s) now in English letters.")
    return changed
