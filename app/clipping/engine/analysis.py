"""
clipping.engine.analysis — AI clip analysis (Gemini primary, NVIDIA NIM optional).

Both providers share the prompt from ``prompt.py`` and the same response shape;
only the structured-output schema dialect differs.
"""

import json
import re
import time

from .prompt import TARGET_ACCOUNTS, get_analysis_prompt

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


def _generate_json_with_retry(client, model, fallback_model, contents, config):
    """Call Gemini with backoff, then try the fallback model once."""
    last_exc = None
    status_code = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            print(f"[Gemini] Attempt {attempt}/{MAX_ATTEMPTS}...")
            return _call_gemini(client, model, contents, config)
        except Exception as exc:
            last_exc = exc
            status_code = _extract_status_code(exc)
            print(
                f"[Gemini] Attempt {attempt}/{MAX_ATTEMPTS} failed | "
                f"status={status_code} | error={exc}"
            )
            if not _is_retryable(exc) or attempt == MAX_ATTEMPTS:
                break
            wait_seconds = INITIAL_WAIT_SECONDS + (attempt - 1) * WAIT_INCREMENT_SECONDS
            print(f"[Gemini] Retrying in {wait_seconds} seconds...")
            time.sleep(wait_seconds)

    print(f"[Gemini] The primary model ({model}) failed.")

    if not fallback_model:
        raise RuntimeError(
            f"Gemini failed after {MAX_ATTEMPTS} attempts. Last error: {last_exc}"
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

def _nvidia_schema() -> dict:
    """JSON Schema for NVIDIA NIM guided_json (lowercase type names)."""
    obj = lambda props, required: {  # noqa: E731 - compact local builder
        "type": "object",
        "additionalProperties": False,
        "properties": props,
        "required": required,
    }
    num, integer, text = {"type": "number"}, {"type": "integer"}, {"type": "string"}
    account_types = list(TARGET_ACCOUNTS.keys())

    classification = obj(
        {
            "tipe_akun": {"type": "string", "enum": account_types},
            "akun_tujuan": text,
            "confidence": integer,
            "angle_utama": text,
            "alasan": text,
            "kata_kunci_pendukung": {"type": "array", "items": text},
            "bio_akun": text,
            "alternatif_akun": obj(
                {
                    "tipe_akun": {"type": "string", "enum": account_types},
                    "akun_tujuan": text,
                    "alasan": text,
                },
                ["tipe_akun", "akun_tujuan", "alasan"],
            ),
        },
        ["tipe_akun", "akun_tujuan", "confidence", "angle_utama", "alasan",
         "kata_kunci_pendukung", "bio_akun", "alternatif_akun"],
    )

    clip_properties = {
        "rank": integer,
        "viral_score": integer,
        "start_time": num,
        "end_time": num,
        "hook_start_time": num,
        "hook_end_time": num,
        "bgm_mood": {"type": "string", "enum": ["chill", "epic", "sad", "upbeat", "suspense"]},
        "typography_plan": {
            "type": "array",
            "items": obj(
                {
                    "kata_utama": text,
                    "scale_level": {"type": "integer", "enum": [1, 2, 3]},
                    "style": {"type": "string", "enum": ["utama", "khusus"]},
                    "animasi": {"type": "string", "enum": ["bounce_pop", "stagger_up"]},
                },
                ["kata_utama", "scale_level", "style", "animasi"],
            ),
        },
        "broll_list": {
            "type": "array",
            "items": obj(
                {"start_time": num, "end_time": num, "search_query": text},
                ["start_time", "end_time", "search_query"],
            ),
        },
        "recommended_visual_broll_hook": {
            "type": "array",
            "items": obj(
                {"broll_idea": text, "search_keyword": text, "why_it_works": text},
                ["broll_idea", "search_keyword", "why_it_works"],
            ),
        },
        "title_indonesia": text,
        "title_inggris": text,
        "hastag": text,
        "description_hook": text,
        "description_context": text,
        "keyword_tags": {"type": "array", "items": text},
        "tiktok_title_id": text,
        "tiktok_caption_id": text,
        "tiktok_caption": text,
        "alasan": text,
        "klasifikasi_akun": classification,
        "hook_v2": obj(
            {
                "enabled": {"type": "boolean"},
                "items": {
                    "type": "array",
                    "items": obj(
                        {"start_time": num, "end_time": num, "text": text},
                        ["start_time", "end_time", "text"],
                    ),
                },
                "transition": obj(
                    {"type": {"type": "string", "enum": ["white_flash", "glitch"]}},
                    ["type"],
                ),
            },
            ["enabled", "items", "transition"],
        ),
        "keep_segments": {
            "type": "array",
            "items": obj({"start_time": num, "end_time": num}, ["start_time", "end_time"]),
        },
    }

    return {"type": "array", "items": obj(clip_properties, list(clip_properties))}


def _gemini_schema() -> dict:
    """response_schema for the Gemini structured-output API (uppercase type names)."""
    obj = lambda props, required: {  # noqa: E731 - compact local builder
        "type": "OBJECT",
        "properties": props,
        "required": required,
    }
    num, integer, text = {"type": "NUMBER"}, {"type": "INTEGER"}, {"type": "STRING"}

    classification = obj(
        {
            "tipe_akun": text,
            "akun_tujuan": text,
            "confidence": integer,
            "angle_utama": text,
            "alasan": text,
            "kata_kunci_pendukung": {"type": "ARRAY", "items": text},
            "bio_akun": text,
            "alternatif_akun": obj(
                {"tipe_akun": text, "akun_tujuan": text, "alasan": text},
                ["tipe_akun", "akun_tujuan", "alasan"],
            ),
        },
        ["tipe_akun", "akun_tujuan", "confidence", "angle_utama", "alasan",
         "kata_kunci_pendukung", "bio_akun", "alternatif_akun"],
    )

    clip_properties = {
        "rank": integer,
        "viral_score": integer,
        "hook_start_time": num,
        "hook_end_time": num,
        "start_time": num,
        "end_time": num,
        "typography_plan": {
            "type": "ARRAY",
            "items": obj(
                {
                    "kata_utama": text,
                    "scale_level": integer,
                    "style": text,
                    "animasi": text,
                },
                ["kata_utama", "scale_level", "style", "animasi"],
            ),
        },
        "broll_list": {
            "type": "ARRAY",
            "items": obj(
                {"start_time": num, "end_time": num, "search_query": text},
                ["start_time", "end_time", "search_query"],
            ),
        },
        "recommended_visual_broll_hook": {
            "type": "ARRAY",
            "items": obj(
                {"broll_idea": text, "search_keyword": text, "why_it_works": text},
                ["broll_idea", "search_keyword", "why_it_works"],
            ),
        },
        "alasan": text,
        "bgm_mood": text,
        "title_indonesia": text,
        "title_inggris": text,
        "hastag": text,
        "description_hook": text,
        "description_context": text,
        "keyword_tags": {"type": "ARRAY", "items": text},
        "tiktok_title_id": text,
        "tiktok_caption_id": text,
        "tiktok_caption": text,
        "klasifikasi_akun": classification,
        "hook_v2": obj(
            {
                "enabled": {"type": "BOOLEAN"},
                "items": {
                    "type": "ARRAY",
                    "items": obj(
                        {"start_time": num, "end_time": num, "text": text},
                        ["start_time", "end_time", "text"],
                    ),
                },
                "transition": obj({"type": text}, ["type"]),
            },
            ["enabled", "items", "transition"],
        ),
        "keep_segments": {
            "type": "ARRAY",
            "items": obj({"start_time": num, "end_time": num}, ["start_time", "end_time"]),
        },
    }

    return {"type": "ARRAY", "items": obj(clip_properties, list(clip_properties))}


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

    print(f"[3/3] Analysing the top {cfg.jumlah_clip} moments with NVIDIA ({cfg.nvidia_model})...")

    if not cfg.api_key_nvidia:
        raise ValueError("NVIDIA_API_KEY not found in the environment.")

    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=cfg.api_key_nvidia,
    )

    prompt = get_analysis_prompt(transcript, cfg.jumlah_clip, cfg.durasi_hook, cfg=cfg)

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
            "nvext": {"guided_json": _nvidia_schema()},
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

    print(f"[3/3] Analysing the top {cfg.jumlah_clip} moments with Gemini...")

    prompt = get_analysis_prompt(transcript, cfg.jumlah_clip, cfg.durasi_hook, cfg=cfg)

    client = genai.Client(
        api_key=cfg.api_key_gemini,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )

    gemini_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_gemini_schema(),
    )

    return _generate_json_with_retry(
        client=client,
        model=cfg.gemini_model,
        fallback_model=getattr(cfg, "gemini_fallback_model", None),
        contents=prompt,
        config=gemini_config,
    )


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
