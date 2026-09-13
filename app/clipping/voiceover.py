"""
clipping.voiceover — AI commentary script generation + TTS.

Generates a commentary script with Gemini and renders it to speech with
edge-tts, returning word-level timings for subtitle rendering.
"""

import asyncio
import os

from google import genai
from google.genai import types

try:
    import edge_tts
except ImportError:
    edge_tts = None


# ==============================================================================
# AVAILABLE EDGE-TTS VOICES (REFERENCE)
# ==============================================================================
# Reference list of edge-tts voices. Pass the value (voice name string) as the
# `voice` argument of synthesize_voice(). Run `edge-tts --list-voices` for the
# full list. See https://github.com/rany2/edge-tts
#
# Edge-TTS ships only two Indonesian voices (Ardi & Gadis); the Malay (ms-MY)
# and regional Indonesian voices are listed as close alternatives.

AVAILABLE_VOICES = {
    "id": {
        "male": [
            "id-ID-ArdiNeural",         # primary Indonesian male
            "ms-MY-OsmanNeural",        # Malay male (close to Indonesian)
            "jv-ID-DimasNeural",        # Javanese male
        ],
        "female": [
            "id-ID-GadisNeural",        # primary Indonesian female
            "jv-ID-SitiNeural",         # Javanese female
            "su-ID-TutiNeural",         # Sundanese female
            "ms-MY-YasminNeural",       # Malay female (close to Indonesian)
        ],
    },
    "en": {
        "male": [
            "en-US-GuyNeural",          # US English male (natural)
            "en-US-ChristopherNeural",  # US English male (formal)
            "en-US-EricNeural",         # US English male (warm)
            "en-GB-RyanNeural",         # British English male
            "en-AU-WilliamNeural",      # Australian English male
        ],
        "female": [
            "en-US-JennyNeural",        # US English female (natural)
            "en-US-AriaNeural",         # US English female (expressive)
            "en-US-MichelleNeural",     # US English female (warm)
            "en-GB-SoniaNeural",        # British English female
            "en-AU-NatashaNeural",      # Australian English female
        ],
    },
}


# ==============================================================================
# TTS SYNTHESIS (EDGE-TTS)
# ==============================================================================

async def _synthesize_async(
    text: str, voice: str, output_audio_path: str, output_subs_path: str | None = None
) -> list[dict]:
    """Async core of the TTS step; returns word-level segments."""
    if edge_tts is None:
        raise ImportError("edge-tts is not installed. Run: pip install edge-tts")

    communicate = edge_tts.Communicate(text, voice)
    submaker = edge_tts.SubMaker()

    with open(output_audio_path, "wb") as file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.feed(chunk)

    if not output_subs_path:
        return []

    # Save the SRT for reference (edge-tts v7+ exposes get_srt, not generate_subs).
    with open(output_subs_path, "w", encoding="utf-8") as file:
        file.write(submaker.get_srt())

    # Read timings straight off submaker.cues rather than re-parsing the file.
    segments = []
    for cue in submaker.cues:
        start_s = cue.start.total_seconds()
        end_s = cue.end.total_seconds()
        segments.append({
            "start": start_s,
            "end": end_s,
            "text": cue.content,
            "words": [{
                "word": cue.content,
                "start": start_s,
                "end": end_s,
                "probability": 1.0,
            }],
        })
    return segments


def _consolidate_segments(raw_segments: list[dict], words_per_seg: int = 3) -> list[dict]:
    """Group word-level segments into small chunks for readable subtitles."""
    consolidated: list[dict] = []
    words: list[dict] = []

    for i, seg in enumerate(raw_segments):
        if not seg["words"]:
            continue
        words.append(seg["words"][0])

        if len(words) >= words_per_seg or i == len(raw_segments) - 1:
            consolidated.append({
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "text": " ".join(w["word"] for w in words),
                "words": words,
            })
            words = []

    if words:
        consolidated.append({
            "start": words[0]["start"],
            "end": words[-1]["end"],
            "text": " ".join(w["word"] for w in words),
            "words": words,
        })

    return consolidated


def synthesize_voice(
    text: str, voice: str, output_dir: str, clip_id: str
) -> tuple[str, list[dict]]:
    """
    Synthesise *text* to speech with edge-tts.

    Returns
    -------
    tuple[str, list[dict]]
        (path to the MP3, subtitle segments grouped three words at a time)
    """
    os.makedirs(output_dir, exist_ok=True)
    audio_path = os.path.join(output_dir, f"vo_clip_{clip_id}.mp3")
    subs_path = os.path.join(output_dir, f"vo_clip_{clip_id}.vtt")

    print(f"   🎙️ Synthesizing voice-over ({voice}) for clip {clip_id}...")
    segments = asyncio.run(_synthesize_async(text, voice, audio_path, subs_path))

    return audio_path, _consolidate_segments(segments, words_per_seg=3)


# ==============================================================================
# AI COMMENTARY SCRIPT GENERATION
# ==============================================================================

_LANG_INSTRUCTIONS = {
    "id": (
        "Write the script in Indonesian — casual but professional, like an "
        "Indonesian YouTube/TikTok narrator."
    ),
    "en": "Use engaging, conversational English suitable for a YouTube/TikTok narrator.",
}

_STYLE_INSTRUCTIONS = {
    "analysis": "Give a sharp analysis or insightful opinion on why this moment matters or is interesting.",
    "reaction": "React naturally, as if you were watching this moment and found it impressive or surprising.",
    "lesson": "Draw out one lesson or takeaway the audience can apply from this moment.",
    "summary": "Give a brief but compelling context or summary of what happens in this moment.",
}

_LENGTH_INSTRUCTIONS = {
    "short": "very short (1-2 sentences, roughly 5-15 seconds when spoken)",
    "normal": "short (3-5 sentences, roughly 20-40 seconds when spoken)",
    "long": "medium length (5-7 sentences, roughly 40-60 seconds when spoken)",
}


def get_commentary_prompt(
    transcript_snippet: str, style: str, language: str, length: str
) -> str:
    """Build the voice-over commentary prompt."""
    lang_instruction = _LANG_INSTRUCTIONS.get(language, _LANG_INSTRUCTIONS["id"])
    style_instruction = _STYLE_INSTRUCTIONS.get(style, _STYLE_INSTRUCTIONS["analysis"])
    length_instruction = _LENGTH_INSTRUCTIONS.get(length, _LENGTH_INSTRUCTIONS["normal"])

    return f"""You are a narrator/commentator for short-form video (Shorts/TikTok/Reels).
Your job is to write a {length_instruction} voice-over script based on the
video transcript below.

{lang_instruction}
{style_instruction}

RULES:
1. Do NOT merely repeat the transcript. Add your own value, opinion or context.
2. Do NOT use an opening greeting ("Hey guys") or a sign-off ("don't forget to
   subscribe"). Go straight to the substance of the moment.
3. Do NOT add formatting or extra explanation. OUTPUT ONLY THE SCRIPT TEXT THAT
   WILL BE READ ALOUD.

CLIP TRANSCRIPT:
\"\"\"
{transcript_snippet}
\"\"\"

VOICE-OVER SCRIPT (spoken text only, no surrounding quotation marks):"""


def generate_commentary_script(
    transcript_snippet: str, cfg, style="analysis", language="id", length="short"
) -> str:
    """Generate a commentary script with Gemini; returns "" if every attempt fails."""
    print(f"   🧠 Generating {style} commentary script via Gemini ({language}, {length})...")

    if not cfg.api_key_gemini:
        raise ValueError("GOOGLE_API_KEY not found in the environment or config.")

    client = genai.Client(api_key=cfg.api_key_gemini)
    prompt = get_commentary_prompt(transcript_snippet, style, language, length)
    gemini_config = types.GenerateContentConfig(temperature=0.7, top_p=0.9)

    models = [
        getattr(cfg, "gemini_model", "gemini-3-flash-preview"),
        getattr(cfg, "gemini_fallback_model", "gemini-2.5-flash"),
    ]

    for attempt, model in enumerate(models):
        if not model:
            continue
        try:
            response = client.models.generate_content(
                model=model, contents=prompt, config=gemini_config
            )
            if response.text:
                script = response.text.strip().strip('"').strip()
                suffix = " via fallback" if attempt else ""
                print(f"   ✅ Script generated{suffix} ({len(script)} chars)")
                return script
        except Exception as e:
            if attempt < len(models) - 1:
                print(f"   ⚠️ Gemini model '{model}' failed: {e}. Trying the fallback...")
            else:
                print(f"   ❌ Gemini fallback failed: {e}")

    return ""
