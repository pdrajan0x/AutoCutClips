"""
clipping.engine.prompt — The clip-selection prompt shared by every AI provider.

NOTE ON FIELD NAMES: the JSON keys below (``kata_utama``, ``alasan``,
``title_indonesia``, ``klasifikasi_akun``, ...) are the pipeline's data
contract — ``metadata.py`` and the Studio renderers read them by name, so they
must stay exactly as they are. Only the instruction text is English.
"""

# ==============================================================================
# TARGET ACCOUNT ROUTING
# ==============================================================================

TARGET_ACCOUNTS = {
    "Business": {
        "akun_tujuan": "Business.Mereska",
        "angle_desc": "When the angle is business, brand, revenue, sales, founders, marketing or small business.",
        "bio": "Insight bisnis, founder story & brand lokal. Business | Founder | Finance | Beauty | Marketing",
    },
    "Life": {
        "akun_tujuan": "Life.Mereska",
        "angle_desc": "When the angle is personal life, lifestyle, skincare, career, mindset, relationships, personal finance or self growth.",
        "bio": "Klip insight buat upgrade hidup & mindset. Podcast | Career | Finance | Beauty | Self Growth",
    },
    "Creator": {
        "akun_tujuan": "Creator.Mereska",
        "angle_desc": "When the angle is digital content, AI, affiliate, tools, clipping, monetisation or making money from content.",
        "bio": "Ngulik konten digital biar bisa jadi uang. AI | Affiliate | Clips | Tools | Monetize",
    },
    "Muslim": {
        "akun_tujuan": "Muslim.Mereska",
        "angle_desc": "When the angle is religion, provision (rezeki), prayer, worship, working for God's sake, Islamic family life or business with Islamic values.",
        "bio": "Reminder kerja, rezeki & hidup bernilai Islam. Islamic | Rezeki | Family | Work | Business",
    },
}

# ==============================================================================
# CLIP DURATION BOUNDS (seconds) — change these to shift the allowed clip length
# ==============================================================================

MIN_CLIP_DURATION = 20
MAX_CLIP_DURATION = 179


def _account_classification_section() -> str:
    lines = []
    for account_type, data in TARGET_ACCOUNTS.items():
        lines.append(f"- {account_type}: {data['angle_desc']}")
        lines.append(
            f"  (akun_tujuan: \"{data['akun_tujuan']}\", bio: \"{data['bio']}\")"
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


def get_analysis_prompt(
    transcript: str, jumlah_clip: int, durasi_hook: int, cfg=None
) -> str:
    """Build the clip-analysis prompt (shared by the Gemini and NVIDIA providers)."""
    return f"""
You are an Art Director, Video Editor and short-form content metadata strategist for TikTok, Reels and YouTube Shorts.

Read the transcript below. Transcript format:
[start_second - end_second] text

MAIN TASK:
- Find the {jumlah_clip} most interesting, strongest, most shareable and most viral-capable moments to turn into short clips.
- Order the clips from the highest viral_score (most likely to go viral) to the lowest. "rank" is only a sequence number (1, 2, 3...).
- For every clip, produce the clip timing, hook, typography plan, b-roll plan, the reason it was picked, cross-platform metadata and the target-account classification.
- Every output must be highly relevant to the clip itself, not to the full video in general.

CLIP SELECTION & VIRALITY RULES:
- Clip duration must be {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION} seconds.
- Pick parts with emotion, conflict, surprise, insight, a strong opinion, a practical lesson or a clear punchline.
- Judge the viral potential and give a "viral_score" (1-100) representing how viral the clip could go.
  - 90-100: very likely to hit the FYP / go viral, strong emotion or conflict, very punchy hook.
  - 80-89: interesting, likely to perform well.
  - 70-79: average, informative but possibly unexciting.
- Favour parts that stay interesting even without the context of the full video.
- Avoid clips that are too similar to each other.
- Do not pick clips that feel flat, rambling or have no clear payoff.

RETENTION & CLIP STRUCTURE RULES:
- Make sure the first 3 seconds are strong: a hook, conflict, curiosity, a sharp statement, emotion or an implicit question.
- The ideal clip has the structure:
  hook -> brief context -> tension/insight -> payoff.
- Do not pick clips that only become interesting after a long run-up.
- If the start of a segment is too slow, move start_time to a stronger sentence.
- Once the payoff is done, do not extend the clip without a reason.
- Do not include intros, small talk, long pauses or transitions that add nothing.
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
- Do not cut too early while a sentence is still hanging.
- Do not keep running long after the core message is finished.
- The clip must still make sense without watching what comes before or after it.
- If two strong moments are very close together and support each other, they may be merged as long as the duration stays within {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION} seconds.
- If two strong moments have different angles, split them into separate clip candidates.

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
- Do not pick clips scoring below 70 unless the transcript has very few good moments.

TARGET ACCOUNT CLASSIFICATION (FOR EVERY CLIP):
Choose the target account based on the clip's ANGLE. Do not judge from the topic alone (e.g. beauty does not automatically mean Life). Judge by angle:
{_account_classification_section()}

SPECIAL CLASSIFICATION RULES:
1. Beauty is not automatically Life. (Revenue/brand talk -> Business. Review/lifestyle -> Life. Affiliate/content -> Creator.)
2. Finance is not automatically Business. (Revenue/business talk -> Business. Personal finance/saving -> Life. How to make finance content -> Creator.)
3. Owner stories are split by angle. (The brand's struggle -> Business. Personal/family life -> Life. Provision/worship -> Muslim.)

HOOK (REQUIRED):
- Take the single punchiest sentence that EXISTS INSIDE the clip.
- The hook must feel strong and grab attention within the first ~{durasi_hook} seconds.
- Store it as hook_start_time and hook_end_time.
- The hook must make people want to keep watching, but must not be fake clickbait.
- Make sure the hook is natural and genuinely spoken in the transcript.
- If the best hook is not right at the start of the candidate clip, adjust start_time so the hook appears as early as possible.
- The hook must work as the opening on-screen text that holds the viewer through the first 3 seconds.

TYPOGRAPHY PLAN (KINETIC TYPOGRAPHY):
- Pick the 3-6 heaviest, most emotional or most emphasis-worthy SINGLE words from each clip.
- For each word, decide:
  1. 'kata_utama': that specific word, spelled exactly as in the transcript.
  2. 'scale_level': 1, 2 or 3.
     - 1 = normal/small
     - 2 = large/emphasis
     - 3 = giant/crucial
  3. 'style': "utama" or "khusus".
  4. 'animasi': "bounce_pop" or "stagger_up".
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
- Include a YouTube/TikTok search keyword for the editor.
- If there is a gesture that works as a visual hook, reference that too.
- This goes in the 'recommended_visual_broll_hook' object and serves only as a reference if the editor wants to source footage manually for the first 3 seconds.

BGM MOOD (BACKGROUND MUSIC):
- Analyse the clip's emotion and topic.
- Pick ONE background-music mood that fits best from this fixed list: [chill, epic, sad, upbeat, suspense].
- Make sure the mood matches the story. (For example: a hard-struggle story = sad/epic, a funny/relaxed story = chill/upbeat.)

SLOW CLOSING:
- end_time MUST be padded by +0.10 to +0.85 seconds after the last word so the ending breathes instead of being cut off abruptly.

SELECTION REASONING:
- Fill the 'alasan' field with a short explanation of why this clip is worth picking.
- Focus on emotional value, hook strength, retention potential, shareability and payoff.
- Explain the clip's main viral trigger.
- Explain why people are likely to watch to the end.
- Explain why the clip stays interesting without the context of the full video.

METADATA LANGUAGE RULES:
- title_indonesia is still required for internal compatibility / fallback.
- title_indonesia MUST be natural Indonesian and at most 100 characters.
- All primary cross-platform metadata must be natural English.
- This applies to:
  - title_inggris
  - hastag
  - description_hook
  - description_context
  - keyword_tags
  - tiktok_caption
- For the Indonesian TikTok variant, also produce:
  - tiktok_title_id
  - tiktok_caption_id
- tiktok_title_id and tiktok_caption_id MUST be natural Indonesian.
- tiktok_title_id must be more descriptive than title_indonesia, may exceed 100 characters if needed, and must clearly explain what the clip/video is about.
- tiktok_caption_id must be natural, informative, suited to an Indonesian audience, and may be slightly longer if that helps explain the clip.
- Do not mix Indonesian and English inside the same field.
- Use natural, concise, readable English that suits short-form content.
- Avoid stiff literal translations.

CROSS-PLATFORM METADATA:
Produce the following metadata for every clip:

1. title_indonesia
- Natural Indonesian, short and relevant.
- For internal compatibility / fallback only.
- At most 100 characters.

2. title_inggris
- Natural, strong, sharp, readable English.
- This is the primary title for platform metadata.
- At most 100 characters.
- Focus on one main idea.
- Relevant to the clip, not to the full video in general.
- No cheap clickbait.
- Do not over-use capital letters.
- Avoid excessive punctuation such as !!! ??? ...
- Do not be too generic.

3. hastag
- Exactly 2 to 3 hashtags in a single string.
- All hashtags MUST be in English.
- Separate them with spaces.
- They must be directly relevant to the clip's topic.
- No duplicates.
- Avoid overly generic hashtags such as #fyp #viral #trending unless they are genuinely relevant.
- Use a format like: #mindset #career #productivity

4. description_hook
- Exactly 1 sentence.
- MUST be in English.
- This is the opening sentence of the metadata.
- Short, strong and curiosity-provoking.
- No fake clickbait.

5. description_context
- Exactly 1 sentence.
- MUST be in English.
- Briefly explains the clip's main context.
- Must match what is being discussed in the clip.

6. keyword_tags
- 5 to 8 short keywords.
- MUST be in English.
- Not hashtags.
- A list of short phrases relevant to the clip.
- Avoid keyword spam.
- Favour keywords people would actually search for.
- This field is mainly for YouTube metadata.

7. tiktok_title_id
- Natural Indonesian.
- Longer and more explanatory about the video than title_indonesia.
- No 100-character limit, but still concise, clear and readable.
- Must be relevant to the clip, not to the long video in general.
- No cheap clickbait.

8. tiktok_caption_id
- 1 to 2 sentences.
- MUST be in Indonesian.
- May be slightly longer than the English caption if that helps explain the clip.
- Natural, light, readable style.
- Must match the clip's content.
- Do not just copy-paste the title.
- Do not be too formal.

9. tiktok_caption
- 1 to 2 short sentences.
- MUST be in English.
- More natural, light and conversational style.
- Must match the clip's content.
- Do not just copy-paste the title.
- Do not be too formal.
- Try to stay under 140 characters.

METADATA QUALITY RULES:
- All metadata must match the clip, not the long video in general.
- Do not promise anything that the clip does not discuss.
- Do not use fake hyperbole such as "100% guaranteed", "you'll definitely get rich", etc., unless it is explicitly stated.
- If there is a number, a strong phrase or a sharp statement in the original speech, prioritise it as title/caption inspiration.
- Title, descriptions and caption must complement each other rather than repeat the same sentence.
- Every metadata field used for a platform must be natural English, not a stiff literal translation.
- For tiktok_title_id and tiktok_caption_id specifically, use natural, clear Indonesian that explains the clip better for an Indonesian audience.

OUTPUT RULES:
- The output MUST be a valid JSON array.
- Do not add any explanation outside the JSON.
- Every field must be filled.
- When in doubt, prioritise accuracy about the clip over excessive creativity.
{_hook_v2_section(cfg)}{_segment_trim_section(cfg)}

REQUIRED JSON STRUCTURE (follow these field names exactly):
[
  {{
    "rank": 1,
    "viral_score": 95,
    "start_time": 30.5,
    "end_time": 90.0,
    "hook_start_time": 30.5,
    "hook_end_time": 35.0,
    "bgm_mood": "mood_here",
    "typography_plan": [{{ "kata_utama": "...", "scale_level": 2, "style": "utama", "animasi": "bounce_pop" }}],
    "broll_list": [{{ "start_time": 40.0, "end_time": 45.0, "search_query": "..." }}],
    "recommended_visual_broll_hook": [
      {{ "broll_idea": "...", "search_keyword": "...", "why_it_works": "..." }}
    ],
    "hook_v2": {{
      "enabled": true,
      "items": [{{ "start_time": 31.0, "end_time": 32.5, "text": "KEY PHRASE" }}],
      "transition": {{ "type": "white_flash" }}
    }},
    "keep_segments": [
      {{ "start_time": 30.5, "end_time": 55.0 }},
      {{ "start_time": 58.0, "end_time": 90.0 }}
    ],
    "title_indonesia": "...",
    "title_inggris": "...",
    "hastag": "#hastag1 #hastag2",
    "description_hook": "...",
    "description_context": "...",
    "keyword_tags": ["tag1", "tag2"],
    "tiktok_title_id": "...",
    "tiktok_caption_id": "...",
    "tiktok_caption": "...",
    "alasan": "...",
    "klasifikasi_akun": {{
      "tipe_akun": "Creator",
      "akun_tujuan": "Creator.Mereska",
      "confidence": 87,
      "angle_utama": "Monetising digital content in the beauty niche",
      "alasan": "...",
      "kata_kunci_pendukung": ["affiliate", "monetisasi"],
      "bio_akun": "...",
      "alternatif_akun": {{
        "tipe_akun": "Life",
        "akun_tujuan": "Life.Mereska",
        "alasan": "..."
      }}
    }}
  }}
]

Transcript:
{transcript}
"""
