"""Reproducible local run; diagnostic draft labels never produce accuracy claims."""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from forte.analyzer import analyze_video


def match_events(expected, predicted, tolerance):
    # Maximum-cardinality one-to-one assignment, so one prediction cannot match
    # two ground truth events. Nearest admissible edges are attempted first.
    neighbors = [[j for j, p in sorted(enumerate(predicted), key=lambda x: abs(x[1]['timecode_sec'] - e['timecode_sec']))
                  if p['type'] == e['type'] and abs(p['timecode_sec'] - e['timecode_sec']) <= tolerance] for e in expected]
    assigned = {}
    def visit(i, seen):
        for j in neighbors[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in assigned or visit(assigned[j], seen):
                assigned[j] = i
                return True
        return False
    for i in range(len(expected)):
        visit(i, set())
    return len(assigned)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--out', type=Path, default=Path('private/benchmark'))
    p.add_argument('--split', choices=['train', 'validation', 'test', 'unassigned'], default='validation')
    p.add_argument('--limit', type=int)
    p.add_argument('--diagnostic', action='store_true', help='Run unreviewed video without calculating quality')
    p.add_argument('--tolerance-sec', type=float, default=2, help='Internal experimental tolerance; jury does not promise this tolerance')
    a = p.parse_args()
    project = json.loads(a.project.read_text())
    from export_dataset import audit, reviewed
    problems = audit(project)
    if problems:
        raise SystemExit('\n'.join(problems))
    records = [r for r in project['videos'] if r.get('split', 'unassigned') == a.split]
    if not a.diagnostic:
        records = [r for r in records if reviewed(r)]
    records = records[:a.limit] if a.limit else records
    if not records:
        raise SystemExit('Нет подходящих записей; для черновой диагностики явно задайте --diagnostic')
    a.out.mkdir(parents=True, exist_ok=True)
    summary = {'mode': 'diagnostic_no_quality_metrics' if a.diagnostic else 'reviewed_evaluation',
               'split': a.split, 'internal_tolerance_sec': a.tolerance_sec, 'records': [], 'tp': 0, 'fp': 0, 'fn': 0}
    for r in records:
        started = time.monotonic()
        try:
            path = Path(r['media']['path'])
            if hashlib.sha256(path.read_bytes()).hexdigest() != r['media']['sha256']:
                raise ValueError('SHA-256 исходного файла изменился')
            result = analyze_video(path, r['video_id'])
            (a.out / f'{r["video_id"]}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
            row = {'video_id': r['video_id'], 'status': 'done', 'violations': len(result['violations']), 'seconds': round(time.monotonic() - started, 2)}
            if not a.diagnostic:
                expected = [{'type': e['type'], 'timecode_sec': e.get('timecode_sec', e['start_sec'])} for e in r.get('events', [])]
                tp = match_events(expected, result['violations'], a.tolerance_sec)
                summary['tp'] += tp
                summary['fp'] += len(result['violations']) - tp
                summary['fn'] += len(expected) - tp
                row['video_verdict_correct'] = bool(expected) == bool(result['violations'])
        except Exception as exc:
            row = {'video_id': r['video_id'], 'status': 'failed', 'error': str(exc), 'seconds': round(time.monotonic() - started, 2)}
        summary['records'].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        (a.out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    if a.diagnostic:
        for key in ['tp', 'fp', 'fn']:
            summary.pop(key)
    else:
        tp, fp, fn = summary['tp'], summary['fp'], summary['fn']
        summary.update(precision=tp / (tp + fp) if tp + fp else None,
                       recall=tp / (tp + fn) if tp + fn else None,
                       failed=sum(r['status'] == 'failed' for r in summary['records']))
    (a.out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
