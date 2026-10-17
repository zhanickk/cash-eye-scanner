const DB_NAME = 'forte-annotation-v2';
const API_BASE_KEY = 'forte_api_base_url';
const DEFAULT_API_BASE = 'https://pl9lv4603tade1-8000.proxy.runpod.net';
const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let project = null;

function openProjectDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 2);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains('projects')) req.result.createObjectStore('projects');
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function readProject(db) {
  return new Promise((resolve, reject) => {
    const req = db.transaction('projects').objectStore('projects').get('current');
    req.onsuccess = () => resolve(req.result || {schema_version: 2, videos: []});
    req.onerror = () => reject(req.error);
  });
}

function writeProject(db, value) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('projects', 'readwrite');
    tx.objectStore('projects').put(value, 'current');
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
}

const reviewed = r => ['reviewed_no_violation', 'reviewed_with_violations'].includes(r.status) &&
  (r.events || []).every(e => e.annotation_status === 'confirmed');
const positive = r => r.status === 'reviewed_with_violations' && (r.events || []).length > 0 &&
  (r.events || []).every(e => e.annotation_status === 'confirmed');
const frameComplete = f => f.reviewed === true && Array.isArray(f.objects) && f.objects.length > 0;

function counts() {
  const videos = project.videos || [];
  const train = videos.filter(r => r.split === 'train');
  const valid = videos.filter(r => r.split === 'validation');
  const test = videos.filter(r => r.split === 'test');
  const confirmedEvents = videos.flatMap(r => (r.events || []).filter(e => e.annotation_status === 'confirmed').map(e => ({record: r, event: e})));
  const trainPositives = train.filter(positive);
  const validPositives = valid.filter(positive);
  const detectorFrames = videos.flatMap(r => (r.object_frames || []).filter(frameComplete).map(frame => ({record: r, frame})));
  const trainBoxes = detectorFrames.filter(x => x.record.split === 'train');
  const validBoxes = detectorFrames.filter(x => x.record.split === 'validation');
  const groups = new Map();
  for (const r of videos) {
    const key = r.source_group || r.media?.sha256;
    if (!key || r.split === 'unassigned') continue;
    if (!groups.has(key)) groups.set(key, new Set());
    groups.get(key).add(r.split);
  }
  const leakage = [...groups.values()].some(splits => splits.size > 1);
  return {videos, train, valid, test, confirmedEvents, trainPositives, validPositives, detectorFrames, trainBoxes, validBoxes, leakage};
}

function check(text, ok, note = '') {
  return `<li class="${ok ? 'check-ok' : 'check-wait'}"><span class="check-icon">${ok ? '✓' : '○'}</span><span>${escapeHtml(text)}${note ? `<small>${escapeHtml(note)}</small>` : ''}</span></li>`;
}

function setState(id, ready, text) {
  const el = $(id);
  el.textContent = text;
  el.className = `state-pill ${ready ? 'ready' : 'waiting'}`;
}

function render() {
  const c = counts();
  const reviewedVideos = c.videos.filter(reviewed).length;
  const conflicts = c.videos.filter(r => r.status === 'needs_adjudication' || (r.events || []).some(e => e.annotation_status === 'uncertain')).length;
  $('metric-total').textContent = c.videos.length;
  $('metric-reviewed').textContent = reviewedVideos;
  $('metric-events').textContent = c.confirmedEvents.length;
  $('metric-conflicts').textContent = conflicts;
  $('split-summary').innerHTML = [
    ['Обучение', c.train.length, c.trainPositives.length],
    ['Проверка', c.valid.length, c.validPositives.length],
    ['Итоговый тест', c.test.length, 0],
    ['Не распределено', c.videos.filter(r => !['train','validation','test'].includes(r.split)).length, 0],
  ].map(([label, total, pos]) => `<div class="split-cell"><span>${label}</span><strong>${total}</strong><small>${pos ? `${pos} с подтверждёнными эпизодами` : 'роликов'}</small></div>`).join('');

  const groupOk = !c.leakage;
  const qwenHasMedia = [...c.train, ...c.valid].every(r => r.media?.sha256 && r.media?.filename);
  const reviewedSplits = [...c.train, ...c.valid].every(reviewed);
  const qwenReady = c.train.length > 0 && c.valid.length > 0 && c.trainPositives.length > 0 && c.validPositives.length > 0 && groupOk && qwenHasMedia && reviewedSplits;
  $('qwen-checks').innerHTML = [
    check('Есть размеченные ролики в train и validation', c.train.length > 0 && c.valid.length > 0, `Сейчас: ${c.train.length} / ${c.valid.length}`),
    check('Все ролики в этих двух частях просмотрены полностью', reviewedSplits, reviewedSplits ? 'Неизвестные ролики не попадут в примеры «без нарушений»' : 'Непросмотренные записи нельзя считать отрицательными примерами'),
    check('В обеих частях есть полностью просмотренные ролики с подтверждёнными событиями', c.trainPositives.length > 0 && c.validPositives.length > 0, `Сейчас: ${c.trainPositives.length} / ${c.validPositives.length}`),
    check('Исходные видео совпадают с разметкой по контрольной сумме', qwenHasMedia, qwenHasMedia ? 'Проверка по сохранённым метаданным; сервер перепроверит сами файлы' : 'Нужно привязать оригинальные видео в разметчике'),
    check('Группы исходников не пересекают train и validation', groupOk, groupOk ? 'Дубли и связанные видео остаются в одной части' : 'Перенесите связанные ролики в одну часть'),
    check('Для каждого класса собраны подтверждённые положительные и отрицательные примеры', false, 'Количество примеров показано после разметки; редкие классы нельзя считать обученными по одной записи'),
    check('Финальный тест жюри не используется для обучения', c.test.length >= 0, `${c.test.length} видео в отдельной части test`),
  ].join('');
  setState('qwen-state', qwenReady, qwenReady ? 'Данные готовы' : 'Нужна разметка');
  $('qwen-detail').textContent = `${c.trainPositives.length} train и ${c.validPositives.length} validation роликов с подтверждёнными нарушениями`;
  $('qwen-train-export').disabled = !qwenReady;
  $('qwen-valid-export').disabled = !qwenReady;
  $('qwen-start').disabled = true;
  $('qwen-start').textContent = qwenReady ? 'Сервер обучения не подключён' : 'Обучение пока недоступно';
  $('qwen-train-export').onclick = () => exportSft('train');
  $('qwen-valid-export').onclick = () => exportSft('validation');

  const detectorHasBoth = c.trainBoxes.length > 0 && c.validBoxes.length > 0;
  const detectorReady = detectorHasBoth && groupOk;
  $('detector-checks').innerHTML = [
    check('Кадры с объектами размечены полностью', c.detectorFrames.length > 0, `${c.detectorFrames.length} проверенных кадров`),
    check('Есть проверенные рамки и в train, и в validation', detectorHasBoth, `Сейчас: ${c.trainBoxes.length} / ${c.validBoxes.length} кадров`),
    check('Связанные видео не разделены между частями', groupOk, groupOk ? 'Утечек между частями не найдено' : 'Перенесите связанные ролики в одну часть'),
    check('Каждая рамка точно охватывает нужный видимый объект', false, 'Проверьте пропущенные объекты и неверные рамки вручную'),
    check('Для каждого класса есть примеры в train и validation', false, 'Сверьте распределение классов до запуска обучения'),
  ].join('');
  setState('detector-state', detectorReady, detectorReady ? 'Данные готовы' : 'Нужна разметка');
  $('detector-detail').textContent = `${c.trainBoxes.length} train и ${c.validBoxes.length} validation кадров с рамками`;
  $('detector-start').disabled = true;
  $('detector-start').textContent = detectorReady ? 'Подключите сервер для запуска' : 'Обучение пока недоступно';

  $('training-alert').textContent = c.videos.length
    ? `В проекте ${c.videos.length} видео. Подтверждено ${reviewedVideos} полных просмотров; сейчас обучение заблокировано, пока не будут собраны train/validation и подтверждённые метки.`
    : 'Проект пока пуст. Сначала импортируйте подготовленный JSON разметки или добавьте видео через страницу «Разметка».';
  $('training-alert').classList.toggle('alert-ready', qwenReady || detectorReady);
}

function downloadProject() {
  const file = new Blob([JSON.stringify({...project, exported_at: new Date().toISOString()}, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(file);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'forte_annotations_backup.json';
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportSft(split) {
  const rows = project.videos.filter(r => r.split === split && reviewed(r)).map(r => ({
    messages: [
      {role: 'user', content: '<video>Определи только наблюдаемые признаки возможных нарушений кассовой процедуры. Не делай выводов по невидимым этапам. Ответь JSON с полем violations и полями type, timecode_sec, start_sec, end_sec, description.'},
      {role: 'assistant', content: JSON.stringify({violations: (r.events || []).filter(e => e.annotation_status === 'confirmed').map(e => ({type: e.type, timecode_sec: Number(e.timecode_sec ?? e.start_sec), start_sec: Number(e.start_sec), end_sec: Number(e.end_sec), description: e.description}))})},
    ],
    videos: [r.media.filename],
  }));
  if (!rows.length) return;
  const blob = new Blob([rows.map(row => JSON.stringify(row)).join('\n') + '\n'], {type: 'application/x-ndjson'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${split}.jsonl`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function checkServer() {
  const status = $('server-status');
  let base;
  try {
    const parsed = new URL($('server-url').value.trim());
    if (parsed.protocol !== 'https:') throw new Error('Используйте HTTPS-адрес Pod.');
    base = parsed.origin;
  } catch (error) {
    status.textContent = error.message || 'Укажите корректный HTTPS-адрес.';
    return;
  }
  status.textContent = `Проверяю ${base}…`;
  try {
    const response = await fetch(`${base}/health`, {headers: {Accept: 'application/json'}, cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const health = await response.json();
    status.textContent = `Сервис доступен. Локальная модель: ${health.model_ready ? 'готова' : 'не запущена'}; обученный детектор: ${health.trained_detector_ready ? 'есть' : 'ещё не обучен'}.`;
  } catch (error) {
    status.textContent = `Не удалось связаться с сервером: ${error.message || 'проверьте адрес, доступность Pod и разрешение CORS.'}`;
  }
}

async function initTraining() {
  const savedBase = (() => { try { return localStorage.getItem(API_BASE_KEY); } catch { return null; } })();
  $('server-url').value = (savedBase || DEFAULT_API_BASE).replace(/\/$/, '');
  $('server-check').onclick = checkServer;
  $('server-save').onclick = () => {
    const value = $('server-url').value.trim().replace(/\/$/, '');
    try {
      const parsed = new URL(value);
      if (parsed.protocol !== 'https:') throw new Error('Используйте HTTPS-адрес Pod.');
      localStorage.setItem(API_BASE_KEY, parsed.origin);
      $('server-url').value = parsed.origin;
      $('server-status').textContent = `Адрес сохранён в этом браузере: ${parsed.origin}`;
    } catch (error) {
      $('server-status').textContent = error.message || 'Укажите корректный HTTPS-адрес.';
    }
  };
  try {
    const db = await openProjectDb();
    project = await readProject(db);
    render();
    $('export-project').onclick = downloadProject;
    $('import-project').onchange = async event => {
      try {
        const file = event.target.files?.[0];
        if (!file) return;
        const incoming = JSON.parse(await file.text());
        if (!incoming || !Array.isArray(incoming.videos) || incoming.videos.some(r => typeof r.video_id !== 'string')) {
          throw new Error('Ожидается проект с массивом videos и идентификаторами video_id.');
        }
        if (!window.confirm(`Заменить текущий проект разметки на «${file.name}»? Текущий проект останется только в скачанной резервной копии.`)) return;
        incoming.schema_version = Number(incoming.schema_version) || 2;
        incoming.cameras ||= {};
        for (const r of incoming.videos) {
          r.events ||= [];
          r.object_frames ||= [];
          r.notes ||= [];
          r.split ||= 'unassigned';
          r.status ||= 'unreviewed';
        }
        await writeProject(db, incoming);
        project = incoming;
        render();
        $('training-alert').textContent = `Проект «${file.name}» загружен в локальное хранилище этого браузера.`;
      } catch (error) {
        $('training-alert').textContent = `Импорт не выполнен: ${error.message}`;
      } finally {
        event.target.value = '';
      }
    };
  } catch (error) {
    $('training-alert').textContent = `Не удалось открыть локальный проект в этом браузере: ${error.message || 'проверьте доступ к IndexedDB'}. Разметка с сайта Lovable хранится отдельно; при переносе между сайтами экспортируйте JSON на странице разметки и импортируйте его здесь.`;
  }
}

initTraining();
