import os
import urllib.request

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision


_FACE_DETECTOR = None

def get_face_detector(cfg):
    """
    Create or reuse a singleton MediaPipe face detector instance.

    Args:
        cfg: Runtime config that includes model path and model URL.

    Returns:
        mp_vision.FaceDetector: Initialized MediaPipe face detector singleton.

    Side Effects:
        Downloads the Mediapipe face detection model from the internet if it doesn't exist locally.
        Initializes a global `_FACE_DETECTOR` variable.

    Raises:
        urllib.error.URLError: If the model download fails.
        Exception: If Mediapipe initialization fails due to invalid model format.
    """
    global _FACE_DETECTOR

    if _FACE_DETECTOR is None:
        if not os.path.exists(cfg.file_mediapipe_model):
            urllib.request.urlretrieve(
                cfg.url_mediapipe_model, cfg.file_mediapipe_model
            )

        base_options = mp_python.BaseOptions(model_asset_path=cfg.file_mediapipe_model)
        _FACE_DETECTOR = mp_vision.FaceDetector.create_from_options(
            mp_vision.FaceDetectorOptions(
                base_options=base_options,
                min_detection_confidence=0.5,
            )
        )

    return _FACE_DETECTOR


def estimate_speaker_count_from_video(video_path: str, cfg) -> int:
    """
    Sample frames from the video to estimate the max number of visible faces.
    Used for automatically setting min_speakers for pyannote.

    Args:
        video_path (str): The absolute path to the video file.
        cfg: Runtime configuration that may specify 'face_detector' (e.g. 'yolo' or 'mediapipe').

    Returns:
        int: The estimated maximum number of speakers (faces) present in any sampled frame. Defaults to 2 if unsure.

    Side Effects:
        Downloads YOLO face detection model if it's set in config and doesn't exist.
        Prints scanning progress logs to stdout.

    Raises:
        Exception: General exceptions may occur during YOLO initialization, falling back to Mediapipe.
    """
    import cv2

    print("🔍 Auto-detecting speaker count via visual scanning...", flush=True)

    yolo_model = None
    detector = None

    if cfg.face_detector == "yolo":
        from ultralytics import YOLO
        import logging

        logging.getLogger("ultralytics").setLevel(logging.ERROR)
        try:
            # Same weights the renderers use. The old "yolov8m-face.pt" name
            # does not exist, so this always failed and — because it mutated
            # cfg — silently switched the whole run to MediaPipe.
            if not os.path.exists(cfg.file_yolo_model):
                urllib.request.urlretrieve(cfg.url_yolo_model, cfg.file_yolo_model)
            yolo_model = YOLO(cfg.file_yolo_model)
        except Exception as e:
            print(f"⚠️ YOLO face detection failed: {e}. Using MediaPipe for the speaker count.")

    if yolo_model is None:
        detector = get_face_detector(cfg)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 2

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = total_frames / fps if fps > 0 else 0

    if duration == 0:
        cap.release()
        return 2

    sample_count = 20
    step = duration / sample_count
    max_faces = 0

    for i in range(sample_count):
        t = i * step
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if not ret:
            continue

        faces_in_frame = 0

        if yolo_model is not None:
            results = yolo_model(frame, verbose=False)
            if results and len(results[0].boxes) > 0:
                faces_in_frame = len(results[0].boxes)
        else:
            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
            )
            results = detector.detect(mp_image)
            if results.detections:
                faces_in_frame = len(results.detections)

        if faces_in_frame > max_faces:
            max_faces = faces_in_frame

    cap.release()
    print(f"   ✅ Found at most {max_faces} face(s) in a single frame.", flush=True)
    return max(1, max_faces)


