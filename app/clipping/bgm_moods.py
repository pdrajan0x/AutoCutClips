"""
clipping.bgm_moods — The background-music moods the AI can pick from.

One list shared by the prompt, the response schema, the config and the
renderer. Each mood is a folder under ``assets/bgm/`` and a key in
``assets/bgm/library.json``.
"""

# mood -> when to use it (shown to the AI)
BGM_MOOD_GUIDE = {
    "chill": "relaxed talk, casual advice, laid-back conversation",
    "calm": "meditation, wellness, slow thoughtful or spiritual moments",
    "happy": "wholesome, feel-good, family or friendly moments",
    "upbeat": "light, positive, lifestyle, tips and how-tos with energy",
    "energetic": "sports, fitness, hype, fast-paced action",
    "motivational": "discipline, hustle, self-improvement, 'you can do it'",
    "inspiring": "hopeful stories, breakthroughs, heartfelt life lessons",
    "epic": "triumph, huge stakes, ambition, legendary achievements",
    "dramatic": "confrontation, intense revelations, serious turning points",
    "sad": "loss, grief, struggle, regret, loneliness",
    "romantic": "love, relationships, dating, tender moments",
    "funny": "comedy, jokes, awkward or silly moments, banter",
    "mysterious": "secrets, unexplained facts, science and curiosity hooks",
    "suspense": "tension building to a reveal, investigations, cliffhangers",
    "scary": "horror, creepy stories, disturbing true crime",
}

BGM_MOODS = list(BGM_MOOD_GUIDE)
DEFAULT_BGM_MOOD = "chill"
