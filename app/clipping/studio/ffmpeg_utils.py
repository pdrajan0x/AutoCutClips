"""
FFmpeg and encoder utilities for Studio rendering pipeline.
"""

import functools
import subprocess

from ..progress import ProgressBar


def format_seconds(seconds):
    """
    Format a duration in seconds into HH:MM:SS.

    Args:
        seconds: Numeric duration in seconds.

    Returns:
        Duration string in `HH:MM:SS` format, clamped to non-negative.
    """
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


@functools.lru_cache(maxsize=None)
def _ffmpeg_has_encoder(name: str) -> bool:
    """
    Check whether a specific FFmpeg encoder is available (cached per process).

    Args:
        name: Encoder name, for example `h264_nvenc`.

    Returns:
        True if encoder exists in local FFmpeg build.
    """
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return name in result.stdout


_RUNTIME_TEST_CACHE: dict[tuple, tuple[bool, str]] = {}
_ANNOUNCED: set[str] = set()


def _test_encoder_runtime(encoder_args):
    """
    Validate encoder arguments by running a short synthetic FFmpeg encode.

    Every renderer asks for the encoder once per clip part, so the result is
    cached: the test encode used to rerun for every hook, segment and clip.

    Args:
        encoder_args: FFmpeg encoder argument list to test.

    Returns:
        Tuple `(ok, stderr_tail)` where `ok` is True on success.
    """
    key = tuple(encoder_args)
    if key in _RUNTIME_TEST_CACHE:
        return _RUNTIME_TEST_CACHE[key]

    cmd = (
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=640x360:r=30:d=1",
        ]
        + encoder_args
        + ["-pix_fmt", "yuv420p", "-an", "-f", "null", "-"]
    )
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    _RUNTIME_TEST_CACHE[key] = (result.returncode == 0, result.stderr[-1000:])
    return _RUNTIME_TEST_CACHE[key]


def _announce(message: str) -> None:
    """Print an encoder choice once per process instead of once per clip part."""
    if message not in _ANNOUNCED:
        _ANNOUNCED.add(message)
        print(message, flush=True)


def _get_auto_bitrate(height: int) -> str:
    """Determine a safe target bitrate based on output height."""
    if height >= 2160: return "20M"
    if height >= 1440: return "12M"
    if height >= 1080: return "8M"
    return "4M"


def detect_video_encoder(cfg=None, target_h=1080):
    """
    Select the best available video encoder with conservative fallback.
    Now supports dynamic bitrate scaling for TikTok optimization.
    """
    # p1 is NVENC's lowest-quality preset; p4 is visibly cleaner on faces and
    # captions at the same bitrate, and still far faster than realtime on a T4.
    nvenc_preset_fast = "p4"
    nvenc_preset_legacy = "medium"
    nvenc_cq = 25
    cpu_preset = "veryfast"
    cpu_crf = 25

    target_bitrate = "auto"

    if cfg is not None:
        nvenc_cq = int(getattr(cfg, "video_quality_cq", nvenc_cq))
        cpu_crf = int(getattr(cfg, "video_quality_crf", cpu_crf))
        target_bitrate = str(getattr(cfg, "video_bitrate", "auto")).lower()
        preset_override = str(getattr(cfg, "video_preset", "auto")).lower()
        if preset_override != "auto":
            nvenc_preset_fast = preset_override
            nvenc_preset_legacy = preset_override
            cpu_preset = preset_override

    if target_bitrate == "auto":
        target_bitrate = _get_auto_bitrate(target_h)

    # Normalise once: target_bitrate was lowercased above, so a user-supplied
    # "8M" would otherwise reach float("8m") and raise.
    bitrate_mbps = float(str(target_bitrate).lower().rstrip("m").strip() or 0)
    target_bitrate = f"{bitrate_mbps:g}M"
    maxrate = f"{int(bitrate_mbps * 1.5)}M"
    bufsize = f"{int(bitrate_mbps * 2)}M"

    nvenc_args_fastest = [
        "-c:v", "h264_nvenc",
        "-preset", nvenc_preset_fast,
        "-rc", "vbr",
        "-cq", str(nvenc_cq),
        "-b:v", target_bitrate,
        "-maxrate", maxrate,
        "-bufsize", bufsize,
    ]
    nvenc_args_legacy = [
        "-c:v", "h264_nvenc",
        "-preset", nvenc_preset_legacy,
        "-rc", "vbr",
        "-cq", str(nvenc_cq),
        "-b:v", target_bitrate,
        "-maxrate", maxrate,
        "-bufsize", bufsize,
    ]
    amf_args = [
        "-c:v", "h264_amf",
        "-b:v", target_bitrate,
        "-maxrate", maxrate,
        "-bufsize", bufsize,
    ]
    vaapi_args = [
        "-init_hw_device", "vaapi=va:/dev/dri/renderD128",
        "-filter_hw_device", "va",
        "-vf", "format=nv12,hwupload",
        "-c:v", "h264_vaapi",
        "-b:v", target_bitrate,
        "-maxrate", maxrate,
        "-bufsize", bufsize,
    ]
    cpu_args = [
        "-c:v", "libx264",
        "-preset", cpu_preset,
        "-crf", str(cpu_crf),
        "-maxrate", target_bitrate,
        "-bufsize", bufsize,
    ]

    # ponytail: NVENC -> AMD AMF -> AMD VAAPI -> CPU
    if _ffmpeg_has_encoder("h264_nvenc"):
        ok, _ = _test_encoder_runtime(nvenc_args_fastest)
        if ok:
            _announce(f"🚀 Using NVIDIA NVENC {nvenc_preset_fast} (Bitrate {target_bitrate}, CQ {nvenc_cq})")
            return {"name": "h264_nvenc", "args": nvenc_args_fastest}

        ok, _ = _test_encoder_runtime(nvenc_args_legacy)
        if ok:
            _announce(f"🚀 Using NVIDIA NVENC {nvenc_preset_legacy} (Bitrate {target_bitrate}, CQ {nvenc_cq})")
            return {"name": "h264_nvenc", "args": nvenc_args_legacy}

    if _ffmpeg_has_encoder("h264_amf"):
        ok, _ = _test_encoder_runtime(amf_args)
        if ok:
            _announce(f"🚀 Using AMD AMF (Bitrate {target_bitrate})")
            return {"name": "h264_amf", "args": amf_args}

    if _ffmpeg_has_encoder("h264_vaapi"):
        ok, _ = _test_encoder_runtime(vaapi_args)
        if ok:
            _announce(f"🚀 Using AMD VAAPI (Bitrate {target_bitrate})")
            return {"name": "h264_vaapi", "args": vaapi_args}

    _announce(f"⚠️ Falling back to CPU libx264 ({cpu_preset}, CRF {cpu_crf}, Max {target_bitrate})")
    return {"name": "libx264", "args": cpu_args}


def get_ts_encode_args(video_encoder, fps=30):
    """
    Build FFmpeg encode args for MPEG-TS output.

    Args:
        video_encoder: Encoder descriptor from `detect_video_encoder`.
        fps: Target frame rate.

    Returns:
        FFmpeg argument list for TS output.
    """
    return video_encoder["args"] + [
        "-pix_fmt",
        "yuv420p",
        "-r",
        f"{fps:g}",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-f",
        "mpegts",
    ]


def get_mp4_encode_args(video_encoder, fps):
    """
    Build FFmpeg encode args for MP4 output.

    Args:
        video_encoder: Encoder descriptor from `detect_video_encoder`.
        fps: Target frame rate.

    Returns:
        FFmpeg argument list for MP4 output.
    """
    return video_encoder["args"] + [
        "-pix_fmt",
        "yuv420p",
        "-r",
        f"{fps:.06f}",
        "-movflags",
        "+faststart",
    ]


INTERMEDIATE_QUALITY = 16


def _intermediate_encoder(video_encoder, quality=INTERMEDIATE_QUALITY):
    """
    Derive fast, near-transparent encoder settings for an intermediate file.

    Every clip is encoded twice — the framed video here, then again when the
    subtitles are burned in — so this first generation uses a low CQ/CRF (no
    compounded artefacts) with the encoder's fastest preset and no rate caps.
    Encoders without a quality knob (AMF, VAAPI) keep their settings.
    """
    args = list(video_encoder["args"])
    if "-cq" not in args and "-crf" not in args:
        return video_encoder

    out = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-b:v", "-maxrate", "-bufsize") and i + 1 < len(args):
            i += 2
            continue
        if arg in ("-cq", "-crf") and i + 1 < len(args):
            out += [arg, str(quality)]
            i += 2
            continue
        out.append(arg)
        i += 1

    if "-preset" in out:
        preset_idx = out.index("-preset") + 1
        if video_encoder["name"] == "libx264":
            out[preset_idx] = "ultrafast"
        elif video_encoder["name"] == "h264_nvenc" and out[preset_idx].startswith("p"):
            out[preset_idx] = "p1"

    if video_encoder["name"] == "h264_nvenc":
        out += ["-b:v", "0"]  # pure constant-quality VBR
    return {"name": video_encoder["name"], "args": out}


def open_ffmpeg_video_writer(output_path, width, height, fps, video_encoder):
    """
    Start an FFmpeg process that accepts raw BGR frames via stdin.

    The output is an intermediate file that is re-encoded later, so it is
    written with ``_intermediate_encoder`` settings.

    Args:
        output_path: Target MP4 path.
        width: Video width in pixels.
        height: Video height in pixels.
        fps: Output frame rate.
        video_encoder: Encoder descriptor from `detect_video_encoder`.

    Returns:
        Running `subprocess.Popen` object.
    """
    video_encoder = _intermediate_encoder(video_encoder)
    cmd = (
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{width}x{height}",
            "-r",
            f"{fps:.06f}",
            "-i",
            "-",
        ]
        + get_mp4_encode_args(video_encoder, fps)
        + [
            "-an",
            output_path,
        ]
    )

    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def build_ffmpeg_progress_cmd(base_cmd, output_path):
    """
    Extend an FFmpeg command so progress can be parsed from stderr.

    Args:
        base_cmd: Base FFmpeg argument list.
        output_path: Output media path.

    Returns:
        FFmpeg command with `-progress pipe:2 -nostats`.
    """
    return base_cmd + ["-progress", "pipe:2", "-nostats", output_path]


def run_ffmpeg_with_progress(ffmpeg_cmd, total_duration, label="Render"):
    """
    Execute FFmpeg command while printing progress updates.

    Args:
        ffmpeg_cmd: Full FFmpeg command list.
        total_duration: Expected output duration in seconds.
        label: Human-readable label for logs.

    Returns:
        Tuple `(return_code, recent_errors)` where `recent_errors` contains
        the latest non-progress stderr lines.
    """
    print(f"🚀 {label} started...", flush=True)

    process = subprocess.Popen(
        ffmpeg_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    progress = ProgressBar(total_duration, label)
    error_lines = []

    for raw_line in process.stderr:
        line = raw_line.strip()

        if "fontselect" in line.lower() or "using font provider" in line.lower():
            print("🔎", line, flush=True)

        if line and "=" not in line:
            error_lines.append(line)
            if len(error_lines) > 50:
                error_lines = error_lines[-50:]

        if line.startswith("out_time_ms="):
            try:
                progress.update(int(line.split("=", 1)[1]) / 1_000_000)
            except ValueError:
                pass

    return_code = process.wait()
    # Only snap the bar to 100% if ffmpeg actually finished the encode.
    progress.close(complete=return_code == 0)
    return return_code, error_lines[-20:]
