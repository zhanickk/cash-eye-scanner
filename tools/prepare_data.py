"""Build a PRIVATE inventory; source notes remain drafts, never training labels."""

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path


def normalized(stem):
    return re.sub(r'^[Ххx]', 'X', stem.strip())


def suggested_types(text):
    text = text.lower()
    checks = {
        'client_not_identified': ['личност'],
        'cash_counting_violation': ['пересчитал', 'второй аппарат'],
        'cash_left_unsecured': ['деньги на столе', 'деньги со стола', 'не убрала деньги', 'не положила деньги'],
        'client_funds_mixed': ['перемешал', 'другого клиента', 'прошлого клиента'],
        'safe_or_keys_exposed': ['сейф открытым', 'ключ'],
        'computer_left_unsecured': ['ноут'],
        'items_left_on_desk': ['пакет на столе', 'журнал', 'штамп', 'куртк', 'сумк', 'напиток'],
        'left_cabinet_open': ['двер'],
        'equipment_not_activated': ['включила до конца'],
        'client_flow_violation': ['второй человек', 'клиент ушел', 'уйти первому'],
        'talked_to_outsider': ['разговор'],
        'money_not_banded': ['резинк', 'бандерол'],
    }
    return [kind for kind, needles in checks.items() if any(s in text for s in needles)]


def build(source_notes, video_dir, out):
    import cv2
    source = json.loads(source_notes.read_text())
    files = {normalized(p.stem): p for p in video_dir.iterdir() if p.suffix.lower() == '.mov'}
    videos, groups, issues = [], defaultdict(list), []
    for old in source['videos']:
        record = {**old, 'split': 'unassigned', 'events': [], 'object_frames': [], 'zones': [],
                  'camera_id': 'camera-01', 'status': old.get('status', 'unreviewed'),
                  'source_label_status': 'draft_from_notes', 'source_group': ''}
        record.pop('events', None)
        record['events'] = []
        for note in record.get('notes', []):
            note['suggested_types'] = suggested_types(note['text'])
            note['type'] = note['suggested_types'][0] if len(note['suggested_types']) == 1 else 'uncertain'
        path = files.get(normalized(record['video_id']))
        if path is None:
            issues.append({'video_id': record['video_id'], 'issue': 'missing_file'})
            videos.append(record)
            continue
        digest = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                digest.update(chunk)
        sha = digest.hexdigest()
        cap = cv2.VideoCapture(str(path))
        fps, n = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
        record['media'] = {'path': str(path.resolve()), 'filename': path.name, 'sha256': sha,
                           'bytes': path.stat().st_size, 'fps': fps,
                           'duration_sec': n / fps if fps else 0,
                           'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), 'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}
        cap.release()
        record['source_group'] = sha[:16]
        groups[sha].append(record['video_id'])
        for note in record.get('notes', []):
            if not 0 <= note['time_sec'] < record['media']['duration_sec']:
                issues.append({'video_id': record['video_id'], 'issue': 'note_outside_video', 'time_sec': note['time_sec']})
        videos.append(record)
    project = {'schema_version': 2, 'source_document': source.get('source_document'),
               'source_note': 'Предоставленные по ТЗ обучающие записи. Заметки — черновики, а не подтверждённые события.',
               'videos': videos}
    report = {'videos': len(videos), 'files_found': sum('media' in v for v in videos),
              'unique_sha256': len(groups), 'duplicate_groups': [g for g in groups.values() if len(g) > 1],
              'source_labels': dict(Counter(v['source_label'] for v in videos)),
              'reviewed_videos': 0, 'confirmed_events': 0, 'issues': issues,
              'unresolved': [{'video_id': v['video_id'], 'reason': v.get('conflict')} for v in videos if v.get('conflict')],
              'note': 'Хеши выявляют точные дубликаты. Связанные исходные сессии требуется дополнительно объединить перед разделением.'}
    out.mkdir(parents=True, exist_ok=True)
    (out / 'project.json').write_text(json.dumps(project, ensure_ascii=False, indent=2) + '\n')
    (out / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return project, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-notes', type=Path, required=True)
    parser.add_argument('--videos', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=Path('private'))
    parser.add_argument('--local-app', action='store_true')
    args = parser.parse_args()
    project, report = build(args.source_notes, args.videos, args.out)
    if args.local_app:
        root = Path(__file__).resolve().parents[1]
        dest = args.out / 'annotation'
        shutil.copytree(root / 'public/annotation', dest, dirs_exist_ok=True)
        rules = json.loads((root / 'config/rules.json').read_text())['rules']
        (dest / 'data.js').write_text('const INITIAL_DATA = ' + json.dumps(project, ensure_ascii=False) + ';\nconst VIOLATION_TYPES = ' + json.dumps(rules, ensure_ascii=False) + ';\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
