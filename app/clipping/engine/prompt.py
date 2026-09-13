"""
clipping.engine.prompt — The clip-selection prompt shared by every AI provider.

NOTE ON FIELD NAMES: the JSON keys produced here are the pipeline's data
contract — ``metadata.py``, the response schemas in ``analysis.py`` and the
Studio renderers read them by name, so a rename must be applied in all of them.
"""

import json
import os

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
# CLIP DURATION BOUNDS (seconds) — change these to shift the allowed clip length
# ==============================================================================

MIN_CLIP_DURATION = 30
MAX_CLIP_DURATION = 80


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


def _hook_v2_section(cfg) -> str:
    if not (cfg and getattr(cfg, "hook_v2", False)):
        return ""
    items = getattr(cfg, "hook_v2_items", 3)
    style = getattr(cfg, "hook_v2_style", "controversial_fast_glitch")
    return f"""

HOOK V2 (MULTI-HOOK INTRO — REQUIRED):
- In addition to the standard hook, produce a "hook_v2" containing {items} short cuts (0.5-2 seconds) taken from the most striking/controversial/emotional moments inside the clip.
- Style: {style}
- Every item must contain: start_time, end_time, and text (a short 2-5 word on-screen caption).
- Order the items from strongest to weakest.
- The system adds the transitions between items automatically (white flash / glitch).
- Fill the "hook_v2" field as an object with:
  - "enabled": true
  - "items": an array of objects (start_time, end_time, text)
  - "transition": an object with "type" ("white_flash" or "glitch")
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
    return f"""

SEGMENT-BASED TRIMMING (KEEP SEGMENTS — REQUIRED):
- For every clip, check whether parts of the middle are uninteresting, too quiet, rambling or filler.
- If so, break the clip into several "keep_segments" — keep only the best parts.
- Every segment contains: start_time and end_time.
- Segments must be in chronological order and must not overlap.
- If the whole clip is already tight and interesting, emit a single segment covering the full duration.{silence_hint}
- Fill the "keep_segments" field as an array of objects (start_time, end_time).
"""


def _json_structure(cfg, accounts: dict) -> str:
    """Build the example JSON, including only the fields actually requested."""
    lines = [
        '    "rank": 1,',
        '    "viral_score": 95,',
        '    "start_time": 30.5,',
        '    "end_time": 90.0,',
        '    "hook_start_time": 30.5,',
        '    "hook_end_time": 35.0,',
        '    "hook_text": "the exact sentence spoken in the hook",',
        '    "bgm_mood": "chill",',
        '    "typography_plan": [{ "word": "...", "scale_level": 2, "style": "main", "animation": "bounce_pop" }],',
        '    "broll_list": [{ "start_time": 40.0, "end_time": 45.0, "search_query": "..." }],',
        '    "recommended_visual_broll_hook": [',
        '      { "broll_idea": "...", "search_keyword": "...", "why_it_works": "..." }',
        '    ],',
    ]

    if cfg and getattr(cfg, "hook_v2", False):
        lines += [
            '    "hook_v2": {',
            '      "enabled": true,',
            '      "items": [{ "start_time": 31.0, "end_time": 32.5, "text": "KEY PHRASE" }],',
            '      "transition": { "type": "white_flash" }',
            '    },',
        ]

    if not (cfg is None or getattr(cfg, "no_segment_trim", False)):
        lines += [
            '    "keep_segments": [',
            '      { "start_time": 30.5, "end_time": 55.0 },',
            '      { "start_time": 58.0, "end_time": 90.0 }',
            '    ],',
        ]

    lines += [
        '    "title": "...",',
        '    "hashtags": "#tag1 #tag2",',
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
You are an Art Director, Video Editor and short-form content metadata strategist for Reels and YouTube Shorts.

Read the transcript below. Transcript format:
[start_second - end_second] text

MAIN TASK:
- Find the {clip_count} most interesting, strongest, most shareable and most viral-capable moments to turn into short clips.
- Order the clips from the highest viral_score (most likely to go viral) to the lowest. "rank" is only a sequence number (1, 2, 3...).
- For every clip, produce the clip timing, hook, typography plan, b-roll plan, the reason it was picked and the metadata.
- Every output must be highly relevant to the clip itself, not to the full video in general.

CLIP SELECTION & VIRALITY RULES:
- Clip duration must be {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION} seconds.
- Pick parts with emotion, conflict, surprise, insight, a strong opinion, a practical lesson or a clear punchline.
- Judge the viral potential and give a "viral_score" (1-100) representing how viral the clip could go.
  - 90-100: very likely to go viral — strong emotion or conflict, very punchy hook.
  - 80-89: interesting, likely to perform well.
  - 70-79: average, informative but possibly unexciting.
- Favour parts that stay interesting even without the context of the full video.
- Do not pick clips that feel flat, rambling or have no clear payoff.

CLIP DISTINCTNESS (STRICT — HARD REQUIREMENT):
- The clips MUST NOT overlap in time. No two clips may share any second of the transcript.
- Every clip must make a genuinely different point. Do not return several clips arguing the same thing in different words.
- Spread the clips across the whole transcript instead of clustering them in one section.
- If the transcript genuinely contains fewer than {clip_count} strong, distinct moments, return FEWER clips. A short list of strong, distinct clips is far better than a padded one.
- Never invent, pad or stretch a weak moment just to reach {clip_count}.

REJECT THESE OUTRIGHT (never return them as clips):
- Intros, outros, sponsor reads, housekeeping, or "welcome back to the podcast".
- Moments that only make sense with visual context the viewer will not have.
- Answers to a question that is never heard inside the clip itself.
- Long setups where the payoff lands outside the clip window.
- Inside jokes or references that need the rest of the episode to land.

RETENTION & CLIP STRUCTURE RULES:
- Make sure the first 3 seconds are strong: a hook, conflict, curiosity, a sharp statement, emotion or an implicit question.
- The ideal clip has the structure:
  hook -> brief context -> tension/insight -> payoff.
- Do not pick clips that only become interesting after a long run-up.
- If the start of a segment is too slow, move start_time to a stronger sentence.
- Once the payoff is done, do not extend the clip without a reason.
- Favour clips that make the viewer want to:
  1. stop scrolling,
  2. watch to the end,
  3. comment,
  4. share,
  5. save,
  6. or feel "this is so me".

TIMING / CUTTING RULES:
- start_time must begin as close as possible to the first strong moment, not merely at the start of a topic.
- end_time must stop after the payoff, conclusion, punchline or main emotional beat is finished.
- Start and end on sentence boundaries — never mid-word or mid-clause.
- Do not cut too early while a sentence is still hanging.
- Do not keep running long after the core message is finished.
- The clip must still make sense without watching what comes before or after it.
- If two strong moments are very close together and support each other, they may be merged as long as the duration stays within {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION} seconds.
- If two strong moments have different angles, split them into separate clip candidates.
- Every timestamp must fall inside the range covered by the transcript. Never emit a timestamp past the final line.

INTERNAL VIRAL_SCORE BREAKDOWN:
Score viral_score 1-100 from the components below. This is for internal scoring only — DO NOT add new fields to the JSON.
- Hook strength: 1-20
- Emotional intensity: 1-20
- Shareability / comment potential: 1-20
- Standalone clarity: 1-20
- Payoff / retention: 1-20

Scoring guidance:
- Hook strength: how strongly the first 3 seconds stop the scroll.
- Emotional intensity: how strong the emotion, conflict, frustration, humour, tenderness, anger, awe or relatability is.
- Shareability / comment potential: how likely people are to comment, debate, tag a friend, share or save.
- Standalone clarity: how easily the clip is understood without the full video.
- Payoff / retention: how clear the reward for watching to the end is — punchline, insight, twist, conclusion or practical lesson.
- Be honest and calibrated. Do not give everything 90+. If a clip is merely decent, score it in the 70s.
- Do not return clips scoring below 70 unless the transcript has very few good moments.
{_account_routing_section(accounts)}

HOOK (REQUIRED):
- Take the single punchiest sentence that EXISTS INSIDE the clip.
- The hook must feel strong and grab attention within the first ~{hook_duration} seconds.
- Store its timing as hook_start_time and hook_end_time, and its exact wording as hook_text.
- hook_text MUST be copied verbatim from the transcript — never paraphrase, reword or invent it.
- hook_start_time and hook_end_time must sit inside the clip's own start_time and end_time.
- The hook must make people want to keep watching, but must not be fake clickbait.
- If the best hook is not right at the start of the candidate clip, adjust start_time so the hook appears as early as possible.

TYPOGRAPHY PLAN (KINETIC TYPOGRAPHY):
- Pick the 3-6 heaviest, most emotional or most emphasis-worthy SINGLE words from each clip.
- Every word MUST actually be spoken inside the clip's time range.
- For each word, decide:
  1. 'word': that specific word, spelled exactly as in the transcript.
  2. 'scale_level': 1, 2 or 3.
     - 1 = normal/small
     - 2 = large/emphasis
     - 3 = giant/crucial
  3. 'style': "main" or "accent".
  4. 'animation': "bounce_pop" or "stagger_up".
- Do not pick long phrases. Single words only.
- Prioritise the words that are strongest emotionally, in meaning or in visual retention.

B-ROLL (REQUIRED WHERE RELEVANT):
- Find at most 1-3 moments in the clip that suit a B-roll / stock footage insert.
- Each B-roll runs 3-7 seconds.
- Provide:
  - start_time
  - end_time
  - search_query
- search_query must be short, clear and in English.
- Do not place B-roll at the same seconds as the hook.
- Only add B-roll when it genuinely helps visualise what is being said.
- If no moment fits, set broll_list to an empty array [].

VISUAL B-ROLL HOOK (FIRST 0-3 SECONDS):
- Give 2-5 opening B-roll ideas that are contrasting, funny, dramatic or curiosity-provoking, to play before the original video starts.
- Include a search keyword for the editor.
- This goes in the 'recommended_visual_broll_hook' object and is only a reference if the editor wants to source footage manually for the first 3 seconds.

BGM MOOD (BACKGROUND MUSIC):
- Analyse the clip's emotion and topic.
- Pick ONE background-music mood that fits best from this fixed list: [chill, epic, sad, upbeat, suspense].
- Make sure the mood matches the story. (For example: a hard-struggle story = sad/epic, a funny/relaxed story = chill/upbeat.)

SLOW CLOSING:
- end_time MUST be padded by +0.10 to +0.85 seconds after the last word so the ending breathes instead of being cut off abruptly.

SELECTION REASONING:
- Fill the 'reason' field with a short explanation of why this clip is worth picking.
- Explain the clip's main viral trigger, why people are likely to watch to the end, and why it stays interesting without the full video.

METADATA LANGUAGE:
- ALL metadata must be in natural, concise, readable English.
- Never output any other language in any field.
- Avoid stiff literal translations and generic filler phrasing.

METADATA:
Produce the following metadata for every clip:

1. title
- Natural, strong, sharp, readable English.
- At most 100 characters.
- Focus on one main idea, relevant to the clip and not to the full video.
- No cheap clickbait, no ALL CAPS, no excessive punctuation such as !!! ???
- Do not be generic.

2. hashtags
- Exactly 2 to 3 hashtags in a single string, separated by spaces.
- Directly relevant to the clip's topic, no duplicates.
- Avoid overly generic tags such as #fyp #viral #trending unless genuinely relevant.
- Format: #mindset #career #productivity

3. description_hook
- Exactly 1 sentence.
- The opening sentence of the description: short, strong and curiosity-provoking.
- No fake clickbait.

4. description_context
- Exactly 1 sentence.
- Briefly explains the clip's main context and matches what is discussed in the clip.

5. keyword_tags
- 5 to 8 short keywords (not hashtags), relevant to the clip.
- Favour keywords people would actually search for. Avoid keyword spam.
- Mainly used for YouTube metadata.

METADATA QUALITY RULES:
- All metadata must match the clip, not the long video in general.
- Do not promise anything the clip does not discuss.
- Do not use fake hyperbole such as "100% guaranteed" unless it is explicitly stated in the clip.
- If there is a number, a strong phrase or a sharp statement in the original speech, prioritise it as title inspiration.
- Title, descriptions and hashtags must complement each other rather than repeat the same sentence.

OUTPUT RULES:
- The output MUST be a valid JSON array.
- Do not add any explanation outside the JSON.
- Every field shown in the structure below must be filled.
- Do not add fields that are not shown in the structure below.
- When in doubt, prioritise accuracy about the clip over excessive creativity.
{_hook_v2_section(cfg)}{_segment_trim_section(cfg)}

REQUIRED JSON STRUCTURE (follow these field names exactly):
{_json_structure(cfg, accounts)}

Transcript:
{transcript}
"""
