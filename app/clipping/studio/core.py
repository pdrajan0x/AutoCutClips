"""
Core Studio pipeline orchestrator.

``process_clip()`` drives the per-clip render: the optional hook teaser,
renderer selection (hybrid / split-screen / camera-switch), smart-trim
segments, captions, B-roll, BGM, the voice-over intro and — for landscape
output only — the thumbnail.
"""

import os
import subprocess

import cv2

from .audio_bgm import LOUDNORM_FILTER, build_bgm_filter, get_local_bgm_file
from .bgm_library import ensure_bgm_library
from .broll import download_pexels_broll
from .ffmpeg_utils import (
    build_ffmpeg_progress_cmd,
    get_ts_encode_args,
    run_ffmpeg_with_progress,
)
from .render_camera_switch import render_camera_switch_video
from .render_hybrid import render_hybrid_video
from .render_split_screen import render_split_screen_video
from .subtitles import build_ass_file
from .thumbnail import build_thumbnail
from .typography import prepare_typography_fonts
from .utils import _get_render_dims, _is_vertical_ratio, ffmpeg_filter_path

# A teaser only makes sense when the hook comes from later in the clip; if the
# clip already opens on the hook, the teaser just plays the same line twice.
TEASER_MIN_HOOK_OFFSET = 2.0

# How long the on-screen hook headline stays up at the start of the clip.
TITLE_OVERLAY_SECONDS = 4.0

SHARPEN_FILTER = "unsharp=5:5:0.5:5:5:0.0"

# Voice-over intro waveform
WAVE_SIZE = (800, 260)
WAVE_COLOR = "0x00FFFF"
WAVE_ALPHA = 0.65
WAVE_LOWPASS_HZ = 300

# Re-mux a finished TS with new audio without re-encoding the video.
_COPY_VIDEO_TS_ARGS = ["-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-f", "mpegts"]


def _subtitle_filter(ass_path, cfg):
    return f"subtitles={ffmpeg_filter_path(ass_path)}:fontsdir={ffmpeg_filter_path(cfg.font_dir)}"


def _work(cfg, name):
    """
    Path for a render intermediate inside the job's own output folder.

    These used to be written to the working directory, where two jobs rendering
    the same rank at the same time overwrote each other's files.
    """
    return os.path.join(cfg.outputs_dir, name)


def _run_checked(cmd, output_path, duration, label):
    rc, errors = run_ffmpeg_with_progress(
        build_ffmpeg_progress_cmd(cmd, output_path), duration, label=label
    )
    if rc != 0:
        raise RuntimeError(f"{label} failed:\n" + "\n".join(errors))


def _concat_ts(parts, output_path, extra_args=()):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", "concat:" + "|".join(parts), "-c", "copy", *extra_args, output_path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _resolve_bgm(clip, cfg):
    """Pick a local BGM track for the clip's mood (falling back to chill), or None."""
    if not cfg.use_auto_bgm:
        return None
    bgm_dir = getattr(cfg, "bgm_dir", os.path.join(cfg.base_dir, "assets", "bgm"))
    mood = clip.get("bgm_mood", "chill")
    if mood not in getattr(cfg, "bgm_moods", ["chill"]):
        mood = "chill"

    print(f"   🎵 Looking for a local BGM file (mood: {mood})...")
    path = get_local_bgm_file(mood, bgm_dir)
    if not path:
        # The curated library is downloaded on demand rather than kept in git.
        try:
            ensure_bgm_library(bgm_dir, [mood, "chill"])
        except Exception as e:
            print(f"   ⚠️ Could not fetch the BGM library: {e}")
        path = get_local_bgm_file(mood, bgm_dir)
    if not path and mood != "chill":
        print("   🔄 Falling back to the chill BGM...")
        path = get_local_bgm_file("chill", bgm_dir)
    if path:
        print(f"   ✅ BGM ready: {path}")
    else:
        print("   ⚠️ The BGM folder is empty or has no mp3 files. Rendering without BGM.")
    return path


def _render_visual(cfg, ratio, source, output, start, end, label, *,
                   use_split, use_camera_switch, diarization_data, broll=None):
    """Render a silent clip part with the renderer the run is configured for."""
    if use_split:
        return render_split_screen_video(
            source, output, start, end, ratio, diarization_data, cfg,
            label=f"{label} SplitScreen", broll_data=broll,
        )
    if use_camera_switch:
        return render_camera_switch_video(
            source, output, start, end, ratio, diarization_data, cfg,
            label=f"{label} CameraSwitch", broll_data=broll,
        )
    return render_hybrid_video(source, output, start, end, ratio, cfg, broll, label=label)


def _audio_duration(path, fallback):
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stdout=subprocess.PIPE, text=True, check=True,
        )
        return float(res.stdout.strip())
    except Exception:
        return fallback


def _render_voiceover_intro(rank, ratio, cfg, vo_data, std_p, source_dim,
                            typography_plan, file_bgm, m_start):
    """Freeze frame + waveform + narrator intro. Returns the TS path, or None."""
    if not vo_data or not os.path.exists(vo_data.get("audio_path", "")):
        return None

    vo_ts = os.path.join(cfg.outputs_dir, f"vo_intro_{rank}.ts")
    frame_path = os.path.join(cfg.outputs_dir, f"vo_bg_{rank}.jpg")
    print("   📸 [VO] Rendering the voice-over intro (freeze frame + waveform)...")

    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", str(m_start), "-i", cfg.source_video_path,
             "-vframes", "1", "-q:v", "2", frame_path],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Could not extract the opening frame for the VO intro:\n{e.stderr}")

    fallback = float(vo_data["segments"][-1]["end"]) if vo_data.get("segments") else 4.5
    vo_duration = _audio_duration(vo_data["audio_path"], fallback) + 0.5
    vo_w, vo_h = _get_render_dims(cfg, ratio, source_h=source_dim[1])

    subs = ""
    overlay_out = "[v_out]"
    if not cfg.no_subs and vo_data.get("segments"):
        ass_vo = os.path.join(cfg.outputs_dir, f"vo_subs_{rank}.ass")
        build_ass_file(
            vo_data["segments"], 0.0, vo_duration, ass_vo, ratio, cfg,
            typography_plan=typography_plan, source_dim=source_dim,
        )
        subs = f"; [v_wave]{_subtitle_filter(ass_vo, cfg)}[v_out]"
        overlay_out = "[v_wave]"

    wave_w, wave_h = WAVE_SIZE
    fps = getattr(cfg, "render_fps", None) or 30
    graph = (
        f"[0:v]scale={vo_w}:{vo_h}:force_original_aspect_ratio=increase,crop={vo_w}:{vo_h},"
        f"colorchannelmixer=rr=0.3:gg=0.3:bb=0.3[v_bg]; "
        f"[1:a]asplit=2[vo_a][vo_wave_in]; "
        f"[vo_wave_in]lowpass=f={WAVE_LOWPASS_HZ},"
        f"showwaves=s={wave_w}x{wave_h}:mode=cline:colors={WAVE_COLOR}:rate={fps:g}:scale=sqrt,"
        f"format=rgba,colorkey=0x000000:0.1:0.1,colorchannelmixer=aa={WAVE_ALPHA}[wave_v]; "
        f"[v_bg][wave_v]overlay=(W-w)/2:(H-h)/2:shortest=1{overlay_out}{subs}"
    )

    vo_vol = getattr(cfg, "voiceover_volume", 1.0)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", f"{fps:g}", "-i", frame_path,
        "-i", vo_data["audio_path"],
    ]
    if file_bgm:
        cmd += ["-stream_loop", "-1", "-i", file_bgm]
        graph += (
            f"; [2:a]volume={cfg.bgm_base_volume}[bgm_vol]; [vo_a]volume={vo_vol}[vo_loud]; "
            f"[bgm_vol][vo_loud]amix=inputs=2:duration=first:dropout_transition=2[a_out]"
        )
    else:
        graph += f"; [vo_a]volume={vo_vol}[a_out]"
    cmd += ["-filter_complex", graph, "-map", "[v_out]", "-map", "[a_out]",
            "-t", str(vo_duration)] + std_p + [vo_ts]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"The FFmpeg VO intro pass failed (rank {rank}):\n{e.stderr}")
    finally:
        if os.path.exists(frame_path):
            os.remove(frame_path)
    return vo_ts


def process_clip(rank, clip, ratio, data_segments, cfg, video_encoder, diarization_data=None):
    """
    Render one clip from the AI's plan to the finished MP4.

    Args:
        rank: Clip rank/index.
        clip: Clip metadata object.
        ratio: Target output ratio.
        data_segments: Transcript segments.
        cfg: Runtime config object.
        video_encoder: Encoder descriptor dict.
        diarization_data: Optional speaker diarization metadata.

    Returns:
        Manifest dictionary describing the result and output paths.
    """
    h_start = float(clip.get("hook_start_time", clip["start_time"]))
    h_end = float(clip.get("hook_end_time", h_start + cfg.hook_duration))

    file_hook_src = cfg.source_video_path
    custom_hook = clip.get("custom_hook_info")
    if custom_hook:
        file_hook_src = custom_hook["file_path"]
        h_start = getattr(cfg, "hook_source_start", 0.0)
        h_end = h_start + cfg.hook_duration
        cap_h = cv2.VideoCapture(file_hook_src)
        try:
            fps = cap_h.get(cv2.CAP_PROP_FPS)
            frames = cap_h.get(cv2.CAP_PROP_FRAME_COUNT)
            if fps > 0 and frames > 0:
                h_end = min(h_end, frames / fps)
        finally:
            cap_h.release()

    m_start = float(clip["start_time"])
    m_end = float(clip["end_time"])
    title = clip.get("title")
    vertical = _is_vertical_ratio(ratio)

    out_vid = os.path.join(cfg.outputs_dir, f"highlight_rank_{rank}_ready.mp4")
    # Shorts and Reels ignore custom thumbnails, so only landscape clips get one.
    out_thm = None if vertical else os.path.join(cfg.outputs_dir, f"thumbnail_rank_{rank}.jpg")

    source_cap = cv2.VideoCapture(cfg.source_video_path)
    source_dim = (
        int(source_cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(source_cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    )
    source_cap.release()

    keep_segments = clip.get("keep_segments")
    use_segments = bool(
        keep_segments and len(keep_segments) > 1 and not getattr(cfg, "no_segment_trim", False)
    )
    rendered_duration = (
        sum(float(s["end_time"]) - float(s["start_time"]) for s in keep_segments)
        if use_segments else m_end - m_start
    )

    manifest_item = {
        "rank": rank,
        "status": "pending",
        "ratio": ratio,
        "video_path": out_vid,
        "thumbnail_path": out_thm,
        "thumbnail_text": title or f"Highlight {rank}",
        "youtube_title_final": clip.get("youtube_title_final", clip.get("title", "")),
        "youtube_description_final": clip.get("youtube_description_final", ""),
        "youtube_tags_final": clip.get("youtube_tags_final", []),
        "title": clip.get("title", ""),
        "hashtags": clip.get("hashtags", ""),
        "viral_score": clip.get("viral_score"),
        "on_screen_hook": clip.get("on_screen_hook", ""),
        "hook_text": clip.get("hook_text", ""),
        "language": getattr(cfg, "transcript_language", None),
        "start_time": m_start,
        "end_time": m_end,
        "hook_start_time": h_start,
        "hook_end_time": h_end,
        "duration": round(rendered_duration, 2),
        "reason": clip.get("reason", ""),
        "broll_list": clip.get("broll_list", []),
        "typography_plan": clip.get("typography_plan", []),
    }

    print(f"\n{'=' * 70}")
    print(f"🔥 [Rank {rank}] Processing clip")
    print(f"📝 [Title]        : '{clip.get('title', '-')}'")
    print(f"#️⃣ [Hashtags]     : '{clip.get('hashtags', '-')}'")
    print(f"🧠 Active encoder : {video_encoder['name']}")
    print(f"{'=' * 70}")

    typography_plan = clip.get("typography_plan", [])
    prepare_typography_fonts(cfg)

    h_ts, m_ts, a_hook, a_main = _work(cfg, f"h_{rank}.ts"), _work(cfg, f"m_{rank}.ts"), _work(cfg, f"ah_{rank}.ass"), _work(cfg, f"am_{rank}.ass")
    h_silent, m_silent = _work(cfg, f"h_silent_{rank}.mp4"), _work(cfg, f"m_silent_{rank}.mp4")

    # --hook-source always plays its clip as the teaser; otherwise the teaser is opt-in.
    hook_enabled = bool(getattr(cfg, "hook_teaser", False) or custom_hook)
    if hook_enabled and not custom_hook and h_start - m_start < TEASER_MIN_HOOK_OFFSET:
        print("   ⏭️ [Hook] The clip already opens on its hook — skipping the teaser so the line isn't heard twice.")
        hook_enabled = False

    title_overlay = None
    if getattr(cfg, "title_overlay", True) and clip.get("on_screen_hook"):
        title_overlay = {"text": clip["on_screen_hook"], "duration": TITLE_OVERLAY_SECONDS}
    # The headline belongs to what the viewer sees first: the teaser when there
    # is one (it used to appear again when the main clip started).
    main_overlay = None if hook_enabled and not custom_hook else title_overlay

    if getattr(cfg, "use_split_screen", False) and vertical:
        if cfg.split_trigger == "face":
            use_split = True
        else:
            use_split = (
                diarization_data is not None
                and len(set(s["speaker"] for s in diarization_data)) >= 2
            )
    else:
        use_split = False

    use_camera_switch = bool(
        not use_split
        and getattr(cfg, "use_camera_switch", False)
        and vertical
        and diarization_data
        and len(set(s["speaker"] for s in diarization_data)) >= 2
    )

    active_broll = []
    broll_list = clip.get("broll_list", [])
    if cfg.use_broll and broll_list:
        print(f"   🎥 Downloading {len(broll_list)} B-roll video(s) from Pexels...")
        for i, br in enumerate(broll_list):
            file_broll = _work(cfg, f"temp_broll_{rank}_{i}.mp4")
            if download_pexels_broll(br.get("search_query", "nature"), ratio, file_broll, cfg.pexels_api_key):
                active_broll.append(dict(br, filepath=file_broll))

    # Every part of the clip is encoded at the source's own frame rate (set by the
    # runner); forcing 30 fps duplicated frames of 24/25 fps sources and made pans judder.
    std_p = get_ts_encode_args(video_encoder, fps=getattr(cfg, "render_fps", None) or 30)
    render_modes = dict(
        use_split=use_split,
        use_camera_switch=use_camera_switch,
        diarization_data=diarization_data,
    )

    try:
        file_bgm = _resolve_bgm(clip, cfg)

        # ---- HOOK TEASER ---------------------------------------------------------
        if hook_enabled:
            print("   📸 [Hook] Rendering the teaser...")
            _render_visual(
                cfg, ratio, file_hook_src, h_silent, h_start, h_end, f"Rank {rank} Hook",
                use_split=use_split, use_camera_switch=use_camera_switch,
                diarization_data=None if custom_hook else diarization_data,
            )

            vf_hook = []
            if not cfg.no_subs and not custom_hook:
                build_ass_file(
                    data_segments, h_start, h_end, a_hook, ratio, cfg,
                    typography_plan=typography_plan, source_dim=source_dim,
                    title_overlay=title_overlay,
                )
                vf_hook.append(_subtitle_filter(a_hook, cfg))
            if cfg.video_sharpen:
                vf_hook.append(SHARPEN_FILTER)

            cmd_h = [
                "ffmpeg", "-hide_banner", "-loglevel", "verbose", "-y",
                "-i", h_silent,
                "-ss", str(h_start), "-to", str(h_end), "-i", file_hook_src,
                "-map", "0:v:0", "-map", "1:a:0", "-af", LOUDNORM_FILTER,
            ]
            if vf_hook:
                cmd_h += ["-vf", ",".join(vf_hook)]
            _run_checked(cmd_h + std_p, h_ts, h_end - h_start, f"Rank {rank} Hook FFmpeg")

        # ---- MAIN: smart-trim segments --------------------------------------------
        if use_segments:
            print(f"   📸 [Main] Rendering {len(keep_segments)} segments (smart trim)...")
            seg_ts_parts = []

            for idx, seg in enumerate(keep_segments):
                s_start, s_end = float(seg["start_time"]), float(seg["end_time"])
                s_silent = _work(cfg, f"m_seg_silent_{rank}_{idx}.mp4")
                s_ass = _work(cfg, f"m_seg_ass_{rank}_{idx}.ass")
                s_ts = _work(cfg, f"m_seg_ts_{rank}_{idx}.ts")

                _render_visual(
                    cfg, ratio, cfg.source_video_path, s_silent, s_start, s_end,
                    f"Rank {rank} Seg {idx}", broll=active_broll, **render_modes,
                )

                vf_seg = []
                if not cfg.no_subs:
                    build_ass_file(
                        data_segments, s_start, s_end, s_ass, ratio, cfg,
                        typography_plan=typography_plan, source_dim=source_dim,
                        title_overlay=main_overlay if idx == 0 else None,
                    )
                    vf_seg.append(_subtitle_filter(s_ass, cfg))
                if cfg.video_sharpen:
                    vf_seg.append(SHARPEN_FILTER)

                cmd_s = [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", s_silent,
                    "-ss", str(s_start), "-to", str(s_end), "-i", cfg.source_video_path,
                    "-map", "0:v:0", "-map", "1:a:0", "-af", LOUDNORM_FILTER,
                ]
                if vf_seg:
                    cmd_s += ["-vf", ",".join(vf_seg)]
                _run_checked(cmd_s + std_p, s_ts, s_end - s_start, f"Rank {rank} Seg FFmpeg {idx}")
                seg_ts_parts.append(s_ts)

            _concat_ts(seg_ts_parts, m_ts)

            if file_bgm:
                print("   🎵 Applying BGM to the trimmed clip...")
                m_ts_bgm = _work(cfg, f"m_bgm_{rank}.ts")
                cmd_bgm = [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", m_ts, "-stream_loop", "-1", "-i", file_bgm,
                    "-filter_complex", build_bgm_filter(
                        getattr(cfg, "bgm_mode", "ducking"), cfg.bgm_base_volume,
                        audio_input_voc="[0:a]", audio_input_bgm="[1:a]",
                    ),
                    "-map", "0:v:0", "-map", "[a_out]", "-shortest",
                ] + _COPY_VIDEO_TS_ARGS
                _run_checked(cmd_bgm, m_ts_bgm, rendered_duration, f"Rank {rank} Seg BGM")
                os.replace(m_ts_bgm, m_ts)

        # ---- MAIN: full span -------------------------------------------------------
        else:
            print("   📸 [Main] Rendering the clip...")
            _render_visual(
                cfg, ratio, cfg.source_video_path, m_silent, m_start, m_end,
                f"Rank {rank} Main", broll=active_broll, **render_modes,
            )

            vf_main = []
            if not cfg.no_subs:
                build_ass_file(
                    data_segments, m_start, m_end, a_main, ratio, cfg,
                    typography_plan=typography_plan, source_dim=source_dim,
                    title_overlay=main_overlay,
                )
                vf_main.append(_subtitle_filter(a_main, cfg))
            if cfg.video_sharpen:
                vf_main.append(SHARPEN_FILTER)

            print(f"   🎬 [Main] FFmpeg {'burn subtitles' if not cfg.no_subs else 'mux audio'}...")
            cmd_m = [
                "ffmpeg", "-hide_banner", "-loglevel", "verbose", "-y",
                "-i", m_silent,
                "-ss", str(m_start), "-to", str(m_end), "-i", cfg.source_video_path,
            ]
            if file_bgm:
                cmd_m += ["-stream_loop", "-1", "-i", file_bgm]
                audio_filter = build_bgm_filter(
                    getattr(cfg, "bgm_mode", "ducking"), cfg.bgm_base_volume,
                    audio_input_voc="[1:a]", audio_input_bgm="[2:a]",
                )
                cmd_m += [
                    "-filter_complex", f"[0:v]{','.join(vf_main) or 'null'}[v_out]; {audio_filter}",
                    "-map", "[v_out]", "-map", "[a_out]", "-shortest",
                ]
            else:
                cmd_m += ["-map", "0:v:0", "-map", "1:a:0", "-af", LOUDNORM_FILTER]
                if vf_main:
                    cmd_m += ["-vf", ",".join(vf_main)]
            _run_checked(cmd_m + std_p, m_ts, m_end - m_start, f"Rank {rank} Main FFmpeg")

        # ---- VOICE-OVER INTRO --------------------------------------------------------
        vo_ts = _render_voiceover_intro(
            rank, ratio, cfg, clip.get("voiceover"), std_p, source_dim,
            typography_plan, file_bgm, m_start,
        )

        # ---- FINAL CONCAT --------------------------------------------------------------
        print("   🔗 [Final] Finalising the clip...")
        parts = [
            path for path in (h_ts if hook_enabled else None, vo_ts, m_ts)
            if path and os.path.exists(path)
        ]
        _concat_ts(parts, out_vid, extra_args=("-bsf:a", "aac_adtstoasc"))

        if out_thm:
            build_thumbnail(out_vid, out_thm, title or f"Highlight {rank}", cfg)

        manifest_item["status"] = "success"
        manifest_item["video_exists"] = os.path.exists(out_vid)
        manifest_item["thumbnail_exists"] = bool(out_thm) and os.path.exists(out_thm)
        print(f"✅ [Rank {rank}] Done.")
        return manifest_item

    except subprocess.CalledProcessError as e:
        print(f"\n❌ ERROR: FFmpeg failed: {e}")
        manifest_item.update(status="failed", error=str(e))
    except Exception as e:
        print(f"\n❌ ERROR: Unexpected failure. Error: {e}")
        manifest_item.update(status="failed", error=str(e))
    finally:
        # Runs after a successful return too: intermediates are several GB over a
        # long queue, which filled the Colab disk when only failures cleaned up.
        _cleanup(rank, cfg, keep_segments, active_broll)

    manifest_item["video_exists"] = os.path.exists(out_vid)
    manifest_item["thumbnail_exists"] = bool(out_thm) and os.path.exists(out_thm)
    return manifest_item


def _cleanup(rank, cfg, keep_segments, active_broll):
    files = [_work(cfg, f"h_{rank}.ts"), _work(cfg, f"m_{rank}.ts"), _work(cfg, f"ah_{rank}.ass"), _work(cfg, f"am_{rank}.ass"),
             _work(cfg, f"h_silent_{rank}.mp4"), _work(cfg, f"m_silent_{rank}.mp4"), _work(cfg, f"m_bgm_{rank}.ts")]
    for idx in range(len(keep_segments or [])):
        files += [_work(cfg, f"m_seg_silent_{rank}_{idx}.mp4"), _work(cfg, f"m_seg_ass_{rank}_{idx}.ass"),
                  _work(cfg, f"m_seg_ts_{rank}_{idx}.ts")]
    files += [
        os.path.join(cfg.outputs_dir, name)
        for name in (f"vo_intro_{rank}.ts", f"vo_subs_{rank}.ass", f"vo_bg_{rank}.jpg")
    ]
    files += [br["filepath"] for br in active_broll]
    for path in files:
        if os.path.exists(path):
            os.remove(path)
