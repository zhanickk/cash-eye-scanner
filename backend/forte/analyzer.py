"""Local visual baseline plus process rules. No trained detector is claimed.

    This deliberately scans the complete recording until a measured detector
    can safely propose intervals. It never reports motion as a violation.
"""

import base64
import json
import math
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import cv2
import httpx

from .contracts import validate_result
from .rules import CATALOG, RULES, ProcessRules, check_observation
from .video_candidates import video_info


def model_url():
    url = os.environ.get('QWEN_CHAT_URL', 'http://127.0.0.1:8081/v1/chat/completions')
    parsed = urlparse(url)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.username or parsed.password:
        raise ValueError('Модель должна работать на локальном loopback-адресе')
    return url


def frame_jpeg(path: Path, second: float, max_side=896):
    cap = cv2.VideoCapture(str(path))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok:
        raise ValueError(f'Кадр на {second:.2f} сек. не прочитан')
    h, w = frame.shape[:2]
    scale = min(1, max_side / max(h, w))
    if scale < 1:
        frame = cv2.resize(frame, (round(w * scale), round(h * scale)))
    ok, data = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise ValueError('Не удалось извлечь JPEG')
    return base64.b64encode(data.tobytes()).decode('ascii')


def prompt():
    rules = [{k: r[k] for k in ['type', 'definition', 'not_violation_examples', 'requires_complete_context']} for r in CATALOG]
    return '''Ты проверяешь визуальные признаки возможных отклонений кассовой процедуры.
Все времена абсолютные от начала видео. Это редкие выборки кадров, а не непрерывная
запись: отсутствие действия между кадрами НЕ доказывает пропуск обязательного шага.
Не идентифицируй лица, не используй звук, не угадывай содержимое экранов, роль
незнакомого человека, намерения и действия вне кадра. Открытая крышка ноутбука
не означает отсутствие блокировки. Поворот головы не доказывает разговор.
Не генерируй нормативные источники. Собственную уверенность числом не оценивай.
Список категорий: ''' + json.dumps(rules, ensure_ascii=False) + '''
Ответ только JSON: {"observations":[],"violations":[],"uncertain":[]}.
observations: наблюдаемые состояния на ТОЧНО переданном кадре:
{"kind":"safe_open","timecode_sec":12.0,"description":"Видимое положение дверцы"}.
Допустимые kind: employee_stood_up, employee_seated, employee_exit, employee_return,
door_open, door_closed, safe_open, safe_closed, keys_exposed, keys_secured,
cash_on_desk, cash_secured, screen_unlocked, screen_locked.
employee_exit означает наблюдаемый выход через границу, а не вставание или уход из
области камеры. Состояния предметов при выходе должны быть на том же кадре.
Для категорий left_cabinet_open, safe_or_keys_exposed, computer_left_unsecured,
cash_left_unsecured возвращай observations; решение соединит программное правило.
Для остальных violations содержит только прямо видимое действие:
{"category":"client_flow_violation","timecode_sec":12.0,"start_sec":11.0,
"end_sec":13.0,"description":"Что видно и почему эпизод требует проверки",
"evidence_times":[12.0],"context_complete":false,"decision":"supported"}.
evidence_times должны ТОЧНО совпадать с временем переданных кадров и лежать внутри
интервала. По редким кадрам нельзя установить отсутствие проверки личности,
пересчёта всех пачек или происхождение смешиваемых денег: такие случаи помещай
в uncertain с причиной. Не превращай неопределённость в подтверждённый факт.
Если признаков нет, возвращай три пустых списка.'''


def parse_model(raw):
    if not isinstance(raw, str):
        raise ValueError('Пустой ответ локальной модели')
    raw = raw.strip()
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
    value = json.loads(raw)
    if not isinstance(value, dict) or any(not isinstance(value.get(k), list) for k in ['observations', 'violations', 'uncertain']):
        raise ValueError('Модель вернула неверную структуру JSON')
    if any(not isinstance(item, dict) for key in ['observations', 'violations', 'uncertain'] for item in value[key]):
        raise ValueError('Модель вернула неверные элементы JSON')
    return value


def ask_model(frames, start, end, timeout):
    content = [{'type': 'text', 'text': f'Фрагмент {start:.2f}–{end:.2f} сек. Проверяй только наблюдаемые события.'}]
    for second, image in frames:
        content += [{'type': 'text', 'text': f'Абсолютное время кадра: {second:.3f} сек.'},
                    {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{image}'}}]
    response = httpx.post(model_url(), json={
        'model': os.environ.get('QWEN_MODEL_NAME', 'qwen3-vl-local'),
        'messages': [{'role': 'system', 'content': prompt()}, {'role': 'user', 'content': content}],
        'temperature': 0, 'max_tokens': 1400, 'response_format': {'type': 'json_object'},
    }, timeout=timeout, trust_env=False)
    response.raise_for_status()
    body = response.json()['choices'][0]
    if body.get('finish_reason') == 'length':
        raise ValueError('Ответ модели обрезан лимитом токенов')
    return parse_model(body['message']['content'])


def accept_proposal(event, times, duration):
    category = event.get('category')
    if category not in RULES or RULES[category]['mode'] == 'rule' or event.get('decision') != 'supported':
        return None
    # With sparse frame sampling the absence of a step is not observable.
    if RULES[category]['requires_complete_context']:
        return None
    try:
        start, end, second = (float(event[k]) for k in ['start_sec', 'end_sec', 'timecode_sec'])
        evidence = event['evidence_times']
        valid = (all(math.isfinite(t) for t in [start, end, second]) and 0 <= start <= second <= end < duration
                 and isinstance(evidence, list) and 1 <= len(evidence) <= 3
                 and all(isinstance(t, (int, float)) and math.isfinite(t) and start <= t <= end
                         and any(abs(t - x) <= .01 for x in times) for t in evidence)
                 and isinstance(event.get('description'), str) and event['description'].strip())
        if not valid:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return {**event, 'origin': 'vlm_visual_proposal'}


def analyze_video(path: Path, job_id: str, progress=None):
    model_url()
    duration, fps = video_info(path)
    started = time.monotonic()
    budget = float(os.environ.get('FORTE_ANALYSIS_TIMEOUT', '270'))
    window = float(os.environ.get('QWEN_WINDOW_SEC', '16'))
    count = int(os.environ.get('QWEN_SAMPLE_COUNT', '8'))
    if window <= 0 or not 2 <= count <= 64:
        raise ValueError('Неверные настройки выборки кадров')
    proposals, observations, review = [], [], []
    scanned = 0.0
    for index in range(math.ceil(duration / window)):
        start, end = index * window, min(duration, (index + 1) * window)
        remaining = budget - (time.monotonic() - started)
        if remaining < 1:
            raise TimeoutError('Лимит анализа исчерпан; частичный анализ не выдан как отсутствие нарушений')
        last = max(start, end - 1 / fps)
        times = [round(start + (last - start) * j / (count - 1), 3) for j in range(count)]
        frames = [(t, frame_jpeg(path, t)) for t in times]
        parsed = ask_model(frames, start, end, remaining)
        for value in parsed['observations']:
            try:
                observations.append(check_observation(value, times))
            except (ValueError, KeyError, TypeError):
                review.append({'reason': 'invalid_model_observation', 'data': value})
        for event in parsed['violations']:
            accepted = accept_proposal(event, times, duration)
            if accepted:
                proposals.append(accepted)
            else:
                review.append({'reason': 'unsupported_or_unobservable_proposal', 'data': event})
        review.extend(parsed['uncertain'])
        scanned = end
        if progress:
            progress(round(90 * end / duration), 'analyzing')
    engine = ProcessRules()
    proposals.extend(engine.feed(observations))
    unique = []
    for item in sorted(proposals, key=lambda p: p['timecode_sec']):
        if not any(p['category'] == item['category'] and abs(p['timecode_sec'] - item['timecode_sec']) < 1 for p in unique):
            unique.append(item)
    violations = []
    for candidate in unique:
        rule = RULES[candidate['category']]
        evidence = [{'timestamp_sec': t, 'image_base64': frame_jpeg(path, t)} for t in candidate['evidence_times'][:3]]
        violations.append({
            'type': candidate['category'], 'timecode_sec': candidate['timecode_sec'],
            'description': candidate['description'], 'evidence_frames': evidence,
            'rule': rule['rule_reference'],
        })
    return validate_result({
        'job_id': job_id, 'status': 'done', 'verdict': 'violation' if violations else 'no_violation',
        'violations': violations, 'review_required': bool(review),
        'limitations': ['Экспериментальный анализ по выборке кадров. Отсутствие обязательного шага не устанавливается.',
                        'Нормативные привязки со статусом unverified требуют проверки.'],
        'analysis': {'model': os.environ.get('QWEN_MODEL_NAME', 'qwen3-vl-local'),
                     'duration_sec': duration, 'scanned_until_sec': scanned,
                     'elapsed_sec': round(time.monotonic() - started, 2),
                     'trained_object_detector': False, 'review_count': len(review)},
    }, duration)
