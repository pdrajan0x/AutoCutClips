# 📝 Subtitles & Typography

AutoCutClips burns word-by-word captions into every clip using the `.ASS` subtitle format, plus a short headline at
the top of the frame for viewers watching with the sound off.

---

## Subtitle System Overview

1. **Transcription** — Faster-Whisper produces word-level timestamps, in the language actually spoken
2. **Grouping** — words are grouped into caption chunks (default: 3 words)
3. **Script** — speech in a non-Latin script is written in English letters (see *Language* below)
4. **ASS generation** — each word is positioned and animated
5. **Rendering** — captions are burned into the video with FFmpeg

---

## The Default Look

- **Heavy font with a thick outline** — `DEFAULT` preset (Montserrat Black), readable over any background
- **Spoken-word highlight** — the word being said pops slightly and turns gold
- **Keywords** — the 3-6 words Gemini marks as the heaviest stay gold and larger for the whole group
- **Headline overlay** — a 3-7 word hook in a dark box near the top for the first 4 seconds

| Flag | Effect |
|---|---|
| `--caption-case upper` | UPPERCASE captions |
| `--simple-captions` | Plain one-line captions with a karaoke colour change instead of the kinetic style |
| `--no-karaoke` | No spoken-word highlight |
| `--no-title-overlay` | No headline at the top |
| `--no-subs` | No captions at all |

```bash
# Bold uppercase captions
python -m app.cli --url "VIDEO_URL" --caption-case upper

# Plain captions, no headline
python -m app.cli --url "VIDEO_URL" --simple-captions --no-title-overlay
```

---

## Font Styles

| Style | Main Font | Emphasis Font | Best For |
|---|---|---|---|
| `DEFAULT` (default) | Montserrat Black | Montserrat Medium | General purpose — the heaviest, most readable |
| `HORMOZI` | Montserrat | Anton | Business / motivational content |
| `STORYTELLER` | Inter | Lora | Narrative / storytelling |
| `CINEMATIC` | Roboto | Bebas Neue | Film / dramatic content |

```bash
python -m app.cli --url "VIDEO_URL" --font-style CINEMATIC
```

> All fonts are auto-downloaded on first run.

---

## Words Per Caption

```bash
# Default: 3 words per caption group
python -m app.cli --url "VIDEO_URL" --words-per-sub 3

# Longer groups (slower reading, fewer changes)
python -m app.cli --url "VIDEO_URL" --words-per-sub 5
```

Two to four words keeps the text in step with the speaker; longer groups make viewers read ahead.

---

## Language

Captions are never translated.

- **English speech** → English captions.
- **Latin-script languages** (Spanish, Indonesian, Hinglish typed in English letters) → captions as spoken.
- **Non-Latin scripts** (Hindi, Tamil, Arabic, Russian, ...) → the same words written in English letters, the way
  people type them online: *"namaste, mera naam priyadarshani rajan hai"*. The headline follows the same rule.

| Flag | Effect |
|---|---|
| `--language auto` (default) | Use the language YouTube reports, else Whisper's detection |
| `--language hi` | Force the spoken language (any Whisper language code) |
| `--caption-script native` | Keep the original script (needs a caption font that supports it) |

Titles, descriptions and hashtags stay in English.

---

## Subtitle Positioning

| Ratio | Alignment | Margin | Font Size |
|---|---|---|---|
| `9:16` (Vertical) | Bottom-center | 450px from bottom (clear of the Shorts/Reels UI) | 90px |
| `16:9` (Landscape) | Bottom-center | 70px from bottom | 80px |

Sizes are defined for 1080×1920 / 1920×1080 and scale with `--render-height`.

---

## Transcription Options

```bash
# Smaller/faster model
python -m app.cli --url "VIDEO_URL" --whisper-model medium

# Force CPU (no CUDA GPU)
python -m app.cli --url "VIDEO_URL" --whisper-device cpu

# Lower VRAM usage
python -m app.cli --url "VIDEO_URL" --whisper-compute-type int8

# Kaggle compatibility
python -m app.cli --url "VIDEO_URL" --whisper-compute-type float32
```

Whisper runs with voice-activity filtering, so music and silence don't produce invented captions.

### YouTube Built-in Subtitles

```bash
python -m app.cli --url "VIDEO_URL" --use-dlp-subs
```

Uses YouTube's subtitles in the video's own language (uploaded subtitles first, then the original-language
auto-captions — never a machine-translated track), and falls back to Whisper when none exist. YouTube sources only.

---

## See Also

- [CLI Reference](CLI-Reference) — All subtitle-related flags
- [Video Quality & Rendering](Video-Quality-and-Rendering) — Output quality settings
