# Background Music (BGM) Library

The **Auto-BGM & Ducking** feature picks a track from this folder. Gemini tags every clip with one mood, and the
renderer chooses a random MP3 from the matching subfolder, mixes it quietly under the voice (`--bgm-volume`,
default `0.12`) and ducks it further while someone speaks.

| Folder | Use it for | Good fits |
|---|---|---|
| `chill/` | Calm advice, discussion, explanations — **most talking-head clips** | lo-fi, soft piano, light ambient |
| `epic/` | Ambition, triumph, big stakes | cinematic build-ups, trailer pads |
| `sad/` | Loss, struggle, regret | slow piano, strings |
| `upbeat/` | Light, funny or energetic moments | happy pop, funky/indie instrumentals |
| `suspense/` | Mystery, danger, a reveal | tense pulses, dark ambient |

If a mood folder is empty, the renderer falls back to `chill/`; if `chill/` is empty too, the clip renders without music.
`_unused/` is never read — tracks that did not suit spoken clips were moved there.

## What makes a good BGM track for clips

- **Instrumental only.** Vocals fight the speaker for attention and hurt caption readability.
- **Steady energy, no big drops or silences** — the clip can start anywhere in the track.
- **Mid/low frequencies, sparse arrangement**, so the voice stays on top after ducking.
- **2-3 tracks per mood**, so a long queue doesn't repeat the same song on every clip.

## Where to get music that is safe on YouTube

Use royalty-free libraries only. Trending songs from other creators' Shorts are almost always copyrighted and
lead to Content ID claims (muted or blocked videos) or copyright strikes.

1. **YouTube Audio Library** — safest for YouTube: YouTube Studio → **Audio Library**, filter by mood
   (Calm, Dramatic, Happy, Dark...) and prefer tracks marked *"No attribution required"*.
2. **Pixabay Music** — free for commercial use, no attribution:
   [chill](https://pixabay.com/music/search/mood/chill/) ·
   [epic](https://pixabay.com/music/search/mood/epic/) ·
   [upbeat](https://pixabay.com/music/search/mood/upbeat/)
3. **Incompetech** (Kevin MacLeod) — [incompetech.com](https://incompetech.com/music/royalty-free/music.html),
   requires attribution in the description.

## Using your own folder (Colab / Google Drive)

Keep your music out of the repo and point the pipeline at it — the folder needs the same mood subfolders:

```bash
python -m app.cli --url "https://..." --bgm-dir /content/drive/MyDrive/AutoCutClips/bgm --bgm-volume 0.12
```

In the Colab notebook, set `BGM_DIR` in the video queue cell.

## Folder layout

```text
assets/bgm/
├── chill/
│   ├── lofi-study-112191.mp3
│   └── calm-acoustic-2415.mp3
├── epic/
│   └── trailer-music-325357.mp3
├── sad/
├── suspense/
└── upbeat/
    └── happy-pop-307007.mp3
```
