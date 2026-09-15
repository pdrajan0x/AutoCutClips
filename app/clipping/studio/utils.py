"""
Shared helpers for the Studio rendering pipeline: duration formatting,
FFmpeg value escaping, OpenCV scaling and aspect-ratio maths.
"""

import math
import os

import cv2

FIREFOX_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0"
)

# Maps a ratio string to (width_part, height_part).
RATIO_MAP = {
    "9:16": (9, 16),
    "16:9": (16, 9),
    "1:1": (1, 1),
    "3:4": (3, 4),
    "4:5": (4, 5),
}

# Ratios that require a face-tracking crop (narrower than the source).
VERTICAL_RATIOS = {"9:16", "1:1", "3:4", "4:5"}


def format_seconds(seconds):
    """Format a duration in seconds as ``HH:MM:SS`` (clamped to non-negative)."""
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def escape_ffmpeg_filter_value(value: str) -> str:
    """Escape a value so it is safe inside an FFmpeg filter expression."""
    return str(value).replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")


def ffmpeg_filter_path(path: str) -> str:
    """
    Quote a file path for use as a filter option (``subtitles=...``, ``fontsdir=...``).

    A filtergraph is unescaped twice, so a singly escaped path broke on any
    drive letter (``C:\\...``) and on commas or brackets. Forward slashes inside
    single quotes, with the colon escaped, survive both levels on every OS.
    """
    text = os.path.abspath(str(path)).replace("\\", "/").replace(":", r"\:")
    return "'" + text.replace("'", r"'\''") + "'"


def _get_cv2_interpolation(cfg=None):
    """Resolve the OpenCV interpolation mode from the runtime config."""
    algo = str(
        getattr(cfg, "video_scale_algo", os.environ.get("OSC_VIDEO_SCALE_ALGO", "lanczos"))
    ).lower()
    return {
        "lanczos": cv2.INTER_LANCZOS4,
        "bicubic": cv2.INTER_CUBIC,
        "bilinear": cv2.INTER_LINEAR,
        "area": cv2.INTER_AREA,
    }.get(algo, cv2.INTER_LANCZOS4)


def _resize_frame(frame, size, cfg=None):
    """Resize a frame to ``size`` using the configured interpolation algorithm."""
    return cv2.resize(frame, size, interpolation=_get_cv2_interpolation(cfg))


def _is_vertical_ratio(ratio: str) -> bool:
    """Return True when the ratio needs a face-tracked crop from the source."""
    return ratio in VERTICAL_RATIOS


def _get_render_dims(cfg, ratio, source_h=1080):
    """
    Calculate the target output resolution for a ratio.

    ``cfg.render_output_height`` may be ``"source"`` (use *source_h*) or a
    pixel height. For vertical ratios the value is treated as the short side.
    Dimensions are rounded up to even numbers for codec compatibility.
    """
    mode = str(getattr(cfg, "render_output_height", "1080")).lower()
    if mode == "source":
        target_h_base = source_h
    else:
        try:
            target_h_base = int(mode)
        except (ValueError, TypeError):
            target_h_base = 1080

    w_part, h_part = RATIO_MAP.get(ratio, (16, 9))

    if _is_vertical_ratio(ratio):
        out_w = target_h_base
        out_h = int(target_h_base * h_part / w_part)
    else:
        out_h = target_h_base
        out_w = int(target_h_base * w_part / h_part)

    if out_w % 2:
        out_w += 1
    if out_h % 2:
        out_h += 1

    return out_w, out_h


def make_blur_fill(frame, out_w, out_h, cfg=None):
    """
    Fit the whole frame inside ``out_w`` x ``out_h`` over a blurred, darkened copy of itself.

    Used for footage a face crop would ruin (slides, screen recordings, gameplay)
    and for mismatched landscape output, instead of black bars.
    """
    h, w = frame.shape[:2]

    cover = max(out_w / w, out_h / h)
    bg_w, bg_h = max(out_w, math.ceil(w * cover)), max(out_h, math.ceil(h * cover))
    background = cv2.resize(frame, (bg_w, bg_h), interpolation=cv2.INTER_AREA)
    x0, y0 = (bg_w - out_w) // 2, (bg_h - out_h) // 2
    background = background[y0:y0 + out_h, x0:x0 + out_w]
    # Blurring a small copy is far cheaper than a huge kernel at full size.
    small = cv2.resize(background, (max(1, out_w // 8), max(1, out_h // 8)), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 4)
    background = cv2.resize(small, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
    background = cv2.convertScaleAbs(background, alpha=0.6, beta=0)

    fit = min(out_w / w, out_h / h)
    fg_w, fg_h = max(2, int(w * fit) // 2 * 2), max(2, int(h * fit) // 2 * 2)
    foreground = _resize_frame(frame, (fg_w, fg_h), cfg)
    x, y = (out_w - fg_w) // 2, (out_h - fg_h) // 2
    background[y:y + fg_h, x:x + fg_w] = foreground
    return background


def blur_fill_filter(out_w, out_h, algo="lanczos"):
    """The FFmpeg filter chain equivalent of ``make_blur_fill`` (prefix with an input label)."""
    small_w, small_h = max(2, out_w // 8 // 2 * 2), max(2, out_h // 8 // 2 * 2)
    return (
        "split=2[bf_bg][bf_fg];"
        f"[bf_bg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},"
        f"scale={small_w}:{small_h},gblur=sigma=4,scale={out_w}:{out_h},eq=brightness=-0.15[bf_back];"
        f"[bf_fg]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags={algo}[bf_front];"
        "[bf_back][bf_front]overlay=(W-w)/2:(H-h)/2"
    )


def _path_keyframes(values, step, cut_px):
    """
    Reduce a sampled path to keyframes ``(t, value, is_cut)``.

    A sample is kept only where the path bends, so still shots and steady pans
    collapse to a handful of points; a jump larger than ``cut_px`` between two
    samples is marked as a cut and rendered as a step, not a fast pan.
    """
    keys = [(0.0, values[0], False)]
    for i in range(1, len(values)):
        prev_t, prev_v, _ = keys[-1]
        jump = abs(values[i] - values[i - 1]) > cut_px
        if jump:
            if keys[-1][0] != (i - 1) * step:
                keys.append(((i - 1) * step, values[i - 1], False))
            keys[-1] = (keys[-1][0], keys[-1][1], True)
            keys.append((i * step, values[i], False))
            continue
        if i == len(values) - 1:
            keys.append((i * step, values[i], False))
            continue
        # Keep the sample if the straight line from the last keyframe to the
        # next sample misses it by more than a pixel.
        span = (i + 1) * step - prev_t
        predicted = prev_v + (values[i + 1] - prev_v) * ((i * step - prev_t) / span)
        if abs(values[i + 1] - values[i]) > cut_px or abs(predicted - values[i]) > 1.0:
            keys.append((i * step, values[i], False))
    return keys


def _piecewise_expression(keys):
    """A balanced FFmpeg expression tree over ``t`` for the keyframes (depth ~log2 n)."""
    if len(keys) == 1:
        return f"{keys[0][1]:g}"

    def segment(i):
        t0, v0, is_cut = keys[i]
        t1, v1, _ = keys[i + 1]
        if is_cut or v0 == v1:
            return f"{v0:g}"
        return f"{v0:g}+({v1 - v0:g})*(t-{t0:.3f})/{t1 - t0:.3f}"

    def build(lo, hi):
        if hi - lo == 1:
            return segment(lo)
        mid = (lo + hi) // 2
        return f"if(lt(t,{keys[mid][0]:.3f}),{build(lo, mid)},{build(mid, hi)})"

    return build(0, len(keys) - 1)


def build_crop_expressions(origin_at, duration, step=0.1, cut_px=40):
    """
    FFmpeg ``crop`` x/y expressions that follow the camera path over clip time ``t``.

    ``origin_at(t)`` returns the crop's top-left ``(x, y)``. Expressions work on
    every FFmpeg version, unlike ``sendcmd`` crop commands, which older builds
    (e.g. Ubuntu 22.04's 4.4 on Colab) ignore — rendering a camera that never moves.
    """
    samples = [origin_at(i * step) for i in range(int(math.ceil(duration / step)) + 1)]
    xs = [float(x) for x, _ in samples]
    ys = [float(y) for _, y in samples]
    return (
        _piecewise_expression(_path_keyframes(xs, step, cut_px)),
        _piecewise_expression(_path_keyframes(ys, step, cut_px)),
    )
