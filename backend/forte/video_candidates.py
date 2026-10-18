"""Find short periods with notable visual changes without using faces or audio."""

from pathlib import Path

import cv2
import numpy as np


def video_info(path: Path) -> tuple[float, float]:
    video = cv2.VideoCapture(str(path))
    if not video.isOpened():
        raise ValueError('Не удалось открыть видео')
    fps = video.get(cv2.CAP_PROP_FPS)
    count = video.get(cv2.CAP_PROP_FRAME_COUNT)
    video.release()
    if fps <= 0 or count <= 0:
        raise ValueError('Видео не содержит кадров')
    return count / fps, fps


def motion_candidates(path: Path, limit: int = 10, spacing_sec: int = 4) -> list[tuple[float, float]]:
    """Return (second, score), strongest first. Regions adapt to any camera angle."""
    duration, _ = video_info(path)
    video = cv2.VideoCapture(str(path))
    width, height = 116, 212
    regions = [
        (0, width, 0, height),
        (0, width // 2, 0, height // 2),
        (width // 2, width, 0, height // 2),
        (0, width // 2, height // 2, height),
        (width // 2, width, height // 2, height),
        (20, 96, 45, 170),
    ]
    scores = []
    prior = None
    for second in range(max(1, int(duration))):
        video.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
        ok, frame = video.read()
        if not ok:
            continue
        gray = cv2.cvtColor(cv2.resize(frame, (width, height)), cv2.COLOR_BGR2GRAY)
        if prior is not None:
            delta = cv2.absdiff(gray, prior)
            score = max(float(delta[y1:y2, x1:x2].mean()) for x1, x2, y1, y2 in regions)
            scores.append((float(second), score))
        prior = gray
    video.release()
    ranked = sorted(scores, key=lambda item: item[1], reverse=True)
    selected = []
    for second, score in ranked:
        if all(abs(second - earlier[0]) >= spacing_sec for earlier in selected):
            selected.append((second, score))
            if len(selected) == limit:
                break
    return selected


def read_frame(video, seconds: float, fps: float = 30.0, max_back_sec: float = 2.0) -> np.ndarray:
    """Container frame counts often overstate the last frames; step back until one decodes."""
    second = max(0.0, seconds)
    floor = max(0.0, second - max_back_sec)
    while second >= floor:
        video.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
        ok, frame = video.read()
        if ok:
            return frame
        second -= 1 / fps
    raise ValueError(f'Нет кадра на {seconds:.1f} секунде')


def frame_at(path: Path, seconds: float) -> np.ndarray:
    video = cv2.VideoCapture(str(path))
    try:
        return read_frame(video, seconds, video.get(cv2.CAP_PROP_FPS) or 30.0)
    finally:
        video.release()


def evidence_jpeg(path: Path, seconds: float, quality: int = 82) -> bytes:
    frame = frame_at(path, seconds)
    ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError('Не удалось создать кадр-доказательство')
    return encoded.tobytes()
