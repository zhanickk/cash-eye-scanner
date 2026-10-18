"""Sample frames for object labelling: every N seconds plus frames around labelled events."""

import argparse
import json
import math
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from forte.video_candidates import read_frame  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--videos', type=Path, required=True)
    p.add_argument('--out', type=Path, default=Path('private/det/frames'))
    p.add_argument('--every', type=float, default=3.0)
    a = p.parse_args()
    project = json.loads(a.project.read_text(encoding='utf-8'))
    a.out.mkdir(parents=True, exist_ok=True)
    index, seen = [], set()
    for rec in project['videos']:
        if rec['media']['sha256'] in seen:
            continue
        seen.add(rec['media']['sha256'])
        cap = cv2.VideoCapture(str(a.videos / rec['media']['filename']))
        fps = cap.get(cv2.CAP_PROP_FPS)
        duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
        times = {round(i * a.every, 1) for i in range(math.ceil(duration / a.every))}
        for note in rec.get('notes', []):
            times |= {round(note['time_sec'] + d, 1) for d in (-1, 0, 1)}
        for t in sorted(x for x in times if 0 <= x < duration - 1 / fps):
            name = f"{rec['video_id']}_{t:06.1f}.jpg"
            cv2.imwrite(str(a.out / name), read_frame(cap, t, fps), [cv2.IMWRITE_JPEG_QUALITY, 92])
            index.append({'file': name, 'video_id': rec['video_id'], 'timestamp_sec': t, 'split': rec.get('split')})
        cap.release()
    (a.out.parent / 'frames.json').write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding='utf-8')
    print({'frames': len(index), 'train': sum(f['split'] == 'train' for f in index),
           'validation': sum(f['split'] == 'validation' for f in index)})


if __name__ == '__main__':
    main()
