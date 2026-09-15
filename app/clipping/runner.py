"""
clipping.runner — Auto-clip pipeline orchestrator.

Single implementation shared by the CLI, the video queue and the web worker.
Callers pass an ``on_progress`` callback to observe each step; the CLI leaves it
unset and just relies on the printed output.

Work is cached in the output folder so a re-run after a crash resumes quickly:
the source video is reused when it was downloaded for the same URL, the
transcript when the transcription settings match, and (with
``--load-gemini-json``) the AI's clip selection.
"""

import glob
import json
import os

from . import diarization as diarization_mod
from . import engine, hook_manager, metadata, studio, voiceover
from .engine.prompt import clip_duration_bounds

TOTAL_STEPS = 7
TRANSCRIPT_CACHE_FILE = "transcript_cache.json"


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


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _source_marker_path(video_path: str) -> str:
    """Records which URL the downloaded source video came from."""
    return os.path.splitext(video_path)[0] + ".source.json"


def _download_source(cfg, progress: Progress) -> None:
    """Fetch the source video, or reuse the file already downloaded for this URL."""
    if not cfg.url_youtube:
        # Web GUI flows pass an uploaded/previously downloaded file instead of a URL.
        if not os.path.exists(cfg.source_video_path):
            raise FileNotFoundError(
                f"No source video found at {cfg.source_video_path} and no URL was given."
            )
        progress("download", 1, "Reusing the existing source video.", 14.0)
        return

    marker_path = _source_marker_path(cfg.source_video_path)
    marker = _read_json(marker_path) or {}
    if os.path.exists(cfg.source_video_path) and marker.get("url") == cfg.url_youtube:
        progress("download", 1, "Reusing the source video already downloaded for this URL.", 14.0)
        return

    # yt-dlp skips any file that already exists, so a leftover source_video.mp4
    # from another URL would silently be re-clipped. Stale subtitle and metadata
    # files would likewise be read as this video's.
    stale = glob.glob(cfg.source_video_path.replace(".mp4", ".*.json3"))
    for path in (cfg.source_video_path, engine.source_info_path(cfg.source_video_path), marker_path):
        if os.path.exists(path):
            stale.append(path)
    for path in stale:
        os.remove(path)

    progress("download", 1, "Downloading the source video...", 5.0)
    engine.download_video(
        cfg.url_youtube,
        cfg.source_video_path,
        getattr(cfg, "use_dlp_subs", False),
        getattr(cfg, "download_source_height", "max"),
        source_platform=getattr(cfg, "source_platform", "youtube"),
        cfg=cfg,
    )
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump({"url": cfg.url_youtube}, f)
    progress("download", 1, "Source video downloaded.", 14.0)


def _load_source_info(cfg) -> None:
    """
    Load the video title/channel/description/language saved at download.

    The AI uses it to name the show and speakers in hashtags, and Whisper uses
    the language as a hint instead of guessing from the first 30 seconds.
    """
    info_path = engine.source_info_path(cfg.source_video_path)
    if not os.path.exists(info_path) or getattr(cfg, "source_info", None):
        return
    try:
        with open(info_path, "r", encoding="utf-8") as f:
            cfg.source_info = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"⚠️ Could not read the source metadata ({e}); continuing without it.")


def _whisper_language(cfg) -> str | None:
    """--language when set, else the language YouTube reports, else auto-detect."""
    lang = str(getattr(cfg, "whisper_language", "auto") or "auto").strip().lower()
    if lang != "auto":
        return lang
    reported = (getattr(cfg, "source_info", None) or {}).get("language")
    return str(reported).split("-")[0].lower() if reported else None


def _transcript_cache_key(cfg) -> dict:
    """Everything that changes the transcript; a cached one is reused only on a full match."""
    source = cfg.source_video_path
    return {
        "source": cfg.url_youtube or os.path.abspath(source),
        "source_size": os.path.getsize(source) if os.path.exists(source) else None,
        "whisper_model": cfg.whisper_model,
        "language": str(getattr(cfg, "whisper_language", "auto")),
        "words_per_sub": cfg.max_words_per_subtitle,
        "use_dlp_subs": bool(getattr(cfg, "use_dlp_subs", False)),
    }


def _transcribe(cfg, progress: Progress) -> tuple[str, list[dict]]:
    """Transcribe the source (or reuse the saved transcript), preferring YouTube subtitles."""
    progress("transcribe", 2, "Starting transcription...", 15.0)

    cache_path = os.path.join(cfg.outputs_dir, TRANSCRIPT_CACHE_FILE)
    cache_key = _transcript_cache_key(cfg)
    cached = _read_json(cache_path)
    if isinstance(cached, dict) and cached.get("key") == cache_key and cached.get("segments"):
        cfg.transcript_language = cached.get("language")
        progress("transcribe", 2, "Reusing the saved transcript.", 35.0)
        return cached.get("transcript", ""), cached["segments"]

    source_platform = getattr(cfg, "source_platform", "youtube")

    # YouTube's own captions, parsed if --use-dlp-subs is set and they exist.
    # Word-level timing has the same shape as Whisper's, but is kept aside —
    # Whisper's audio-aligned timing is what rendering/snapping uses below.
    youtube_transcript, youtube_segments = "", []
    if source_platform == "youtube" and getattr(cfg, "use_dlp_subs", False):
        # The subtitle language suffix is unknown (.hi-orig.json3 / .en.json3), so glob.
        json3_files = glob.glob(cfg.source_video_path.replace(".mp4", ".*.json3"))
        if json3_files and os.path.exists(json3_files[0]):
            youtube_transcript, youtube_segments = engine.parse_youtube_json3_subs(
                json3_files[0], max_words_per_subtitle=cfg.max_words_per_subtitle
            )
            if youtube_transcript and youtube_segments:
                # source_video.hi-orig.json3 -> "hi"
                track = os.path.basename(json3_files[0]).split(".")[-2]
                cfg.transcript_language = track.split("-")[0].lower()
                print(f"✅ Parsed subtitles from YouTube ({os.path.basename(json3_files[0])}).")

    whisper_info: dict = {}
    transcript, segments = engine.transcribe_video(
        cfg.source_video_path,
        max_words_per_subtitle=cfg.max_words_per_subtitle,
        model_size=cfg.whisper_model,
        device=cfg.whisper_device,
        compute_type=cfg.whisper_compute_type,
        language=_whisper_language(cfg),
        info_out=whisper_info,
    )
    # YouTube's own subtitle track names its language explicitly; Whisper only
    # guesses, and guesses badly on singing (a Hindi song can come back as "nn"),
    # so the track's language wins whenever there is one.
    cfg.transcript_language = (
        getattr(cfg, "transcript_language", None) or whisper_info.get("language")
    )

    if youtube_transcript and transcript:
        # Both sources exist: let Gemini reconcile wording/gaps between them.
        # The merged text only feeds clip *selection* — segments (word timing
        # for rendering/snapping) stay Whisper's, since those are the ones
        # actually aligned to this file's audio.
        transcript = engine.merge_transcripts_with_ai(transcript, youtube_transcript, cfg)
    elif youtube_transcript and not transcript:
        # Whisper found nothing (e.g. VAD wiped out sung vocals) — the YouTube
        # captions are all there is; use their timing too since Whisper has none.
        transcript, segments = youtube_transcript, youtube_segments

    if not segments:
        # Everything downstream reads the transcript, so an empty one would fail
        # much later as a confusing "the AI picked 0 clips" instead of the truth.
        raise RuntimeError(
            "No speech could be transcribed from this video. Whisper returned nothing"
            + (" and YouTube had no subtitles either." if source_platform == "youtube"
               else ".")
            + " If the video is music or mostly non-speech there may be nothing to"
            " caption; otherwise check that the downloaded file actually has audio."
        )

    # Saved before captions are romanised, so a rerun starts from the real transcript.
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "key": cache_key,
                "language": getattr(cfg, "transcript_language", None),
                "transcript": transcript,
                "segments": segments,
            },
            f, ensure_ascii=False,
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

    if not (needs_diarization and studio._is_vertical_ratio(cfg.aspect_ratio)):
        return None

    mode_label = "Split-Screen" if getattr(cfg, "use_split_screen", False) else "Camera-Switch"
    audio_path = cfg.source_video_path.replace(".mp4", "_audio.wav")

    try:
        progress("diarization", 5, f"[{mode_label}] Running speaker diarization...", 56.0)
        diarization_mod.extract_audio(cfg.source_video_path, audio_path)

        num_speakers = getattr(cfg, "diarization_num_speakers", 2)
        min_spk = max_spk = None
        if str(num_speakers).lower() == "auto":
            max_faces = studio.estimate_speaker_count_from_video(cfg.source_video_path, cfg)
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


def _source_video_props(video_path: str) -> tuple[int, float]:
    """Read the source height (render size, auto-bitrate) and frame rate."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), float(cap.get(cv2.CAP_PROP_FPS) or 0)
    finally:
        cap.release()


def render_fps_for(source_fps: float) -> float:
    """
    The frame rate clips are encoded at: the source's own rate, halved for
    48-60 fps sources and capped at 30. Converting 24/25 fps footage to 30
    duplicated frames and made camera moves judder.
    """
    if not source_fps or source_fps != source_fps or source_fps <= 0:
        return 30.0
    if source_fps >= 47:
        source_fps /= 2
    return round(min(source_fps, 30.0), 3)


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
    _load_source_info(cfg)
    transcript, segments = _transcribe(cfg, progress)
    clips = _analyze(cfg, transcript, progress)

    # --- Step 4: metadata normalisation ---
    progress("metadata", 4, "Normalising metadata...", 55.0)
    # The description (with its source credit) is built during normalisation,
    # so the URL has to be on each clip before it runs, not after rendering.
    for clip in clips:
        if isinstance(clip, dict) and not clip.get("source_url"):
            clip["source_url"] = getattr(cfg, "url_youtube", None)
    min_duration, max_duration = clip_duration_bounds(cfg)
    clips = metadata.normalize_and_validate(
        clips, min_duration=min_duration, max_duration=max_duration
    )
    clips = metadata.snap_clips_to_words(clips, segments, min_duration=min_duration)
    if not clips:
        raise RuntimeError(
            "No clips survived validation — every AI-picked moment was dropped "
            f"(too short for --min-duration {min_duration:g}s, invalid timings, or "
            "duplicates). Try lowering --min-duration or re-running; the AI response "
            "was still saved to gemini_response.json for --load-gemini-json."
        )
    if getattr(cfg, "caption_script", "latin") == "latin":
        # Hindi/Tamil/Arabic/... speech keeps its language but is written in
        # English letters ("mera naam ... hai"); Latin-script speech is untouched.
        engine.romanize_clip_captions(clips, segments, cfg)
    metadata.print_preview(clips)
    metadata.save_metadata_preview(
        clips, path=os.path.join(cfg.outputs_dir, "metadata_preview.json")
    )

    diarization_data = _run_diarization(cfg, progress)

    # --- Step 6: render preparation ---
    progress("render", 6, "Preparing the renderer...", 60.0)
    os.environ["OSC_VIDEO_SCALE_ALGO"] = str(getattr(cfg, "video_scale_algo", "lanczos"))

    source_h, source_fps = _source_video_props(cfg.source_video_path)
    cfg.render_fps = render_fps_for(source_fps)
    _, target_h = studio._get_render_dims(cfg, cfg.aspect_ratio, source_h=source_h)
    video_encoder = studio.detect_video_encoder(cfg, target_h=target_h)

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

        rendered = studio.process_clip(
            clip["rank"],
            clip,
            cfg.aspect_ratio,
            segments,
            cfg,
            video_encoder,
            diarization_data=diarization_data,
        )
        if rendered:
            if not rendered.get("source_url"):
                rendered["source_url"] = getattr(cfg, "url_youtube", None)
            render_manifest.append(rendered)

    # --- Step 7: save the manifest ---
    manifest_path = os.path.join(cfg.outputs_dir, "render_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(render_manifest, f, ensure_ascii=False, indent=2)

    succeeded = [r for r in render_manifest if r.get("status") == "success"]
    if render_manifest and not succeeded:
        errors = "; ".join(f"rank {r.get('rank')}: {r.get('error')}" for r in render_manifest)
        raise RuntimeError(f"Every clip failed to render — {errors}")

    progress(
        "done", 7,
        f"Done! {len(render_manifest)} clip(s) rendered — manifest: {manifest_path}",
        100.0,
    )
    return render_manifest
