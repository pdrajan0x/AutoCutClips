"""
clipping.studio.render_hybrid — The default single-camera renderer.

For every clip part it:
  1. analyses the faces — and, with several people in frame, who is talking;
  2. chooses the framing: a crop that follows the chosen face, or, for footage
     without faces (slides, screen recordings, gameplay), the whole frame over
     a blurred copy of itself;
  3. renders the silent video.

Rendering is one FFmpeg pass (the crop follows a time expression) unless
per-frame compositing is needed for B-roll or a watermark; those clips go
through the OpenCV frame loop, which is also the fallback if FFmpeg refuses the
fast path.
"""

import bisect
import math
import os
import statistics
import urllib.request

import cv2
import mediapipe as mp

from ..progress import ProgressBar
from .active_speaker import get_mouth_meter, select_speaker_faces
from .broll import crop_center_broll, open_broll_captures, read_broll_frame
from .face_detection import get_face_detector
from .ffmpeg_utils import (
    _intermediate_encoder,
    build_ffmpeg_progress_cmd,
    detect_video_encoder,
    get_mp4_encode_args,
    open_ffmpeg_video_writer,
    run_ffmpeg_with_progress,
)
from .utils import (
    RATIO_MAP,
    _get_render_dims,
    _is_vertical_ratio,
    _resize_frame,
    blur_fill_filter,
    build_crop_expressions,
    make_blur_fill,
)
from .watermark import apply_watermark

# Seconds a large face jump must persist before the camera cuts to it. Shorter
# jumps are a false detection or a second person briefly leaning into frame.
SNAP_CONFIRM_SECONDS = 0.5

# Below this share of analysed moments with a face, the clip is treated as
# faceless footage and the whole frame is fitted over a blurred background.
MIN_FACE_SHARE = 0.3

# Where the face sits vertically when the crop is shorter than the source.
FACE_VERTICAL_ANCHOR = 0.42

BROLL_TRANSITION = 0.3
BROLL_MAX_ZOOM = 1.10

_YOLO_MODELS: dict = {}


def _face_detector_fn(cfg):
    """Return ``detect(frame) -> [(x1, y1, x2, y2), ...]`` for the configured model."""
    if cfg.face_detector == "yolo":
        model = _YOLO_MODELS.get(cfg.file_yolo_model)
        if model is None:
            if not os.path.exists(cfg.file_yolo_model):
                print(f"   📥 Downloading the YOLOv8 face model ({cfg.yolo_size})...")
                urllib.request.urlretrieve(cfg.url_yolo_model, cfg.file_yolo_model)
            from ultralytics import YOLO

            model = YOLO(cfg.file_yolo_model)
            _YOLO_MODELS[cfg.file_yolo_model] = model

        def detect_yolo(frame):
            results = model(frame, verbose=False)
            if not results or len(results[0].boxes) == 0:
                return []
            return [tuple(float(v) for v in box) for box in results[0].boxes.xyxy.cpu().numpy()]

        return detect_yolo

    detector = get_face_detector(cfg)

    def detect_mediapipe(frame):
        results = detector.detect(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        )
        return [
            (bb.origin_x, bb.origin_y, bb.origin_x + bb.width, bb.origin_y + bb.height)
            for bb in (det.bounding_box for det in (results.detections or []))
        ]

    return detect_mediapipe


def _analyse_faces(cap, fps, start_clip, duration, step, detect, meter, label):
    """
    Sample the clip every *step* seconds.

    Frames are read sequentially (``grab`` skips the ones in between) instead
    of seeking to every sample, which decoded from the previous keyframe each time.
    """
    samples = []
    cap.set(cv2.CAP_PROP_POS_MSEC, start_clip * 1000)
    bar = ProgressBar(duration, f"{label} - Face analysis")
    frame_idx = 0
    next_t = 0.0
    half_frame = 0.5 / fps

    while next_t <= duration:
        if frame_idx / fps + half_frame < next_t:
            if not cap.grab():
                break
            frame_idx += 1
            continue

        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1

        boxes = detect(frame)
        mouths = [None] * len(boxes)
        if meter is not None and len(boxes) >= 2:
            mouths = [meter.measure(frame, box) for box in boxes]
        samples.append({"time": next_t, "boxes": boxes, "mouths": mouths})

        bar.update(next_t)
        next_t += step

    bar.close(f"🧠 {label} - Face analysis complete.")
    return samples


def _camera_path(samples, chosen, crop_w, step, deadzone_ratio, smooth_factor, snap_px):
    """Turn the chosen face per sample into a smoothed camera centre per sample."""
    raw = []
    for sample, box in zip(samples, chosen):
        if box:
            raw.append({"time": sample["time"], "box": box,
                        "cx": (box[0] + box[2]) / 2, "cy": (box[1] + box[3]) / 2})
        else:
            raw.append({"time": sample["time"], "box": None, "cx": None, "cy": None})

    first_hit = next((r for r in raw if r["box"]), None)
    if first_hit is None:
        return []

    # A missed detection (head turned, motion blur) holds the last known face
    # instead of jumping to the frame centre and back.
    last_cx, last_cy = first_hit["cx"], first_hit["cy"]
    for r in raw:
        if r["box"]:
            last_cx, last_cy = r["cx"], r["cy"]
        else:
            r["cx"], r["cy"] = last_cx, last_cy

    cam_cx = statistics.median(r["cx"] for r in raw[:5])
    cam_cy = statistics.median(r["cy"] for r in raw[:5])
    deadzone_px = crop_w * deadzone_ratio
    snap_confirm = max(1, round(SNAP_CONFIRM_SECONDS / step))
    jump_start = None
    smooth = []

    for i, r in enumerate(raw):
        face_cx, face_cy = r["cx"], r["cy"]

        if abs(face_cx - cam_cx) > snap_px:
            # Hold still until the jump proves real, then cut — backdated to
            # where the jump began so it lands on the source's own cut.
            if jump_start is None:
                jump_start = i
            if i - jump_start + 1 >= snap_confirm:
                cam_cx = face_cx
                for s in smooth[jump_start:]:
                    s["cx"] = cam_cx
                jump_start = None
        else:
            jump_start = None
            if face_cx > cam_cx + deadzone_px:
                cam_cx += (face_cx - (cam_cx + deadzone_px)) * smooth_factor
            elif face_cx < cam_cx - deadzone_px:
                cam_cx += (face_cx - (cam_cx - deadzone_px)) * smooth_factor

        cam_cy += (face_cy - cam_cy) * smooth_factor
        smooth.append({"time": r["time"], "cx": cam_cx, "cy": cam_cy})

    return smooth


def _position_fn(smooth, snap_px, default):
    """Interpolate the camera centre at any clip time (hard cuts are not interpolated)."""
    times = [s["time"] for s in smooth]

    def position(t):
        if not smooth:
            return default
        if t <= times[0]:
            return smooth[0]["cx"], smooth[0]["cy"]
        if t >= times[-1]:
            return smooth[-1]["cx"], smooth[-1]["cy"]
        i = bisect.bisect_right(times, t) - 1
        a, b = smooth[i], smooth[i + 1]
        if b["time"] == a["time"]:
            return a["cx"], a["cy"]
        if abs(b["cx"] - a["cx"]) > snap_px:
            chosen = a if t < (a["time"] + b["time"]) / 2 else b
            return chosen["cx"], chosen["cy"]
        frac = (t - a["time"]) / (b["time"] - a["time"])
        return a["cx"] + (b["cx"] - a["cx"]) * frac, a["cy"] + (b["cy"] - a["cy"]) * frac

    return position


def _render_with_ffmpeg(input_video, output_video, start_clip, duration, fps, mode,
                        out_dims, crop, origin_at, moving, cfg, video_encoder, label):
    """Render the framing in one FFmpeg pass. Returns False if FFmpeg failed."""
    out_w, out_h = out_dims
    algo = str(getattr(cfg, "video_scale_algo", "lanczos"))

    if mode == "scale":
        graph = f"[0:v]scale={out_w}:{out_h}:flags={algo},setsar=1[v]"
    elif mode == "fill":
        graph = f"[0:v]{blur_fill_filter(out_w, out_h, algo)},setsar=1[v]"
    else:
        crop_w, crop_h = crop
        if moving:
            x_expr, y_expr = build_crop_expressions(origin_at, duration)
        else:
            x_expr, y_expr = (str(v) for v in origin_at(0.0))
        # Quoted so the commas inside the expressions don't split the filter chain.
        graph = (
            f"[0:v]crop=w={crop_w}:h={crop_h}:x='{x_expr}':y='{y_expr}',"
            f"scale={out_w}:{out_h}:flags={algo},setsar=1[v]"
        )

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start_clip:.3f}", "-t", f"{duration:.3f}", "-i", input_video,
        "-filter_complex", graph, "-map", "[v]", "-an",
    ] + get_mp4_encode_args(_intermediate_encoder(video_encoder), fps)

    rc, errors = run_ffmpeg_with_progress(
        build_ffmpeg_progress_cmd(cmd, output_video), duration, label=f"{label} - Rendering"
    )

    if rc != 0:
        print(f"   ⚠️ {label} - FFmpeg framing pass failed: {' | '.join(errors[-3:])}")
        return False
    return True


def _render_with_opencv(cap, output_video, start_clip, duration, fps, mode, out_dims,
                        crop, origin_at, broll_data, cfg, video_encoder, label):
    """Frame-by-frame render, needed for B-roll inserts and watermarks."""
    out_w, out_h = out_dims
    crop_w, crop_h = crop

    broll_caps = open_broll_captures(broll_data)
    writer = open_ffmpeg_video_writer(output_video, out_w, out_h, fps, video_encoder)

    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, start_clip * 1000)
        frame_count = 0
        print(f"🎬 {label} - Frame render started...", flush=True)
        render_bar = ProgressBar(duration, f"{label} - Rendering")

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            t = frame_count / fps
            if t > duration:
                break
            absolute_time = start_clip + t

            if mode == "fill":
                out_frame = make_blur_fill(frame, out_w, out_h, cfg)
            elif mode == "scale":
                out_frame = _resize_frame(frame, (out_w, out_h), cfg)
            else:
                x, y = origin_at(t)
                out_frame = _resize_frame(frame[y:y + crop_h, x:x + crop_w], (out_w, out_h), cfg)

            for bc in broll_caps:
                if not bc["start"] <= absolute_time <= bc["end"]:
                    continue
                elapsed = absolute_time - bc["start"]
                frame_b = read_broll_frame(bc, elapsed)
                if frame_b is not None:
                    span = bc["end"] - bc["start"]
                    zoom = 1.0 + (BROLL_MAX_ZOOM - 1.0) * (elapsed / span if span > 0 else 0)
                    frame_b = crop_center_broll(frame_b, out_w, out_h)
                    matrix = cv2.getRotationMatrix2D((out_w / 2, out_h / 2), 0, zoom)
                    frame_b = cv2.warpAffine(frame_b, matrix, (out_w, out_h))

                    alpha = 1.0
                    if elapsed < BROLL_TRANSITION:
                        alpha = elapsed / BROLL_TRANSITION
                    elif bc["end"] - absolute_time < BROLL_TRANSITION:
                        alpha = (bc["end"] - absolute_time) / BROLL_TRANSITION
                    out_frame = frame_b if alpha >= 1.0 else cv2.addWeighted(
                        frame_b, alpha, out_frame, 1.0 - alpha, 0
                    )
                break

            if getattr(cfg, "watermark_enabled", False):
                out_frame = apply_watermark(out_frame, cfg)

            writer.stdin.write(out_frame.tobytes())
            frame_count += 1
            render_bar.update(t)

        render_bar.close()
        writer.stdin.close()
        stderr_data = writer.stderr.read().decode("utf-8", errors="ignore")
        if writer.wait() != 0:
            raise RuntimeError(f"The FFmpeg writer failed: {stderr_data[-1000:]}")
    finally:
        for bc in broll_caps:
            bc["cap"].release()


def render_hybrid_video(
    input_video,
    output_video,
    start_clip,
    end_clip,
    ratio,
    cfg,
    broll_data=None,
    label="Hybrid",
):
    """
    Render one clip part with automatic framing.

    Args:
        input_video (str): Source video file path.
        output_video (str): Output (silent, intermediate) video path.
        start_clip (float): Start timestamp in seconds.
        end_clip (float): End timestamp in seconds.
        ratio (str): Output ratio string.
        cfg: Runtime config (tracking tuning, layout, speaker tracking, encoder).
        broll_data (list, optional): B-roll inserts (dicts with filepath/start_time/end_time).
        label (str, optional): Label used in progress output.

    Returns:
        callable: ``get_x(t)`` — the camera's horizontal centre at clip time ``t``.
    """
    broll_data = broll_data or []
    step = cfg.track_step if cfg.track_step is not None else 0.25
    deadzone_ratio = cfg.track_deadzone if cfg.track_deadzone is not None else 0.15
    smooth_factor = cfg.track_smooth if cfg.track_smooth is not None else 0.30
    snap_threshold = cfg.track_snap if cfg.track_snap is not None else 0.08

    video_encoder = detect_video_encoder(cfg)

    cap = cv2.VideoCapture(input_video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if math.isnan(fps) or fps <= 0:
        fps = 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = end_clip - start_clip
    out_dims = _get_render_dims(cfg, ratio, source_h=height)
    vertical = _is_vertical_ratio(ratio)

    # Largest crop of the target shape that fits the source (a portrait source
    # cropped to 1:1 used to ask for a crop wider than the frame).
    w_part, h_part = RATIO_MAP.get(ratio, (16, 9))
    target_ratio = w_part / h_part
    if width / height > target_ratio:
        crop_w, crop_h = int(round(height * target_ratio)), height
    else:
        crop_w, crop_h = width, int(round(width / target_ratio))
    crop_w, crop_h = max(2, crop_w - crop_w % 2), max(2, crop_h - crop_h % 2)

    layout = str(getattr(cfg, "layout", "auto")).lower()
    static = getattr(cfg, "static_crop", False) and ratio in ("1:1", "3:4", "4:5")
    snap_px = width * snap_threshold
    smooth = []

    if not vertical:
        # Landscape output: scale a matching source, blur-fill anything else
        # (a portrait source used to get black bars).
        mode = "scale" if abs(width / height - target_ratio) < 0.01 else "fill"
    elif layout == "blur":
        mode = "fill"
    else:
        mode = "crop"

    try:
        if mode == "crop" and static:
            print(f"🧠 {label} - Static crop enabled (no face tracking)...", flush=True)
        elif mode == "crop":
            print(f"🧠 {label} - Face analysis started...", flush=True)
            meter = get_mouth_meter(cfg) if getattr(cfg, "speaker_tracking", True) else None
            samples = _analyse_faces(
                cap, fps, start_clip, duration, step, _face_detector_fn(cfg), meter, label
            )
            face_share = sum(1 for s in samples if s["boxes"]) / len(samples) if samples else 0.0

            if layout == "auto" and samples and face_share < MIN_FACE_SHARE:
                print(
                    f"   🖼️ {label} - Faces in only {face_share:.0%} of the clip; "
                    "fitting the whole frame over a blurred background."
                )
                mode = "fill"
            else:
                if meter is not None and any(len(s["boxes"]) >= 2 for s in samples):
                    print(f"   🗣️ {label} - Several people in frame; following whoever is talking.")
                chosen = select_speaker_faces(samples, width, step)
                smooth = _camera_path(
                    samples, chosen, crop_w, step, deadzone_ratio, smooth_factor, snap_px
                )

        position = _position_fn(smooth, snap_px, (width / 2, height / 2))

        def origin_at(t):
            if not smooth:
                return (width - crop_w) // 2, (height - crop_h) // 2
            cx, cy = position(t)
            x = int(max(0, min(cx - crop_w / 2, width - crop_w)))
            y = int(max(0, min(cy - crop_h * FACE_VERTICAL_ANCHOR, height - crop_h)))
            return x, y

        has_broll = any(
            os.path.exists(br.get("filepath", ""))
            and br["end_time"] > start_clip and br["start_time"] < end_clip
            for br in broll_data
        )
        fast = (
            not has_broll
            and not getattr(cfg, "watermark_enabled", False)
            and video_encoder["name"] != "h264_vaapi"
        )

        rendered = fast and _render_with_ffmpeg(
            input_video, output_video, start_clip, duration, fps, mode, out_dims,
            (crop_w, crop_h), origin_at, bool(smooth), cfg, video_encoder, label,
        )
        if not rendered:
            if fast:
                print(f"   ↩️ {label} - Falling back to frame-by-frame rendering.")
            _render_with_opencv(
                cap, output_video, start_clip, duration, fps, mode, out_dims,
                (crop_w, crop_h), origin_at, broll_data, cfg, video_encoder, label,
            )

        print(f"✅ {label} done.", flush=True)
    finally:
        cap.release()

    def get_x(t):
        return position(t)[0]

    return get_x
