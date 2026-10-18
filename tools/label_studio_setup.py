"""Create the Label Studio project for object boxes, attach local frames and import OWLv2 drafts.

Run after `label-studio start` with LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true and
LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT pointing at the folder that contains `frames/`.
"""

import argparse
import json
import sys
from pathlib import Path

import requests

LABELS = [
    ('person_sitting', 'Человек сидит', '1'), ('person_standing', 'Человек стоит', '2'),
    ('safe_open', 'Сейф открыт', '3'), ('safe_closed', 'Сейф закрыт', '4'),
    ('door_open', 'Дверь открыта', '5'), ('door_closed', 'Дверь закрыта', '6'),
    ('laptop_open', 'Ноутбук открыт', '7'), ('laptop_closed', 'Ноутбук закрыт', '8'),
    ('cash', 'Деньги / пачка', '9'), ('keys', 'Ключи', 'q'), ('id_document', 'Удостоверение', 'w'),
    ('counting_machine', 'Счётный аппарат (большой)', 'e'), ('counting_machine_small', 'Счётный аппарат (малый)', 'r'),
    ('bag_package', 'Пакет / инкассаторская сумка', 't'), ('journal', 'Журнал', 'y'), ('stamp', 'Штамп', 'u'),
    ('drink', 'Напиток', 'i'), ('personal_item', 'Личная вещь (куртка, сумка)', 'o'),
]


def config():
    labels = '\n'.join(f'    <Label value="{v}" alias="{v}" hotkey="{k}" hint="{h}"/>' for v, h, k in LABELS)
    return f'''<View>
  <Header value="$video_id · $timestamp_sec с — обведите ВСЕ видимые объекты этих классов внутри кабинета"/>
  <Image name="image" value="$image" zoom="true" zoomControl="true" rotateControl="false"/>
  <RectangleLabels name="label" toName="image" strokeWidth="2" canRotate="false">
{labels}
  </RectangleLabels>
</View>'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--url', default='http://localhost:8080')
    p.add_argument('--email', required=True)
    p.add_argument('--password', required=True)
    p.add_argument('--root', type=Path, required=True, help='LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT')
    p.add_argument('--tasks', type=Path, required=True)
    a = p.parse_args()
    # Label Studio 1.23 disables legacy API tokens by default; log in like the browser does.
    s = requests.Session()
    s.get(f'{a.url}/user/login/')
    r = s.post(f'{a.url}/user/login/', data={'email': a.email, 'password': a.password,
                                              'csrfmiddlewaretoken': s.cookies.get('csrftoken')},
               headers={'Referer': f'{a.url}/user/login/'}, allow_redirects=False)
    if r.status_code not in (302, 303):
        sys.exit(f'Вход не выполнен (HTTP {r.status_code})')
    s.headers.update({'X-CSRFToken': s.cookies.get('csrftoken'), 'Referer': a.url})
    # Error bodies also carry an 'id' (the error id), so check the HTTP status, not the keys.
    r = s.post(f'{a.url}/api/projects', json={
        'title': 'Forte Vision — объекты', 'label_config': config(),
        'description': 'Исправьте черновые рамки: класс, границы, пропуски. Люди за стеклом не размечаются.',
        'show_collab_predictions': True, 'evaluate_predictions_automatically': False})
    if r.status_code != 201:
        sys.exit(f'Не удалось создать проект: {r.text[:300]}')
    project = r.json()
    r = s.post(f'{a.url}/api/storages/localfiles', json={
        'project': project['id'], 'title': 'frames', 'path': str((a.root / 'frames').resolve()),
        'use_blob_urls': False})
    if r.status_code != 201:
        sys.exit(f'Не удалось подключить кадры (включите LOCAL_FILES_SERVING_ENABLED): {r.text[:300]}')
    tasks = json.loads(a.tasks.read_text(encoding='utf-8'))
    # Train frames first; validation frames are labelled last and only used to measure the detector.
    tasks.sort(key=lambda t: (t['data']['split'] != 'train', t['data']['video_id'], t['data']['timestamp_sec']))
    r = s.post(f"{a.url}/api/projects/{project['id']}/import", json=tasks)
    r.raise_for_status()
    print({'project': project['id'], 'url': f"{a.url}/projects/{project['id']}/data", 'imported': r.json().get('task_count')})


if __name__ == '__main__':
    main()
