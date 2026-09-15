# 📹 Video Quality & Rendering

This guide covers all the options for controlling video output quality, resolution, encoding, and sharpness.

---

## Resolution Pipeline

```
Source Video → Download (--source-height) → Render (--render-height) → Final Output
   4K/2K/1080p       max / 1440 / 1080         source / 1440 / 1080
```

### Source Download Height

Controls the maximum resolution downloaded from the source platform:

| Value | Description |
|---|---|
| `max` (default) | Fetch the highest available quality |
| `1080` | Cap at 1080p |
| `1440` | Cap at 2K (1440p) |
| `2160` | Cap at 4K (2160p) |

```bash
# Download highest quality available
python -m app.cli --url "VIDEO_URL" --source-height max

# Cap at 1440p to save bandwidth
python -m app.cli --url "VIDEO_URL" --source-height 1440
```

### Render Output Height

Controls the final output video height:

| Value | Description |
|---|---|
| `1080` (default) | Standard HD output |
| `1440` | 2K output |
| `2160` | 4K output |
| `source` | Match the source video height |

```bash
# Standard 1080p output
python -m app.cli --url "VIDEO_URL" --render-height 1080

# Native 2K rendering
python -m app.cli --url "VIDEO_URL" --source-height 1440 --render-height source
```

---

## Encoder Quality

### CQ (NVENC — NVIDIA GPU Encoder)

| Value | Quality | File Size |
|---|---|---|
| 15-18 | Ultra Sharp | Very Large |
| 19-22 | Sharp | Large |
| **23** (default) | **Standard** | **Balanced** |
| 24-28 | Soft | Small |
| 29-50 | Blurry | Very Small |

### CRF (libx264 — CPU Encoder)

| Value | Quality | File Size |
|---|---|---|
| 15-17 | Ultra Sharp | Very Large |
| 18-19 | Sharp | Large |
| **20** (default) | **Standard** | **Balanced** |
| 21-25 | Soft | Small |
| 26-50 | Blurry | Very Small |

```bash
# Ultra-sharp output
python -m app.cli --url "VIDEO_URL" --video-cq 19 --video-crf 17

# Smaller files (lower quality)
python -m app.cli --url "VIDEO_URL" --video-cq 28 --video-crf 25
```

---

## Encoder Preset

Controls the speed vs. quality tradeoff of the encoding process:

### NVENC Presets (GPU)
`p1` (fastest, lowest quality) → `p7` (slowest, highest quality). `auto` uses `p4`.

### x264 Presets (CPU)
`ultrafast` → `superfast` → `veryfast` → `faster` → `fast` → `medium` → `slow` → `slower` → `veryslow`

```bash
# Slow encoding for maximum quality
python -m app.cli --url "VIDEO_URL" --video-preset slow

# Fast encoding for quick preview
python -m app.cli --url "VIDEO_URL" --video-preset veryfast
```

> Use `auto` (default) to let the system choose the optimal preset.

---

## Bitrate

| Value | Description |
|---|---|
| `auto` (default) | Resolution-aware: 4M (below 1080p), 8M (1080p), 12M (1440p), 20M (2160p) |
| `8M` | Fixed 8 Mbps |
| `12M` | Fixed 12 Mbps |

```bash
# High bitrate for maximum quality
python -m app.cli --url "VIDEO_URL" --video-bitrate 12M
```

---

## Sharpening

Apply a subtle sharpening filter for clearer output:

```bash
python -m app.cli --url "VIDEO_URL" --video-sharpen
```

Best used in combination with high-resolution rendering:

```bash
# Ultra-HD 2K with sharpening
python -m app.cli --url "VIDEO_URL" \
  --source-height 1440 \
  --render-height source \
  --video-sharpen
```

---

## Scaling Algorithm

Controls how the video is resized during rendering:

| Algorithm | Description | Speed |
|---|---|---|
| `lanczos` (default) | Sharpest, preserves detail | Slowest |
| `bicubic` | Balanced quality | Medium |
| `bilinear` | Smooth but softer | Fast |
| `area` | Good for downscaling | Fast |

```bash
python -m app.cli --url "VIDEO_URL" --video-scale-algo lanczos
```

---

## How a Clip Is Rendered

Each clip is encoded twice: once for the framed video, then again when captions are burned in and the audio is mixed.

1. **Framing** — a single FFmpeg pass crops (the crop position is a time expression following the camera path), or blur-fills, and scales the
   source. Clips with B-roll inserts or a watermark use the frame-by-frame OpenCV renderer instead.
2. **Intermediate quality** — that first file uses the encoder's fastest preset at near-transparent quality (CQ/CRF 16,
   no bitrate cap), so the second encode does not compound compression artefacts.
3. **Final pass** — captions, loudness normalisation (−14 LUFS) and background music, at the `--video-cq` /
   `--video-crf` / `--video-bitrate` you choose.

The encoder test (NVENC → AMF → VAAPI → libx264) runs once per session and is reused for every clip part.

---

## Quality Presets (Recipes)

### Maximum Quality (Slow)
```bash
python -m app.cli --url "VIDEO_URL" \
  --source-height 2160 \
  --render-height source \
  --video-cq 18 \
  --video-crf 16 \
  --video-preset slow \
  --video-scale-algo lanczos \
  --video-sharpen \
  --video-bitrate 20M
```

### Standard Quality (Default)
```bash
python -m app.cli --url "VIDEO_URL"
# Uses: source-height max, render-height 1080, cq 23, crf 20, lanczos
```

### Fast Preview (Low Quality)
```bash
python -m app.cli --url "VIDEO_URL" \
  --source-height 1080 \
  --video-cq 30 \
  --video-crf 28 \
  --video-preset veryfast \
  --video-scale-algo bilinear
```

### TikTok/Reels Optimized
```bash
python -m app.cli --url "VIDEO_URL" \
  --source-height 1440 \
  --render-height 1080 \
  --video-cq 21 \
  --video-crf 19 \
  --video-sharpen
```

---

## See Also

- [CLI Reference](CLI-Reference) — Full list of quality flags
- [Google Colab Guide](Google-Colab-Guide) — Quality settings for cloud GPUs
