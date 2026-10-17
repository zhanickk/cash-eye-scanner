import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from export_dataset import audit, export_sft


def test_duplicate_source_cannot_cross_splits():
    project = {'videos': [
        {'video_id': 'A', 'source_group': 'same', 'split': 'train'},
        {'video_id': 'B', 'source_group': 'same', 'split': 'validation'},
    ]}
    assert any('разные части' in p for p in audit(project))


def test_source_notes_and_test_videos_cannot_become_training_samples(tmp_path):
    project = {'videos': [
        {'video_id': 'A', 'split': 'train', 'source_label': 'violation', 'status': 'unreviewed', 'notes': [{'time_sec': 3}]},
        {'video_id': 'B', 'split': 'test', 'status': 'reviewed_no_violation'},
    ]}
    with pytest.raises(ValueError):
        export_sft(project, tmp_path)
    assert not list(tmp_path.glob('*.jsonl'))
