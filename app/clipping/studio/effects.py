import os
import subprocess

from yt_dlp import YoutubeDL

from .utils import RATIO_MAP, _is_vertical_ratio, _get_render_dims
from .ffmpeg_utils import get_ts_encode_args


def prepare_glitch_video(ratio, cfg, video_encoder, source_h=1080, custom_dims=None):
    """
    Generate a 1-second VHS glitch transition video.

    Primary: download glitch video from cfg.url_glitch_video via yt_dlp.
    Fallback: generate RGB-shift noise via FFmpeg lavfi filters if download fails.

    Args:
        ratio (str): Target output ratio string ('9:16', '16:9', etc.).
        cfg: Runtime config (used for render_output_height, video_scale_algo,
             and url_glitch_video).
        video_encoder: Encoder descriptor dict from detect_video_encoder().
        source_h (int): Source video height for dimension calculation.
        custom_dims (tuple|None): Optional (width, height) override.

    Returns:
        str: Path to the generated .ts glitch transition file, or None on failure.
    """
    if custom_dims:
        out_w, out_h = custom_dims
    else:
        out_w, out_h = _get_render_dims(cfg, ratio, source_h=source_h)

    # Use dimensions in filename to allow multiple cached versions
    glitch_ts = f"glitch_ready_{out_w}x{out_h}.ts"
    if os.path.exists(glitch_ts):
        return glitch_ts

    # --- Primary: download glitch video from YouTube ---
    glitch_raw = "glitch_raw.mp4"
    use_downloaded = False
    if not os.path.exists(glitch_raw):
        try:
            url_glitch = getattr(cfg, "url_glitch_video", None)
            if url_glitch:
                print("⬇️ Downloading glitch video...", flush=True)
                YoutubeDL(
                    {
                        "format": "best[ext=mp4]",
                        "outtmpl": glitch_raw,
                        "quiet": True,
                        "extractor_args": {"youtube": ["player_client=android,web"]},
                    }
                ).download([url_glitch])
                use_downloaded = True
            else:
                print("⚠️ url_glitch_video is not set; generating the glitch locally...", flush=True)
        except Exception as e:
            print(f"⚠️ Glitch download failed: {e}. Generating it locally instead...", flush=True)
            # Clean up partial download
            if os.path.exists(glitch_raw):
                os.remove(glitch_raw)
    else:
        use_downloaded = True

    if use_downloaded and os.path.exists(glitch_raw):
        # Build filter from downloaded video
        algo = getattr(cfg, "video_scale_algo", "lanczos")
        if custom_dims:
            filter_g = f"scale={out_w}:{out_h}:flags={algo},setsar=1"
        else:
            if _is_vertical_ratio(ratio):
                w_part, h_part = RATIO_MAP.get(ratio, (9, 16))
                filter_g = (
                    f"crop=ih*{w_part}/{h_part}:ih:(iw-ih*{w_part}/{h_part})/2:0,"
                    f"scale={out_w}:{out_h}:flags={algo},setsar=1"
                )
            else:
                filter_g = f"scale={out_w}:{out_h}:flags={algo},setsar=1"

        cmd = (
            [
                "ffmpeg", "-y",
                "-ss", "0.2",
                "-t", "1",
                "-i", glitch_raw,
                "-vf", filter_g,
            ]
            + get_ts_encode_args(video_encoder, fps=30)
            + [glitch_ts]
        )
    else:
        # --- Fallback: generate VHS glitch noise via FFmpeg lavfi ---
        print("🎬 Generating glitch via FFmpeg lavfi...", flush=True)
        duration = 1.0
        cmd = (
            [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"color=c=black:s={out_w}x{out_h}:d={duration}:r=30",
                "-f", "lavfi",
                "-i", "anullsrc=r=48000:cl=stereo",
                "-t", str(duration),
                "-vf", "noise=alls=100:allf=t+u,rgbashift=rh=20:bv=20",
            ]
            + get_ts_encode_args(video_encoder, fps=30)
            + [glitch_ts]
        )

    subprocess.run(
        cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return glitch_ts


