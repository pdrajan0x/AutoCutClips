"""
clipping.ytdl — Shared yt-dlp options.

Every YouTube request (source video, subtitles, glitch/transition assets) goes
through ``base_opts`` so a cookies file only has to be configured once.

YouTube blocks most datacenter IPs — Colab and Kaggle included — with
"Sign in to confirm you're not a bot". Passing an exported ``cookies.txt``
(Netscape format) from a logged-in browser session gets past that check.
The cookies only authenticate *downloads*; uploading uses the YouTube Data API
OAuth token instead (see ``app.uploaders.youtube_token``).

yt-dlp also needs a JavaScript runtime to solve YouTube's signature/nsig
challenges. Without one it silently drops the formats it cannot decrypt, which
surfaces as "Requested format is not available" rather than anything mentioning
JavaScript. yt-dlp only enables Deno by default, so every runtime it supports is
enabled here instead — Colab/Kaggle images usually carry Node, not Deno.
"""

import os

COOKIES_ENV = "YTDLP_COOKIES_FILE"

# yt-dlp's own minimums: deno>=2.3.0, node>=22.0.0, bun>=1.2.11, quickjs>=2023.12.9.
# Listing a runtime that is absent or too old is harmless — it just probes the
# next one — so enable all of them and let whatever is installed win.
JS_RUNTIMES = {"deno": {}, "node": {}, "bun": {}, "quickjs": {}}


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
    opts = {
        "quiet": True,
        "no_warnings": True,
        "js_runtimes": dict(JS_RUNTIMES),
        # Solving YouTube's challenges needs the EJS solver script as well as a
        # runtime to execute it; without this yt-dlp refuses to fetch it.
        "remote_components": ["ejs:github"],
        # A "watch?v=...&list=..." link is one video; playlists are expanded
        # into separate jobs by the web API instead.
        "noplaylist": True,
    }
    cookies = resolve_cookies_file(cfg)
    if cookies:
        opts["cookiefile"] = cookies
    opts.update(extra)
    return opts


_RUNTIME_CACHE: dict = {}


def reset_runtime_cache() -> None:
    """Forget the probe result, after installing a runtime mid-process."""
    _RUNTIME_CACHE.clear()


def available_js_runtime() -> str | None:
    """Name of the first usable JS runtime, or None when yt-dlp can't find one."""
    # Probing shells out to each runtime; the answer cannot change mid-run, and a
    # queue would otherwise repeat four subprocess probes per video.
    if "name" in _RUNTIME_CACHE:
        return _RUNTIME_CACHE["name"]

    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        _RUNTIME_CACHE["name"] = None
        return None

    found = None
    try:
        with YoutubeDL({"quiet": True, "no_warnings": True, "js_runtimes": dict(JS_RUNTIMES)}) as ydl:
            for name, runtime in ydl._js_runtimes.items():
                info = getattr(runtime, "info", None) if runtime is not None else None
                if info is not None and getattr(info, "supported", False):
                    found = name
                    break
    except Exception:
        # Private yt-dlp internals; a future release renaming them must not be
        # able to break downloads, since this only drives a diagnostic message.
        found = None

    _RUNTIME_CACHE["name"] = found
    return found
