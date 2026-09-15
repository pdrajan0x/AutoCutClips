# ✂️ Segment Trimming & Hook Teaser

Two ways to keep viewers watching past the first seconds: cut the dead weight out of the clip, and (optionally)
open with a flash-forward to its best line.

---

## Final Video Structure

```
[Hook Teaser (optional)] → [Voice-over intro (optional)] → [MAIN CLIP] → done
         ↑                                                       ↑
   peak line, clean cut                          affected by Segment Trimming
```

---

## Segment Trimming

Segment Trimming applies to the main clip. Gemini marks the parts that carry the idea as `keep_segments`; tangents,
false starts and long pauses are **cut out** (not sped up) and the kept parts are joined back to back.

```
Example:
  Main clip: second 30 - 90 (60 seconds total)

  AI finds:
    ✅ Second 30-55 : strong content, engaging
    ❌ Second 55-58 : speaker pauses/filler (removed)
    ✅ Second 58-90 : strong punchline

  Result: segment 1 + segment 2 joined directly
  Final duration: 57 seconds (3 seconds of filler removed)
```

Every cut is a visible jump cut, so the AI is told to cut only filler longer than about 2 seconds, never inside a
sentence, and to use at most 4 segments. Segment edges are snapped to word boundaries, and a trim that would leave
the clip shorter than `--min-duration` is ignored (the full clip renders instead).

### Trimming Modes

| Flag | Behavior |
|---|---|
| *(default, no flag)* | AI trims clear filler and tangents |
| `--silence-trim` | AI trims aggressively — pauses over 0.5s are removed |
| `--no-segment-trim` | No trimming, full start-to-end render |

```bash
# Default: AI smart-trim
python -m app.cli --url "VIDEO_URL"

# Aggressive silence removal
python -m app.cli --url "VIDEO_URL" --silence-trim

# No trimming (full render)
python -m app.cli --url "VIDEO_URL" --no-segment-trim
```

---

## Hook Teaser (`--hook-teaser`)

By default every clip opens directly on its strongest sentence — short-form viewers decide within 1-2 seconds, so
the clip itself is the hook.

With `--hook-teaser`, the renderer first plays a ~`--hook-duration` second **flash-forward**: the most intense line
from later in the clip, followed by a clean cut to the clip's start. Gemini is then told to pick the hook from the
clip's peak rather than its first sentence. If the chosen line opens the clip anyway, the teaser is skipped so the
line is not heard twice.

```bash
python -m app.cli --url "VIDEO_URL" --hook-teaser --hook-duration 4
```

### Custom Hook Source

Play your own clip as the teaser (captions are skipped to keep the original look):

```bash
# Local .mp4
python -m app.cli --url "VIDEO_URL" --hook-source "/path/to/hook.mp4" --hook-source-start 5.0 --hook-duration 4

# Google Drive link
python -m app.cli --url "VIDEO_URL" --hook-source "DRIVE_URL" --hook-source-start 2.0
```

> The older multi-hook intro (`--hook-v2`) and the downloaded TV-glitch transition were removed in v1.15.0.

---

## See Also

- [CLI Reference](CLI-Reference) — Full flag details
- [Subtitles & Typography](Subtitles-and-Typography) — Captions and the on-screen headline
