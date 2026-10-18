"""Local Qwen3-VL scan of the whole recording in 16-second windows of 1 fps frames.

The prompt and answer format come from prompting.py, the same module that
builds the LoRA training data, so the fine-tuned model sees at run time exactly
what it was trained on.
"""

import base64
import math
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import cv2
import httpx

from .contracts import validate_result
from .prompting import WINDOW_SEC, parse_answer, system_prompt, user_content, window_times
from .rules import RULES
from .video_candidates import frame_at, video_info

SNAP_SEC = 1.0
DEDUP_SEC = 3.0


def model_url():
    url = os.environ.get('QWEN_CHAT_URL', 'http://127.0.0.1:8081/v1/chat/completions')
    parsed = urlparse(url)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.username or parsed.password:
        raise ValueError('Модель должна работать на локальном loopback-адресе')
    return url


def frame_jpeg(path: Path, second: float, max_side=896):
    frame = frame_at(path, second)
    h, w = frame.shape[:2]
    scale = min(1, max_side / max(h, w))
    if scale < 1:
        frame = cv2.resize(frame, (round(w * scale), round(h * scale)))
    ok, data = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError('Не удалось извлечь JPEG')
    return base64.b64encode(data.tobytes()).decode('ascii')


def image_part(b64):
    return {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}'}}


def ask_model(frames, start, end, timeout):
    response = httpx.post(model_url(), json={
        'model': os.environ.get('QWEN_MODEL_NAME', 'qwen3-vl-local'),
        'messages': [{'role': 'system', 'content': system_prompt()},
                     {'role': 'user', 'content': user_content(frames, start, end, image_part)}],
        'temperature': 0, 'max_tokens': 700, 'response_format': {'type': 'json_object'},
    }, timeout=timeout, trust_env=False)
    response.raise_for_status()
    body = response.json()['choices'][0]
    if body.get('finish_reason') == 'length':
        raise ValueError('Ответ модели обрезан лимитом токенов')
    return parse_answer(body['message']['content'])


def accept_event(event, times):
    """Keep a model event only if its category is known and its time is one of the sent frames."""
    category = event.get('category')
    if category not in RULES or not RULES[category].get('enabled', True):
        return None
    try:
        second = float(event['timecode_sec'])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(second) or not times:
        return None
    nearest = min(times, key=lambda t: abs(t - second))
    description = event.get('description')
    if abs(nearest - second) > SNAP_SEC or not isinstance(description, str) or not description.strip():
        return None
    return {'category': category, 'timecode_sec': nearest, 'description': description.strip()[:600]}


def basis(reference):
    """The jury schema has no rule field, so the verified source also goes into the description."""
    if reference.get('status') != 'verified_text':
        return ' Нормативный источник не указан: прямая норма в открытых актах НБРК не найдена.'
    return f" Основание: {reference['title']}, {reference['section']} ({reference['url']})."


def evidence_times(second, duration, fps):
    last = duration - 1 / fps
    return [t for t in [second, second - 1, second + 1] if 0 <= t <= last][:3]


def analyze_video(path: Path, job_id: str, progress=None):
    model_url()
    duration, fps = video_info(path)
    started = time.monotonic()
    budget = float(os.environ.get('FORTE_ANALYSIS_TIMEOUT', '270'))
    windows = max(1, math.ceil(duration / WINDOW_SEC))
    found, review, failed_windows = [], [], []
    for index in range(windows):
        start, end = index * WINDOW_SEC, min(duration, (index + 1) * WINDOW_SEC)
        times = window_times(start, end, fps)
        frames = [(t, frame_jpeg(path, t)) for t in times]
        parsed = None
        for _ in range(2):
            remaining = budget - (time.monotonic() - started)
            if remaining < 1:
                raise TimeoutError('Лимит анализа исчерпан; частичный анализ не выдан как отсутствие нарушений')
            try:
                parsed = ask_model(frames, start, end, remaining)
                break
            except (ValueError, KeyError, httpx.HTTPError):
                # One malformed answer must not discard the whole recording.
                continue
        if parsed is None:
            failed_windows.append([start, end])
            review.append({'reason': 'window_not_analyzed', 'start_sec': start, 'end_sec': end})
        else:
            for event in parsed:
                accepted = accept_event(event, times)
                if accepted:
                    found.append(accepted)
                else:
                    review.append({'reason': 'unsupported_model_event', 'data': event})
        if progress:
            progress(round(90 * end / duration), 'analyzing')
    if len(failed_windows) == windows:
        raise ValueError('Локальная модель не дала корректного ответа ни по одному фрагменту')
    unique = []
    for item in sorted(found, key=lambda p: p['timecode_sec']):
        if not any(p['category'] == item['category'] and abs(p['timecode_sec'] - item['timecode_sec']) < DEDUP_SEC for p in unique):
            unique.append(item)
    violations = []
    for item in unique:
        rule = RULES[item['category']]
        violations.append({
            'type': rule['name'], 'category': item['category'], 'timecode_sec': item['timecode_sec'],
            'description': item['description'] + basis(rule['rule_reference']),
            'evidence_frames': [{'timestamp_sec': t, 'image_base64': frame_jpeg(path, t)}
                                for t in evidence_times(item['timecode_sec'], duration, fps)],
            'rule': rule['rule_reference'],
        })
    return validate_result({
        'job_id': job_id, 'status': 'done', 'verdict': 'violation' if violations else 'no_violation',
        'violations': violations, 'review_required': bool(review),
        'limitations': ['Анализ по кадрам с частотой 1 кадр/с; результат — подсказка для проверки человеком.'],
        'analysis': {'model': os.environ.get('QWEN_MODEL_NAME', 'qwen3-vl-local'),
                     'duration_sec': duration, 'windows': windows, 'failed_windows': failed_windows,
                     'elapsed_sec': round(time.monotonic() - started, 2), 'review_count': len(review)},
    }, duration)
