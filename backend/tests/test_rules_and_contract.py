import base64
import math

import pytest

from forte.contracts import validate_result
from forte.rules import Observation as O, ProcessRules
from forte.analyzer import accept_proposal, parse_model


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


def test_sparse_frames_cannot_prove_missing_identity_step():
    event = {'category': 'client_not_identified', 'decision': 'supported', 'context_complete': True,
             'start_sec': 0, 'end_sec': 3, 'timecode_sec': 2, 'evidence_times': [2], 'description': 'no ID'}
    assert accept_proposal(event, [0, 2, 3], 10) is None


def test_hallucinated_frame_or_nonfinite_time_is_rejected():
    event = {'category': 'client_flow_violation', 'decision': 'supported', 'context_complete': True,
             'start_sec': 0, 'end_sec': 3, 'timecode_sec': 2, 'evidence_times': [1.7], 'description': 'action'}
    assert accept_proposal(event, [0, 2, 3], 10) is None
    event.update(evidence_times=[2], timecode_sec=math.nan)
    assert accept_proposal(event, [0, 2, 3], 10) is None


def test_bad_model_output_is_an_error_not_a_clean_video():
    with pytest.raises(ValueError):
        parse_model('{"events":[]}')


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
