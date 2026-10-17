import importlib
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv('FORTE_DATA_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setenv('FORTE_API_KEY', 'test-key-not-for-production')
    import forte.app as module
    module = importlib.reload(module)
    # Model stub verifies HTTP/job wiring only; it is not model quality evidence.
    monkeypatch.setattr(module, 'analyze_video', lambda path, job_id, progress: {
        'job_id': job_id, 'status': 'done', 'verdict': 'no_violation', 'violations': []})
    yield TestClient(module.app), module
    module.POOL.shutdown(wait=True)


def video_bytes(tmp_path):
    path = tmp_path / 'synthetic.mov'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 10, (64, 64))
    for i in range(10):
        writer.write(np.full((64, 64, 3), i * 10, dtype=np.uint8))
    writer.release()
    return path.read_bytes()


def test_jury_key_required_and_bad_files_rejected(service):
    client, module = service
    assert client.post('/api/v1/analyze', files={'file': ('x.mov', b'not video')}).status_code == 401
    assert client.post('/api/v1/analyze', headers={'X-API-Key': module.API_KEY}, files={'file': ('x.mov', b'not video')}).status_code == 415
    assert not list((module.DATA / 'uploads').iterdir())


def test_jobs_are_scoped_to_browser_and_uploads_deleted(service, tmp_path):
    client, module = service
    owner = client.get('/ui/session').json()['session_token']
    stranger = client.get('/ui/session').json()['session_token']
    response = client.post('/ui/analyze', headers={'X-UI-Session': owner}, files={'file': ('synthetic.mov', video_bytes(tmp_path))})
    assert response.status_code == 202
    job_id = response.json()['job_id']
    assert client.get('/ui/jobs/' + job_id).status_code == 401
    assert client.get('/ui/jobs/' + job_id, headers={'X-UI-Session': stranger}).status_code == 404
    module.POOL.shutdown(wait=True)
    result = client.get('/api/v1/jobs/' + job_id, headers={'X-API-Key': module.API_KEY}).json()
    assert result['status'] == 'done' and result['violations'] == []
    assert not list((module.DATA / 'uploads').iterdir())


def test_model_failure_is_failed_not_no_violation(service, tmp_path, monkeypatch):
    client, module = service
    def fail(*args):
        raise TimeoutError('private path or model response should not leak')
    monkeypatch.setattr(module, 'analyze_video', fail)
    response = client.post('/api/v1/analyze', headers={'X-API-Key': module.API_KEY}, files={'file': ('synthetic.mov', video_bytes(tmp_path))})
    module.POOL.shutdown(wait=True)
    result = client.get('/api/v1/jobs/' + response.json()['job_id'], headers={'X-API-Key': module.API_KEY}).json()
    assert result['status'] == 'failed'
    assert 'verdict' not in result and 'private path' not in result['error']
