"""Score the analyzer against the official labels (verdict, timecode) and the typed training labels."""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from forte.analyzer import analyze_video  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--labels', type=Path, required=True, help='labels.json written by build_sft_clips.py')
    p.add_argument('--videos', type=Path, required=True)
    p.add_argument('--split', default='validation', help='train, validation or all')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    project = json.loads(a.project.read_text(encoding='utf-8'))
    labels = json.loads(a.labels.read_text(encoding='utf-8'))
    a.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for rec in project['videos']:
        vid = rec['video_id']
        if vid not in labels or (a.split != 'all' and labels[vid]['split'] != a.split):
            continue
        started = time.monotonic()
        try:
            result = analyze_video(a.videos / rec['media']['filename'], vid)
            pred = [(v['category'], v['timecode_sec']) for v in result['violations']]
            status = 'done'
        except Exception as exc:  # noqa: BLE001 - every failure is scored as unprocessed
            result, pred, status = {'error': repr(exc)}, [], 'failed'
        truth_violation = rec['source_label'] == 'violation'
        official_t = rec.get('official_timecode_sec')
        expected = labels[vid]['events']
        row = {'video_id': vid, 'truth': rec['source_label'], 'official_t': official_t, 'status': status,
               'verdict_ok': status == 'done' and bool(pred) == truth_violation,
               'pred': pred, 'expected': [(e['category'], e['timecode_sec']) for e in expected],
               'seconds': round(time.monotonic() - started, 1)}
        if pred and official_t is not None:
            row['official_t_error'] = min(abs(t - official_t) for _, t in pred)
        hits = [e for e in expected if any(c == e['category'] and abs(t - e['timecode_sec']) <= 2 for c, t in pred)]
        row['typed_hits'] = len(hits)
        rows.append(row)
        (a.out / f'{vid}.json').write_text(json.dumps({k: v for k, v in result.items() if k != 'violations'} |
                                                      {'pred': pred}, ensure_ascii=False), encoding='utf-8')
        print(json.dumps(row, ensure_ascii=False), flush=True)
    n = len(rows)
    t_errors = [r['official_t_error'] for r in rows if 'official_t_error' in r]
    summary = {
        'videos': n, 'failed': sum(r['status'] == 'failed' for r in rows),
        'verdict_accuracy': round(sum(r['verdict_ok'] for r in rows) / n, 3) if n else None,
        'missed_violations': sum(r['truth'] == 'violation' and not r['pred'] for r in rows),
        'false_alarms': sum(r['truth'] == 'no_violation' and bool(r['pred']) for r in rows),
        'timecode_within_2s': sum(e <= 2 for e in t_errors), 'timecode_scored': len(t_errors),
        'typed_event_recall': f"{sum(r['typed_hits'] for r in rows)}/{sum(len(r['expected']) for r in rows)}",
        'mean_seconds': round(sum(r['seconds'] for r in rows) / n, 1) if n else None,
    }
    (a.out / 'summary.json').write_text(json.dumps(summary | {'rows': rows}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
