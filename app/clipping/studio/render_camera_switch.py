import math
import os
import urllib.request

import cv2
import numpy as np
import mediapipe as mp

from ..progress import ProgressBar
from .broll import crop_center_broll, open_broll_captures, read_broll_frame
from .face_detection import get_face_detector
from .utils import _resize_frame, _get_render_dims, make_blur_fill
from .ffmpeg_utils import detect_video_encoder, open_ffmpeg_video_writer, run_ffmpeg_with_progress
from .watermark import apply_watermark


def render_camera_switch_video(
    input_video,
    output_video,
    start_clip,
    end_clip,
    ratio,
    diarization_data,
    cfg,
    label="CameraSwitch",
    broll_data=None,
):
    """
    Render a dynamic camera-switch video, which cuts between active speakers automatically.

    Args:
        input_video (str): Path to input video file.
        output_video (str): Path to output video file.
        start_clip (float): Subclip start boundary in seconds.
        end_clip (float): Subclip end boundary in seconds.
        ratio (str): Output ratio string ('9:16' or '16:9').
        diarization_data (list | None): Timeline of active speakers; None falls
            back to treating the clip as single-speaker.
        cfg: The runtime config containing camera-switch timing preferences.
        label (str, optional): Progress reporting name.
        broll_data (list, optional): Data about B-roll sequences to blend in.

    Returns:
        callable: A function mapping timestamp to horizontal subtitle coordinate `get_x_final(t)`.

    Side Effects:
        Perform multi-pass face detection, smoothing, and transitions.
        Outputs via `run_ffmpeg_with_progress`.

    Raises:
        May raise Exceptions if FFMPEG piped commands fail.
    """
    from ..diarization import get_active_speakers

    STEP_DETECTION     = cfg.track_step if cfg.track_step is not None else 0.25
    DEADZONE_RATIO   = cfg.track_deadzone if cfg.track_deadzone is not None else 0.15
    SMOOTH_FACTOR    = cfg.track_smooth if cfg.track_smooth is not None else 0.30
    JITTER_THRESHOLD = cfg.track_jitter if cfg.track_jitter is not None else 5
    SNAP_THRESHOLD   = cfg.track_snap if cfg.track_snap is not None else 0.25
    MIN_HOLD = float(getattr(cfg, "switch_hold_duration", 2.0))
    BLUR_KERNEL = 99
    BLUR_SIGMA = 30

    video_encoder = detect_video_encoder(cfg)

    if broll_data is None:
        broll_data = []

    broll_caps = open_broll_captures(broll_data)

    # ---------------------------------------------------------------- face detector
    yolo_model = None
    detector = None
    if cfg.face_detector == "yolo":
        if not os.path.exists(cfg.file_yolo_model):
            print(f"   📥 Downloading the YOLOv8 face model ({cfg.yolo_size})...")
            import urllib.request

            urllib.request.urlretrieve(cfg.url_yolo_model, cfg.file_yolo_model)
        from ultralytics import YOLO

        yolo_model = YOLO(cfg.file_yolo_model)
    else:
        detector = get_face_detector(cfg)

    cap = cv2.VideoCapture(input_video)
    orig_fps = cap.get(cv2.CAP_PROP_FPS)
    if math.isnan(orig_fps) or orig_fps == 0:
        orig_fps = 30.0

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = end_clip - start_clip

    out_w, out_h = _get_render_dims(cfg, ratio, source_h=height)

    # 9:16 crop region from the source frame
    crop_ratio = out_w / out_h  # ≈ 0.5625
    if (width / height) > crop_ratio:  # source is wider  → crop width
        crop_h = height
        crop_w = int(height * crop_ratio)
    else:  # source is taller → crop height
        crop_w = width
        crop_h = int(width / crop_ratio)

    # All unique speakers in this clip. The custom-hook path deliberately passes
    # no diarization, so fall back to a single speaker rather than crashing.
    speakers = sorted(set(s["speaker"] for s in diarization_data or []))
    if not speakers:
        speakers = ["SPEAKER_00"]

    # ================================================================
    # PHASE 1 — Per-speaker face profiling (diarization-guided)
    # ================================================================
    # Strategy:
    #   1 active + 1 face  → trivial: face belongs to active speaker
    #   N active + N faces → sort faces by X; sort speakers by label; assign in order
    #   1 active + N faces → use speaker's last-known position to pick nearest face
    #   otherwise          → skip (ambiguous / no data)
    print(f"🧠 {label} - Face analysis (camera switch) started...", flush=True)

    all_frame_data: list[dict] = []  # [{time, face_centers, active_now}]
    speaker_solo_cxs: dict[str, list] = {}  # speaker → [cx, ...] from 1:1 frames
    solo_counts: dict[str, int] = {spk: 0 for spk in speakers}
    multi_counts: dict[str, int] = {spk: 0 for spk in speakers}
    current_time = 0.0
    detect_bar = ProgressBar(duration, f"{label} - Face analysis")

    def _clamp_x_cs(cx_center: float) -> int:
        return max(0, min(int(cx_center - crop_w / 2), width - crop_w))

    while current_time <= duration:
        cap.set(cv2.CAP_PROP_POS_MSEC, (start_clip + current_time) * 1000)
        ret, frame = cap.read()
        if not ret:
            break

        face_centers = []
        face_boxes = []

        if cfg.face_detector == "yolo":
            yolo_results = yolo_model(frame, verbose=False)
            if yolo_results and len(yolo_results[0].boxes) > 0:
                boxes = yolo_results[0].boxes.xyxy.cpu().numpy()
                for box in boxes:
                    x1, y1, x2, y2 = box
                    face_centers.append(((x1 + x2) / 2, (y1 + y2) / 2))
                    face_boxes.append((x1, y1, x2, y2))
        else:
            results = detector.detect(
                mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                )
            )
            if results.detections:
                for d in results.detections:
                    bb = d.bounding_box
                    face_centers.append(
                        (
                            bb.origin_x + bb.width / 2,
                            bb.origin_y + bb.height / 2,
                        )
                    )
                    face_boxes.append(
                        (
                            bb.origin_x,
                            bb.origin_y,
                            bb.origin_x + bb.width,
                            bb.origin_y + bb.height,
                        )
                    )

        face_centers.sort(key=lambda fc: fc[0])  # left → right
        active_now = get_active_speakers(diarization_data, start_clip + current_time)
        n_faces = len(face_centers)
        n_active = len(active_now)

        # Pass A: collect face data and build canonical solo observations.
        # Full assignment happens in Pass B after canonical_cx is built from entire clip.
        if n_faces == 1 and n_active == 1:
            spk = active_now[0]
            speaker_solo_cxs.setdefault(spk, []).append((face_centers[0][0], face_centers[0][1]))
            solo_counts[spk] = solo_counts.get(spk, 0) + 1
        elif n_faces >= 2 and n_active >= 1:
            for spk in active_now:
                multi_counts[spk] = multi_counts.get(spk, 0) + 1

        all_frame_data.append(
            {
                "time": current_time,
                "face_centers": face_centers,
                "face_boxes": face_boxes,
                "active_now": active_now,
            }
        )

        detect_bar.update(current_time)

        current_time += STEP_DETECTION

    detect_bar.close(f"🧠 {label} - Face analysis complete.")

    # Build canonical center-X per speaker from 1:1 frames
    import statistics as _stats

    speaker_canonical_cx: dict[str, float] = {
        spk: _stats.median([c[0] for c in cxs]) for spk, cxs in speaker_solo_cxs.items() if cxs
    }

    if not diarization_data:
        # Visual-only: assume L is left and R is right
        if "FACE_L" not in speaker_canonical_cx:
            speaker_canonical_cx["FACE_L"] = width * 0.25
        if "FACE_R" not in speaker_canonical_cx:
            speaker_canonical_cx["FACE_R"] = width * 0.75

    # Determine which speakers appear mostly in solo-scene frames
    speaker_is_solo: dict[str, bool] = {
        spk: (solo_counts.get(spk, 0) > multi_counts.get(spk, 0))
        for spk in speakers
    }

    # ================================================================
    # Pass B — Canonical-guided face-to-speaker assignment
    # ================================================================
    # Re-process all stored frames using canonical_cx built from entire clip.
    # Multi-scene videos: Speaker C's solo canonical eliminates their face from
    # Scene A frames, leaving the correct face for Scene A speakers.
    # ================================================================
    raw_data: dict[str, list] = {spk: [] for spk in speakers}

    for fd in all_frame_data:
        fc_list = fd["face_centers"]  # list of (cx, cy), sorted left → right
        act_list = fd["active_now"]
        nf = len(fc_list)
        na = len(act_list)

        if nf == 0 or na == 0:
            continue

        if nf == 1 and na == 1:
            spk = act_list[0]
            if spk in raw_data:
                others = [fc for fc in fc_list if fc != fc_list[0]]
                d_near = min([abs(fc[0] - fc_list[0][0]) for fc in others]) if others else width
                raw_data[spk].append({"time": fd["time"], "cx": fc_list[0][0], "cy": fc_list[0][1], "dist": d_near})

        elif nf >= 2 and na >= 2:
            remaining = list(fc_list)
            for spk in sorted(
                act_list, key=lambda s: speaker_canonical_cx.get(s, width / 2)
            ):
                if not remaining or spk not in raw_data:
                    break
                best = min(
                    remaining,
                    key=lambda fc: abs(
                        fc[0] - speaker_canonical_cx.get(spk, width / 2)
                    ),
                )
                remaining.remove(best)
                others = [fc for fc in fc_list if fc != best]
                d_near = min([abs(fc[0] - best[0]) for fc in others]) if others else width
                raw_data[spk].append({"time": fd["time"], "cx": best[0], "cy": best[1], "dist": d_near})

        elif nf >= 2 and na == 1:
            spk = act_list[0]
            if spk not in raw_data:
                continue
            remaining = list(fc_list)
            for other in speakers:
                if other == spk or other not in speaker_canonical_cx or not remaining:
                    continue
                claimed = min(
                    remaining, key=lambda fc: abs(fc[0] - speaker_canonical_cx[other])
                )
                remaining.remove(claimed)
            pool = remaining if remaining else fc_list
            if raw_data[spk]:
                last_cx = raw_data[spk][-1]["cx"]
                best = min(pool, key=lambda fc: abs(fc[0] - last_cx))
            elif spk in speaker_canonical_cx:
                best = min(pool, key=lambda fc: abs(fc[0] - speaker_canonical_cx[spk]))
            else:
                best = pool[len(pool) // 2]
            
            others = [fc for fc in fc_list if fc != best]
            d_near = min([abs(fc[0] - best[0]) for fc in others]) if others else width
            raw_data[spk].append({"time": fd["time"], "cx": best[0], "cy": best[1], "dist": d_near})

    # ================================================================
    # PHASE 2 — Smooth per-speaker camera positions
    # ================================================================
    def _smooth_positions_cs(raw_list):
        smooth_list = []
        if not raw_list:
            return smooth_list
        cam_cx = raw_list[0]["cx"]
        cam_cy = raw_list[0]["cy"]
        
        # Reference crop width before any zoom is applied
        p_ratio = crop_w / crop_h
        if (width / height) > p_ratio:
            ref_crop_w = int(height * p_ratio)
        else:
            ref_crop_w = width

        # Auto-zoom logic setup
        def _calc_target_zoom(dist_val):
            if not cfg.split_auto_zoom:
                return 1.0
            # Aggressive separation multiplier: 1.6
            buffer = ref_crop_w * 0.10
            effective_dist = max(50, dist_val - buffer)
            t_zoom = (ref_crop_w / (2 * effective_dist)) * 1.6
            return max(1.0, min(t_zoom, getattr(cfg, "split_max_zoom", 4.5)))

        # Look ahead at first few frames to avoid "zoom-in" lag at start
        initial_dist = width
        for d in raw_list[:10]:
            d_val = d.get("dist", width)
            if d_val < initial_dist:
                initial_dist = d_val
        
        cam_zoom = _calc_target_zoom(initial_dist)
        
        deadzone_px = crop_w * DEADZONE_RATIO
        snap_px = width * SNAP_THRESHOLD
        
        for d in raw_list:
            face_cx = d["cx"]
            face_cy = d["cy"]
            if abs(face_cx - cam_cx) > snap_px:
                cam_cx = face_cx
            else:
                if face_cx > cam_cx + deadzone_px:
                    cam_cx += (face_cx - (cam_cx + deadzone_px)) * SMOOTH_FACTOR
                elif face_cx < cam_cx - deadzone_px:
                    cam_cx += (face_cx - (cam_cx - deadzone_px)) * SMOOTH_FACTOR
            
            # Vertical smoothing
            cam_cy += (face_cy - cam_cy) * SMOOTH_FACTOR
            
            # Auto-zoom logic
            target_zoom = _calc_target_zoom(d.get("dist", width))
            cam_zoom += (target_zoom - cam_zoom) * SMOOTH_FACTOR
            
            smooth_list.append({"time": d["time"], "cx": cam_cx, "cy": cam_cy, "zoom": cam_zoom})
        return smooth_list

    smooth: dict[str, list] = {
        spk: _smooth_positions_cs(raw_data[spk]) for spk in speakers
    }

    def _get_pos_cs(speaker, t):
        sd = smooth.get(speaker, [])
        if not sd:
            return width / 2, height / 2, 1.0
        if t <= sd[0]["time"]:
            return sd[0]["cx"], sd[0]["cy"], sd[0]["zoom"]
        if t >= sd[-1]["time"]:
            return sd[-1]["cx"], sd[-1]["cy"], sd[-1]["zoom"]
        for i in range(len(sd) - 1):
            if sd[i]["time"] <= t <= sd[i + 1]["time"]:
                t1, t2 = sd[i]["time"], sd[i + 1]["time"]
                cx1, cx2 = sd[i]["cx"], sd[i + 1]["cx"]
                cy1, cy2 = sd[i]["cy"], sd[i + 1]["cy"]
                z1, z2 = sd[i]["zoom"], sd[i + 1]["zoom"]
                if t1 == t2:
                    return cx1, cy1, z1
                frac = (t - t1) / (t2 - t1)
                return (
                    cx1 + (cx2 - cx1) * frac,
                    cy1 + (cy2 - cy1) * frac,
                    z1 + (z2 - z1) * frac
                )
        return width / 2, height / 2, 1.0

    # ----------------------------------------------------------------
    # Helper: blurred pillarbox for wide-shot / simultaneous speech
    # ----------------------------------------------------------------
    def _make_blurred_pillarbox(frame):
        return make_blur_fill(frame, out_w, out_h, cfg)

    # PHASE 3: RENDER FRAME
    out_w, out_h = _get_render_dims(cfg, ratio, source_h=height)

    writer = open_ffmpeg_video_writer(
        output_video, out_w, out_h, orig_fps, video_encoder
    )

    current_speaker = None
    last_switch_time = 0.0

    # --- Anti-Sliding: Last-known position cache per speaker ---
    # Remembers each speaker's last crop (cx, cy, zoom). When switching back to
    # a speaker we have already framed, snap straight to their previous position
    # instead of sliding/panning a long way across the frame.
    last_speaker_pos: dict[str, tuple[float, float, float]] = {}
    prev_speaker = None  # the speaker before the switch, used to detect a transition
    SWITCH_BLEND_DUR = float(getattr(cfg, "switch_blend_duration", 0.0))
    switch_blend_t0 = -1.0  # when blending starts after a switch

    def _resolve_switch_pos(speaker, t, is_new_switch):
        """Return (cx, cy, zoom) with anti-sliding cache + optional blend."""
        nonlocal switch_blend_t0
        smoothed = _get_pos_cs(speaker, t)
        if is_new_switch and speaker in last_speaker_pos:
            cached = last_speaker_pos[speaker]
            if SWITCH_BLEND_DUR <= 0:
                # Instant snap
                result = cached
            else:
                switch_blend_t0 = t
                result = cached
        elif SWITCH_BLEND_DUR > 0 and switch_blend_t0 >= 0 and (t - switch_blend_t0) < SWITCH_BLEND_DUR:
            # Still blending from cached → smoothed
            frac = min(1.0, (t - switch_blend_t0) / SWITCH_BLEND_DUR)
            cached = last_speaker_pos.get(speaker, smoothed)
            result = (
                cached[0] + (smoothed[0] - cached[0]) * frac,
                cached[1] + (smoothed[1] - cached[1]) * frac,
                cached[2] + (smoothed[2] - cached[2]) * frac,
            )
        else:
            result = smoothed
            switch_blend_t0 = -1.0
        last_speaker_pos[speaker] = result
        return result

    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, start_clip * 1000)
        frame_count = 0
        tracking_log = [] # Store (t, cx) for each frame

        print(f"🎬 {label} - Camera-switch render started...", flush=True)
        render_bar = ProgressBar(duration, f"{label} - Rendering")

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            t = frame_count / orig_fps
            if t > duration:
                break

            timestamp_abs = start_clip + t
            active_speakers = get_active_speakers(diarization_data, timestamp_abs)

            # tracking_log stores the crop CENTRE (subtitles.py reads it as one).
            cx = width // 2

            if len(active_speakers) >= 2:
                # ... standard logic ...
                all_multi_scene = all(
                    not speaker_is_solo.get(spk, False) for spk in active_speakers
                )
                if all_multi_scene:
                    cx = width // 2
                    out_frame = _make_blurred_pillarbox(frame)
                else:
                    is_new_switch = False
                    if current_speaker is None or current_speaker not in active_speakers:
                        prev_speaker = current_speaker
                        current_speaker = active_speakers[0]
                        last_switch_time = t
                        is_new_switch = prev_speaker is not None
                    # Anti-sliding: resolve position with cache + optional blend
                    cx, cy, s_zoom = _resolve_switch_pos(current_speaker, t, is_new_switch)
                    eff_cw = int(crop_w / s_zoom)
                    eff_ch = int(crop_h / s_zoom)
                    x_full = int(max(0, min(cx - eff_cw / 2, width - eff_cw)))
                    y_full = int(max(0, min(cy - eff_ch / 2, height - eff_ch)))
                    crop_fr = frame[y_full : y_full + eff_ch, x_full : x_full + eff_cw]
                    out_frame = _resize_frame(crop_fr, (out_w, out_h))

            elif len(active_speakers) == 1:
                new_speaker = active_speakers[0]
                is_new_switch = False
                if current_speaker is None:
                    current_speaker = new_speaker
                    last_switch_time = t
                elif (
                    new_speaker != current_speaker
                    and (t - last_switch_time) >= MIN_HOLD
                ):
                    prev_speaker = current_speaker
                    current_speaker = new_speaker
                    last_switch_time = t
                    is_new_switch = True
                # Anti-sliding: resolve position with cache + optional blend
                cx, cy, s_zoom = _resolve_switch_pos(current_speaker, t, is_new_switch)
                eff_cw = int(crop_w / s_zoom)
                eff_ch = int(crop_h / s_zoom)
                x_full = int(max(0, min(cx - eff_cw / 2, width - eff_cw)))
                y_full = int(max(0, min(cy - eff_ch / 2, height - eff_ch)))
                crop_fr = frame[y_full : y_full + eff_ch, x_full : x_full + eff_cw]
                out_frame = _resize_frame(crop_fr, (out_w, out_h))

            else:
                if current_speaker is not None:
                    cx, cy, s_zoom = _resolve_switch_pos(current_speaker, t, False)
                    eff_cw = int(crop_w / s_zoom)
                    eff_ch = int(crop_h / s_zoom)
                    x_full = int(max(0, min(cx - eff_cw / 2, width - eff_cw)))
                    y_full = int(max(0, min(cy - eff_ch / 2, height - eff_ch)))
                    crop_fr = frame[y_full : y_full + eff_ch, x_full : x_full + eff_cw]
                    out_frame = _resize_frame(crop_fr, (out_w, out_h))
                else:
                    cx = width // 2  # Centre for the blurred pillarbox view
                    out_frame = _make_blurred_pillarbox(frame)

            # --- B-ROLL OVERLAY ---
            absolute_time = start_clip + t
            TRANSITION_DUR = 0.3
            MAX_ZOOM = 1.10
            for bc in broll_caps:
                if bc["start"] <= absolute_time <= bc["end"]:
                    elapsed_broll = absolute_time - bc["start"]
                    frame_b = read_broll_frame(bc, elapsed_broll)

                    if frame_b is not None:
                        total_broll_duration = bc["end"] - bc["start"]
                        progress_broll = elapsed_broll / total_broll_duration if total_broll_duration > 0 else 0
                        zoom_factor = 1.0 + ((MAX_ZOOM - 1.0) * progress_broll)

                        frame_b_crop = crop_center_broll(frame_b, out_w, out_h)
                        M = cv2.getRotationMatrix2D((out_w / 2, out_h / 2), 0, zoom_factor)
                        frame_b_zoomed = cv2.warpAffine(frame_b_crop, M, (out_w, out_h))

                        alpha = 1.0
                        if elapsed_broll < TRANSITION_DUR:
                            alpha = elapsed_broll / TRANSITION_DUR
                        elif (bc["end"] - absolute_time) < TRANSITION_DUR:
                            alpha = (bc["end"] - absolute_time) / TRANSITION_DUR

                        if alpha >= 1.0:
                            out_frame = frame_b_zoomed
                        else:
                            out_frame = cv2.addWeighted(frame_b_zoomed, alpha, out_frame, 1.0 - alpha, 0)
                    break

            # --- WATERMARK OVERLAY ---
            if getattr(cfg, "watermark_enabled", False):
                out_frame = apply_watermark(out_frame, cfg)

            tracking_log.append((t, cx))
            writer.stdin.write(out_frame.tobytes())
            frame_count += 1

            render_bar.update(t)

        render_bar.close()
        writer.stdin.close()
        stderr_data = writer.stderr.read().decode("utf-8", errors="ignore")
        return_code = writer.wait()

        if return_code != 0:
            raise RuntimeError(f"The FFmpeg writer failed: {stderr_data[-1000:]}")

        print(f"✅ {label} done.", flush=True)

        # Helper for subtitle positioning
        def get_x_final(t):
            if not tracking_log:
                return width // 2  # centre, matching what tracking_log stores
            if t <= tracking_log[0][0]:
                return int(tracking_log[0][1])
            
            for i in range(len(tracking_log)-1):
                if tracking_log[i][0] <= t <= tracking_log[i+1][0]:
                    t1, t2 = tracking_log[i][0], tracking_log[i+1][0]
                    cx1, cx2 = tracking_log[i][1], tracking_log[i+1][1]
                    cx = cx1 + (cx2 - cx1) * (t - t1) / (t2 - t1)
                    return int(cx)
            
            return int(tracking_log[-1][1])

        return get_x_final

    finally:
        cap.release()
        for bc in broll_caps:
            bc["cap"].release()


