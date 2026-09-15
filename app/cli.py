#!/usr/bin/env python3
"""
app.cli — Command-line entry points for AutoCutClips.

Clip / story mode (the default — flags are parsed by clipping.config):
    python -m app.cli --url "https://..."
    python -m app.cli --url "https://..." --clips 5 --ratio 16:9
    python -m app.cli --story-mode --story-recipe story_recipe.json
    python -m app.cli --help

Video queue (one URL per line in a text file; clip flags apply to every video):
    python -m app.cli queue --links links.txt [--retry-failed] --clips 5 --ratio 9:16

Publishing and maintenance subcommands:
    python -m app.cli upload-youtube        [--test-mode ...]
    python -m app.cli upload-instagram      [--test-mode ...]
    python -m app.cli reschedule-youtube    [--apply ...]
    python -m app.cli youtube-token         generate | verify
    python -m app.cli learn-youtube         [--output ...]

Each subcommand is also installed as its own console script — see
[project.scripts] in pyproject.toml.
"""

import argparse
import os
import sys

VERSION = "1.12.0"
DEFAULT_TZ_ENV = "APP_TIMEZONE"
DEFAULT_TZ = "Asia/Kolkata"

# The pipeline logs emoji throughout; on a legacy-codepage console (Windows
# cp1252) that raises UnicodeEncodeError mid-render and kills the run.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def _default_tz() -> str:
    return os.environ.get(DEFAULT_TZ_ENV, DEFAULT_TZ).strip() or DEFAULT_TZ


def _banner(title: str, rows: list[tuple[str, object]] | None = None) -> None:
    print("=" * 70)
    print(title)
    print("=" * 70)
    for label, value in rows or []:
        print(f"   {label:<12}: {value}")
    if rows:
        print("=" * 70)


def _on_off(flag: bool) -> str:
    return "ON" if flag else "OFF"


# ==============================================================================
# CLIP / STORY PIPELINE
# ==============================================================================

def _print_story_summary(cfg) -> None:
    _banner(
        f"🎬 AutoCutClips v{VERSION} — Story Clip Mode",
        [
            ("Recipe", cfg.story_recipe_path),
            ("Sources", cfg.sources_json_path),
            ("Ratio", cfg.aspect_ratio),
            ("Output Dir", cfg.story_output_dir),
            ("Skip DL", "YES" if cfg.skip_download else "NO"),
        ],
    )


def _print_clip_summary(cfg) -> None:
    platform_labels = {
        "youtube": "YouTube",
        "tiktok": "TikTok",
        "instagram": "Instagram",
        "gdrive": "Google Drive",
    }
    platform_key = getattr(cfg, "source_platform", "youtube")

    rows = [
        ("Source", platform_labels.get(platform_key, platform_key)),
        ("URL", cfg.url_youtube),
        ("Clips", cfg.clip_count),
        ("Ratio", cfg.aspect_ratio),
        ("Clip Length", f"{cfg.min_clip_duration:g}-{cfg.max_clip_duration:g}s"),
        ("Font Style", cfg.active_font_style),
        ("Subtitles", _on_off(not cfg.no_subs)),
        ("B-Roll", _on_off(cfg.use_broll)),
        ("Hook Teaser", _on_off(getattr(cfg, "hook_teaser", False))),
        ("BGM", _on_off(cfg.use_auto_bgm)),
        ("Karaoke", _on_off(cfg.use_karaoke_effect)),
        ("Split-Screen", _on_off(cfg.use_split_screen)),
        ("Camera-Switch", _on_off(getattr(cfg, "use_camera_switch", False))),
    ]
    if cfg.use_split_screen:
        rows += [
            ("Dyn. Split", _on_off(cfg.use_dynamic_split)),
            ("Split Trig.", cfg.split_trigger),
        ]
    rows += [
        ("Whisper", f"{cfg.whisper_model} ({cfg.whisper_device})"),
        ("Language", f"{getattr(cfg, 'whisper_language', 'auto')} — captions in "
                     f"{'original script' if getattr(cfg, 'caption_script', 'latin') == 'native' else 'English letters'}"),
        ("Gemini", cfg.gemini_model),
    ]
    if getattr(cfg, "watermark_enabled", False):
        wm_type = "Text" if cfg.watermark_text else "Image"
        rows += [
            ("Watermark", f"ON ({wm_type}: {cfg.watermark_text or cfg.watermark_image or '-'})"),
            ("WM Opacity", f"{cfg.watermark_opacity}%"),
            ("WM Position", cfg.watermark_position),
            ("WM Padding", f"{cfg.watermark_padding}px"),
        ]
        if cfg.watermark_image:
            rows.append(
                ("WM Scale", f"{getattr(cfg, 'watermark_scale', 15)}% of frame height")
            )

    _banner(f"🎬 AutoCutClips v{VERSION}", rows)


def _preflight_warnings(cfg) -> list[str]:
    """
    Report requested features that will silently degrade, before any work runs.

    These used to surface only part-way through the pipeline — after the
    download, transcription and AI call had already been paid for.
    """
    warnings: list[str] = []

    wants_diarization = getattr(cfg, "use_camera_switch", False) or (
        getattr(cfg, "use_split_screen", False)
        and getattr(cfg, "split_trigger", "diarization") == "diarization"
    )
    if wants_diarization and not cfg.hf_token:
        mode = "--camera-switch" if getattr(cfg, "use_camera_switch", False) else "--split-screen"
        warnings.append(
            f"{mode} needs HF_TOKEN for speaker diarization, which is not set — "
            "the run will fall back to the standard single-frame render.\n"
            "     Set HF_TOKEN in your .env, and accept the model agreement at\n"
            "     https://huggingface.co/pyannote/speaker-diarization-3.1\n"
            "     (--split-screen can instead use --split-trigger face, which needs no token.)"
        )

    if getattr(cfg, "use_broll", False) and not getattr(cfg, "pexels_api_key", ""):
        warnings.append(
            "B-roll is enabled but PEXELS_API_KEY is not set — clips will render "
            "without stock footage. Pass --no-broll to silence this."
        )

    ratio = getattr(cfg, "aspect_ratio", "9:16")
    if getattr(cfg, "use_camera_switch", False) and getattr(cfg, "use_split_screen", False):
        warnings.append(
            "--camera-switch and --split-screen were both given; split-screen wins."
        )

    vertical = {"9:16", "1:1", "3:4", "4:5"}
    if (
        getattr(cfg, "use_camera_switch", False) or getattr(cfg, "use_split_screen", False)
    ) and ratio not in vertical:
        warnings.append(
            f"Podcast modes only apply to vertical ratios {sorted(vertical)}; "
            f"--ratio {ratio} will render normally."
        )

    return warnings


def clip(argv: list[str] | None = None) -> None:
    """Run the auto-clip pipeline, or story mode when --story-mode is set."""
    from .clipping.config import build_config

    cfg = build_config(sys.argv[1:] if argv is None else argv)

    if getattr(cfg, "story_mode", False):
        from .clipping.story_runner import run_story_pipeline

        _print_story_summary(cfg)
        run_story_pipeline(cfg)
        print("\n✅ Done! Every story clip has been rendered.")
        return

    if not cfg.api_key_gemini:
        print("❌ ERROR: the GOOGLE_API_KEY environment variable is not set.")
        print("   Set it with: export GOOGLE_API_KEY='your-key' — or create a .env file.")
        sys.exit(1)

    # Imported late so --help works without the heavy render dependencies.
    from .clipping.runner import run_pipeline

    _print_clip_summary(cfg)

    for warning in _preflight_warnings(cfg):
        print(f"\n⚠️  {warning}")
    print()

    run_pipeline(cfg)
    print("\n✅ Done! Every clip has been rendered.")


# ==============================================================================
# YOUTUBE UPLOAD
# ==============================================================================

def _youtube_upload_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clipping-upload-youtube",
        description="🚀 AutoCutClips — YouTube auto-uploader & scheduler",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--token-file", default=".credentials/youtube_token.json",
                   help="Path to the YouTube OAuth token (JSON)")
    p.add_argument("--manifest-file", default="outputs/render_manifest.json",
                   help="Input manifest from the clipping pipeline")
    p.add_argument("--result-file", default="outputs/youtube_upload_results.json",
                   help="Output JSON trace file for the upload responses")
    p.add_argument("--updated-manifest", default="outputs/render_manifest_uploaded.json",
                   help="Output manifest enriched with the upload results")
    p.add_argument("--tz-name", default=_default_tz(),
                   help="Timezone used for scheduling (IANA name)")
    p.add_argument("--interval-hours", type=int, default=24,
                   help="Gap between scheduled publishes (the safety config enforces a minimum)")
    p.add_argument("--start-local", default=None,
                   help="Manual first publish time (YYYY-MM-DD HH:MM), bypassing queue detection")
    p.add_argument("--test-mode", action="store_true",
                   help="Upload only the FIRST pending item, for testing")

    group = p.add_argument_group("Safety Options")
    group.add_argument("--safety-config", default="upload_safety.json",
                      help="Path to the upload safety config JSON")
    group.add_argument("--no-approval", action="store_true",
                      help="Skip the manual approval prompt (⚠️ risky — not recommended "
                           "for a channel recovering from a strike)")
    return p


def upload_youtube(argv: list[str] | None = None) -> None:
    """Upload the render manifest to YouTube."""
    from .uploaders.youtube import upload_manifest_to_youtube
    from .uploaders.youtube_safety import load_safety_config

    args = _youtube_upload_parser().parse_args(
        sys.argv[1:] if argv is None else argv
    )

    _banner("🚀 YouTube Uploader")

    creds_dir = os.path.dirname(args.token_file)
    if creds_dir:
        os.makedirs(creds_dir, exist_ok=True)

    if not os.path.exists(args.token_file):
        print(f"❌ ERROR: credentials file not found at '{args.token_file}'.")
        print("   Generate it with: python -m app.uploaders.youtube_token generate")
        sys.exit(1)

    if args.no_approval:
        print("\n⚠️  WARNING: manual approval is disabled (--no-approval).")
        print("   Every video will be uploaded without confirmation.")
        print("   This is NOT RECOMMENDED for a channel that has been banned before.\n")

    upload_manifest_to_youtube(
        token_file=args.token_file,
        manifest_file=args.manifest_file,
        result_file=args.result_file,
        updated_manifest_file=args.updated_manifest,
        tz_name=args.tz_name,
        interval_hours=args.interval_hours,
        start_local=args.start_local,
        test_mode=args.test_mode,
        safety_config=load_safety_config(args.safety_config),
        skip_approval=args.no_approval,
    )

    print("\n✅ The YouTube upload run has finished.")


# ==============================================================================
# INSTAGRAM UPLOAD
# ==============================================================================

def _instagram_upload_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clipping-upload-instagram",
        description="AutoCutClips — Instagram Reels auto-uploader",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--manifest-file", default="outputs/render_manifest.json",
                   help="Input manifest from the clipping pipeline")
    p.add_argument("--result-file", default="outputs/ig_upload_results.json",
                   help="Output JSON trace file for the upload responses")
    p.add_argument("--updated-manifest", default="outputs/render_manifest_ig_uploaded.json",
                   help="Output manifest enriched with the publish results")
    p.add_argument("--tz-name", default=_default_tz(),
                   help="Timezone used for the interval maths (IANA name)")
    p.add_argument("--interval-hours", type=int, default=5,
                   help="Minimum gap between publishes; later clips are deferred to a future run")
    p.add_argument("--test-mode", action="store_true",
                   help="Publish only the FIRST pending item, for testing")
    p.add_argument("--publish-now", action="store_true",
                   help="Ignore --interval-hours and publish the whole batch back to back")
    return p


def upload_instagram(argv: list[str] | None = None) -> None:
    """Publish the render manifest to Instagram as Reels."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from .uploaders.instagram import upload_manifest_to_instagram

    args = _instagram_upload_parser().parse_args(
        sys.argv[1:] if argv is None else argv
    )

    _banner("🚀 Instagram Reels Uploader")

    missing = [
        name for name in ("IG_USER_ID", "IG_ACCESS_TOKEN")
        if not os.environ.get(name)
    ]
    # The Facebook-era token variable is still accepted for IG_ACCESS_TOKEN.
    if "IG_ACCESS_TOKEN" in missing and os.environ.get("META_PAGE_ACCESS_TOKEN"):
        missing.remove("IG_ACCESS_TOKEN")

    if missing:
        for name in missing:
            print(f"❌ ERROR: {name} is not set.")
        print("   Add them to your .env file or export them as environment variables.")
        sys.exit(1)

    upload_manifest_to_instagram(
        manifest_file=args.manifest_file,
        result_file=args.result_file,
        updated_manifest_file=args.updated_manifest,
        tz_name=args.tz_name,
        interval_hours=args.interval_hours,
        test_mode=args.test_mode,
        publish_now=args.publish_now,
    )

    print("\n✅ The Instagram upload run has finished.")


# ==============================================================================
# DISPATCH
# ==============================================================================

def reschedule_youtube(argv: list[str] | None = None) -> None:
    """Re-space the channel's scheduled videos onto a new interval."""
    from .uploaders.youtube_reschedule import main as _main

    _main(argv)


def youtube_token(argv: list[str] | None = None) -> None:
    """Create or verify the YouTube OAuth token."""
    from .uploaders.youtube_token import main as _main

    _main(argv)


def _learn_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clipping-learn-youtube",
        description="📈 AutoCutClips — fetch views for uploaded clips, so clip selection "
        "learns what works on your channel",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--token-file", default=".credentials/youtube_token.json",
                   help="Path to the YouTube OAuth token (JSON)")
    p.add_argument("--history-file", default=None,
                   help="Upload history written by upload-youtube "
                        "(default: upload_log_file from the safety config)")
    p.add_argument("--safety-config", default="upload_safety.json",
                   help="Safety config that names the upload history file")
    p.add_argument("--output", default="outputs/channel_performance.json",
                   help="Where to save the results; clip runs read this path by default")
    return p


def learn_youtube(argv: list[str] | None = None) -> None:
    """Fetch statistics for uploaded clips into channel_performance.json."""
    from .uploaders.performance import refresh_channel_performance

    args = _learn_parser().parse_args(sys.argv[1:] if argv is None else argv)

    if not os.path.exists(args.token_file):
        print(f"❌ ERROR: credentials file not found at '{args.token_file}'.")
        print("   Generate it with: python -m app.cli youtube-token generate")
        sys.exit(1)

    history_file = args.history_file
    if not history_file:
        from .uploaders.youtube_safety import load_safety_config

        history_file = load_safety_config(args.safety_config)["upload_log_file"]

    _banner("📈 Channel results")
    refresh_channel_performance(args.token_file, history_file, args.output)


def _queue_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clipping queue",
        description="📋 AutoCutClips — clip a list of videos one after another. "
        "Any other flag (--clips, --ratio, --cookies, ...) is passed to every video's clip run.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--links", required=True,
                   help="Text file with one video URL per line (# comments allowed)")
    p.add_argument("--retry-failed", action="store_true",
                   help="Re-run videos that failed last time (finished videos are always skipped)")
    p.add_argument("--keep-source", action="store_true",
                   help="Keep each downloaded source video instead of deleting it after rendering")
    return p


def queue(argv: list[str] | None = None) -> None:
    """Run the clip pipeline over every URL in a links file."""
    from .clipping.queue_runner import read_links, run_queue

    args, clip_argv = _queue_parser().parse_known_args(
        sys.argv[1:] if argv is None else argv
    )

    if "--url" in clip_argv or "-u" in clip_argv:
        print("❌ ERROR: put the URLs in the --links file instead of passing --url.")
        sys.exit(1)

    if not os.path.exists(args.links):
        print(f"❌ ERROR: links file not found: {args.links}")
        sys.exit(1)

    links = read_links(args.links)
    if not links:
        print(f"❌ ERROR: no http(s) URLs found in {args.links}")
        sys.exit(1)

    from .clipping.config import build_config

    # Validate the shared flags once, up front, instead of failing on video 1.
    cfg = build_config(["--url", links[0], *clip_argv])
    if not cfg.api_key_gemini and not getattr(cfg, "load_gemini_json", False):
        print("❌ ERROR: the GOOGLE_API_KEY environment variable is not set.")
        sys.exit(1)

    _print_clip_summary(cfg)
    for warning in _preflight_warnings(cfg):
        print(f"\n⚠️  {warning}")

    run_queue(
        links,
        clip_argv,
        retry_failed=args.retry_failed,
        keep_source=args.keep_source,
    )


def story(argv: list[str] | None = None) -> None:
    """Run the clip pipeline in Story Clip mode (implies --story-mode)."""
    argv = list(argv) if argv is not None else []
    if "--story-mode" not in argv:
        argv = ["--story-mode", *argv]
    clip(argv)


SUBCOMMANDS = {
    "clip": clip,
    "story": story,
    "queue": queue,
    "upload-youtube": upload_youtube,
    "upload-instagram": upload_instagram,
    "reschedule-youtube": reschedule_youtube,
    "learn-youtube": learn_youtube,
    "youtube-token": youtube_token,
}


def main() -> None:
    """
    Entry point.

    If the first argument names a subcommand it is dispatched with the remaining
    arguments; otherwise every argument goes to the clip/story pipeline, so the
    historical ``--url ...`` invocation keeps working unchanged.
    """
    argv = sys.argv[1:]

    if argv and argv[0] in SUBCOMMANDS:
        SUBCOMMANDS[argv[0]](argv[1:])
        return

    clip(argv)


if __name__ == "__main__":
    main()
