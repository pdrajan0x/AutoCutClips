#!/usr/bin/env python3
"""
app.cli — Command-line entry points for OpenSource Clipping.

Clip / story mode (the default — flags are parsed by clipping.config):
    python -m app.cli --url "https://..."
    python -m app.cli --url "https://..." --clips 5 --ratio 16:9
    python -m app.cli --story-mode --story-recipe story_recipe.json
    python -m app.cli --help

Publishing and maintenance subcommands:
    python -m app.cli upload-youtube        [--test-mode ...]
    python -m app.cli upload-instagram      [--test-mode ...]
    python -m app.cli reschedule-youtube    [--apply ...]
    python -m app.cli youtube-token         generate | verify

Each subcommand is also installed as its own console script — see
[project.scripts] in pyproject.toml.
"""

import argparse
import os
import sys

VERSION = "1.12.0"
DEFAULT_TZ_ENV = "APP_TIMEZONE"
DEFAULT_TZ = "Asia/Makassar"


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
        f"🎬 OpenSource Clipping v{VERSION} — Story Clip Mode",
        [
            ("Recipe", cfg.story_recipe_path),
            ("Sources", cfg.sources_json_path),
            ("Ratio", cfg.pilihan_rasio),
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
        ("Clips", cfg.jumlah_clip),
        ("Ratio", cfg.pilihan_rasio),
        ("Font Style", cfg.gaya_font_aktif),
        ("Subtitles", _on_off(not cfg.no_subs)),
        ("B-Roll", _on_off(cfg.use_broll)),
        ("Hook Glitch", _on_off(cfg.use_hook_glitch)),
        ("BGM", _on_off(cfg.use_auto_bgm)),
        ("Karaoke", _on_off(cfg.use_karaoke_effect)),
        ("Split-Screen", _on_off(cfg.use_split_screen)),
    ]
    if cfg.use_split_screen:
        rows += [
            ("Dyn. Split", _on_off(cfg.use_dynamic_split)),
            ("Split Trig.", cfg.split_trigger),
        ]
    rows += [
        ("Whisper", f"{cfg.whisper_model} ({cfg.whisper_device})"),
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

    _banner(f"🎬 OpenSource Clipping v{VERSION}", rows)


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
    run_pipeline(cfg)
    print("\n✅ Done! Every clip has been rendered.")


# ==============================================================================
# YOUTUBE UPLOAD
# ==============================================================================

def _youtube_upload_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clipping-upload-youtube",
        description="🚀 OpenSource Clipping — YouTube auto-uploader & scheduler",
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
        description="OpenSource Clipping — Instagram Reels auto-uploader",
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


SUBCOMMANDS = {
    "clip": clip,
    "story": clip,  # story mode is selected with --story-mode
    "upload-youtube": upload_youtube,
    "upload-instagram": upload_instagram,
    "reschedule-youtube": reschedule_youtube,
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
