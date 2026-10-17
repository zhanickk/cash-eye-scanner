"""The jury contract uses exactly violations/timecode_sec/evidence_frames."""

import base64
import math


def validate_result(result: dict, duration: float | None = None) -> dict:
    if result.get('status') != 'done' or not isinstance(result.get('job_id'), str):
        raise ValueError('Invalid completed job')
    if not isinstance(result.get('violations'), list):
        raise ValueError('violations must be a list')
    expected = 'violation' if result['violations'] else 'no_violation'
    if result.get('verdict') != expected:
        raise ValueError('Verdict disagrees with violations')
    for event in result['violations']:
        for key in ['type', 'description']:
            if not isinstance(event.get(key), str) or not event[key].strip():
                raise ValueError(f'{key} is required')
        times = [event.get('timecode_sec')]
        frames = event.get('evidence_frames')
        if not isinstance(frames, list) or not 1 <= len(frames) <= 3:
            raise ValueError('Every event requires 1–3 evidence frames')
        for frame in frames:
            times.append(frame.get('timestamp_sec'))
            try:
                image = base64.b64decode(frame['image_base64'], validate=True)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError('Invalid evidence base64') from exc
            if not image.startswith(b'\xff\xd8') or not image.endswith(b'\xff\xd9'):
                raise ValueError('Evidence must be JPEG')
        for time in times:
            if isinstance(time, bool) or not isinstance(time, (int, float)) or not math.isfinite(time) or time < 0:
                raise ValueError('Invalid timecode')
            if duration is not None and time >= duration:
                raise ValueError('Timecode outside video')
    return result
