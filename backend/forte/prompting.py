"""One prompt and answer format shared by inference and fine-tuning data.

Training examples must look exactly like what the analyzer sends at run time,
otherwise a LoRA learns a format the service never uses.
"""

import json

from .rules import CATALOG

WINDOW_SEC = 16.0
FRAMES_PER_WINDOW = 16


def window_times(start: float, end: float, fps: float, count: int = FRAMES_PER_WINDOW) -> list[float]:
    """Evenly spaced frames on whole steps (1 s for 16 frames per 16 s), like the jury labels."""
    last = max(start, end - 1 / fps)
    step = WINDOW_SEC / count
    times = [round(start + j * step, 3) for j in range(count) if start + j * step <= last]
    return times or [round(start, 3)]


def system_prompt() -> str:
    categories = [{'code': r['type'], 'name': r['name'], 'definition': r['definition'],
                   'not_violation': r['not_violation_examples']} for r in CATALOG if r.get('enabled', True)]
    return ('Ты проверяешь видео работы банковского кассира (вид сверху, без звука) и ищешь '
            'визуально наблюдаемые признаки нарушения кассовой процедуры. '
            'Не идентифицируй лиц, не угадывай содержимое экранов и действия вне кадра. '
            'Категории: ' + json.dumps(categories, ensure_ascii=False) + '\n'
            'Ответ только JSON: {"events":[{"category":"<code>","timecode_sec":<время кадра>,'
            '"description":"что видно и почему это нарушение"}]}. '
            'timecode_sec — время одного из переданных кадров, где нарушение видно лучше всего. '
            'Если нарушения не подходят ни под одну категорию, используй код other_procedure_violation. '
            'Если нарушений нет, верни {"events":[]}.')


def user_content(frames: list[tuple[float, str]], start: float, end: float, image_part) -> list:
    """frames: (absolute second, image ref); image_part builds the runtime-specific image item."""
    # Mirrors the training text: 'Фрагмент …' then '\nКадр t сек. <image>' per frame.
    content = [{'type': 'text', 'text': f'Фрагмент {start:.1f}–{end:.1f} сек.'}]
    for second, image in frames:
        content.append({'type': 'text', 'text': f'\nКадр {second:.1f} сек. '})
        content.append(image_part(image))
    return content


def answer(events: list[dict]) -> str:
    return json.dumps({'events': [{'category': e['category'], 'timecode_sec': round(float(e['timecode_sec']), 1),
                                   'description': e['description']} for e in events]}, ensure_ascii=False)


def parse_answer(raw: str) -> list[dict]:
    if not isinstance(raw, str):
        raise ValueError('Пустой ответ локальной модели')
    raw = raw.strip()
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
    value = json.loads(raw)
    events = value.get('events') if isinstance(value, dict) else None
    if not isinstance(events, list) or any(not isinstance(e, dict) for e in events):
        raise ValueError('Модель вернула неверную структуру JSON')
    return events
