"""
clipping.story.assembler — Scene trim, normalise, concat & render for Story Clip.

Every scene is trimmed out of its cached source, re-encoded to one common
format, then concatenated (hard cut or crossfade) into a hook or highlight file.
"""

import os
import shutil
import subprocess

TARGET_FPS = 30

RATIO_DIMS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "3:4": (1080, 1440),
    "4:5": (1080, 1350),
}

# Recipe transition names -> the concat strategies implemented here.
TRANSITION_ALIASES = {
    "smooth": "crossfade",
    "crossfade": "crossfade",
    "jedag_jedug": "cut",  # TODO: implement the beat-synced "jedag jedug" transition
    "cut": "cut",
}


# ==============================================================================
# FFMPEG / FFPROBE HELPERS
# ==============================================================================

def _run_ffmpeg(cmd: list[str], label: str = "") -> None:
    """Run an FFmpeg command, raising RuntimeError with its stderr on failure."""
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except subprocess.CalledProcessError as e:
        stderr_text = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        suffix = f" ({label})" if label else ""
        raise RuntimeError(f"FFmpeg failed{suffix}: {stderr_text[:500]}") from e


def _probe(path: str, stream_args: list[str]) -> str:
    """Run ffprobe and return its single-line stdout (empty string on failure)."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", *stream_args, "-of",
             "default=noprint_wrappers=1:nokey=1", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        return result.stdout.decode("utf-8", errors="replace").strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""


def probe_duration(path: str) -> float:
    """Return a media file's duration in seconds (0.0 when it cannot be read)."""
    raw = _probe(path, ["-show_entries", "format=duration"]).splitlines()
    try:
        return float(raw[0]) if raw else 0.0
    except ValueError:
        return 0.0


def has_audio_stream(path: str) -> bool:
    """Return True when the file carries at least one audio stream."""
    return bool(_probe(path, ["-select_streams", "a", "-show_entries", "stream=index"]))


# ==============================================================================
# TRIM & NORMALISE
# ==============================================================================

def trim_scene(
    video_path: str,
    start: float,
    end: float,
    output_path: str,
    reencode: bool = False,
) -> str:
    """
    Trim ``[start, end]`` out of *video_path* with FFmpeg.

    With ``reencode=True`` the cut is frame-accurate; otherwise stream copy is
    used, which is faster but only accurate to GOP boundaries.
    """
    duration = end - start
    codec_args = (
        ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac", "-b:a", "192k"]
        if reencode
        else ["-c", "copy"]
    )

    _run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}",
            "-i", video_path,
            "-t", f"{duration:.3f}",
            *codec_args,
            "-avoid_negative_ts", "make_zero",
            output_path,
        ],
        label=f"trim {start:.1f}-{end:.1f}",
    )
    return output_path


def _normalize_scene_segment(
    input_path: str,
    output_path: str,
    target_width: int = 1080,
    target_height: int = 1920,
    target_fps: int = TARGET_FPS,
) -> str:
    """
    Re-encode a trimmed scene to one consistent format so every segment can be
    concatenated safely (same resolution, frame rate, pixel format and codecs).

    Scenes are scaled to fit and padded (letterbox/pillarbox) rather than
    stretched. A silent stereo track is synthesised when the source has no
    audio, because the concat demuxer corrupts output if the segments disagree
    on stream layout.
    """
    vf = (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={target_fps},"
        f"format=yuv420p"
    )

    needs_silent_audio = not has_audio_stream(input_path)

    cmd = ["ffmpeg", "-y", "-i", input_path]
    if needs_silent_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest"]

    cmd += [
        "-map", "0:v:0",
        "-map", "1:a:0" if needs_silent_audio else "0:a:0",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        output_path,
    ]

    _run_ffmpeg(cmd, label="normalize")
    return output_path


# ==============================================================================
# CONCAT
# ==============================================================================

def concat_scenes(
    scene_paths: list[str],
    output_path: str,
    transition: str = "cut",
) -> str:
    """
    Concatenate normalised scene segments into a single video.

    ``transition`` is ``"cut"`` (hard cut, stream copy) or ``"crossfade"``
    (0.5s dissolve). All inputs must already share format and resolution.
    """
    if not scene_paths:
        raise ValueError("No scenes to concatenate.")

    if len(scene_paths) == 1:
        shutil.copy2(scene_paths[0], output_path)
        return output_path

    if transition == "crossfade":
        return _concat_with_crossfade(scene_paths, output_path)
    return _concat_hard_cut(scene_paths, output_path)


def _concat_hard_cut(scene_paths: list[str], output_path: str) -> str:
    """Concatenate with the FFmpeg concat demuxer (lossless for same-format files)."""
    list_path = output_path + ".concat_list.txt"
    try:
        with open(list_path, "w", encoding="utf-8") as f:
            for p in scene_paths:
                # The concat demuxer wants forward slashes and quoted paths.
                f.write(f"file '{os.path.abspath(p).replace(os.sep, '/')}'\n")

        _run_ffmpeg(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-c", "copy", output_path],
            label="concat_hard_cut",
        )
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)

    return output_path


def _xfade_pair(
    first: str, second: str, output_path: str, fade_duration: float, label: str
) -> str:
    """
    Crossfade exactly two clips.

    The xfade offset must be ``duration(first) - fade_duration`` so the dissolve
    lands at the end of the first clip; an offset of 0 would overlay the clips
    from the very start and throw most of the first clip away.
    """
    first_duration = probe_duration(first)
    offset = max(0.0, first_duration - fade_duration)
    # A clip shorter than the fade cannot cross-fade for the full duration.
    fade = min(fade_duration, first_duration) if first_duration else fade_duration

    _run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-i", first,
            "-i", second,
            "-filter_complex",
            f"[0:v][1:v]xfade=transition=fade:duration={fade}:offset={offset:.3f}[v];"
            f"[0:a][1:a]acrossfade=d={fade}[a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac",
            output_path,
        ],
        label=label,
    )
    return output_path


def _concat_with_crossfade(
    scene_paths: list[str],
    output_path: str,
    fade_duration: float = 0.5,
) -> str:
    """
    Crossfade a list of already-normalised clips.

    Three or more clips are folded pairwise through intermediate files, because
    chaining xfade in one filtergraph gets unwieldy fast.
    """
    if len(scene_paths) == 2:
        return _xfade_pair(scene_paths[0], scene_paths[1], output_path, fade_duration, "crossfade")

    temp_dir = output_path + "_xfade_tmp"
    os.makedirs(temp_dir, exist_ok=True)
    try:
        current = scene_paths[0]
        for i in range(1, len(scene_paths)):
            temp_out = os.path.join(temp_dir, f"xfade_{i}.mp4")
            current = _xfade_pair(
                current, scene_paths[i], temp_out, fade_duration, f"crossfade_{i}"
            )
        shutil.copy2(current, output_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return output_path


# ==============================================================================
# ASSEMBLY
# ==============================================================================

def _get_target_dims(ratio: str) -> tuple[int, int]:
    """Return (width, height) for an aspect-ratio string."""
    return RATIO_DIMS.get(ratio, RATIO_DIMS["9:16"])


def _resolve_scene_video(scene: dict, source_registry: dict, cache_dir: str) -> str:
    """Return the local file path backing a scene's source."""
    src = source_registry[scene["source_id"]]
    if src["platform"] == "local":
        return src["local_path"]
    return os.path.join(cache_dir, f"{scene['source_id']}.mp4")


def _assemble_segment(
    clip_config: dict,
    section: str,
    source_registry: dict[str, dict],
    cache_dir: str,
    output_dir: str,
    ratio: str,
    file_prefix: str,
    scene_prefix: str,
    transition: str,
    icon: str,
) -> str | None:
    """
    Trim, normalise and concatenate every scene of one recipe section.

    Shared by :func:`assemble_hook` and :func:`assemble_highlight` — the two
    differ only in the section read, the filenames written and the transition.

    Returns the rendered path, or None when no scene could be used.
    """
    cid = clip_config["clip_id"]
    scenes = clip_config[section].get("scenes", [])

    print(f"\n   {icon} Assembling {file_prefix}_{cid}...")

    target_w, target_h = _get_target_dims(ratio)
    temp_dir = os.path.join(output_dir, f"_temp_{section}_{cid}")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        normalized_parts: list[str] = []

        for idx, scene in enumerate(scenes):
            sid = scene["source_id"]
            start, end = scene.get("start"), scene.get("end")
            label = scene.get("label", "")

            if start is None or end is None:
                print(f"      ⏩ Scene #{idx} ({sid}): null timestamp, skipped. [{label}]")
                continue

            video_path = _resolve_scene_video(scene, source_registry, cache_dir)
            if not os.path.exists(video_path):
                print(f"      ⚠️ Scene #{idx} ({sid}): file not found, skipped.")
                continue

            trimmed = os.path.join(temp_dir, f"{scene_prefix}_{cid}_scene_{idx}_trim.mp4")
            trim_scene(video_path, start, end, trimmed, reencode=True)

            normed = os.path.join(temp_dir, f"{scene_prefix}_{cid}_scene_{idx}_norm.mp4")
            _normalize_scene_segment(trimmed, normed, target_w, target_h)
            normalized_parts.append(normed)

            print(
                f"      ✅ Scene #{idx}: {sid} [{start:.1f}s - {end:.1f}s] "
                f"({end - start:.1f}s) — {label}"
            )

        if not normalized_parts:
            print(f"      ❌ {file_prefix} #{cid}: no valid scenes.")
            return None

        output_path = os.path.join(output_dir, f"{file_prefix}_{cid}.mp4")
        concat_scenes(normalized_parts, output_path, transition=transition)

        print(
            f"      ✅ {file_prefix}_{cid}.mp4 rendered "
            f"({len(normalized_parts)} scene(s), transition: {transition})."
        )
        return output_path
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def assemble_hook(
    clip_config: dict,
    source_registry: dict[str, dict],
    cache_dir: str,
    output_dir: str,
    ratio: str = "9:16",
) -> str | None:
    """Assemble a clip's hook segment — always clean video, hard cuts only."""
    return _assemble_segment(
        clip_config, "hook", source_registry, cache_dir, output_dir, ratio,
        file_prefix="hook", scene_prefix="hook", transition="cut", icon="🎣",
    )


def assemble_highlight(
    clip_config: dict,
    source_registry: dict[str, dict],
    cache_dir: str,
    output_dir: str,
    ratio: str = "9:16",
) -> str | None:
    """Assemble a clip's highlight segment, honouring the recipe's transition."""
    requested = clip_config["highlight"].get("transition", "cut")
    return _assemble_segment(
        clip_config, "highlight", source_registry, cache_dir, output_dir, ratio,
        file_prefix="highlight", scene_prefix="hl",
        transition=TRANSITION_ALIASES.get(requested, "cut"), icon="🎬",
    )
