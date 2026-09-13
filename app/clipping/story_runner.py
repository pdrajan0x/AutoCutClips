"""
clipping.story_runner — Story Clip pipeline orchestrator.

Runs the full Story Clip pipeline:
  1. Load & validate sources.json
  2. Download & cache every source video
  3. Transcribe each source with Whisper
  4. Load & validate story_recipe.json
  5. Assemble each clip (hook + highlight) — clean, no subtitles
  6. Save story_manifest.json
"""

import json
import os

from .story import assembler, loader, source_manager


def _transcribe_sources(
    cached_paths: dict[str, str],
    cache_dir: str,
    cfg,
) -> dict[str, dict]:
    """
    Transcribe every cached source with Faster-Whisper.

    Existing transcript JSON files are reused. Failures are reported per source
    and never abort the pipeline — transcripts are reference data, not required
    for assembly.

    Returns
    -------
    dict[str, dict]
        Mapping of source_id -> {"transkrip", "segmen", "path"}.
    """
    from . import engine

    whisper_model = getattr(cfg, "whisper_model", "large-v3")
    whisper_device = getattr(cfg, "whisper_device", "cuda")
    whisper_compute = getattr(cfg, "whisper_compute_type", "float16")
    max_words = getattr(cfg, "max_kata_per_subtitle", 5)

    transcripts: dict[str, dict] = {}
    total = len(cached_paths)

    for idx, (sid, video_path) in enumerate(cached_paths.items(), 1):
        transcript_path = os.path.join(cache_dir, f"{sid}_transcript.json")

        if os.path.exists(transcript_path):
            try:
                with open(transcript_path, "r", encoding="utf-8") as f:
                    transcripts[sid] = json.load(f)
                print(f"   ⏩ [{idx}/{total}] '{sid}' already has a transcript, skipping.")
                continue
            except (OSError, json.JSONDecodeError):
                pass  # corrupted cache — re-transcribe

        if not os.path.exists(video_path):
            print(f"   ⚠️ [{idx}/{total}] '{sid}' file not found, skipping transcription.")
            continue

        print(f"   🎤 [{idx}/{total}] Transcribing '{sid}'...")
        try:
            transcript, segments = engine.transcribe_video(
                video_path,
                max_words_per_subtitle=max_words,
                model_size=whisper_model,
                device=whisper_device,
                compute_type=whisper_compute,
            )
        except Exception as e:
            print(f"   ⚠️ '{sid}' could not be transcribed: {e}")
            continue

        result = {
            "source_id": sid,
            "transkrip": transcript,
            "segmen": segments,
            "path": transcript_path,
        }
        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        transcripts[sid] = result
        print(f"   ✅ '{sid}' transcribed ({len(segments)} segment(s)).")

    return transcripts


def _resolve_cached_paths(source_registry: dict, cache_dir: str) -> dict[str, str]:
    """Map source IDs to existing cached files without downloading anything."""
    cached_paths: dict[str, str] = {}
    for sid, src in source_registry.items():
        if src["platform"] == "local":
            cached_paths[sid] = src["local_path"]
            continue
        cached = os.path.join(cache_dir, f"{sid}.mp4")
        if os.path.exists(cached):
            cached_paths[sid] = cached
        else:
            print(f"   ⚠️ No cache found for '{sid}': {cached}")
    return cached_paths


def _assemble_clip(clip_config: dict, source_registry: dict, cache_dir: str,
                   story_output_dir: str, ratio: str) -> dict:
    """Assemble one recipe clip (hook + highlight) into a manifest entry."""
    cid = clip_config["clip_id"]
    title = clip_config.get("title", f"Clip {cid}")

    print(f"\n{'─' * 50}")
    print(f"📎 Clip #{cid}: {title}")
    print(f"{'─' * 50}")

    entry = {
        "clip_id": cid,
        "title": title,
        "hook_path": None,
        "highlight_path": None,
        "status": "failed",
        "error": None,
        "metadata": clip_config.get("metadata", {}),
    }

    clip_dir = os.path.join(story_output_dir, f"clip_{cid}")
    os.makedirs(clip_dir, exist_ok=True)

    kwargs = {
        "clip_config": clip_config,
        "source_registry": source_registry,
        "cache_dir": cache_dir,
        "output_dir": clip_dir,
        "ratio": ratio,
    }

    try:
        entry["hook_path"] = assembler.assemble_hook(**kwargs)
        entry["highlight_path"] = assembler.assemble_highlight(**kwargs)
    except Exception as e:
        # One bad clip must not lose the whole run (and its manifest).
        entry["error"] = f"{type(e).__name__}: {e}"
        print(f"      ❌ Clip #{cid} failed: {entry['error']}")

    if entry["hook_path"] and entry["highlight_path"]:
        entry["status"] = "ok"
    elif entry["hook_path"] or entry["highlight_path"]:
        entry["status"] = "partial"

    return entry


def run_story_pipeline(cfg) -> list[dict]:
    """
    Run the full Story Clip pipeline.

    Parameters
    ----------
    cfg : SimpleNamespace
        Config from ``config.build_config()``; must include
        ``story_recipe_path``, ``sources_json_path`` and the standard fields.

    Returns
    -------
    list[dict]
        The story manifest — one entry per clip, with its output paths.
    """
    print("=" * 70)
    print("🎬 Story Clip — Multi-Source Narrative Assembly")
    print("=" * 70)

    # --- Step 1: sources.json ---
    sources_path = getattr(cfg, "sources_json_path", "sources.json")
    print(f"\n[1/6] Loading sources: {sources_path}")
    source_registry = loader.load_sources(sources_path)

    # --- Step 2: download & cache ---
    cache_dir = source_manager.get_cache_dir(cfg.outputs_dir)
    if getattr(cfg, "skip_download", False):
        print("\n[2/6] ⏩ Skipping downloads (--skip-download)")
        cached_paths = _resolve_cached_paths(source_registry, cache_dir)
    else:
        print(f"\n[2/6] Downloading sources -> {cache_dir}")
        cached_paths = source_manager.download_all_sources(
            source_registry, cache_dir, getattr(cfg, "download_source_height", "max")
        )

    source_manager.save_sources_status(source_registry, cached_paths, cfg.outputs_dir)

    # --- Step 3: transcribe ---
    print("\n[3/6] Transcribing sources with Whisper...")
    transcripts = _transcribe_sources(cached_paths, cache_dir, cfg)
    print(f"   📝 {len(transcripts)}/{len(cached_paths)} source(s) transcribed.")

    # --- Step 4: recipe ---
    recipe_path = getattr(cfg, "story_recipe_path", "story_recipe.json")
    print(f"\n[4/6] Loading recipe: {recipe_path}")
    recipe = loader.load_recipe(recipe_path, source_registry)

    # --- Step 5: assemble every clip ---
    clips = recipe["clips"]
    defaults = recipe.get("_defaults")
    ratio = getattr(cfg, "pilihan_rasio", None) or (defaults.ratio if defaults else "9:16")

    story_output_dir = getattr(cfg, "story_output_dir", None) or os.path.join(
        cfg.outputs_dir, "story_clips"
    )
    os.makedirs(story_output_dir, exist_ok=True)

    print(f"\n[5/6] Assembling {len(clips)} clip(s)...")
    print(f"   Output dir: {story_output_dir}")
    print(f"   Ratio: {ratio}")
    print("   Mode: clean (no subtitles, no text overlay)")

    manifest = [
        _assemble_clip(clip_config, source_registry, cache_dir, story_output_dir, ratio)
        for clip_config in sorted(clips, key=lambda c: c["clip_id"])
    ]

    # --- Step 6: save the manifest ---
    manifest_path = os.path.join(cfg.outputs_dir, "story_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    transcripts_index_path = os.path.join(cfg.outputs_dir, "story_transcripts.json")
    with open(transcripts_index_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                sid: {
                    "path": t.get("path", ""),
                    "segmen_count": len(t.get("segmen", [])),
                }
                for sid, t in transcripts.items()
            },
            f, ensure_ascii=False, indent=2,
        )

    ok_count = sum(1 for entry in manifest if entry["status"] == "ok")

    print(f"\n{'=' * 70}")
    print(f"✅ Story Clip finished! {ok_count}/{len(manifest)} clip(s) fully rendered.")
    print(f"💾 Manifest: {manifest_path}")
    print(f"📝 Transcripts: {transcripts_index_path}")
    print(f"📁 Output: {story_output_dir}")
    print(f"{'=' * 70}")

    print(f"\n{'Clip':>6} | {'Title':<35} | {'Hook':>6} | {'Highlight':>10} | Status")
    print(f"{'─' * 6} | {'─' * 35} | {'─' * 6} | {'─' * 10} | {'─' * 8}")
    for entry in manifest:
        hook_ok = "✅" if entry["hook_path"] else "❌"
        hl_ok = "✅" if entry["highlight_path"] else "❌"
        print(
            f"  {entry['clip_id']:>4} | {entry['title'][:35]:<35} | "
            f"{hook_ok:>6} | {hl_ok:>10} | {entry['status']}"
        )

    return manifest
