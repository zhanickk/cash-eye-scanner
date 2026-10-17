"""Private local inference, authenticated jury API, browser-scoped public UI."""

import hashlib
import json
import os
import secrets
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .analyzer import analyze_video, model_url
from .video_candidates import video_info

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get('FORTE_DATA_DIR', ROOT / 'runtime')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
(DATA / 'uploads').mkdir(exist_ok=True)
KEY_FILE = DATA / 'api_key'
if not KEY_FILE.exists() and not os.environ.get('FORTE_API_KEY'):
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(secrets.token_urlsafe(32))
API_KEY = os.environ.get('FORTE_API_KEY') or KEY_FILE.read_text().strip()
if len(API_KEY) < 16:
    raise RuntimeError('FORTE_API_KEY должен содержать минимум 16 символов')
WORKERS = int(os.environ.get('FORTE_WORKERS', '1'))
SLOTS = BoundedSemaphore(WORKERS)
POOL = ThreadPoolExecutor(max_workers=WORKERS)


def db():
    conn = sqlite3.connect(DATA / 'jobs.sqlite3', timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


with db() as conn:
    conn.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, result TEXT, error TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires REAL NOT NULL)')
    conn.execute("UPDATE jobs SET status='failed', error='Анализ прерван перезапуском сервиса' WHERE status='processing'")

app = FastAPI(title='Forte Vision API', version='0.2.0')
origins = [x.strip() for x in os.environ.get('FORTE_ALLOWED_ORIGINS', '').split(',') if x.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET', 'POST'], allow_headers=['X-API-Key', 'X-UI-Session', 'Content-Type'])
app.mount('/annotation', StaticFiles(directory=ROOT / 'public/annotation', html=True), name='annotation')


def check_key(x_api_key: str | None = Header(default=None)):
    if not x_api_key or not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(401, 'Неверный API-ключ')


def check_session(x_ui_session: str | None = Header(default=None)):
    if not x_ui_session:
        raise HTTPException(401, 'Сессия интерфейса не создана')
    digest = hashlib.sha256(x_ui_session.encode()).hexdigest()
    with db() as conn:
        row = conn.execute('SELECT expires FROM sessions WHERE token_hash=?', (digest,)).fetchone()
    if row is None or row['expires'] < time.time():
        raise HTTPException(401, 'Сессия истекла; обновите страницу')
    return digest


@app.get('/ui/session')
def new_session():
    token = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
        conn.execute('INSERT INTO sessions VALUES (?, ?)', (hashlib.sha256(token.encode()).hexdigest(), time.time() + 12 * 3600))
    return {'session_token': token}


@app.get('/health')
def health():
    try:
        base = model_url().split('/v1/')[0]
        ready = httpx.get(base + '/health', timeout=1, trust_env=False).is_success
    except (httpx.HTTPError, ValueError):
        ready = False
    return {'status': 'ok', 'model_ready': ready, 'trained_detector_ready': False}


def progress(job_id, value, stage):
    with db() as conn:
        conn.execute('UPDATE jobs SET progress=? WHERE id=?', (value, job_id))


def run_job(job_id, path):
    try:
        result = analyze_video(path, job_id, lambda value, stage: progress(job_id, value, stage))
        with db() as conn:
            conn.execute("UPDATE jobs SET status='done', progress=100, result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), job_id))
    except Exception:
        # Do not expose model payloads, paths, network internals or tokens to clients.
        with db() as conn:
            conn.execute("UPDATE jobs SET status='failed', error=? WHERE id=?", ('Анализ не завершён. Проверьте готовность локальной модели и лимит обработки.', job_id))
    finally:
        path.unlink(missing_ok=True)
        SLOTS.release()


async def upload(file, owner):
    if not SLOTS.acquire(blocking=False):
        await file.close()
        raise HTTPException(429, 'Сервис обрабатывает другое видео; повторите позднее')
    job_id = secrets.token_hex(16)
    path = DATA / 'uploads' / f'{job_id}.mov'
    submitted = False
    try:
        if Path(file.filename or '').suffix.lower() != '.mov':
            raise HTTPException(415, 'По ТЗ требуется видео .mov')
        size = 0
        with path.open('wb') as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > int(os.environ.get('FORTE_MAX_UPLOAD_BYTES', str(64 * 1024 * 1024))):
                    raise HTTPException(413, 'Видео превышает ограничение размера')
                target.write(chunk)
        try:
            duration, _ = video_info(path)
        except ValueError as exc:
            raise HTTPException(415, 'Файл не содержит читаемое видео') from exc
        if duration > float(os.environ.get('FORTE_MAX_DURATION_SEC', '180')):
            raise HTTPException(422, 'Видео слишком длинное для текущего лимита обработки')
        with db() as conn:
            conn.execute('INSERT INTO jobs (id,owner,status,created) VALUES (?,?,?,?)', (job_id, owner, 'processing', time.time()))
        POOL.submit(run_job, job_id, path)
        submitted = True
        return {'job_id': job_id, 'status': 'processing'}
    finally:
        await file.close()
        if not submitted:
            path.unlink(missing_ok=True)
            SLOTS.release()


@app.post('/api/v1/analyze', dependencies=[Depends(check_key)], status_code=202)
async def analyze(file: UploadFile = File(...)):
    return await upload(file, 'jury')


@app.post('/ui/analyze', status_code=202)
async def ui_analyze(file: UploadFile = File(...), session=Depends(check_session)):
    return await upload(file, session)


def job(job_id, owner=None):
    with db() as conn:
        row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
    if row is None or (owner is not None and row['owner'] != owner):
        raise HTTPException(404, 'Задача не найдена')
    if row['status'] == 'done':
        return json.loads(row['result'])
    return {'job_id': job_id, 'status': row['status'], 'progress': row['progress'],
            **({'error': row['error']} if row['error'] else {})}


@app.get('/api/v1/jobs/{job_id}', dependencies=[Depends(check_key)])
def api_job(job_id: str):
    return job(job_id)


@app.get('/ui/jobs/{job_id}')
def ui_job(job_id: str, session=Depends(check_session)):
    return job(job_id, session)


@app.get('/ui/rules')
def rules():
    return FileResponse(ROOT / 'config/rules.json')


@app.get('/')
def home():
    return {'service': 'Forte Vision', 'annotation': '/annotation/', 'api_docs': '/docs', 'health': '/health'}
