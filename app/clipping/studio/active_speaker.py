"""
clipping.studio.active_speaker — Follow whoever is talking, from mouth movement.

With two or more people in frame, the largest face is often the listener. A
speaking mouth opens and closes several times a second while a listening one
barely moves, so the face whose mouth opening varies most over a short window
is treated as the speaker. No audio model and no HuggingFace token are needed.

``select_speaker_faces`` is pure Python so it can be tested without OpenCV or
MediaPipe; ``MouthMeter`` does the landmark measurement.
"""

import os
import statistics
import urllib.request

URL_FACE_LANDMARKER = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)

# Face-mesh landmark indices: inner lips, and the face's vertical extent.
UPPER_LIP, LOWER_LIP = 13, 14
FOREHEAD, CHIN = 10, 152

ACTIVITY_WINDOW_SECONDS = 1.5  # mouth movement is measured over this window
MIN_ACTIVITY = 0.012           # std-dev of the normalised mouth opening that counts as talking
LEAD_MARGIN = 1.3              # the speaker must move this much more than the next face
SWITCH_HOLD_SECONDS = 1.0      # a new person must lead this long before the camera moves
# The current speaker may go undetected this long (head turned, hand over face)
# before another face takes over. Switches are backdated, so a real camera cut
# still lands on the cut; a shorter value let the silent listener grab the frame.
MISSING_HOLD_SECONDS = 3.0
TRACK_MATCH_RATIO = 0.12       # faces this close (fraction of frame width) are the same person
RELAXED_MATCH_FACTOR = 2.0     # an otherwise unmatched face may continue last sample's track this much further away
CROP_PADDING = 0.35            # context added around each face box before landmarking
CROP_SIDE = 256                # face crops are resized to this longest side


class MouthMeter:
    """Measure how open a face's mouth is, with MediaPipe Face Landmarker on a face crop."""

    def __init__(self, model_path):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        if not os.path.exists(model_path):
            print("   📥 Downloading the MediaPipe face landmarker model...")
            urllib.request.urlretrieve(URL_FACE_LANDMARKER, model_path)

        self._mp = mp
        self._landmarker = mp_vision.FaceLandmarker.create_from_options(
            mp_vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=model_path),
                num_faces=1,
                min_face_detection_confidence=0.3,
            )
        )

    def measure(self, frame_bgr, box):
        """Mouth opening divided by face height, or None when no face mesh is found."""
        import cv2

        height, width = frame_bgr.shape[:2]
        x1, y1, x2, y2 = box
        pad_w, pad_h = (x2 - x1) * CROP_PADDING, (y2 - y1) * CROP_PADDING
        cx1, cy1 = int(max(0, x1 - pad_w)), int(max(0, y1 - pad_h))
        cx2, cy2 = int(min(width, x2 + pad_w)), int(min(height, y2 + pad_h))
        if cx2 - cx1 < 16 or cy2 - cy1 < 16:
            return None

        crop = frame_bgr[cy1:cy2, cx1:cx2]
        scale = CROP_SIDE / max(crop.shape[:2])
        crop = cv2.resize(crop, (max(1, int(crop.shape[1] * scale)), max(1, int(crop.shape[0] * scale))))
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)

        result = self._landmarker.detect(
            self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        )
        if not result.face_landmarks:
            return None

        landmarks = result.face_landmarks[0]
        face_height = abs(landmarks[CHIN].y - landmarks[FOREHEAD].y)
        if face_height <= 1e-6:
            return None
        return abs(landmarks[LOWER_LIP].y - landmarks[UPPER_LIP].y) / face_height


_METERS: dict = {}


def get_mouth_meter(cfg):
    """A cached MouthMeter, or None (with one warning) when it cannot be created."""
    path = getattr(cfg, "file_face_landmarker", None) or os.path.join(
        getattr(cfg, "base_dir", os.getcwd()), "face_landmarker.task"
    )
    if path not in _METERS:
        try:
            _METERS[path] = MouthMeter(path)
        except Exception as e:
            print(f"   ⚠️ Speaker tracking unavailable ({e}); following faces by position instead.")
            _METERS[path] = None
    return _METERS[path]


# ==============================================================================
# SELECTION (pure)
# ==============================================================================

def _center_x(box):
    return (box[0] + box[2]) / 2


def _area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


def assign_tracks(samples, frame_width):
    """
    Give each detected face a track id that follows the same person across samples.

    A face keeps the most recently seen track within TRACK_MATCH_RATIO of it —
    matching on distance alone let a talker grab a stale track of their own
    earlier position and lose their activity history. A face that matches
    nothing may still continue a track from the previous sample within
    RELAXED_MATCH_FACTOR times that distance (a quick head movement or a jumpy
    detection box).
    """
    max_jump = frame_width * TRACK_MATCH_RATIO
    last_cx: dict[int, float] = {}
    last_idx: dict[int, int] = {}
    next_id = 0
    ids = []

    for idx, sample in enumerate(samples):
        boxes = sample["boxes"]
        row = [None] * len(boxes)
        taken = set()
        order = sorted(range(len(boxes)), key=lambda k: -_area(boxes[k]))

        for relaxed in (False, True):
            for i in order:
                if row[i] is not None:
                    continue
                cx = _center_x(boxes[i])
                if relaxed:
                    pool = [
                        t for t in last_cx
                        if t not in taken and last_idx[t] == idx - 1
                        and abs(last_cx[t] - cx) <= max_jump * RELAXED_MATCH_FACTOR
                    ]
                    key = lambda t: abs(last_cx[t] - cx)
                else:
                    pool = [t for t in last_cx if t not in taken and abs(last_cx[t] - cx) <= max_jump]
                    key = lambda t: (-last_idx[t], abs(last_cx[t] - cx))
                if pool:
                    row[i] = min(pool, key=key)
                    taken.add(row[i])

        for i in order:
            if row[i] is None:
                row[i] = next_id
                next_id += 1
        for i, track in enumerate(row):
            last_cx[track] = _center_x(boxes[i])
            last_idx[track] = idx
        ids.append(row)
    return ids


def _activity(samples, ids, step):
    """Per sample, the mouth-movement score of every track present in it."""
    half = max(1, round(ACTIVITY_WINDOW_SECONDS / step / 2))
    series: dict[int, dict[int, float]] = {}
    for idx, (sample, row) in enumerate(zip(samples, ids)):
        for mouth, track in zip(sample.get("mouths") or [], row):
            if mouth is not None:
                series.setdefault(track, {})[idx] = mouth

    scores = []
    for idx, row in enumerate(ids):
        per_track = {}
        for track in row:
            window = [
                value for j, value in series.get(track, {}).items() if abs(j - idx) <= half
            ]
            per_track[track] = statistics.pstdev(window) if len(window) >= 3 else 0.0
        scores.append(per_track)
    return scores


def select_speaker_faces(samples, frame_width, step):
    """
    Pick the face to frame in every sample.

    *samples* are ``{"boxes": [(x1, y1, x2, y2), ...], "mouths": [float|None, ...]}``.
    Returns one box per sample, or None when the camera should simply hold.

    - The candidate is the only face, the face whose mouth is clearly moving most,
      or else the current person (or the largest face when starting).
    - The camera moves to a different person only after they have been the
      candidate for SWITCH_HOLD_SECONDS; the switch is then backdated to when
      that started, so it lands on the real change.
    - When the current person is briefly undetected (a missed detection), the
      sample returns None and the camera holds — it used to jump to whoever
      happened to be detected, often the listener.
    - If the current person has been gone longer than the hold (a camera cut),
      the camera switches immediately.
    """
    ids = assign_tracks(samples, frame_width)
    scores = _activity(samples, ids, step)
    hold = max(1, round(SWITCH_HOLD_SECONDS / step))
    missing_hold = max(hold, round(MISSING_HOLD_SECONDS / step))

    def clear_talker(idx):
        row = ids[idx]
        if len(row) < 2:
            return None
        ranked = sorted(row, key=lambda t: scores[idx][t], reverse=True)
        top, runner_up = ranked[0], ranked[1]
        if scores[idx][top] >= MIN_ACTIVITY and scores[idx][top] >= scores[idx][runner_up] * LEAD_MARGIN:
            return top
        return None

    talkers = [clear_talker(i) for i in range(len(ids))]

    chosen: list = []
    current = None
    last_seen: dict[int, int] = {}
    pending = None
    pending_start = 0

    for idx, (sample, row) in enumerate(zip(samples, ids)):
        if not row:
            chosen.append(None)
            continue

        if len(row) == 1:
            candidate = row[0]
        elif talkers[idx] is not None:
            candidate = talkers[idx]
        elif current in row:
            candidate = current
        else:
            # Nobody is clearly talking yet: start on whoever talks first rather
            # than on the largest face, which is as likely to be the listener.
            upcoming = next(
                (talkers[j] for j in range(idx, min(len(ids), idx + missing_hold))
                 if talkers[j] is not None and talkers[j] in row),
                None,
            )
            candidate = upcoming if upcoming is not None else max(
                row, key=lambda t: _area(sample["boxes"][row.index(t)])
            )

        current_present = current in row
        current_gone = current is None or (
            not current_present and idx - last_seen.get(current, -missing_hold - 1) > missing_hold
        )
        for track in row:
            last_seen[track] = idx

        if current_gone:
            current, pending = candidate, None
        elif candidate != current:
            if pending != candidate:
                pending, pending_start = candidate, idx
            required = hold if current_present else missing_hold
            if idx - pending_start + 1 >= required:
                current, pending = candidate, None
                for j in range(pending_start, idx):
                    if current in ids[j]:
                        chosen[j] = current
        else:
            pending = None

        chosen.append(current if current in row else None)

    return [
        sample["boxes"][row.index(track)] if track is not None and track in row else None
        for sample, row, track in zip(samples, ids, chosen)
    ]
