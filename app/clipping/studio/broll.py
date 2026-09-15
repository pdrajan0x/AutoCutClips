import json
import os
import random
import shutil
import urllib.parse
import urllib.request

import cv2
import numpy as np

from .utils import _resize_frame, _is_vertical_ratio


USED_PEXELS_IDS = set()


def download_pexels_broll(query, ratio, output_filename, pexels_api_key):
    """
    Search and download one Pexels B-roll video clip matching the query and aspect ratio.

    Args:
        query (str): Search query term (e.g., 'nature', 'technology').
        ratio (str): Target aspect ratio string (`9:16` for portrait or `16:9` for landscape).
        output_filename (str): Local file path where the downloaded MP4 will be saved.
        pexels_api_key (str): Valid Pexels API key for authorization.

    Returns:
        bool: True if the video was successfully downloaded and saved, False otherwise.

    Side Effects:
        Makes HTTP GET requests to the Pexels API and video CDN.
        Mutates the global `USED_PEXELS_IDS` set to prevent duplicate downloads.
        Writes a temporary file (`.part`) and renames it upon successful download.
        Prints status and error messages to stdout.

    Raises:
        None explicitly. Exceptions during download or API calls are caught and return False.
    """
    global USED_PEXELS_IDS

    if not pexels_api_key:
        print("   ⚠️ PEXELS_API_KEY not found. Skipping B-roll.")
        return False

    orientation = "portrait" if _is_vertical_ratio(ratio) else "landscape"

    params = urllib.parse.urlencode(
        {
            "query": query,
            "orientation": orientation,
            "per_page": 30,
            "size": "large",
            "resolution_name": "1080p",
        }
    )
    search_url = f"https://api.pexels.com/videos/search?{params}"

    req = urllib.request.Request(
        search_url,
        headers={
            "Authorization": pexels_api_key,
            "User-Agent": "Mozilla/5.0",
        },
    )

    try:
        with urllib.request.urlopen(req) as response:
            data = json.load(response)
    except Exception as e:
        print(f"   ⚠️ Pexels API error while searching for '{query}': {e}")
        return False

    if not data.get("videos"):
        print(f"   ⚠️ Pexels found no video for '{query}'.")
        return False

    available_videos = [v for v in data["videos"] if v["id"] not in USED_PEXELS_IDS]
    if not available_videos:
        print(f"   🔄 The B-roll pool for '{query}' is exhausted, resetting it.")
        available_videos = data["videos"]

    # Pexels returns results by relevance; picking at random from all 30 made
    # the footage only loosely related to what the speaker is saying.
    video_data = random.choice(available_videos[:3])
    USED_PEXELS_IDS.add(video_data["id"])

    video_files = [
        vf
        for vf in video_data.get("video_files", [])
        if vf.get("file_type") == "video/mp4"
    ]
    if not video_files:
        print(f"   ⚠️ No MP4 file in the video data for '{query}'.")
        return False

    video_files.sort(
        key=lambda vf: (
            vf.get("quality") != "hd",
            -(vf.get("width") or 0),
            -(vf.get("height") or 0),
        )
    )

    download_url = video_files[0]["link"]
    download_req = urllib.request.Request(
        download_url, headers={"User-Agent": "Mozilla/5.0"}
    )

    try:
        temp_path = output_filename + ".part"
        with (
            urllib.request.urlopen(download_req) as response,
            open(temp_path, "wb") as f,
        ):
            shutil.copyfileobj(response, f)
        os.replace(temp_path, output_filename)
        return True
    except Exception as e:
        print(f"   ⚠️ Error while downloading the B-roll for '{query}': {e}")
        return False


def open_broll_captures(broll_data):
    """Open every downloaded B-roll insert for sequential reading during a render."""
    captures = []
    for br in broll_data or []:
        if "filepath" in br and os.path.exists(br["filepath"]):
            cap = cv2.VideoCapture(br["filepath"])
            captures.append({
                "start": br["start_time"],
                "end": br["end_time"],
                "cap": cap,
                "fps": cap.get(cv2.CAP_PROP_FPS) or 30.0,
                "next_index": 0,
                "frame": None,
            })
    return captures


def read_broll_frame(capture, elapsed):
    """
    The B-roll frame for *elapsed* seconds into the insert.

    Reads forward instead of seeking on every output frame: each seek decoded
    from the previous keyframe, so inserts stuttered and rendered slowly. A clip
    shorter than its slot holds its last frame.
    """
    target_index = int(elapsed * capture["fps"])
    while capture["next_index"] <= target_index:
        ok, frame = capture["cap"].read()
        if not ok:
            capture["next_index"] = target_index + 1
            break
        capture["frame"] = frame
        capture["next_index"] += 1
    return capture["frame"]


def crop_center_broll(img, target_w, target_h):
    """
    Center-crop an image frame to the exact target aspect ratio, then resize it.

    Args:
        img (np.ndarray): Input image frame array (from OpenCV).
        target_w (int): Desired output width in pixels.
        target_h (int): Desired output height in pixels.

    Returns:
        np.ndarray: The cropped and resized frame.

    Side Effects:
        None.

    Raises:
        cv2.error: If the input image format is invalid or resizing fails.
    """
    h, w = img.shape[:2]
    target_ratio = target_w / target_h
    img_ratio = w / h

    if img_ratio > target_ratio:
        new_w = int(h * target_ratio)
        x = (w - new_w) // 2
        img = img[:, x : x + new_w]
    elif img_ratio < target_ratio:
        new_h = int(w / target_ratio)
        y = (h - new_h) // 2
        img = img[y : y + new_h, :]

    return _resize_frame(img, (target_w, target_h))


