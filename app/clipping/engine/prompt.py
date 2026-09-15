"""
clipping.engine.prompt — The clip-selection prompt shared by every AI provider.

The selection rules follow what short-form retention data consistently shows:
viewers decide to stay or swipe within the first 1-2 seconds, most watch with
the sound off, and clips that carry one self-contained idea from a cold-open
hook to a clean payoff are the ones watched to the end.

NOTE ON FIELD NAMES: the JSON keys produced here are the pipeline's data
contract — ``metadata.py``, the response schemas in ``analysis.py`` and the
Studio renderers read them by name, so a rename must be applied in all of them.
"""

import json
import os

from ..channel_learning import build_learning_section

# ==============================================================================
# TARGET ACCOUNT ROUTING
# ==============================================================================
# Loaded from a JSON config so the routing table isn't hardcoded to one brand.
# Override the path with --target-accounts; disable routing with
# --no-account-routing.

DEFAULT_ACCOUNTS_FILE = "target_accounts.json"

DEFAULT_TARGET_ACCOUNTS = {
    "Business": {
        "handle": "@yourbrand.business",
        "angle": "The angle is business, brand, revenue, sales, founders, marketing, or small business operations.",
        "bio": "Business insight, founder stories and brand breakdowns.",
    },
    "Life": {
        "handle": "@yourbrand.life",
        "angle": "The angle is personal life, lifestyle, career, mindset, relationships, personal finance, or self growth.",
        "bio": "Clips to upgrade your life, mindset and career.",
    },
    "Creator": {
        "handle": "@yourbrand.creator",
        "angle": "The angle is digital content, AI, tools, affiliate, content workflow, or monetising an audience.",
        "bio": "Making digital content work: AI, tools and monetisation.",
    },
    "Tech": {
        "handle": "@yourbrand.tech",
        "angle": "The angle is technology, software, engineering, product, science, or how something technical actually works.",
        "bio": "Technology and engineering explained without the fluff.",
    },
}


def load_target_accounts(cfg=None) -> dict:
    """
    Return the account routing table.

    Reads ``--target-accounts`` (or ``target_accounts.json`` in the working
    directory) and falls back to the built-in English defaults when that file
    is absent or unreadable. Returns ``{}`` when routing is switched off.
    """
    if cfg is not None and getattr(cfg, "no_account_routing", False):
        return {}

    path = getattr(cfg, "target_accounts_path", None) or DEFAULT_ACCOUNTS_FILE
    if not os.path.exists(path):
        return dict(DEFAULT_TARGET_ACCOUNTS)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"⚠️ Could not read {path} ({e}); using the built-in account defaults.")
        return dict(DEFAULT_TARGET_ACCOUNTS)

    accounts = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(accounts, dict) or not accounts:
        print(f"⚠️ No 'accounts' object in {path}; using the built-in account defaults.")
        return dict(DEFAULT_TARGET_ACCOUNTS)

    return accounts


# Module-level convenience for callers that just want the default table.
TARGET_ACCOUNTS = DEFAULT_TARGET_ACCOUNTS

# ==============================================================================
# CLIP DURATION BOUNDS (seconds) — defaults for --min-duration / --max-duration
# ==============================================================================

MIN_CLIP_DURATION = 30
MAX_CLIP_DURATION = 80

# The length most clips should land in; only a story whose payoff genuinely
# needs the room should run past it.
SWEET_SPOT_MAX_DURATION = 60


def clip_duration_bounds(cfg=None) -> tuple[float, float]:
    """The (min, max) clip length for this run: --min/--max-duration, else the defaults."""
    low = getattr(cfg, "min_clip_duration", None) if cfg is not None else None
    high = getattr(cfg, "max_clip_duration", None) if cfg is not None else None
    return float(low or MIN_CLIP_DURATION), float(high or MAX_CLIP_DURATION)


def _length_rule(cfg) -> str:
    low, high = clip_duration_bounds(cfg)
    sweet = max(low, min(SWEET_SPOT_MAX_DURATION, high))
    rule = (
        f"- Duration must be {low:g}-{high:g} seconds. Prefer the SHORTEST cut that fully lands the idea"
    )
    if sweet < high:
        rule += (
            f" — most great clips are {low:g}-{sweet:g} seconds.\n"
            f"  Only go past {sweet:g} seconds for a story whose payoff genuinely needs the room."
        )
    else:
        rule += "."
    return rule


def _account_routing_section(accounts: dict) -> str:
    if not accounts:
        return ""

    lines = [
        "",
        "TARGET ACCOUNT CLASSIFICATION (FOR EVERY CLIP):",
        "Choose the target account from the clip's ANGLE, not its surface topic.",
    ]
    for name, data in accounts.items():
        lines.append(f"- {name}: {data.get('angle', '')}")
        lines.append(
            f"  (handle: \"{data.get('handle', '')}\", bio: \"{data.get('bio', '')}\")"
        )
    lines.append(
        "The same topic can belong to different accounts depending on whether it "
        "is framed commercially, personally, or technically."
    )
    return "\n".join(lines)


def _source_section(cfg) -> str:
    """Describe the source video (title, channel, description) when it is known."""
    info = getattr(cfg, "source_info", None) if cfg is not None else None
    if not isinstance(info, dict) or not any(info.get(k) for k in ("title", "channel", "description")):
        return """
SOURCE VIDEO: unknown (no title or channel metadata). Identify the show and speakers only from names
that are clearly said in the transcript; never guess.
"""

    lines = ["", "SOURCE VIDEO (metadata of the long video these clips come from — use it to identify the source):"]
    for label, key in (("Title", "title"), ("Channel", "channel"), ("Upload date", "upload_date")):
        if info.get(key):
            lines.append(f"- {label}: {info[key]}")
    if info.get("categories"):
        lines.append(f"- Categories: {', '.join(map(str, info['categories']))}")
    if info.get("tags"):
        lines.append(f"- Creator's tags: {', '.join(map(str, info['tags']))}")
    if info.get("chapters"):
        lines.append(f"- Chapters: {' | '.join(map(str, info['chapters']))}")
    if info.get("description"):
        description = " ".join(str(info["description"]).split())
        lines.append(f"- Description (truncated): {description}")
    lines.append(
        "Use this to work out the show/podcast/channel name and who the host and guests are. The description "
        "may contain sponsor links and timestamps — ignore those. Only treat a name as confirmed when it appears "
        "here or is clearly said in the transcript."
    )
    return "\n".join(lines) + "\n"


def _language_section(cfg) -> str:
    """Rules for non-English speech: what stays in the transcript's script, what is romanised."""
    lang = getattr(cfg, "transcript_language", None) if cfg is not None else None
    spoken = f'"{lang}" (detected)' if lang else "unknown — work it out from the transcript"

    if cfg is not None and getattr(cfg, "caption_script", "latin") == "native":
        overlay_rule = (
            "on_screen_hook: in the SAME language as the speech, in that language's own script "
            "(English speech -> English)."
        )
    else:
        overlay_rule = (
            "on_screen_hook: if the speech is English, write English. Otherwise write it in the SAME language as the\n"
            "  speech but in English (Latin) letters — transliterate, do NOT translate — the way people casually type that\n"
            '  language online, e.g. Hindi speech -> "Paise bachane ka asli tareeka". Never use a non-Latin script.'
        )

    return f"""
SPOKEN LANGUAGE: {spoken}
- The transcript can be in any language or script (Hindi, Tamil, Arabic, Spanish, ...) or mix languages (e.g. Hinglish).
  Every selection rule applies the same way whatever the language.
- hook_text and typography_plan words: copy them exactly as written in the transcript, in its own script.
  The system writes the on-screen captions itself.
- {overlay_rule}
- All other metadata (title, descriptions, hashtags, keyword_tags, reason) is written in English.
"""


def _hook_section(cfg, hook_duration: int) -> str:
    """
    Hook instructions. They differ with the teaser: when the renderer plays the
    hook *before* the clip, a hook taken from the clip's opening line would
    simply be heard twice in a row.
    """
    common = """- hook_text MUST be copied verbatim from the transcript — never paraphrase, reword or invent it.
- hook_start_time and hook_end_time must sit inside the clip's own start_time and end_time.
- The hook must make people want to keep watching, but must not be fake clickbait."""

    if cfg is not None and getattr(cfg, "hook_teaser", False):
        return f"""
HOOK (FLASH-FORWARD TEASER — REQUIRED):
- The renderer plays the hook as a ~{hook_duration}s teaser BEFORE the clip, then cuts to the clip's start.
- So take the hook from the clip's peak — the most intense, surprising or quotable line — ideally from the
  middle or the payoff, NOT from the first sentence of the clip (that would be heard twice in a row).
- It must be a complete, punchy thought on its own (roughly {hook_duration}-6 seconds of speech) that raises a question the clip answers.
{common}
"""

    return f"""
HOOK (REQUIRED):
- The clip's own opening IS the hook: start_time must land on the single punchiest sentence, so the hook
  normally starts at start_time (within the first ~{hook_duration} seconds at most).
{common}
"""


def _segment_trim_section(cfg) -> str:
    if cfg is None or getattr(cfg, "no_segment_trim", False):
        return ""
    silence_hint = ""
    if getattr(cfg, "silence_trim", False):
        silence_hint = (
            "\n- AGGRESSIVELY cut silence and dead air. Do not include pauses "
            "longer than 0.5 seconds."
        )
    low, _ = clip_duration_bounds(cfg)
    return f"""

SEGMENT-BASED TRIMMING (KEEP SEGMENTS — REQUIRED):
- Every cut inside a clip is a visible jump cut, so only cut what clearly hurts retention: a tangent, a
  false start, a long pause, crosstalk or filler lasting more than ~2 seconds.
- If so, break the clip into "keep_segments" — at most 4 — keeping only the parts that carry the idea.
- Every segment starts and ends on a sentence boundary. Never cut inside a sentence.
- Segments must be in chronological order, must not overlap, and must add up to at least {low:g} seconds.
- If the whole clip is already tight, emit a single segment covering start_time to end_time.{silence_hint}
- Fill the "keep_segments" field as an array of objects (start_time, end_time).
"""


def _json_structure(cfg, accounts: dict) -> str:
    """Build the example JSON, including only the fields actually requested."""
    lines = [
        '    "rank": 1,',
        '    "viral_score": 88,',
        '    "start_time": 312.4,',
        '    "end_time": 361.9,',
        '    "hook_start_time": 312.4,',
        '    "hook_end_time": 316.8,',
        '    "hook_text": "the exact sentence spoken in the hook",',
        '    "on_screen_hook": "Why most startups die in year two",',
        '    "bgm_mood": "chill",',
        '    "typography_plan": [{ "word": "...", "scale_level": 2, "style": "main", "animation": "bounce_pop" }],',
        '    "broll_list": [],',
        '    "recommended_visual_broll_hook": [',
        '      { "broll_idea": "...", "search_keyword": "...", "why_it_works": "..." }',
        '    ],',
    ]

    if not (cfg is None or getattr(cfg, "no_segment_trim", False)):
        lines += [
            '    "keep_segments": [',
            '      { "start_time": 312.4, "end_time": 335.0 },',
            '      { "start_time": 338.1, "end_time": 361.9 }',
            '    ],',
        ]

    lines += [
        '    "title": "...",',
        '    "hashtags": "#ShowName #GuestName #SpecificTopic #RelatedConcept #NicheCommunity #PodcastClips ...",',
        '    "description_hook": "...",',
        '    "description_context": "...",',
        '    "keyword_tags": ["tag1", "tag2"],',
        '    "reason": "..."',
    ]

    if accounts:
        names = list(accounts)
        first = names[0]
        alt = names[1] if len(names) > 1 else first
        lines[-1] += ","
        lines += [
            '    "account_classification": {',
            f'      "account_type": "{first}",',
            f'      "target_account": "{accounts[first].get("handle", "")}",',
            '      "confidence": 87,',
            '      "main_angle": "...",',
            '      "reason": "...",',
            '      "supporting_keywords": ["keyword1", "keyword2"],',
            '      "account_bio": "...",',
            '      "alternative_account": {',
            f'        "account_type": "{alt}",',
            f'        "target_account": "{accounts[alt].get("handle", "")}",',
            '        "reason": "..."',
            '      }',
            '    }',
        ]

    return "[\n  {\n" + "\n".join(lines) + "\n  }\n]"


def get_analysis_prompt(
    transcript: str, clip_count: int, hook_duration: int, cfg=None
) -> str:
    """Build the clip-analysis prompt (shared by the Gemini and NVIDIA providers)."""
    accounts = load_target_accounts(cfg)

    return f"""
You are a senior short-form video editor who has cut thousands of podcast and interview clips into
YouTube Shorts, Reels and TikToks that were watched to the end. You are also the channel's metadata strategist.

Read the transcript below. Transcript format:
[start_second - end_second] text
{_source_section(cfg)}{_language_section(cfg)}
MAIN TASK:
- Find up to {clip_count} moments that will stop the scroll AND be watched to the end as standalone short clips.
- Return them best first (highest viral_score first). "rank" is only a sequence number (1, 2, 3...).
- For every clip, produce the timing, hook, on-screen hook, typography plan, b-roll plan, reasoning and metadata.
- Everything you write must be about the clip itself, not the full episode in general.

HOW SHORT-FORM VIEWERS ACTUALLY BEHAVE (the reason for every rule below):
- They decide to stay or swipe in the first 1-2 seconds. Most of the audience that leaves, leaves before second 3.
- Most of them watch with the sound OFF at first, so the opening must also work as on-screen text.
- They have never seen this episode. They do not know the speakers, the earlier discussion or the context.
- They reward ONE clear idea delivered fast, and they punish setup, rambling and endings that fizzle out.

STEP 1 — BUILD A CANDIDATE POOL (internally, do not output it):
Read the WHOLE transcript first. Internally list about {clip_count * 3} candidate moments, then keep only the best.
A strong candidate usually has one of these shapes:
- Contrarian or bold claim: "Everyone thinks X. It's actually Y."
- Surprising specific number, result or fact that lands against expectation.
- Hard-won lesson or expert authority: "The biggest mistake I made...", "After 20 years of doing this..."
- A story that starts in the middle of the action and has a turn or punchline.
- A confession, vulnerable admission or raw emotional moment.
- Real tension: a disagreement, a pushback, a speaker being challenged.
- A specific, practical framework or how-to that people will save.
- A funny exchange with a clear punchline.

STEP 2 — QUALITY GATE (a candidate must pass EVERY test, otherwise discard it):
1. COLD-OPEN TEST: the first words spoken at start_time are already interesting. The clip must NOT open on
   filler or run-up: "so", "yeah", "um", "and", "but", "like I said", "that's a great question", "you know what",
   a greeting, throat-clearing, or the tail of the previous sentence.
2. STRANGER TEST: someone who never saw the episode fully understands it. No unresolved "he / she / they / that /
   this / it" pointing to something said before start_time. No "as we discussed", no inside references.
3. ONE-IDEA TEST: the clip makes exactly one point. Two points = two clips (or pick the stronger one).
4. PAYOFF TEST: the answer, punchline, twist, lesson or conclusion lands INSIDE the window.
5. ENDING TEST: the last sentence feels final — a punchline, a conclusion, a strong line. It must not trail
   into "yeah", "right", "anyway", laughter that goes nowhere, or the first words of a new topic.
6. DENSITY TEST: no long tangents, dead air, crosstalk or repeated explanations inside the window.

REJECT THESE OUTRIGHT (never return them as clips):
- Intros, outros, sponsor reads, housekeeping, "welcome back to the podcast", calls to subscribe.
- Moments that only make sense with visual context the viewer will not have.
- Answers to a question that is never heard inside the clip, when the answer does not stand alone.
- Long setups where the payoff lands outside the clip window.
- Inside jokes or references that need the rest of the episode to land.

STEP 3 — CUT PRECISELY:
- start_time = the start of the line containing the first strong sentence. If the best material begins in the
  middle of an answer, start there. Include the interviewer's question only when it is short (under ~5 seconds),
  sharp, and the answer needs it.
- end_time = the end of the line containing the payoff. Stop right after it lands.
- A line can hold several sentences. When the strong sentence begins (or the payoff ends) partway through a line,
  estimate that moment inside the line — speech runs at a roughly even pace — rather than taking the whole line.
- The system snaps both cut points to exact word boundaries and adds breathing room — do NOT pad the times yourself,
  and never choose a time that falls in the middle of a sentence.
{_length_rule(cfg)}
- Structure inside the window: hook (0-3s) -> just enough context -> escalation/tension -> payoff.
- Every timestamp must fall inside the range covered by the transcript. Never emit a timestamp past the final line.

CLIP DISTINCTNESS (STRICT — HARD REQUIREMENT):
- Clips MUST NOT overlap in time. No two clips may share any second of the transcript.
- Every clip must make a genuinely different point. Do not return several clips arguing the same thing.
- Spread the clips across the whole transcript instead of clustering them in one section.
- If the transcript genuinely contains fewer than {clip_count} moments that pass the quality gate, return FEWER clips.
  Three excellent clips are far better than {clip_count} mediocre ones. Never pad, stretch or invent a weak moment.

VIRAL_SCORE (1-100) — score honestly from these five components (internal only, DO NOT add fields):
- Hook strength (1-20): would the first 2 seconds, heard or read as text, stop a stranger's thumb?
- Emotional intensity (1-20): conflict, surprise, humour, vulnerability, anger, awe, relatability.
- Shareability (1-20): would people comment, argue, tag a friend, share or save it?
- Standalone clarity (1-20): fully understood with zero context?
- Payoff & ending (1-20): is there a clear reward, and does the clip end the moment it lands?
Calibration: 90+ is rare — a clip you would bet on. 80-89 is strong. 70-79 is decent but ordinary.
Do not give everything 90+. Do not return clips below 70 unless the transcript has almost no good moments.
{build_learning_section(cfg)}{_account_routing_section(accounts)}
{_hook_section(cfg, hook_duration)}
ON-SCREEN HOOK (REQUIRED — for sound-off viewers):
- "on_screen_hook" is a text overlay shown at the top of the screen during the opening seconds.
- 3-7 words, at most 42 characters. It states the promise or tension of the clip so a muted viewer stops scrolling.
- Write it as a sharp headline, not a transcript quote, in the language set by SPOKEN LANGUAGE: e.g. "The mistake that cost me $2M",
  "Why he quit Google after 10 years", "Nobody tells you this about sleep".
- It must be true to the clip. No emojis, no hashtags, no ALL CAPS, no fake promises.

TYPOGRAPHY PLAN (KINETIC TYPOGRAPHY):
- Pick the 3-6 heaviest, most emotional or most emphasis-worthy SINGLE words from each clip.
- Every word MUST actually be spoken inside the clip's time range, spelled exactly as in the transcript.
- For each word, decide:
  1. 'word': that specific word.
  2. 'scale_level': 1 (normal), 2 (large/emphasis) or 3 (giant/crucial — use at most once per clip).
  3. 'style': "main" or "accent".
  4. 'animation': "bounce_pop" or "stagger_up".
- Prefer numbers, strong verbs and loaded nouns ("million", "fired", "never", "quit"). Never filler words.

B-ROLL (ONLY WHEN IT CLEARLY HELPS — EMPTY IS THE DEFAULT):
- B-roll replaces the speaker's face on screen, and the face carries most of the emotion, so use it sparingly.
- Add at most 1-2 inserts, and only when the speaker names something concrete and filmable
  (a place, an object, an activity: "stock market crash", "surgeon operating", "desert road").
- Never during the hook, the payoff, an emotional moment, a joke, or abstract talk (ideas, feelings, opinions).
- Each insert runs 3-5 seconds. search_query is 2-4 plain English words describing literal footage.
- If no moment clearly qualifies, set broll_list to an empty array [].

VISUAL B-ROLL HOOK (REFERENCE ONLY):
- Give 2-5 contrasting, funny, dramatic or curiosity-provoking opening B-roll ideas an editor could source manually.
- Include a search keyword for each. This goes in 'recommended_visual_broll_hook' and is never rendered automatically.

BGM MOOD (BACKGROUND MUSIC):
- The music sits quietly under the voice. Pick ONE mood from this fixed list: [chill, epic, sad, upbeat, suspense].
- Match the emotional tone, not the topic: calm advice or discussion = chill; ambition, triumph or big stakes = epic;
  loss, struggle or regret = sad; light, funny or energetic = upbeat; mystery, danger or a reveal = suspense.

SELECTION REASONING:
- Fill 'reason' with 1-2 sentences: the hook shape, why a stranger stays to the end, and what the payoff is.

METADATA LANGUAGE:
- title, hashtags, description_hook, description_context, keyword_tags and reason must be natural, concise,
  readable English — even when the speech is in another language.
- on_screen_hook, hook_text and typography words follow the SPOKEN LANGUAGE rules above.

METADATA:
1. title
- The single idea of the clip, front-loaded with the most searchable or intriguing words.
- Aim for 40-60 characters (mobile truncates longer titles); hard maximum 100 characters.
- No cheap clickbait, no ALL CAPS, no "!!!" or "???", no emojis, not generic.
- Must complement the on_screen_hook, not repeat it word for word.

2. hashtags
- 10 to 15 hashtags in one string, separated by spaces. NEVER more than 15 (YouTube ignores every hashtag
  on a video that has more than 15).
- Hashtags are for discovery: someone searching for the show, the person or the subject should find this clip.
  Build them in this order (YouTube shows the first three above the title, so the most identifying go first):
  a. SOURCE (2-4): the show / podcast / channel name and the people speaking in this clip (host, guest),
     e.g. #DiaryOfACEO #StevenBartlett #AndrewHuberman. Only confirmed names from the SOURCE VIDEO section
     or clearly said in the transcript — never guess a name. If the source is unknown, skip this group.
  b. SUBJECT (4-6): the specific topics, entities and concepts discussed in THIS clip — companies, products,
     places, events, methods, fields — e.g. #IntermittentFasting #Dopamine #Tesla #VentureCapital.
  c. NICHE / COMMUNITY (2-3): the audience that follows this subject, e.g. #Entrepreneurship #Neuroscience #Biohacking.
  d. FORMAT (1-2): e.g. #PodcastClips #Interview #Shorts.
- Do NOT make hashtags out of the caption's emotion or mood (#shocking #mindblown #sad #inspiring #deep) —
  describe who and what the clip is about, not how it feels.
- Never use #fyp #foryou #viral #trending #explore.
- CamelCase, letters and digits only, no spaces or punctuation, no duplicates.

3. description_hook
- Exactly 1 sentence: short, curiosity-provoking, true to the clip.

4. description_context
- Exactly 1 sentence explaining who is speaking about what (use names only if they are said in the transcript).

5. keyword_tags
- 5 to 8 short keywords people would actually search for (not hashtags). No keyword spam.
- Include the show/channel name and the speakers' names when they are confirmed, then the clip's subject keywords.

METADATA QUALITY RULES:
- Match the clip, never promise anything the clip does not deliver, no fake hyperbole.
- If the speech contains a striking number or phrase, prefer it as title inspiration.
- Title, on-screen hook, descriptions and hashtags complement each other rather than repeating one sentence.

OUTPUT RULES:
- The output MUST be a valid JSON array.
- Do not add any explanation outside the JSON.
- Every field shown in the structure below must be filled (broll_list may be []).
- Do not add fields that are not shown in the structure below.
- When in doubt, prioritise accuracy about the clip over creativity.
{_segment_trim_section(cfg)}

REQUIRED JSON STRUCTURE (follow these field names exactly; the values are only illustrative):
{_json_structure(cfg, accounts)}

Transcript:
{transcript}
"""
