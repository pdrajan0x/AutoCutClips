# 📱 Instagram Reels Uploader

AutoCutClips includes a standalone Instagram Reels auto-publisher built on the
**Instagram Graph API**. It replaces the project's older Facebook Page Reels
uploader — there is no Facebook Page uploader anymore, and publishing now
targets an Instagram Business/Creator account directly.

---

## Prerequisites

1. An **Instagram Business or Creator account**, linked to a Facebook Page.
2. A **long-lived access token** with the `instagram_content_publish`
   permission for that account.
3. The account's **Instagram User ID** (not the Facebook Page ID).
4. Generated clips in `outputs/` with a `render_manifest.json` (produced by
   the clip/story pipeline).

---

## Setup

Add these to your `.env` file (see `.env.sample`):

```env
IG_USER_ID=your-instagram-user-id
IG_ACCESS_TOKEN=your-long-lived-access-token
IG_GRAPH_VERSION=v25.0            # Optional, defaults to v25.0
IG_PUBLIC_BASE_URL=https://your-domain.example/clips   # Optional
APP_TIMEZONE=Asia/Jakarta         # Optional, used for interval scheduling
```

| Variable | Required | Description |
|---|---|---|
| `IG_USER_ID` | ✅ | Instagram **User** ID of the Business/Creator account. |
| `IG_ACCESS_TOKEN` | ✅ | Token with the `instagram_content_publish` permission. Falls back to `META_PAGE_ACCESS_TOKEN` if set, for backwards compatibility with older `.env` files. |
| `IG_GRAPH_VERSION` | ❌ | Graph API version, default `v25.0`. Falls back to `META_GRAPH_VERSION`. |
| `IG_PUBLIC_BASE_URL` | ❌ | Public base URL that serves your rendered clips. When set, the uploader passes a `video_url` and lets Instagram fetch the file directly (remote mode) instead of uploading the bytes itself (local/resumable mode). |
| `APP_TIMEZONE` | ❌ | Default timezone (IANA name) used for `--tz-name` on this and the other uploaders. |

> **Backwards compatibility:** the older `META_PAGE_ACCESS_TOKEN` and
> `META_GRAPH_VERSION` variables from a Facebook-era `.env` file still work as
> fallbacks for `IG_ACCESS_TOKEN` / `IG_GRAPH_VERSION`, but there is no
> `META_PAGE_ID` equivalent — Instagram publishing only needs the Instagram
> User ID.

---

## Usage

After rendering clips, run:

```bash
python -m app.cli upload-instagram
# or, if installed as a console script:
clipping-upload-instagram
```

This will:
1. Validate the access token against the Graph API.
2. Read `outputs/render_manifest.json` (or a previous
   `outputs/render_manifest_ig_uploaded.json` run, if present) for pending clips.
3. Re-check any container left mid-flight from an earlier run.
4. Publish each pending clip as a Reel, respecting the 24h publish quota and
   the configured interval.

### Options

| Argument | Default | Description |
|---|---|---|
| `--manifest-file` | `outputs/render_manifest.json` | Input manifest from the clipping pipeline |
| `--result-file` | `outputs/ig_upload_results.json` | Output JSON trace of the publish responses |
| `--updated-manifest` | `outputs/render_manifest_ig_uploaded.json` | Output manifest enriched with publish results |
| `--tz-name` | `$APP_TIMEZONE` or `Asia/Makassar` | Timezone used for the interval maths (IANA name) |
| `--interval-hours` | `5` | Minimum gap between publishes; later clips are deferred to a future run |
| `--test-mode` | `False` | Publish only the first pending item, for testing |
| `--publish-now` | `False` | Ignore `--interval-hours` and publish the whole batch back to back |

```bash
# Test with only the first clip
python -m app.cli upload-instagram --test-mode

# Custom interval (3 hours between Reels)
python -m app.cli upload-instagram --interval-hours 3 --tz-name "Asia/Jakarta"

# Publish everything immediately, ignoring the interval
python -m app.cli upload-instagram --publish-now

# See all options
python -m app.cli upload-instagram --help
```

---

## Publishing Flow

The uploader follows the Instagram Graph API's three-step Reels flow:

1. **Create a media container** — `POST /{ig-user-id}/media` with
   `media_type=REELS`, the caption, and `share_to_feed`.
   - **Remote mode**: if `IG_PUBLIC_BASE_URL` is set (or the manifest row has
     an explicit `ig_video_url`/`public_video_url`), a `video_url` is passed
     and Instagram fetches the file itself.
   - **Local (resumable) mode**: otherwise the container is opened with
     `upload_type=resumable` and the clip's bytes are POSTed directly to
     `rupload.facebook.com`.
2. **Poll the container** — `GET /{container-id}?fields=status_code` until
   the status is `FINISHED` (or up to 300 seconds; `ERROR`/`EXPIRED` raise
   immediately).
3. **Publish** — `POST /{ig-user-id}/media_publish` with the container's
   `creation_id`.

If a container is still processing when a run ends, it is recorded with a
`processing` status and re-checked (and published, if ready) automatically on
the next run.

---

## Scheduling — Local, Not Native

> **Important:** the Instagram Graph API has **no** scheduled-publish
> parameter — a publish goes live immediately once step 3 above completes.

`--interval-hours` is therefore enforced **locally**: the uploader looks at
the most recent `ig_published_at_utc` timestamp in the manifest and, if a
clip's turn hasn't arrived yet, marks it `deferred` with a `next_slot`
instead of publishing it. Run the command again later (e.g. from cron) and
it will publish whatever clips have become due. Pass `--publish-now` to
skip this and publish the whole pending batch back to back.

---

## Rate Limits

The Instagram content-publishing API allows **50 API-published posts per
rolling 24-hour window**. The uploader counts how many clips it has
published (via recorded `ig_published_at_utc` timestamps) in the last 24
hours and stops before exceeding the limit; if fewer slots remain than
pending clips, only that many are published in the run.

Captions are also truncated to Instagram's **2200-character** Reels caption
limit.

---

## Status Fields Written to the Manifest

Each processed row in the updated manifest gets:

| Field | Meaning |
|---|---|
| `ig_upload_status` | `published`, `processing`, `deferred`, or `failed` |
| `ig_container_id` | The Graph API media container ID |
| `ig_media_id` | The published media ID (once live) |
| `ig_container_status` | Last known container `status_code` |
| `ig_caption` | The caption actually sent |
| `ig_published_at_utc` | Publish timestamp, once published |
| `ig_next_slot_local` | The next eligible local time, if deferred |
| `ig_upload_error` | Error message, if the publish failed |

A batch **stops at the first failure** rather than continuing to hammer the
API — re-run the command after fixing the issue to resume from where it left
off.

---

## See Also

- [YouTube Auto-Upload](YouTube-Auto-Upload) — The equivalent uploader for YouTube
- [CLI Arguments Reference](CLI-Arguments-Reference) — Full flag list for every entry point
