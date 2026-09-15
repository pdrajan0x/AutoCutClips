# 🎯 Face Tracking & Auto-Framing

AutoCutClips frames every vertical clip (9:16, 1:1, 3:4, 4:5) automatically: it follows the person who is talking,
and fits footage without faces over a blurred background instead of cropping it.

---

## How It Works

1. **Detection** — faces are detected every `--track-step` seconds (default 0.25). Frames are read sequentially
   rather than seeking to each sample, which is much faster.
2. **Who to follow** — with one face, that face. With two or more, the face whose **mouth is moving** (see below).
3. **Smoothing** — the camera follows inside a deadzone with a catch-up factor, so small movements don't pan.
4. **Cuts** — a large jump (a camera cut or a new speaker) must persist for 0.5s before the camera cuts to it, and
   the cut is then placed where the jump began; the camera never whip-pans between two people.
5. **Missed detections** — a head turn or motion blur holds the last known position instead of jumping to the centre.
6. **Faceless footage** — if faces appear in less than 30% of the clip (slides, screen recordings, gameplay), the
   whole frame is fitted over a blurred, darkened copy of itself.

```
Source Frame (16:9)
┌─────────────────────────────────┐
│                                 │
│         ┌─────────┐             │
│         │  9:16   │             │
│         │  crop   │  ← Follows  │
│         │ window  │    the      │
│         │         │    speaker  │
│         └─────────┘             │
│                                 │
└─────────────────────────────────┘
```

---

## Following the Speaker

In a two-person podcast the largest face is often the listener. When two or more faces are in frame, a
[MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker) measures how far
each mouth is open. A speaking mouth opens and closes several times a second, a listening one barely moves, so the
face with the most mouth movement over a 1.5-second window is framed. A new speaker must lead for 1 second before the
camera moves, which stops it flickering on short interjections.

- No audio model and no HuggingFace token are needed; the landmarker model downloads automatically.
- Works best when both faces are reasonably large and facing the camera.
- For audio-based switching (who is actually heard), use `--camera-switch` with `HF_TOKEN` — see [Podcast Modes](Podcast-Modes).

```bash
# Turn speaker following off (follow faces by position only)
python -m app.cli --url "VIDEO_URL" --no-speaker-tracking
```

---

## Layout (`--layout`)

| Value | Behaviour |
|---|---|
| `auto` (default) | Face-tracked crop; blurred-background fill when the clip has few faces |
| `crop` | Always crop, even without faces |
| `blur` | Always fit the whole frame over a blurred background (skips face analysis) |

```bash
# Screen recording or slides
python -m app.cli --url "VIDEO_URL" --layout blur
```

---

## Face Detection Models

### MediaPipe BlazeFace (Default)

- **Flag**: `--face-detector mediapipe`
- **Device**: CPU only
- **Speed**: Fast and lightweight
- **Best for**: Standard single-speaker content
- **Model**: [BlazeFace Full-Range](https://ai.google.dev/edge/mediapipe/solutions/vision/face_detector)

### YOLOv8 ADetailer

- **Flag**: `--face-detector yolo`
- **Device**: GPU (CUDA) if available
- **Speed**: Slightly slower but more accurate
- **Best for**: Podcasts, multi-speaker, and profile-heavy scenarios
- **Sizes**: `8n` (nano), `8s` (small), `8m` (medium, default), `8n_v2`, `9c`

```bash
python -m app.cli --url "VIDEO_URL" --face-detector yolo --yolo-size 8m
```

---

## Tracking Parameters

| Parameter | Flag | Default | Description |
|---|---|---|---|
| **Detection Frequency** | `--track-step` | `0.25` | How often faces are checked (seconds). Lower = more responsive but heavier |
| **Deadzone** | `--track-deadzone` | `0.15` | Ratio of the "safe zone" where the camera doesn't move. Lower = tighter framing |
| **Smoothing** | `--track-smooth` | `0.30` | Camera catch-up speed. Higher = faster following |
| **Jitter Threshold** | `--track-jitter` | `5` | Pixel threshold to ignore micro-shakes |
| **Snap Threshold** | `--track-snap` | `0.08` | Fraction of the frame width a jump must exceed to count as a cut |

### Tuning for Different Scenarios

**Solo Speaker (Talking Head)**
```bash
--track-deadzone 0.10 --track-smooth 0.35
```

**Interview / 2 Speakers**
```bash
--track-deadzone 0.20 --track-smooth 0.25
```

**High-Energy / Active Movement**
```bash
--track-step 0.15 --track-deadzone 0.08 --track-smooth 0.40
```

---

## Advanced / Experimental Parameters (split-screen renderer)

| Parameter | Flag | Default | Description |
|---|---|---|---|
| **Confidence Threshold** | `--track-conf` | `0.55` | Raise to prevent ghost detections, lower if faces disappear |
| **Smooth Window** | `--track-smooth-window` | `12` | Frame window for layout stability (12 ≈ 0.5s at 24fps) |
| **Scene Cut Threshold** | `--scene-cut-threshold` | `18` | Sensitivity for camera cut detection. Range: 15-20 (dark/studio), 30-45 (bright) |
| **IOU Threshold** | `--track-iou-threshold` | `0.2` | Overlap threshold for merging duplicate face detections. Range: 0.1-0.5 |

---

## Aspect Ratios & Face Tracking

| Ratio | Resolution | Face Tracking | Best For |
|---|---|---|---|
| `9:16` | 1080×1920 | ✅ Always active | TikTok, Reels, YouTube Shorts |
| `16:9` | 1920×1080 | ❌ No (blurred fill if the source shape differs) | YouTube, Landscape |
| `1:1` | 1080×1080 | ✅ Active (disable with `--static-crop`) | Instagram Feed, Twitter/X |
| `3:4` | 1080×1440 | ✅ Active (disable with `--static-crop`) | Instagram Portrait, Pinterest |
| `4:5` | 1080×1350 | ✅ Active (disable with `--static-crop`) | Instagram/Facebook Feed |

---

## Static Crop Mode

If you don't need face tracking for square/portrait ratios, use `--static-crop`:

```bash
python -m app.cli --url "VIDEO_URL" --ratio "1:1" --static-crop
```

This skips face detection entirely.

---

## Rendering

The framing is rendered in a single FFmpeg pass — the crop position is a time expression that follows the camera path — unless a clip has B-roll
inserts or a watermark, which need the frame-by-frame OpenCV renderer. If FFmpeg rejects the fast path, the frame
renderer takes over automatically.

---

## See Also

- [Podcast Modes](Podcast-Modes) — Split-screen and diarization-based camera-switch
- [Video Quality & Rendering](Video-Quality-and-Rendering) — High-resolution rendering options
