"""
clipping.engine.analysis — AI clip analysis (Gemini primary, NVIDIA NIM optional).

Both providers share the prompt from ``prompt.py`` and the same response shape;
only the structured-output schema dialect differs.
"""

import json
import re
import time

from ..bgm_moods import BGM_MOODS
from .prompt import get_analysis_prompt, load_target_accounts

# ==============================================================================
# RETRY CONFIG
# ==============================================================================

MAX_ATTEMPTS = 10
INITIAL_WAIT_SECONDS = 60
WAIT_INCREMENT_SECONDS = 30
REQUEST_TIMEOUT_MS = 15 * 60 * 1000  # 15 minutes
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

_RETRYABLE_KEYWORDS = (
    "timeout", "temporarily unavailable", "deadline",
    "connection reset", "connection aborted", "service unavailable",
)


def _extract_status_code(exc: Exception):
    for attr in ("status_code", "code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)

    match = re.search(r"\b(408|429|500|502|503|504)\b", str(exc))
    return int(match.group(1)) if match else None


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, json.JSONDecodeError):
        return True
    # An empty response.text is usually transient (overload, cut-off stream);
    # it used to skip every retry and go straight to the weaker fallback model.
    if isinstance(exc, ValueError) and "empty response" in str(exc):
        return True
    if _extract_status_code(exc) in RETRYABLE_STATUS_CODES:
        return True
    msg = str(exc).lower()
    return any(k in msg for k in _RETRYABLE_KEYWORDS)


def _call_gemini(client, model, contents, config):
    """One Gemini call; raises on an empty response or invalid JSON."""
    response = client.models.generate_content(model=model, contents=contents, config=config)
    text = getattr(response, "text", None)
    if not text or not text.strip():
        raise ValueError(f"Gemini model '{model}' returned an empty response.text.")
    return json.loads(text)


def _generate_json_with_retry(client, model, fallback_model, contents, config, max_attempts=None):
    """Call Gemini with backoff, then try the fallback model once."""
    max_attempts = max_attempts or MAX_ATTEMPTS
    last_exc = None
    status_code = None

    for attempt in range(1, max_attempts + 1):
        try:
            print(f"[Gemini] Attempt {attempt}/{max_attempts}...")
            return _call_gemini(client, model, contents, config)
        except Exception as exc:
            last_exc = exc
            status_code = _extract_status_code(exc)
            print(
                f"[Gemini] Attempt {attempt}/{max_attempts} failed | "
                f"status={status_code} | error={exc}"
            )
            if not _is_retryable(exc) or attempt == max_attempts:
                break
            wait_seconds = INITIAL_WAIT_SECONDS + (attempt - 1) * WAIT_INCREMENT_SECONDS
            print(f"[Gemini] Retrying in {wait_seconds} seconds...")
            time.sleep(wait_seconds)

    print(f"[Gemini] The primary model ({model}) failed.")

    if not fallback_model:
        raise RuntimeError(
            f"Gemini failed after {max_attempts} attempts. Last error: {last_exc}"
        ) from last_exc

    print(f"[Gemini] Trying once more with the fallback model ({fallback_model})...")
    try:
        return _call_gemini(client, fallback_model, contents, config)
    except Exception as exc_fallback:
        print(f"[Gemini] Fallback model failed | error={exc_fallback}")
        raise RuntimeError(
            f"Both the primary and fallback Gemini calls failed. "
            f"Primary: status={status_code}, error={last_exc} | "
            f"Fallback: error={exc_fallback}"
        ) from exc_fallback


# ==============================================================================
# RESPONSE SCHEMAS
# ==============================================================================

def _build_clip_schema(cfg, *, uppercase: bool) -> dict:
    """
    Build the structured-output schema for one clip list.

    Gemini wants uppercase type names ("STRING"), NVIDIA NIM wants lowercase
    ("string"); everything else is identical, so both providers share this
    builder to stop the two schemas drifting apart.
    """
    def t(name):
        return {"type": name.upper() if uppercase else name.lower()}

    num, integer, text, boolean = t("number"), t("integer"), t("string"), t("boolean")

    def obj(props, required):
        schema = {
            "type": "OBJECT" if uppercase else "object",
            "properties": props,
            "required": required,
        }
        if not uppercase:
            schema["additionalProperties"] = False
        return schema

    def array(items):
        return {"type": "ARRAY" if uppercase else "array", "items": items}

    def enum(values):
        # Gemini's schema dialect is stricter about enum, so only NVIDIA gets it.
        return dict(text, enum=values) if not uppercase else text

    clip_properties = {
        "rank": integer,
        "viral_score": integer,
        "start_time": num,
        "end_time": num,
        "hook_start_time": num,
        "hook_end_time": num,
        "hook_text": text,
        "on_screen_hook": text,
        "bgm_mood": enum(BGM_MOODS),
        "typography_plan": array(
            obj(
                {
                    "word": text,
                    "scale_level": integer,
                    "style": enum(["main", "accent"]),
                    "animation": enum(["bounce_pop", "stagger_up"]),
                },
                ["word", "scale_level", "style", "animation"],
            )
        ),
        "broll_list": array(
            obj(
                {"start_time": num, "end_time": num, "search_query": text},
                ["start_time", "end_time", "search_query"],
            )
        ),
        "recommended_visual_broll_hook": array(
            obj(
                {"broll_idea": text, "search_keyword": text, "why_it_works": text},
                ["broll_idea", "search_keyword", "why_it_works"],
            )
        ),
        "title": text,
        "hashtags": text,
        "description_hook": text,
        "description_context": text,
        "keyword_tags": array(text),
        "reason": text,
    }

    # Only ask for the optional blocks when the prompt actually requested them —
    # requiring them unconditionally wastes tokens and degrades clip quality.
    if not (cfg is None or getattr(cfg, "no_segment_trim", False)):
        clip_properties["keep_segments"] = array(
            obj({"start_time": num, "end_time": num}, ["start_time", "end_time"])
        )

    accounts = load_target_accounts(cfg)
    if accounts:
        account_types = list(accounts)
        clip_properties["account_classification"] = obj(
            {
                "account_type": enum(account_types),
                "target_account": text,
                "confidence": integer,
                "main_angle": text,
                "reason": text,
                "supporting_keywords": array(text),
                "account_bio": text,
                "alternative_account": obj(
                    {
                        "account_type": enum(account_types),
                        "target_account": text,
                        "reason": text,
                    },
                    ["account_type", "target_account", "reason"],
                ),
            },
            [
                "account_type", "target_account", "confidence", "main_angle",
                "reason", "supporting_keywords", "account_bio",
                "alternative_account",
            ],
        )

    return {
        "type": "ARRAY" if uppercase else "array",
        "items": obj(clip_properties, list(clip_properties)),
    }



# ==============================================================================
# PROVIDERS
# ==============================================================================

def _unwrap_clip_list(parsed, provider: str) -> list[dict]:
    """Accept a bare array, or a dict wrapping the array under a known key."""
    if isinstance(parsed, dict):
        for key in ("clips", "data", "highlights"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
        return [parsed]
    if isinstance(parsed, list):
        return parsed
    raise ValueError(f"Provider {provider} returned a non-list/dict format: {type(parsed)}")


def analyze_with_nvidia(transcript: str, cfg) -> list[dict]:
    """Analyse the transcript with the NVIDIA NIM API (OpenAI-compatible)."""
    from openai import OpenAI

    print(f"[3/3] Analysing the top {cfg.clip_count} moments with NVIDIA ({cfg.nvidia_model})...")

    if not cfg.api_key_nvidia:
        raise ValueError("NVIDIA_API_KEY not found in the environment.")

    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=cfg.api_key_nvidia,
    )

    prompt = get_analysis_prompt(transcript, cfg.clip_count, cfg.hook_duration, cfg=cfg)

    completion = client.chat.completions.create(
        model=cfg.nvidia_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a professional video editor and strategist. Return JSON "
                    "only. Follow the provided JSON schema exactly."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
        top_p=1,
        max_tokens=16384,
        extra_body={
            "chat_template_kwargs": {"thinking": False},
            "nvext": {"guided_json": _build_clip_schema(cfg, uppercase=False)},
        },
    )

    content = completion.choices[0].message.content
    if "```" in content:
        content = re.sub(r"```(json)?", "", content).strip()
        content = content.split("```")[0].strip()

    return _unwrap_clip_list(json.loads(content), "NVIDIA")


def analyze_with_gemini(transcript: str, cfg) -> list[dict]:
    """Analyse the transcript with Gemini."""
    import google.genai as genai
    from google.genai import types

    print(f"[3/3] Analysing the top {cfg.clip_count} moments with Gemini...")

    prompt = get_analysis_prompt(transcript, cfg.clip_count, cfg.hook_duration, cfg=cfg)

    client = genai.Client(
        api_key=cfg.api_key_gemini,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )

    gemini_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_build_clip_schema(cfg, uppercase=True),
    )

    parsed = _generate_json_with_retry(
        client=client,
        model=cfg.gemini_model,
        fallback_model=getattr(cfg, "gemini_fallback_model", None),
        contents=prompt,
        config=gemini_config,
    )
    return _unwrap_clip_list(parsed, "Gemini")


MERGE_WINDOW_SECONDS = 600
MERGE_PARALLEL_CALLS = 3
_TRANSCRIPT_LINE = re.compile(r"^\s*\[\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*\]")


def _split_transcript_windows(transcript: str, window: float) -> dict[int, list[str]]:
    """Bucket '[start - end] text' lines by which *window*-second slice they start in."""
    buckets: dict[int, list[str]] = {}
    for line in transcript.splitlines():
        match = _TRANSCRIPT_LINE.match(line)
        if match:
            buckets.setdefault(int(float(match.group(1)) // window), []).append(line.strip())
    return buckets


def _merge_window(client, cfg, types, whisper_lines: list[str], youtube_lines: list[str]) -> str | None:
    """Merge one time window; None when the reply is unusable."""
    prompt = (
        "You are given two independent transcripts of the SAME stretch of a video, each "
        "with [start - end] timestamps in seconds. One is from an ASR model (Whisper), the "
        "other is YouTube's own captions. They can disagree on wording, have different line "
        "breaks, or one can be missing lines the other has.\n\n"
        "Produce ONE merged transcript that is the most accurate reading of what is actually "
        "said/sung, keeping the same '[start - end] text' line format and the Whisper "
        "timestamps as the timing backbone (do not invent new timestamps). Prefer whichever "
        "source's wording is clearer or more complete for each line; if a line appears in "
        "only one source, keep it. Output ONLY the transcript lines — no commentary, no "
        "headings, no code fences.\n\n"
        "=== WHISPER TRANSCRIPT ===\n" + "\n".join(whisper_lines) + "\n\n"
        "=== YOUTUBE CAPTIONS ===\n" + "\n".join(youtube_lines) + "\n"
    )
    config = types.GenerateContentConfig(temperature=0.2, max_output_tokens=32768)

    for model in dict.fromkeys(filter(None, (cfg.gemini_model, getattr(cfg, "gemini_fallback_model", None)))):
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=config)
            finish = str(getattr((response.candidates or [None])[0], "finish_reason", "") or "")
            lines = [l.strip() for l in (response.text or "").splitlines() if _TRANSCRIPT_LINE.match(l)]
            # A reply cut off by the token limit, or one that silently dropped most
            # lines, is worse than Whisper's own text for this window.
            if "MAX_TOKENS" in finish or len(lines) < 0.6 * len(whisper_lines):
                print(f"   ⚠️ Merge window from {model} was incomplete ({len(lines)}/{len(whisper_lines)} lines).")
                continue
            return "\n".join(lines)
        except Exception as e:
            print(f"   ⚠️ Merge window failed on {model}: {e}")
    return None


def merge_transcripts_with_ai(whisper_transcript: str, youtube_transcript: str, cfg) -> str:
    """
    Ask Gemini to reconcile the Whisper transcript with YouTube's own captions
    into one clean, more accurate transcript.

    Whisper sometimes mishears lyrics/jargon; YouTube's captions (creator-
    uploaded or auto-generated) sometimes miss lines VAD or ASR dropped, or use
    different line breaks. Merging plays each source's strengths against the
    other's timestamps rather than trusting either one alone. Word-level
    timing used for rendering still comes from Whisper's own segments — this
    only improves the text Gemini reasons over when picking clips.

    The merge runs in fixed time windows: a long video's full transcript is
    bigger than one reply can hold, and a single JSON reply cut off mid-string
    used to fail the whole merge. Each window that fails keeps Whisper's text.
    """
    from concurrent.futures import ThreadPoolExecutor

    import google.genai as genai
    from google.genai import types

    whisper_windows = _split_transcript_windows(whisper_transcript, MERGE_WINDOW_SECONDS)
    youtube_windows = _split_transcript_windows(youtube_transcript, MERGE_WINDOW_SECONDS)
    if not whisper_windows:
        return whisper_transcript

    keys = sorted(whisper_windows)
    print(f"[3/4] Merging the Whisper transcript with YouTube's captions ({len(keys)} window(s))...")

    client = genai.Client(
        api_key=cfg.api_key_gemini,
        http_options=types.HttpOptions(
            timeout=5 * 60 * 1000,
            retry_options=types.HttpRetryOptions(attempts=3),
        ),
    )

    def merge_key(key):
        youtube_lines = youtube_windows.get(key)
        if not youtube_lines:
            return whisper_windows[key], False
        merged = _merge_window(client, cfg, types, whisper_windows[key], youtube_lines)
        return (merged.splitlines(), True) if merged else (whisper_windows[key], False)

    try:
        with ThreadPoolExecutor(max_workers=MERGE_PARALLEL_CALLS) as pool:
            results = list(pool.map(merge_key, keys))
    except Exception as e:
        # Merging only sharpens the text the clip picker reads; never fail the job over it.
        print(f"⚠️ Transcript merge failed ({e}); falling back to the Whisper transcript alone.")
        return whisper_transcript

    merged_count = sum(1 for _, ok in results if ok)
    print(f"✅ Merged {merged_count}/{len(keys)} window(s); the rest keep Whisper's text.")
    return "\n".join(line for lines, _ in results for line in lines) + "\n"


def analyze_with_ai(transcript: str, cfg) -> list[dict]:
    """Dispatch to the configured AI provider, falling back to Gemini."""
    if getattr(cfg, "ai_provider", "gemini") == "nvidia":
        if not cfg.api_key_nvidia:
            print("⚠️ NVIDIA_API_KEY not found! Falling back to Gemini...")
        else:
            try:
                return analyze_with_nvidia(transcript, cfg)
            except Exception as e:
                print(f"⚠️ The NVIDIA API failed: {e}. Falling back to Gemini...")

    return analyze_with_gemini(transcript, cfg)
