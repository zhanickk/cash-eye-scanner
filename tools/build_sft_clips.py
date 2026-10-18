"""Build ms-swift LoRA data from the annotation project in the exact runtime window format.

Label policy (official open_labels.xlsx wins over team notes):
- videos officially without violation get empty answers for every window;
- in violation videos every typed team note becomes an event;
- client_not_identified notes are kept only where the official timecode points at
  them: the organisers rejected that note on X-19/35/37/39, so elsewhere it is unreliable.
"""

import argparse
import json
import math
import random
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from forte.prompting import FRAMES_PER_WINDOW, WINDOW_SEC, answer, system_prompt, window_times  # noqa: E402
from forte.rules import RULES  # noqa: E402
from forte.video_candidates import read_frame  # noqa: E402

# Notes that describe two violations at one moment.
SPLIT_NOTES = {'X-11': ['computer_left_unsecured', 'safe_or_keys_exposed'],
               'X-46': ['cash_left_unsecured', 'items_left_on_desk']}


def events_for(record):
    if record.get('source_label') != 'violation':
        return []
    official = record.get('official_timecode_sec')
    events = []
    for note in record.get('notes', []):
        types = SPLIT_NOTES.get(record['video_id']) or (
            [note['type']] if note.get('type') in RULES else [t for t in note.get('suggested_types', []) if t in RULES][-1:])
        for kind in types:
            if kind == 'client_not_identified' and (official is None or abs(note['time_sec'] - official) > 1):
                continue
            text = note['text'].strip().rstrip('.')
            events.append({'category': kind, 'timecode_sec': float(note['time_sec']),
                           'description': f'Кассир: {text[0].lower() + text[1:]}. {RULES[kind]["name"]}.'})
    return events


def save_frame(cap, second, path, fps):
    if path.exists():
        return
    frame = read_frame(cap, second, fps)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--videos', type=Path, required=True, help='Folder with the .mov files on this machine')
    p.add_argument('--out', type=Path, default=Path('private/sft'))
    p.add_argument('--train-stride', type=float, default=4.0, help='Overlapping windows multiply train examples')
    p.add_argument('--positive-repeat', type=int, default=0,
                   help='Repeat event windows N times; 0 balances them 1:1 against clean windows')
    p.add_argument('--keep-unlabeled-windows', action='store_true',
                   help='Also train on event-free windows of violation videos (their state may still be violating)')
    a = p.parse_args()
    project = json.loads(a.project.read_text(encoding='utf-8'))
    system = system_prompt()
    rows = {'train': [], 'validation': []}
    stats = {'train': [0, 0], 'validation': [0, 0]}
    labels, seen = {}, set()
    for rec in project['videos']:
        split = rec.get('split')
        # Byte-identical duplicates (X-4/X-47, X-5/X-48) carry inconsistent notes; keep the first.
        if split not in rows or rec['media']['sha256'] in seen:
            continue
        seen.add(rec['media']['sha256'])
        path = a.videos / rec['media']['filename']
        cap = cv2.VideoCapture(str(path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
        events = events_for(rec)
        labels[rec['video_id']] = {'split': split, 'events': events}
        stride = a.train_stride if split == 'train' else WINDOW_SEC
        starts = [i * stride for i in range(max(1, math.ceil((duration - 1) / stride)))]
        for start in starts:
            end = min(duration, start + WINDOW_SEC)
            times = window_times(start, end, fps, FRAMES_PER_WINDOW)
            inside = []
            for e in events:
                if start - 0.5 <= e['timecode_sec'] <= end:
                    nearest = min(times, key=lambda t: abs(t - e['timecode_sec']))
                    inside.append({**e, 'timecode_sec': nearest})
            images = []
            for t in times:
                f = a.out / 'frames' / rec['video_id'] / f'{t:.3f}.jpg'
                save_frame(cap, t, f, fps)
                images.append(str(f.resolve()))
            text = f'Фрагмент {start:.1f}–{end:.1f} сек.' + ''.join(f'\nКадр {t:.1f} сек. <image>' for t in times)
            # A safe opened at 5 s is usually still open at 20 s: in a violation video an
            # event-free window is not evidence of a clean scene, so it is a contradictory label.
            if split == 'train' and not inside and events and not a.keep_unlabeled_windows:
                continue
            row = {'messages': [{'role': 'system', 'content': system},
                                {'role': 'user', 'content': text},
                                {'role': 'assistant', 'content': answer(inside)}],
                   'images': images}
            rows[split].append(row)
            stats[split][bool(inside)] += 1
        cap.release()
    positives = [r for r in rows['train'] if '"category"' in r['messages'][2]['content']]
    negatives = len(rows['train']) - len(positives)
    repeat = a.positive_repeat or max(1, round(negatives / max(1, len(positives))))
    rows['train'].extend(positives * (repeat - 1))
    random.Random(0).shuffle(rows['train'])
    print({'positive_repeat': repeat})
    a.out.mkdir(parents=True, exist_ok=True)
    for split, items in rows.items():
        (a.out / f'{split}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in items), encoding='utf-8')
    (a.out / 'labels.json').write_text(json.dumps(labels, ensure_ascii=False, indent=1), encoding='utf-8')
    print({s: {'windows': sum(v), 'with_events': v[1]} for s, v in stats.items()})


if __name__ == '__main__':
    main()
