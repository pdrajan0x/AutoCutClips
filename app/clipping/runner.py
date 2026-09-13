"""
clipping.runner — Auto-clip pipeline orchestrator.

Single implementation shared by the CLI and the web worker. Callers pass an
``on_progress`` callback to observe each step; the CLI leaves it unset and just
relies on the printed output.
"""

import glob
import json
import os

from . import diarization as diarization_mod
from . import engine, hook_manager, metadata, studio, voiceover

TOTAL_STEPS = 7


class Progress:
    """Prints each pipeline step and forwards it to an optional callback."""

    def __init__(self, callback=None):
        self._callback = callback

    def __call__(self, step: str, step_number: int, message: str, percent: float):
        print(f"\n[{step_number}/{TOTAL_STEPS}] {message}")
        if self._callback:
            self._callback(
                step=step,
                step_number=step_number,
                total_steps=TOTAL_STEPS,
                message=message,
                percent=percent,
            )


def _download_source(cfg, progress: Progress) -> None:
    """Fetch the source video, or reuse an existing local file."""
    if not cfg.url_youtube:
        # Web GUI flows pass an uploaded/previously downloaded file instead of a URL.
        if not os.path.exists(cfg.file_video_asli):
            raise FileNotFoundError(
                f"No source video found at {cfg.file_video_asli} and no URL was given."
            )
        progress("download", 1, "Reusing the existing source video.", 14.0)
        return

    progress("download", 1, "Downloading the source video...", 5.0)
    engine.download_video(
        cfg.url_youtube,
        cfg.file_video_asli,
        getattr(cfg, "use_dlp_subs", False),
        getattr(cfg, "download_source_height", "max"),
        source_platform=getattr(cfg, "source_platform", "youtube"),
    )
    progress("download", 1, "Source video downloaded.", 14.0)


def _transcribe(cfg, progress: Progress) -> tuple[str, list[dict]]:
    """Transcribe the source, preferring YouTube JSON3 subtitles when available."""
    progress("transcribe", 2, "Starting transcription...", 15.0)

    transcript, segments = "", []
    source_platform = getattr(cfg, "source_platform", "youtube")

    if source_platform == "youtube" and getattr(cfg, "use_dlp_subs", False):
        # The subtitle language suffix is unknown (.id.json3 / .en.json3), so glob.
        json3_files = glob.glob(cfg.file_video_asli.replace(".mp4", ".*.json3"))
        if json3_files and os.path.exists(json3_files[0]):
            transcript, segments = engine.parse_youtube_json3_subs(
                json3_files[0], max_words_per_subtitle=cfg.max_kata_per_subtitle
            )
            if transcript and segments:
                print(
                    f"✅ Parsed subtitles from YouTube "
                    f"({os.path.basename(json3_files[0])}); skipping Whisper."
                )

    if not transcript or not segments:
        transcript, segments = engine.transcribe_video(
            cfg.file_video_asli,
            max_words_per_subtitle=cfg.max_kata_per_subtitle,
            model_size=cfg.whisper_model,
            device=cfg.whisper_device,
            compute_type=cfg.whisper_compute_type,
        )

    progress("transcribe", 2, "Transcription finished.", 35.0)
    return transcript, segments


def _analyze(cfg, transcript: str, progress: Progress) -> list[dict]:
    """Run the AI analysis, or reload a cached response when asked to."""
    progress("analyze", 3, f"Analysing with AI ({cfg.ai_provider})...", 36.0)

    cache_path = os.path.join(cfg.outputs_dir, "gemini_response.json")

    if getattr(cfg, "load_gemini_json", False) and os.path.exists(cache_path):
        print(f"🔄 Loading the cached AI response from: {cache_path}")
        with open(cache_path, "r", encoding="utf-8") as f:
            clips = json.load(f)
    else:
        clips = engine.analyze_with_ai(transcript, cfg)
        # Keep the raw response so a rerun can reproduce the same clip set.
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(clips, f, indent=4, ensure_ascii=False)
        print(f"💾 Raw AI response saved to: {cache_path}")

    progress("analyze", 3, f"The AI found {len(clips)} viral clips.", 50.0)
    return clips


def _run_diarization(cfg, progress: Progress):
    """Run speaker diarization for split-screen / camera-switch modes."""
    needs_diarization = (
        getattr(cfg, "use_split_screen", False) and cfg.split_trigger == "diarization"
    ) or getattr(cfg, "use_camera_switch", False)

    if not (needs_diarization and studio._is_vertical_ratio(cfg.pilihan_rasio)):
        return None

    mode_label = "Split-Screen" if getattr(cfg, "use_split_screen", False) else "Camera-Switch"
    audio_path = cfg.file_video_asli.replace(".mp4", "_audio.wav")

    try:
        progress("diarization", 5, f"[{mode_label}] Running speaker diarization...", 56.0)
        diarization_mod.extract_audio(cfg.file_video_asli, audio_path)

        num_speakers = getattr(cfg, "diarization_num_speakers", 2)
        min_spk = max_spk = None
        if str(num_speakers).lower() == "auto":
            max_faces = studio.estimate_speaker_count_from_video(cfg.file_video_asli, cfg)
            min_spk = max(1, max_faces)
            max_spk = min_spk + 2
            print(f"   ℹ️ Pyannote hint: between {min_spk} and {max_spk} speakers.")

        return diarization_mod.run_diarization(
            audio_path,
            hf_token=cfg.hf_token,
            num_speakers=num_speakers,
            min_speakers=min_spk,
            max_speakers=max_spk,
        )
    except Exception as e:
        progress(
            "diarization", 5,
            f"Diarization failed: {e}. Falling back to the standard render mode.",
            58.0,
        )
        return None
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)


def _source_height(video_path: str) -> int:
    """Read the source video height (used for auto-bitrate and glitch scaling)."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()


def _generate_voiceovers(cfg, clips: list[dict], segments: list[dict]) -> None:
    """Generate a TTS commentary track per clip (in place, best effort)."""
    print(f"\n🎙️ Generating voice-overs for {len(clips)} clips...")

    for clip in clips:
        try:
            start = float(clip["start_time"])
            end = float(clip["end_time"])

            # Collect the transcript text overlapping this clip's time range.
            snippet_lines = []
            for seg in segments:
                if float(seg["end"]) > start and float(seg["start"]) < end:
                    # Whisper segments carry 'text'; YouTube JSON3 only has 'words'.
                    seg_text = seg.get("text") or " ".join(
                        w["word"] for w in seg.get("words", [])
                    )
                    if seg_text:
                        snippet_lines.append(seg_text)

            script = voiceover.generate_commentary_script(
                " ".join(snippet_lines),
                cfg,
                style=cfg.voiceover_style,
                language=cfg.voiceover_lang,
                length=cfg.voiceover_length,
            )
            if not script:
                continue

            audio_path, vo_segments = voiceover.synthesize_voice(
                script, cfg.voiceover_voice, cfg.outputs_dir, str(clip["rank"])
            )
            if os.path.exists(audio_path):
                clip["voiceover"] = {
                    "script": script,
                    "audio_path": audio_path,
                    "segments": vo_segments,
                    "voice": cfg.voiceover_voice,
                }
        except Exception as e:
            print(f"   ⚠️ Failed to generate a voice-over for rank {clip.get('rank')}: {e}")


def run_pipeline(cfg, on_progress=None) -> list[dict]:
    """
    Run the full clipping pipeline:
      1. Download the source video
      2. Transcribe it (Whisper, or YouTube JSON3 subtitles)
      3. Analyse it with the AI provider
      4. Normalise the metadata
      5. Speaker diarization (split-screen / camera-switch only)
      6. Render every clip
      7. Save render_manifest.json

    Parameters
    ----------
    cfg : SimpleNamespace
        Configuration from ``config.build_config()`` or the web config adapter.
    on_progress : callable, optional
        ``fn(step, step_number, total_steps, message, percent)`` progress hook.

    Returns
    -------
    list[dict]
        The render manifest (one dict per rendered clip).
    """
    progress = Progress(on_progress)

    _download_source(cfg, progress)
    transcript, segments = _transcribe(cfg, progress)
    clips = _analyze(cfg, transcript, progress)

    # --- Step 4: metadata normalisation ---
    progress("metadata", 4, "Normalising metadata...", 55.0)
    clips = metadata.normalize_and_validate(clips)
    metadata.print_preview(clips)
    metadata.save_metadata_preview(
        clips, path=os.path.join(cfg.outputs_dir, "metadata_preview.json")
    )

    diarization_data = _run_diarization(cfg, progress)

    # --- Step 6: render preparation ---
    progress("render", 6, "Preparing the renderer...", 60.0)
    os.environ["OSC_VIDEO_SCALE_ALGO"] = str(getattr(cfg, "video_scale_algo", "lanczos"))

    source_h = _source_height(cfg.file_video_asli)
    _, target_h = studio._get_render_dims(cfg, cfg.pilihan_rasio, source_h=source_h)
    video_encoder = studio.detect_video_encoder(cfg, target_h=target_h)

    file_glitch_ts = None
    if cfg.use_hook_glitch:
        print("⚙️ Preparing the glitch transition video...")
        file_glitch_ts = studio.siapkan_glitch_video(
            cfg.pilihan_rasio, cfg, video_encoder, source_h=source_h
        )

    custom_hook_path = None
    if getattr(cfg, "hook_source", None):
        print("\n🎣 Fetching the custom hook clip source...")
        custom_hook_path = hook_manager.download_custom_hook(cfg)

    if getattr(cfg, "voiceover", False):
        _generate_voiceovers(cfg, clips, segments)

    # --- Step 6: render every clip ---
    render_manifest: list[dict] = []
    ordered_clips = sorted(clips, key=lambda c: c["rank"])

    for idx, clip in enumerate(ordered_clips, 1):
        progress(
            "render", 6,
            f"Rendering clip {idx}/{len(ordered_clips)}...",
            60.0 + 35.0 * idx / len(ordered_clips),
        )

        if custom_hook_path:
            clip["custom_hook_info"] = {"file_path": custom_hook_path}

        rendered = studio.proses_klip(
            clip["rank"],
            clip,
            cfg.pilihan_rasio,
            file_glitch_ts,
            segments,
            cfg,
            video_encoder,
            diarization_data=diarization_data,
        )
        if rendered:
            # Attach the source URL so metadata.py can add the source credit.
            if not rendered.get("source_url"):
                rendered["source_url"] = getattr(cfg, "url_youtube", None)
            render_manifest.append(rendered)

    # --- Step 7: save the manifest ---
    manifest_path = os.path.join(cfg.outputs_dir, "render_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(render_manifest, f, ensure_ascii=False, indent=2)

    progress(
        "done", 7,
        f"Done! {len(render_manifest)} clip(s) rendered — manifest: {manifest_path}",
        100.0,
    )
    return render_manifest
