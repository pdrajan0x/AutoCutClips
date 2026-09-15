"""
clipping.ytdl — Shared yt-dlp options.

Every YouTube request (source video, subtitles, glitch/transition assets) goes
through ``base_opts`` so a cookies file only has to be configured once.

YouTube blocks most datacenter IPs — Colab and Kaggle included — with
"Sign in to confirm you're not a bot". Passing an exported ``cookies.txt``
(Netscape format) from a logged-in browser session gets past that check.
The cookies only authenticate *downloads*; uploading uses the YouTube Data API
OAuth token instead (see ``app.uploaders.youtube_token``).
"""

import os

COOKIES_ENV = "YTDLP_COOKIES_FILE"


def resolve_cookies_file(cfg=None) -> str | None:
    """Return the cookies file from ``--cookies`` or $YTDLP_COOKIES_FILE, if it exists."""
    path = getattr(cfg, "cookies_file", None) or os.environ.get(COOKIES_ENV, "")
    path = os.path.expanduser(path.strip()) if path else ""
    if not path:
        return None
    if not os.path.isfile(path):
        print(f"⚠️ Cookies file not found: {path} — continuing without cookies.")
        return None
    return path


def base_opts(cfg=None, **extra) -> dict:
    """yt-dlp options shared by every download, with the cookies file applied."""
    opts = {"quiet": True, "no_warnings": True}
    cookies = resolve_cookies_file(cfg)
    if cookies:
        opts["cookiefile"] = cookies
    opts.update(extra)
    return opts
