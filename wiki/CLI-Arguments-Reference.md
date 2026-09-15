# CLI Arguments Reference

A flat, grouped list of **every** command-line argument across all entry points.
For narrative explanations of each feature, see the numbered pages in this wiki
(this page is the lookup table).

## Entry points

| Command | What it runs |
| --- | --- |
| `clipping` / `python -m app.cli` | Auto-clip pipeline; switches to Story Clip mode with `--story-mode` |
| `python -m app.cli queue` | Clip pipeline over every URL in a links file |
| `clipping-upload-youtube` / `python -m app.cli upload-youtube` | YouTube upload & scheduling |
| `clipping-upload-instagram` / `python -m app.cli upload-instagram` | Instagram Reels publishing |
| `clipping-reschedule-youtube` / `python -m app.cli reschedule-youtube` | Re-space already-scheduled YouTube videos |
| `clipping-youtube-token` / `python -m app.cli youtube-token` | Create / verify the YouTube OAuth token |
| `clipping-learn-youtube` / `python -m app.cli learn-youtube` | Fetch views for uploaded clips (channel learning) |
| `clipping-tracker` / `python -m app.tracker.server` | YouTube performance tracker (no flags; see env vars) |
| `uvicorn app.web.api.app:app` | Web API backend for the Studio pages |

---

## Input & Output

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--url`, `-u` | str, `None` | Video URL to process (YouTube, TikTok, Instagram, Google Drive). Required unless `--story-mode`. |
| `--source` | `youtube` \| `tiktok` \| `instagram` \| `gdrive`, default `youtube` | Source platform; decides download behaviour and subtitle availability. |
| `--cookies` | str, `None` | Netscape `cookies.txt` for yt-dlp; fixes YouTube's "Sign in to confirm you're not a bot" on Colab/Kaggle. Also read from `$YTDLP_COOKIES_FILE`. |
| `--tiktok` | flag, `False` | **Deprecated** — use `--source tiktok`. |
| `--clips`, `-n` | int, `7` | Maximum number of clips to generate. |
| `--ratio`, `-r` | `9:16` \| `16:9` \| `1:1` \| `3:4` \| `4:5`, default `9:16` | Output aspect ratio. |
| `--min-duration` | float, `30` | Shortest clip length, in seconds. |
| `--max-duration` | float, `80` | Longest clip length, in seconds (5-180; `min` must be below `max`). |
| `--source-height` | `max` or int, default `max` | Max source download height; `max` fetches the highest available quality. |
| `--render-height` | str, `1080` | Target output height; `source` matches the source video, or give a number (1080, 1440). |
| `--load-gemini-json` | flag, `False` | Reuse the saved `gemini_response.json` and skip the AI step. |
| `--target-accounts` | str, `target_accounts.json` | JSON routing table the AI uses to assign each clip to a publishing account. |
| `--no-account-routing` | flag, `False` | Disable account classification entirely. |
| `--performance-file` | str, `outputs/channel_performance.json` | Channel results from `learn-youtube`; the AI is shown the best and weakest clips. |
| `--no-channel-learning` | flag, `False` | Don't show the AI how earlier clips performed. |

## Rendering / Studio Effects

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--no-broll` | flag, `False` | Disable B-roll footage. |
| `--hook-teaser` | flag, `False` | Open with a flash-forward to the clip's peak line, then a clean cut to the clip. |
| `--hook-duration` | int, `3` | Hook teaser duration in seconds. |
| `--hook-source` | str, `None` | Google Drive URL or local path to a custom hook video (`.mp4`), played as the teaser. |
| `--hook-source-start` | float, `0.0` | Start time in seconds inside the custom hook video. |
| `--layout` | `auto` \| `crop` \| `blur`, default `auto` | Vertical framing: face-tracked crop, blurred-background fill for faceless clips, or always one of them. |
| `--no-speaker-tracking` | flag, `False` | With several people in frame, follow faces by position instead of by who is talking. |
| `--video-bitrate` | str, `auto` | Target bitrate (e.g. `8M`, `12M`); `auto` scales with resolution. |
| `--video-sharpen` | flag, `False` | Apply a subtle sharpening filter. |
| `--video-cq` | int, `23` | NVENC constant-quality value (lower = sharper, bigger file). |
| `--video-crf` | int, `20` | libx264 CRF value (lower = sharper, bigger file). |
| `--video-preset` | str, `auto` | Override the NVENC/libx264 preset, or `auto` (NVENC `p4`, x264 `veryfast`). |
| `--video-scale-algo` | `lanczos` \| `bicubic` \| `bilinear` \| `area`, default `lanczos` | Resize algorithm used during rendering. |

### Segment trimming

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--no-segment-trim` | flag, `False` | Disable AI segment trimming (render full start-to-end instead of `keep_segments`). |
| `--silence-trim` | flag, `False` | Tell the AI to aggressively trim silence and dead air. |

## Subtitles & Typography

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--no-subs` | flag, `False` | Disable all subtitle rendering. |
| `--words-per-sub` | int, `3` | Max words per caption group. |
| `--no-karaoke` | flag, `False` | No spoken-word highlight. |
| `--font-style` | `DEFAULT` \| `STORYTELLER` \| `HORMOZI` \| `CINEMATIC`, default `DEFAULT` | Font style preset. |
| `--caption-case` | `normal` \| `upper`, default `normal` | UPPERCASE captions with `upper`. |
| `--simple-captions` | flag, `False` | Plain one-line karaoke captions instead of the kinetic style. |
| `--no-title-overlay` | flag, `False` | Disable the AI headline at the top of the frame. |
| `--language` | str, `auto` | Spoken language code for transcription; `auto` uses YouTube's language, then Whisper detection. |
| `--caption-script` | `latin` \| `native`, default `latin` | `latin` writes non-Latin speech in English letters (never translated); `native` keeps the script. |
| `--use-dlp-subs` | flag, `False` | Use YouTube's subtitles in the spoken language and skip Whisper when found. |
| `--whisper-model` | str, `large-v3` | Faster-Whisper model size. |
| `--whisper-device` | `cuda` \| `cpu` \| `auto`, default `cuda` | Device used for Whisper inference. |
| `--whisper-compute-type` | str, `float16` | Whisper compute type (`float16`, `int8`, ...). |

## BGM & Audio

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--no-bgm` | flag, `False` | Disable background music. |
| `--bgm-mode` | `ducking` \| `background`, default `ducking` | `ducking` sidechain-compresses BGM under speech; `background` mixes it at a constant low volume. |
| `--bgm-dir` | str, `assets/bgm` | Folder with `chill/ epic/ sad/ upbeat/ suspense/` subfolders. |
| `--bgm-volume` | float, `0.12` | Music volume before ducking. |

### Voice-over commentary (TTS)

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--voiceover` | flag, `False` | Enable AI voice-over commentary (Gemini script + edge-tts). |
| `--voiceover-voice` | str, `en-GB-MaisieNeural` | edge-tts voice name (e.g. `id-ID-ArdiNeural`, `en-US-AvaNeural`). |
| `--voiceover-lang` | `id` \| `en`, default `en` | Language of the generated commentary script. |
| `--voiceover-style` | `analysis` \| `reaction` \| `lesson` \| `summary`, default `analysis` | Commentary style. |
| `--voiceover-length` | `short` \| `normal` \| `long`, default `short` | Commentary length (~10s / ~30s / ~50s). |
| `--voiceover-volume` | float, `1.0` | Volume of the voice-over track. |
| `--original-volume` | float, `0.15` | Volume of the original audio while the voice-over plays. |

## Face Tracking & Framing

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--face-detector` | `mediapipe` \| `yolo`, default `mediapipe` | Face-tracking model (MediaPipe is CPU; YOLO uses the GPU when available). |
| `--yolo-size` | `8n` \| `8s` \| `8m` \| `8n_v2` \| `9c`, default `8m` | YOLO face model size; only used with `--face-detector yolo`. |
| `--static-crop` | flag, `False` | Disable face tracking and centre-crop statically for 1:1, 3:4 and 4:5. |
| `--track-step` | float, `None` (0.25) | Face-detection frequency, in seconds. |
| `--track-deadzone` | float, `None` (0.15) | Camera deadzone ratio. |
| `--track-smooth` | float, `None` (0.30) | Camera smoothing speed. |
| `--track-jitter` | int, `None` (5) | Pixel jitter threshold. |
| `--track-snap` | float, `None` (0.08) | Face-jump threshold (fraction of frame width) that counts as a cut. |
| `--track-conf` | float, `0.55` | *Experimental.* Detection confidence threshold, to suppress ghost faces (split-screen). |
| `--track-smooth-window` | int, `12` | *Experimental.* Majority-vote window (frames) for layout stability. |
| `--scene-cut-threshold` | int, `18` | *Experimental.* Visibility change that counts as a camera cut and resets layout history. |
| `--track-iou-threshold` | float, `0.2` | *Experimental.* Box-overlap threshold for merging duplicate detections. |

### Podcast modes (split-screen & camera-switch)

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--split-screen` | flag, `False` | Split-screen mode for 2+ speaker podcasts. Works on any vertical/square ratio; `--split-trigger diarization` needs `HF_TOKEN`, `--split-trigger face` does not. |
| `--camera-switch` | flag, `False` | Diarization-based camera-switch mode. Works on any vertical/square ratio; needs `HF_TOKEN`. `--split-screen` wins if both are set. |
| `--diarization-speakers` | int or `auto`, default `auto` | Speaker count for diarization, or `auto` to detect visually. |
| `--split-trigger` | `diarization` \| `face`, default `diarization` | What decides when to split: audio (who is talking) or video (how many faces). |
| `--dynamic-split` | flag, `False` | Switch between full-screen (1 speaker) and split-screen (2 speakers) automatically. Needs `--split-screen`. |
| `--split-zoom` | float, `1.0` | Zoom factor for split-screen panels. |
| `--split-v-align` | float, `0.5` | Panel vertical alignment (0.0 top, 0.5 centre, 1.0 bottom). |
| `--split-auto-zoom` | flag, `False` | Zoom each panel until only one person is visible in it. |
| `--split-max-zoom` | float, `2.5` | Maximum zoom factor allowed for auto-zoom. |
| `--switch-hold-duration` | float, `2.0` | Minimum seconds to hold on a speaker before switching cameras. |
| `--switch-blend-duration` | float, `0.0` | Blend length when switching speakers (0 = instant snap, 0.2 = 200ms blend). |

## AI Provider

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--ai-provider` | `gemini` \| `nvidia`, default `gemini` | Provider used for clip analysis; NVIDIA falls back to Gemini on failure. |
| `--gemini-model` | str, `gemini-3-flash-preview` | Gemini model name. |
| `--gemini-fallback-model` | str, `gemini-2.5-flash` | Gemini model tried once if the main model fails. |
| `--nvidia-model` | str, `deepseek-ai/deepseek-v4-pro` | Model name for the NVIDIA NIM API. |

## Watermark

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--watermark` | flag, `False` | Enable the watermark overlay. Requires `--text` or `--image`. |
| `--text` | str, `None` | Watermark text to overlay (e.g. a channel name). |
| `--image` | str, `None` | Path to a watermark image (PNG, JPG, JPEG, WEBP, BMP, TIFF); transparent PNG recommended. |
| `--opacity` | int, `70` | Watermark opacity, 1-100. |
| `--position` | 9 anchors, default `center-right` | `top-left`, `top-center`, `top-right`, `center-left`, `center`, `center-right`, `bottom-left`, `bottom-center`, `bottom-right`. |
| `--padding` | int, `0` | Padding from the nearest edge, in pixels. |
| `--watermark-font-size` | int, `0` | Text watermark font size in pixels; `0` = auto (3% of frame height). |
| `--watermark-scale` | int, `15` | Image watermark height as a percentage of the frame height, 1-100. |

## Story Mode

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--story-mode` | flag, `False` | Assemble clips from multiple sources using a JSON recipe instead of auto-clipping one video. |
| `--story-recipe` | str, `story_recipe.json` | Path to the story recipe JSON. |
| `--sources-json` | str, `sources.json` | Path to the sources registry JSON. |
| `--story-output-dir` | str, `None` | Output directory for story clips (default `outputs/story_clips`). |
| `--skip-download` | flag, `False` | Skip source downloads and use the existing cache. |

In story mode `--ratio`, `--words-per-sub` and the `--whisper-*` flags still
apply (the recipe's `default_settings.ratio` is used only when `--ratio` is
absent); the Studio effect flags do not, because story clips are assembled
clean, with no subtitles or overlays.

## Video Queue

`python -m app.cli queue` — every other clip flag above is applied to each video.

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--links` | str, required | Text file with one video URL per line (`#` comments allowed). |
| `--retry-failed` | flag, `False` | Re-run videos that failed last time, reusing their download, transcript and AI selection. |
| `--keep-source` | flag, `False` | Keep each downloaded source video after its clips render. |

## YouTube Upload & Scheduling

`clipping-upload-youtube`:

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--token-file` | str, `.credentials/youtube_token.json` | YouTube OAuth token JSON. |
| `--manifest-file` | str, `outputs/render_manifest.json` | Input manifest from the clipping pipeline (or `outputs/queue/queue_manifest.json`). |
| `--result-file` | str, `outputs/youtube_upload_results.json` | Output JSON trace of the upload responses. |
| `--updated-manifest` | str, `outputs/render_manifest_uploaded.json` | Output manifest enriched with the upload results; also read to skip clips already uploaded. |
| `--tz-name` | str, `$APP_TIMEZONE` or `Asia/Kolkata` | Timezone used for scheduling (IANA name). |
| `--interval-hours` | int, `24` | Gap between scheduled publishes; the safety config enforces a minimum. |
| `--start-local` | str, `None` | Manual first publish time (`YYYY-MM-DD HH:MM`), bypassing queue detection. |
| `--test-mode` | flag, `False` | Upload only the first pending item. |
| `--safety-config` | str, `upload_safety.json` | Path to the upload safety config JSON. |
| `--no-approval` | flag, `False` | Skip the interactive approval prompt. The other safety rails still apply. |

`upload_safety.json` keys (not CLI flags, but they gate this command):
`max_upload_per_day`, `max_upload_per_run`, `interval_hours_min`,
`max_scheduled_queue`, `require_manual_approval`, `upload_log_file`.

`clipping-learn-youtube`:

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--token-file` | str, `.credentials/youtube_token.json` | YouTube OAuth token JSON (the upload token works). |
| `--history-file` | str, `None` | Upload history; defaults to `upload_log_file` from the safety config. |
| `--safety-config` | str, `upload_safety.json` | Safety config that names the upload history file. |
| `--output` | str, `outputs/channel_performance.json` | Where to save the results (clip runs read this path by default). |

`clipping-reschedule-youtube`:

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--token-file` | str, `.credentials/youtube_token.json` | YouTube OAuth token JSON. Needs the `youtube.force-ssl` scope. |
| `--tz-name` | str, `Asia/Kolkata` | Timezone for the new schedule. |
| `--interval-hours` | int, `2` | New gap between scheduled publishes. |
| `--start-local` | str, `None` | Manual start time for the first slot (`YYYY-MM-DD HH:MM`). |
| `--max-pages` | int, `10` | How many playlist pages to scan for scheduled videos. |
| `--apply` | flag, `False` | Actually update YouTube. Without it the run is a dry-run. |
| `--manifest-file` | str, `outputs/render_manifest_uploaded.json` | Manifest to update with the new times. |
| `--updated-manifest` | str, `outputs/render_manifest_rescheduled.json` | Output manifest with the new times. |

`clipping-youtube-token`:

| Argument | Type / Default | Description |
| --- | --- | --- |
| `command` | `generate` \| `verify` (positional, required) | `generate` runs the OAuth login; `verify` refreshes the token and prints the channel. |
| `--token-file` | str, `.credentials/youtube_token.json` | Token file to write or verify. |
| `--client-secret` | str, `.credentials/client_secret.json` | Google OAuth client-secret JSON (`generate` only). |
| `--manual` | flag, `False` | No local browser (Colab/Kaggle/SSH): print a login link and paste the redirected URL back. |

## Instagram Upload

`clipping-upload-instagram` publishes Reels through the **Instagram Graph API**
(it replaces the old Facebook Page Reels uploader).

| Argument | Type / Default | Description |
| --- | --- | --- |
| `--manifest-file` | str, `outputs/render_manifest.json` | Input manifest from the clipping pipeline. |
| `--result-file` | str, `outputs/ig_upload_results.json` | Output JSON trace of the publish responses. |
| `--updated-manifest` | str, `outputs/render_manifest_ig_uploaded.json` | Output manifest enriched with the publish results. |
| `--tz-name` | str, `$APP_TIMEZONE` or `Asia/Kolkata` | Timezone used for the interval maths (IANA name). |
| `--interval-hours` | int, `5` | Minimum gap between publishes. Clips whose slot has not arrived are recorded as `deferred` for a later run. |
| `--test-mode` | flag, `False` | Publish only the first pending item. |
| `--publish-now` | flag, `False` | Ignore `--interval-hours` and publish the whole batch back to back. |

Required environment variables:

| Variable | Description |
| --- | --- |
| `IG_USER_ID` | Instagram **User** ID of the Business/Creator account (not the Facebook Page ID). |
| `IG_ACCESS_TOKEN` | Token with the `instagram_content_publish` permission. Falls back to `META_PAGE_ACCESS_TOKEN`. |
| `IG_GRAPH_VERSION` | Graph API version, default `v25.0`. Falls back to `META_GRAPH_VERSION`. |
| `IG_PUBLIC_BASE_URL` | Optional. Public base URL serving the rendered clips; when set, the `video_url` flow is used instead of the resumable upload. |
| `APP_TIMEZONE` | Default value for `--tz-name`. |

The Instagram Graph API has **no** scheduled-publish parameter, so the interval
is enforced locally: run the command repeatedly (e.g. from cron) and each run
publishes the clips whose slot has arrived.

## Web API / Studio config

The backend takes no CLI flags of its own — it is configured by environment
variables and the `PUT /api/settings` endpoint. Job requests accept the same
settings as the CLI (`clips`, `ratio`, `min_duration`, `max_duration`,
`hook_teaser`, `layout`, `speaker_tracking`, `caption_case`, `title_overlay`,
`language`, `caption_script`, ...); any field left out uses the CLI default.

| Variable | Default | Description |
| --- | --- | --- |
| `GOOGLE_API_KEY` | — | Gemini API key (required for the clipping pipeline). |
| `NVIDIA_API_KEY` | — | NVIDIA NIM API key (only for `--ai-provider nvidia`). |
| `PEXELS_API_KEY` | — | Pexels key used to fetch B-roll. |
| `HF_TOKEN` | — | HuggingFace token, required by Pyannote for the diarization podcast modes. |
| `YTDLP_COOKIES_FILE` | — | Cookies file for YouTube downloads. |
| `MAX_CONCURRENT_JOBS` | `1` | Maximum jobs the web worker runs at once. |
| `STUDIO_ALLOWED_ORIGINS` | — | Extra CORS origins (comma-separated) for your own Studio host. |
| `APP_TIMEZONE` | `Asia/Kolkata` | Default timezone for the uploaders. |
| `OSC_VIDEO_SCALE_ALGO` | `lanczos` | Fallback for the scaling algorithm (normally set from `--video-scale-algo`). |

Settings writable through the API (`PUT /api/settings`): `google_api_key`,
`pexels_api_key`, `hf_token`, `nvidia_api_key`, `default_clips`,
`default_ratio`, `default_font_style`, `default_whisper_model`,
`default_whisper_device`, `default_ai_provider`.

Serve the backend with `uvicorn app.web.api.app:app --host 0.0.0.0 --port 8000`
and open the static Studio pages from GitHub Pages, or locally with
`python -m http.server 8080 --directory docs`.
