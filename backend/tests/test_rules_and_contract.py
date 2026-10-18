import base64
import math

import pytest

from forte.contracts import validate_result
from forte.rules import Observation as O, ProcessRules
from forte.analyzer import accept_event, evidence_times
from forte.prompting import parse_answer, window_times


def obs(kind, time):
    return O(kind, time, kind, time)


def test_standing_and_returning_does_not_accuse():
    engine = ProcessRules()
    assert engine.feed([obs('safe_open', 1), obs('employee_stood_up', 2), obs('employee_seated', 3)]) == []
    assert [a['state'] for a in engine.audit] == ['pending', 'cancelled']


def test_exit_with_visible_open_safe_confirms_but_open_laptop_does_not():
    engine = ProcessRules()
    events = engine.feed([obs('employee_stood_up', 2), obs('employee_exit', 5), obs('safe_open', 5), obs('laptop_open', 5)])
    assert [e['category'] for e in events] == ['safe_or_keys_exposed']
    assert events[0]['timecode_sec'] == 5


def test_stale_and_cancelled_states_cannot_prove_unsafe_exit():
    assert ProcessRules().feed([obs('safe_open', 1), obs('employee_exit', 10)]) == []
    assert ProcessRules().feed([obs('safe_open', 1), obs('safe_closed', 2), obs('employee_exit', 3)]) == []


def test_event_snaps_to_a_sent_frame_and_unknown_category_is_rejected():
    event = {'category': 'client_flow_violation', 'timecode_sec': 2.3, 'description': 'action'}
    assert accept_event(event, [0, 1, 2, 3])['timecode_sec'] == 2
    assert accept_event({**event, 'category': 'invented'}, [0, 1, 2, 3]) is None
    assert accept_event({**event, 'description': ' '}, [0, 1, 2, 3]) is None


def test_hallucinated_frame_or_nonfinite_time_is_rejected():
    event = {'category': 'client_flow_violation', 'timecode_sec': 9.0, 'description': 'action'}
    assert accept_event(event, [0, 1, 2, 3]) is None
    assert accept_event({**event, 'timecode_sec': math.nan}, [0, 1, 2, 3]) is None


def test_bad_model_output_is_an_error_not_a_clean_video():
    with pytest.raises(ValueError):
        parse_answer('{"violations":[]}')
    assert parse_answer('```json\n{"events":[]}\n```') == []


def test_windows_use_whole_seconds_and_stay_inside_video():
    assert window_times(16, 32, 30) == [float(t) for t in range(16, 32)]
    assert window_times(0, 11.6, 30)[-1] == 11
    assert evidence_times(11.0, 11.6, 30) == [11.0, 10.0]


def test_jury_verdict_consistency_and_evidence_required():
    with pytest.raises(ValueError):
        validate_result({'job_id': 'test', 'status': 'done', 'verdict': 'violation', 'violations': []})
    event = {'type': 'safe_or_keys_exposed', 'timecode_sec': 2, 'description': 'safe open', 'evidence_frames': []}
    with pytest.raises(ValueError):
        validate_result({'job_id': 'test', 'status': 'done', 'verdict': 'violation', 'violations': [event]})


def test_real_jpeg_is_accepted():
    import cv2
    import numpy as np
    _, data = cv2.imencode('.jpg', np.zeros((8, 8, 3), dtype=np.uint8))
    event = {'type': 'safe_or_keys_exposed', 'timecode_sec': 2, 'description': 'safe open',
             'evidence_frames': [{'timestamp_sec': 2, 'image_base64': base64.b64encode(data).decode()}]}
    assert validate_result({'job_id': 'test', 'status': 'done', 'verdict': 'violation', 'violations': [event]}, 3)
