# ⚙️ CLI Reference

Complete reference for all command-line arguments. Run `python -m app.cli --help` for a quick overview (the `clipping` console script installed by `pyproject.toml` works the same way).

---

## Subcommands

`python -m app.cli <subcommand> ...` dispatches to one of the following. If the
first argument isn't a recognized subcommand, everything is forwarded to the
clip/story pipeline (so the historical `--url ...` invocation still works).

| Subcommand | Console script | What it does |
|---|---|---|
| `clip` (default) | `clipping` | Runs the auto-clip pipeline |
| `story` | `clipping story` | Same pipeline, with `--story-mode` implied |
| `queue` | `clipping queue` | Clips every URL in a links file, one after another |
| `upload-youtube` | `clipping-upload-youtube` | Uploads/schedules clips to YouTube |
| `upload-instagram` | `clipping-upload-instagram` | Publishes clips as Instagram Reels |
| `reschedule-youtube` | `clipping-reschedule-youtube` | Re-spaces already-scheduled YouTube videos |
| `youtube-token` | `clipping-youtube-token` | Generates/verifies the YouTube OAuth token |
| `learn-youtube` | `clipping-learn-youtube` | Fetches views for uploaded clips so selection learns from them |

This page covers the **clip/story pipeline** flags only. For the uploader and
token subcommands see [YouTube Auto-Upload](YouTube-Auto-Upload), [Instagram
Reels Uploader](Instagram-Reels-Uploader), and the
[CLI Arguments Reference](CLI-Arguments-Reference).

---

## Core Settings

| Argument | Default | Description |
|---|---|---|
| `--url`, `-u` | — | Video URL to process (**Required** unless `--story-mode`) |
| `--source` | `youtube` | Video source platform: `youtube`, `tiktok`, `instagram`, `gdrive` |
| `--cookies` | — | Netscape `cookies.txt` for yt-dlp (fixes YouTube's bot check on Colab/Kaggle); also `$YTDLP_COOKIES_FILE` |
| `--tiktok` | — | **[Deprecated]** Use `--source tiktok` instead |
| `--clips`, `-n` | `7` | Maximum number of clips (the AI returns fewer when a video has fewer great moments) |
| `--ratio`, `-r` | `9:16` | Output aspect ratio: `9:16`, `16:9`, `1:1`, `3:4`, `4:5` |
| `--min-duration` | `30` | Shortest clip length in seconds |
| `--max-duration` | `80` | Longest clip length in seconds (up to 180 for Shorts) |
| `--source-height` | `max` | Preferred source download max height (`max`, `1080`, `1440`, `2160`) |
| `--render-height` | `1080` | Target output render height (`1080`, `1440`, `2160`, `source`) |

---

## AI Provider Settings

| Argument | Default | Description |
|---|---|---|
| `--ai-provider` | `gemini` | AI provider for analysis: `gemini` or `nvidia` |
| `--gemini-model` | `gemini-3-flash-preview` | Gemini model name |
| `--gemini-fallback-model` | `gemini-2.5-flash` | Fallback model if main model fails |
| `--nvidia-model` | `deepseek-ai/deepseek-v4-pro` | Model name for NVIDIA NIM API |
| `--load-gemini-json` | `False` | Load saved `gemini_response.json` to bypass AI call |
| `--target-accounts` | `target_accounts.json` | Path to the account-routing config used to classify each clip |
| `--no-account-routing` | `False` | Skip account classification entirely |
| `--performance-file` | `outputs/channel_performance.json` | Channel results from `learn-youtube`, shown to the AI |
| `--no-channel-learning` | `False` | Don't show the AI how earlier clips performed |

---

## Content & Hook Settings

| Argument | Default | Description |
|---|---|---|
| `--words-per-sub` | `3` | Max words per caption group |
| `--hook-teaser` | `False` | Open with a flash-forward to the clip's peak line, then a clean cut |
| `--hook-duration` | `3` | Hook teaser duration (seconds) |
| `--hook-source` | `None` | Path or URL for a custom hook video (.mp4), played as the teaser |
| `--hook-source-start` | `0.0` | Start time in seconds for custom hook |
| `--no-broll` | — | Disable B-roll footage |
| `--no-bgm` | — | Disable background music |
| `--no-subs` | — | Disable all subtitle rendering |
| `--no-karaoke` | — | No spoken-word highlight |

---

## Segment Trimming

| Argument | Default | Description |
|---|---|---|
| `--no-segment-trim` | `False` | Disable AI segment trimming (render full clip) |
| `--silence-trim` | `False` | Aggressively trim silence/dead air |

---

## Subtitle & Typography

| Argument | Default | Description |
|---|---|---|
| `--font-style` | `DEFAULT` | Font preset: `DEFAULT`, `STORYTELLER`, `HORMOZI`, `CINEMATIC` |
| `--caption-case` | `normal` | `normal` or `upper` (UPPERCASE captions) |
| `--simple-captions` | `False` | Plain one-line karaoke captions instead of the kinetic style |
| `--no-title-overlay` | `False` | Disable the AI headline at the top of the frame |

---

## Language

| Argument | Default | Description |
|---|---|---|
| `--language` | `auto` | Spoken language code (`hi`, `en`, `ta`, ...); `auto` uses YouTube's language, then Whisper detection |
| `--caption-script` | `latin` | `latin` writes non-Latin speech in English letters (never translated); `native` keeps the original script |

---

## BGM (Background Music)

| Argument | Default | Description |
|---|---|---|
| `--bgm-mode` | `ducking` | `ducking` (auto-lower during speech) or `background` (constant low volume) |
| `--bgm-dir` | `assets/bgm` | Folder with `chill/ epic/ sad/ upbeat/ suspense/` subfolders of your own music |
| `--bgm-volume` | `0.12` | Music volume before ducking |

---

## AI Voice-Over Commentary (TTS)

| Argument | Default | Description |
|---|---|---|
| `--voiceover` | `False` | Enable AI voice-over commentary mode (Gemini script + edge-tts) |
| `--voiceover-voice` | `en-GB-MaisieNeural` | edge-tts voice name |
| `--voiceover-lang` | `en` | Script language: `en` or `id` |
| `--voiceover-style` | `analysis` | `analysis`, `reaction`, `lesson`, or `summary` |
| `--voiceover-length` | `short` | `short` (~10s), `normal` (~30s), or `long` (~50s) |
| `--voiceover-volume` | `1.0` | Volume of the voice-over track |
| `--original-volume` | `0.15` | Volume of the original video audio while the voice-over plays |

---

## Watermark Settings

| Argument | Default | Description |
|---|---|---|
| `--watermark` | `False` | Enable watermark overlay on rendered clips |
| `--text` | `None` | Watermark text to overlay (e.g. 'Channel Name') |
| `--image` | `None` | Path to watermark image (PNG with alpha recommended, also supports JPG, JPEG, WEBP) |
| `--opacity` | `70` | Watermark opacity in percent (1-100) |
| `--position` | `center-right`| Watermark position (9 anchors: `top-left`, `center-right`, etc.) |
| `--padding` | `0` | Watermark padding from the nearest edge in pixels |
| `--watermark-font-size` | `0` | Watermark font size in pixels (0 = auto ~3% frame height) |
| `--watermark-scale` | `15` | Image watermark height as % of frame height (1-100) |

---

## Podcast / Split-Screen

| Argument | Default | Description |
|---|---|---|
| `--split-screen` | `False` | Enable split-screen mode. Works with any vertical/square ratio (`9:16`, `1:1`, `3:4`, `4:5`) |
| `--dynamic-split` | `False` | Auto-toggle between full and split based on speakers |
| `--split-trigger` | `diarization` | Trigger: `diarization` (audio) or `face` (visual count) |
| `--diarization-speakers` | `auto` | Number of speakers or `auto` for visual detection |
| `--camera-switch` | `False` | Diarization-based camera switching (needs `HF_TOKEN`). Works with any vertical/square ratio |
| `--switch-hold-duration` | `2.0` | Min seconds before switching speakers |
| `--switch-blend-duration` | `0.0` | Transition duration when switching speakers (0 = instant snap, 0.2 = smooth blend) |
| `--split-zoom` | `1.0` | Manual zoom factor for split panels |
| `--split-v-align` | `0.5` | Vertical alignment (0.0=top, 0.5=center, 1.0=bottom) |
| `--split-auto-zoom` | `False` | Auto-zoom to isolate each speaker |
| `--split-max-zoom` | `2.5` | Maximum zoom limit for auto-zoom |

---

## Whisper (Transcription)

| Argument | Default | Description |
|---|---|---|
| `--whisper-model` | `large-v3` | Faster-Whisper model size |
| `--whisper-device` | `cuda` | Device: `cuda`, `cpu`, `auto` |
| `--whisper-compute-type` | `float16` | Compute type: `float32`, `float16`, `int8` |
| `--use-dlp-subs` | — | Use YouTube's subtitles in the spoken language (skips Whisper if found) |

---

## Face Detection & Framing

| Argument | Default | Description |
|---|---|---|
| `--face-detector` | `mediapipe` | AI model: `mediapipe` (CPU) or `yolo` (GPU) |
| `--yolo-size` | `8m` | YOLO model size: `8n`, `8s`, `8m`, `8n_v2`, `9c` |
| `--layout` | `auto` | `auto` (crop, blur-fill faceless clips), `crop`, or `blur` |
| `--no-speaker-tracking` | `False` | Follow faces by position instead of by who is talking |
| `--static-crop` | `False` | Disable face tracking, use static center crop |

---

## Camera Tracking Tuning

| Argument | Default | Description |
|---|---|---|
| `--track-step` | `0.25` | Face detection frequency (seconds) |
| `--track-deadzone` | `0.15` | Camera deadzone ratio |
| `--track-smooth` | `0.30` | Camera catch-up speed factor |
| `--track-jitter` | `5` | Pixel threshold to ignore micro-shakes |
| `--track-snap` | `0.08` | Jump threshold (fraction of frame width) for a hard cut |
| `--track-conf` | `0.55` | Face detection confidence threshold (split-screen) |
| `--track-smooth-window` | `12` | Frame window for layout stability (~0.5s) |
| `--scene-cut-threshold` | `18` | Sensitivity for camera-cut detection |
| `--track-iou-threshold` | `0.2` | Overlap threshold for merging duplicate detections |

---

## Video Quality

| Argument | Default | Description |
|---|---|---|
| `--video-bitrate` | `auto` | Target bitrate (e.g. `8M`, `12M`, `auto`) |
| `--video-sharpen` | — | Apply subtle sharpening filter |
| `--video-cq` | `23` | NVENC CQ quality (lower = sharper) |
| `--video-crf` | `20` | libx264 CRF quality (lower = sharper) |
| `--video-preset` | `auto` | Encoder preset (NVENC: `p1`-`p7`, x264: `ultrafast`-`veryslow`) |
| `--video-scale-algo` | `lanczos` | Resize algorithm: `lanczos`, `bicubic`, `bilinear`, `area` |

---

## Story Clip Mode

| Argument | Default | Description |
|---|---|---|
| `--story-mode` | `False` | Enable Story Clip multi-source assembly |
| `--story-recipe` | `story_recipe.json` | Path to story recipe JSON file |
| `--sources-json` | `sources.json` | Path to sources registry JSON |
| `--story-output-dir` | `outputs/story_clips` | Output directory for story clips |
| `--skip-download` | `False` | Skip downloads, use cached files |
