# 📤 YouTube Auto-Upload

AutoCutClips includes a standalone YouTube auto-uploader with scheduling support, allowing you to automatically publish generated clips with full metadata.

---

## Prerequisites

1. A Google Cloud project with the **YouTube Data API v3** enabled
2. An OAuth 2.0 token (`.credentials/youtube_token.json`) generated for your YouTube channel
3. Generated clips in the `outputs/` directory with a `render_manifest.json`

> **First time?** Follow the complete **[YouTube API Setup Guide](YouTube-API-Setup-Guide)** for step-by-step instructions with screenshots on creating your Google Cloud project, OAuth credentials, and generating the token.

---

## Setup

### 1. Generate the YouTube Token

Run the token generator to authenticate your YouTube account:

```bash
python -m app.uploaders.youtube_token generate
# or, if installed as a console script:
clipping-youtube-token generate
```

This opens a browser window for Google OAuth (requesting the
`youtube.upload` and `youtube.readonly` scopes) and, after you authorize it,
writes `.credentials/youtube_token.json` directly — there's no manual move
step. The client secret must already exist at
`.credentials/client_secret.json` (see the [YouTube API Setup
Guide](YouTube-API-Setup-Guide)).

### 2. Verify the Token (optional)

```bash
python -m app.uploaders.youtube_token verify
```

Refreshes the stored token and prints the channel it resolves to, so you can
confirm the credentials work before uploading anything.

---

## Usage

### Basic Upload

After rendering clips, run:

```bash
python -m app.cli upload-youtube
# or:
clipping-upload-youtube
```

This will:
1. Read `outputs/render_manifest.json` for clip metadata
2. Prompt for manual approval before each upload (unless `--no-approval` is passed)
3. Upload each clip to YouTube with AI-generated titles, descriptions, and tags
4. Schedule uploads at 24-hour intervals by default, subject to the
   `upload_safety.json` safety rails (max uploads per run/day, minimum
   interval, max scheduled queue)

### Custom Scheduling

```bash
# 12-hour intervals with India timezone
python -m app.cli upload-youtube --interval-hours 12 --tz-name "Asia/Kolkata"

# Test with only the first pending video
python -m app.cli upload-youtube --test-mode

# Manual first publish time, bypassing queue detection
python -m app.cli upload-youtube --start-local "2026-01-01 08:00"
```

### All Options

```bash
python -m app.cli upload-youtube --help
```

Key flags: `--token-file` (default `.credentials/youtube_token.json`),
`--manifest-file` (default `outputs/render_manifest.json`), `--result-file`,
`--updated-manifest`, `--tz-name` (defaults to the `APP_TIMEZONE` env var, or
`Asia/Kolkata`), `--interval-hours` (default `24`), `--start-local`,
`--test-mode`, `--safety-config` (default `upload_safety.json`), and
`--no-approval` to skip the manual confirmation prompt (⚠️ not recommended for
a channel recovering from a strike). See the [CLI Arguments
Reference](CLI-Arguments-Reference) for the full list.

---

## Safety Config (`upload_safety.json`)

The uploader reads a JSON file (default `upload_safety.json` in the repo
root) that gates how aggressively it's allowed to publish:

```json
{
  "$schema": "upload_safety_v1",
  "max_upload_per_run": 1,
  "max_upload_per_day": 2,
  "interval_hours_min": 24,
  "max_scheduled_queue": 7,
  "require_manual_approval": true,
  "upload_log_file": "outputs/upload_history.json"
}
```

| Key | Meaning |
|---|---|
| `max_upload_per_run` | Maximum clips uploaded in a single invocation |
| `max_upload_per_day` | Maximum clips uploaded within a rolling 24h window |
| `interval_hours_min` | Minimum enforced gap between scheduled publishes |
| `max_scheduled_queue` | Maximum number of videos allowed to sit in the scheduled queue at once |
| `require_manual_approval` | Whether to prompt for confirmation before each upload |
| `upload_log_file` | Where the upload history is recorded |

---

## Metadata

The uploader uses the AI-generated metadata from `metadata_preview.json` /
`render_manifest.json`:

- **Title** — YouTube-optimized title
- **Description** — SEO-friendly description with relevant context
- **Tags** — Keyword tags for discoverability
- **TikTok Caption** — Also generated for cross-platform publishing

---

## Rescheduling Already-Uploaded Videos

Need to re-space videos that are still `private` and scheduled in the
future? Use the reschedule subcommand — it lists them, re-computes new
publish times at a new interval, and by default runs as a **dry-run**:

```bash
# Dry-run (prints the plan, changes nothing)
python -m app.cli reschedule-youtube

# Actually apply the new schedule
python -m app.cli reschedule-youtube --apply

# Custom interval and start time
python -m app.cli reschedule-youtube --interval-hours 2 --start-local "2026-08-22 08:00" --apply
```

This calls `videos.update`, which needs a broader OAuth scope than plain
uploading — see the *Rescheduling requires a wider scope* note below.

### Rescheduling requires a wider scope

The token generated for uploading only has `youtube.upload` +
`youtube.readonly`, which is **not** enough to update a video's schedule.
To reschedule, add `https://www.googleapis.com/auth/youtube.force-ssl` to
`YOUTUBE_SCOPES` in `app/uploaders/youtube.py`, delete
`.credentials/youtube_token.json`, and re-run
`python -m app.uploaders.youtube_token generate` so the new token carries the
update permission.

---

## Troubleshooting

| Issue | Solution |
|---|---|
| Token expired or revoked | Re-run `python -m app.uploaders.youtube_token generate` |
| API quota exceeded | Wait 24 hours or use a different Google Cloud project |
| Rate limited (429) | Increase `--interval-hours` between uploads |
| Upload fails silently | Check `outputs/render_manifest.json` for valid file paths |
| `reschedule-youtube` fails on `videos.update` | Token is missing the `youtube.force-ssl` scope — see above |

---

## See Also

- [Getting Started](Getting-Started) — Initial setup
- [YouTube API Setup Guide](YouTube-API-Setup-Guide) — Full OAuth walkthrough
- [Instagram Reels Uploader](Instagram-Reels-Uploader) — The equivalent uploader for Instagram
- [CLI Arguments Reference](CLI-Arguments-Reference) — Full flag list
