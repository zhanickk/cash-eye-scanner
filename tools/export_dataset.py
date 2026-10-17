"""Export only reviewed, explicit labels. Never promote source notes into labels."""

import argparse
import base64
import hashlib
import json
import math
from pathlib import Path


def audit(project):
    problems, group_splits = [], {}
    rules = {r['type'] for r in json.loads((Path(__file__).resolve().parents[1] / 'config/rules.json').read_text())['rules']}
    for r in project['videos']:
        vid = r['video_id']
        split = r.get('split', 'unassigned')
        if split not in {'train', 'validation', 'test', 'unassigned'}:
            problems.append(f'{vid}: неизвестная часть набора')
        group = r.get('source_group') or r.get('media', {}).get('sha256')
        if not group:
            problems.append(f'{vid}: не задана исходная группа')
        if group and split != 'unassigned':
            if group in group_splits and group_splits[group] != split:
                problems.append(f'{vid}: одна исходная группа попала в разные части набора')
            group_splits[group] = split
        events = r.get('events', [])
        if r.get('status') == 'reviewed_no_violation' and events:
            problems.append(f'{vid}: метка «без нарушения» конфликтует с эпизодами')
        if r.get('status') == 'reviewed_with_violations' and not events:
            problems.append(f'{vid}: отсутствуют события для положительной метки')
        duration = r.get('media', {}).get('duration_sec', math.inf)
        for e in events:
            if e.get('type') not in rules:
                problems.append(f'{vid}: неизвестная категория')
            try:
                start, end = float(e['start_sec']), float(e['end_sec'])
                anchor = float(e.get('timecode_sec', start))
                if not all(math.isfinite(t) for t in [start, end, anchor]) or not 0 <= start <= anchor <= end < duration:
                    raise ValueError()
                frames = e.get('evidence_frames', [])
                if not 1 <= len(frames) <= 3 or any(not start <= f['timestamp_sec'] <= end for f in frames):
                    raise ValueError()
                for frame in frames:
                    image = base64.b64decode(frame['image_base64'], validate=True)
                    if not image.startswith(b'\xff\xd8'):
                        raise ValueError()
            except (KeyError, TypeError, ValueError):
                problems.append(f'{vid}: неверный интервал или доказательства')
    return problems


def reviewed(r):
    return r.get('status') in {'reviewed_no_violation', 'reviewed_with_violations'} and all(e.get('annotation_status') == 'confirmed' for e in r.get('events', []))


def export_sft(project, out):
    rows = {'train': [], 'validation': []}
    for r in project['videos']:
        split = r.get('split')
        if split not in rows or not reviewed(r):
            continue
        path = Path(r.get('media', {}).get('path', ''))
        if not path.is_file():
            raise ValueError(f'{r["video_id"]}: исходный видеофайл отсутствует')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != r['media'].get('sha256'):
            raise ValueError(f'{r["video_id"]}: изменён исходный видеофайл')
        target = {'violations': [{'type': e['type'], 'timecode_sec': e.get('timecode_sec', e['start_sec']),
                                  'start_sec': e['start_sec'], 'end_sec': e['end_sec'],
                                  'description': e['description']} for e in r.get('events', [])]}
        rows[split].append({'messages': [{'role': 'user', 'content': '<video>Определи наблюдаемые признаки возможных нарушений кассовой процедуры. Ответь JSON с violations, type, timecode_sec, start_sec, end_sec и description.'},
                                        {'role': 'assistant', 'content': json.dumps(target, ensure_ascii=False)}], 'videos': [str(path)]})
    if not rows['train'] or not rows['validation']:
        raise ValueError('Для обучения нужны подтверждённые train И validation; черновики/тестовые записи не используются')
    for split, records in rows.items():
        (out / f'{split}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records))
    return {k: len(v) for k, v in rows.items()}


def export_coco(project, out):
    frames = {'train': [], 'validation': []}
    for r in project['videos']:
        split = r.get('split')
        if split in frames:
            frames[split].extend((r, f) for f in r.get('object_frames', []) if f.get('reviewed'))
    if not frames['train'] or not frames['validation']:
        raise ValueError('Нет полностью размеченных кадров в train И validation')
    labels = sorted({o['label'] for values in frames.values() for _, f in values for o in f['objects']})
    category_ids = {label: i + 1 for i, label in enumerate(labels)}
    for split, pairs in frames.items():
        dest = out / ('valid' if split == 'validation' else 'train')
        dest.mkdir(parents=True, exist_ok=True)
        coco = {'images': [], 'annotations': [], 'categories': [{'id': i, 'name': name, 'supercategory': 'object'} for name, i in category_ids.items()]}
        for index, (r, frame) in enumerate(pairs, 1):
            name = f'{r["video_id"]}_{index}.jpg'
            image = base64.b64decode(frame['image_base64'], validate=True)
            (dest / name).write_bytes(image)
            width, height = frame['width'], frame['height']
            coco['images'].append({'id': index, 'file_name': name, 'width': width, 'height': height})
            for obj in frame['objects']:
                x, y, w, h = obj['rect']
                if not (0 <= x <= 1 and 0 <= y <= 1 and w > 0 and h > 0 and x + w <= 1.000001 and y + h <= 1.000001):
                    raise ValueError('Рамка выходит за границы кадра')
                box = [x * width, y * height, w * width, h * height]
                coco['annotations'].append({'id': len(coco['annotations']) + 1, 'image_id': index,
                                             'category_id': category_ids[obj['label']], 'bbox': box,
                                             'area': box[2] * box[3], 'iscrowd': 0})
        (dest / '_annotations.coco.json').write_text(json.dumps(coco, ensure_ascii=False))
    return {k: len(v) for k, v in frames.items()}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('format', choices=['audit', 'sft', 'coco'])
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--out', type=Path, default=Path('private/exports'))
    a = p.parse_args()
    project = json.loads(a.project.read_text())
    problems = audit(project)
    if problems:
        raise SystemExit('\n'.join(problems))
    if a.format == 'audit':
        print(json.dumps({'videos': len(project['videos']), 'reviewed': sum(reviewed(r) for r in project['videos']), 'issues': []}, ensure_ascii=False))
        return
    a.out.mkdir(parents=True, exist_ok=True)
    print(export_sft(project, a.out) if a.format == 'sft' else export_coco(project, a.out))


if __name__ == '__main__':
    main()
