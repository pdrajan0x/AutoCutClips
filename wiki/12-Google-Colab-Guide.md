# ☁️ Google Colab Guide

Google Colab's free T4 GPU runs the full pipeline. The ready-made notebook
[`notebooks/Lib_AutoCutClips.ipynb`](../notebooks/Lib_AutoCutClips.ipynb) does everything below — open it in Colab,
set **Runtime → Change runtime type → T4 GPU**, and run the sections in order.

---

## 1. Secrets

Add these in the 🔑 **Secrets** panel and enable notebook access:

| Secret | Needed for |
|---|---|
| `GOOGLE_API_KEY` | **Required** — Gemini clip selection |
| `PEXELS_API_KEY` | Optional — B-roll |
| `HF_TOKEN` | Optional — split-screen / camera-switch podcast modes |
| `YT_COOKIES` | Downloading from YouTube — contents of `cookies.txt` |
| `YOUTUBE_TOKEN_JSON` | Uploading — contents of `.credentials/youtube_token.json` |
| `YOUTUBE_CLIENT_SECRET_JSON` | Uploading — only to create the token inside Colab |

---

## 2. Cookies (downloading)

Colab's IP addresses usually get **"Sign in to confirm you're not a bot"** from YouTube. Pass a browser
cookies file to yt-dlp:

1. In a private browser window, log in to YouTube (a secondary account is safest).
2. Export `cookies.txt` in **Netscape format**, e.g. with the "Get cookies.txt LOCALLY" extension, then close the window.
3. Paste the file contents into the `YT_COOKIES` secret — or upload the file and point `COOKIES_PATH` at it.

The notebook writes the file and passes `--cookies` to every run. From the CLI:

```bash
python -m app.cli --url "https://www.youtube.com/watch?v=VIDEO_ID" --cookies cookies.txt
# or: export YTDLP_COOKIES_FILE=cookies.txt
```

> Cookies only authenticate **downloads**. They cannot upload to a channel — YouTube accepts uploads only
> through the Data API with an OAuth token (section 5).

---

## 3. Video queue

Put one link per line in a text file (`#` comments allowed) and run the queue. Every clip flag applies to each video:

```bash
python -m app.cli queue --links links.txt --clips 5 --ratio 9:16 --font-style DEFAULT --cookies cookies.txt
```

- Each video renders into `outputs/queue/<video-id>/`.
- `outputs/queue/queue_state.json` records progress: re-running skips finished videos; `--retry-failed` retries failed ones.
- Source videos are deleted after rendering to save disk space (`--keep-source` keeps them).
- `outputs/queue/queue_manifest.json` lists every clip from every video, **best first**.

Mount Google Drive and link `outputs/` to it (the notebook's `USE_DRIVE = True`) so a disconnect doesn't lose the
queue state or the upload history.

---

## 4. Review

The notebook prints every clip with its score and title, embeds small previews of the top clips, and can zip
all clips for download.

---

## 5. Upload to YouTube

Create the OAuth token once:

- **On your computer:** save your OAuth *Desktop app* client JSON as `.credentials/client_secret.json`, run
  `python -m app.cli youtube-token generate`, and paste `.credentials/youtube_token.json` into the
  `YOUTUBE_TOKEN_JSON` secret.
- **In Colab:** add the client JSON as `YOUTUBE_CLIENT_SECRET_JSON` and run
  `python -m app.cli youtube-token generate --manual` (or the notebook cell). Open the printed link, approve,
  copy the `http://localhost...` address the browser fails to load, and paste it back.

Then upload the combined queue manifest:

```bash
python -m app.cli upload-youtube \
  --manifest-file outputs/queue/queue_manifest.json \
  --updated-manifest outputs/queue/queue_manifest_uploaded.json \
  --result-file outputs/queue/youtube_upload_results.json \
  --interval-hours 24 --no-approval
```

Clips go up as private videos scheduled to publish later. `upload_safety.json` caps uploads per run and per day
and enforces a minimum gap; already-uploaded clips are skipped on the next run, so run the cell again later to
publish the rest.

---

## 6. Learn from your results

Once uploads have been public for a couple of days:

```bash
python -m app.cli learn-youtube
```

It saves each uploaded clip's views to `outputs/channel_performance.json` (on Drive when `USE_DRIVE = True`). Every
later queue run shows Gemini the channel's best and weakest clips, so selection leans towards what works for your
audience. It starts once at least 6 public clips are older than 48 hours.

---

## Tips

- **GPU memory:** use `--whisper-model medium` if `large-v3` runs out of memory.
- **Kaggle:** add `--whisper-compute-type float32`.
- **Runtime limits:** free sessions disconnect after inactivity — with Drive persistence the queue resumes where it stopped.

## See Also

- [YouTube Auto Upload](11-YouTube-Auto-Upload) — scheduling and safety rails
- [Video Quality & Rendering](9-Video-Quality-and-Rendering) — quality tuning
