import os
import textwrap
import urllib.request

import cv2
from PIL import Image, ImageDraw, ImageFont


def build_thumbnail(video_path, output_image_path, text, cfg):
    """
    Extract a frame from the video, composite the clip title on top, and save as a thumbnail image.

    Args:
        input_video (str): Path to the source video file.
        output_image (str): Destination path for the generated JPEG thumbnail.
        start_clip (float): Clip start time in seconds (to locate a frame).
        end_clip (float): Clip end time in seconds.
        title_id (str): The title text to be written on the thumbnail.
        ratio (str): Target output ratio string ('9:16' or '16:9').
        cfg: Runtime configuration object.

    Returns:
        str: The path to the created image, or None if creation fails.

    Side Effects:
        Uses `cv2.VideoCapture` to extract a frame from `input_video`.
        Writes a JPEG file to `output_image`.

    Raises:
        Exception: If image processing or saving fails.
    """
    if not os.path.exists(cfg.file_font_thumbnail):
        urllib.request.urlretrieve(cfg.url_font_thumbnail, cfg.file_font_thumbnail)

    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, 5000)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        return

    img = Image.alpha_composite(
        Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA"),
        Image.new("RGBA", (frame.shape[1], frame.shape[0]), (0, 0, 0, 128)),
    ).convert("RGB")

    draw = ImageDraw.Draw(img)
    font_sz = int(img.size[0] * 0.12)
    font = ImageFont.truetype(cfg.file_font_thumbnail, font_sz)
    lines = textwrap.wrap(text, width=12)

    y_text = (img.size[1] - (len(lines) * (font_sz + 10))) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x_text = (img.size[0] - line_w) // 2
        draw.text(
            (x_text, y_text),
            line,
            font=font,
            fill="white",
            stroke_width=5,
            stroke_fill="black",
        )
        y_text += font_sz + 10

    img.save(output_image_path)


