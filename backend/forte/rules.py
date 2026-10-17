"""Temporal rules over observations; a model prediction is never a policy source."""

import json
import math
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / 'config/rules.json').read_text())['rules']
RULES = {r['type']: r for r in CATALOG}


@dataclass(frozen=True)
class Observation:
    kind: str
    timecode_sec: float
    description: str
    evidence_time: float
    # Scope is the recording/session, not a face identity.
    scope: str = 'cashier'


def check_observation(value: dict, sampled_times: list[float]) -> Observation:
    time = float(value['timecode_sec'])
    if not math.isfinite(time) or not sampled_times:
        raise ValueError('Invalid observation time')
    evidence = min(sampled_times, key=lambda t: abs(t - time))
    if abs(evidence - time) > 0.15:
        raise ValueError('Observation must refer to an actual supplied frame')
    text = value.get('description')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Observation description is required')
    return Observation(str(value['kind']), time, text[:800], evidence)


class ProcessRules:
    """Stood up is pending; seated cancels; an observed exit confirms candidates.

    State must be refreshed at the exit frame. A stale observation of an open
    safe from ten seconds earlier cannot prove that the safe stayed open.
    """

    def __init__(self):
        self.pending = None
        self.states = {}
        self.audit = []

    def feed(self, observations: list[Observation]) -> list[dict]:
        result = []
        order = {'employee_exit': 2, 'employee_stood_up': 1, 'employee_seated': 1}
        for obs in sorted(observations, key=lambda o: (o.timecode_sec, order.get(o.kind, 0))):
            if obs.kind == 'employee_stood_up':
                self.pending = obs.timecode_sec
                self.audit.append({'state': 'pending', 'timecode_sec': obs.timecode_sec})
            elif obs.kind in {'employee_seated', 'employee_return'}:
                if self.pending is not None:
                    self.audit.append({'state': 'cancelled', 'timecode_sec': obs.timecode_sec})
                self.pending = None
            elif obs.kind == 'employee_exit':
                for rule in CATALOG:
                    if rule['mode'] != 'rule' or not rule['enabled']:
                        continue
                    states = [self.states.get(k) for k in rule['state_events']]
                    fresh = [s for s in states if s and abs(s.timecode_sec - obs.timecode_sec) <= 0.15]
                    if not fresh:
                        continue
                    state = fresh[-1]
                    result.append({
                        'category': rule['type'], 'timecode_sec': obs.timecode_sec,
                        'start_sec': self.pending if self.pending is not None else obs.timecode_sec,
                        'end_sec': obs.timecode_sec,
                        'description': f'{obs.description} {state.description}',
                        'evidence_times': sorted({obs.evidence_time, state.evidence_time}),
                        'origin': 'temporal_rule', 'context_complete': True,
                    })
                self.audit.append({'state': 'exit_confirmed', 'timecode_sec': obs.timecode_sec})
                self.pending = None
                self.states.clear()
            else:
                self.states[obs.kind] = obs
                for rule in CATALOG:
                    if obs.kind in rule['cancel_events']:
                        for state in rule['state_events']:
                            self.states.pop(state, None)
        return result
