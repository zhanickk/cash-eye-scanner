"""Draft boxes with OWLv2 (Apache-2.0) as Label Studio predictions; people only correct them.

States (open/closed, sitting/standing) are guesses here: the labeller fixes the class.
"""

import argparse
import json
from pathlib import Path

import torch
from PIL import Image
from transformers import Owlv2ForObjectDetection, Owlv2Processor

# text query -> draft class
QUERIES = {
    'a person': 'person',
    'a metal safe cabinet': 'safe_closed',
    'a grey metal box cabinet on the floor': 'safe_closed',
    'an open safe with its door open': 'safe_open',
    'a glass door': 'door_closed',
    'a laptop': 'laptop_open',
    'a stack of banknotes': 'cash',
    'paper money': 'cash',
    'keys': 'keys',
    'an identity card': 'id_document',
    'a money counting machine': 'counting_machine',
    'a plastic bag': 'bag_package',
    'a notebook or journal': 'journal',
    'a rubber stamp': 'stamp',
    'a cup or a bottle': 'drink',
    'a jacket': 'personal_item',
    'a handbag': 'personal_item',
}
THRESHOLDS = {'person': 0.25, 'cash': 0.2, 'keys': 0.2, 'id_document': 0.3, 'safe_closed': 0.12}
# The room has one door and one safe; glass walls otherwise multiply door boxes.
SINGLE = {'door_closed', 'safe_closed', 'safe_open'}
MIN_PERSON_HEIGHT = 0.18  # smaller people are behind the glass, outside the cash room


def iou(a, b):
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    w = max(0, min(ax2, bx2) - max(a[0], b[0]))
    h = max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = w * h
    return inter / (a[2] * a[3] + b[2] * b[3] - inter + 1e-9)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--frames', type=Path, default=Path('private/det/frames'))
    p.add_argument('--index', type=Path, default=Path('private/det/frames.json'))
    p.add_argument('--out', type=Path, default=Path('private/det/ls_tasks.json'))
    p.add_argument('--url-prefix', default='/data/local-files/?d=frames/')
    p.add_argument('--default-threshold', type=float, default=0.3)
    a = p.parse_args()
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    name = 'google/owlv2-base-patch16-ensemble'
    processor = Owlv2Processor.from_pretrained(name)
    model = Owlv2ForObjectDetection.from_pretrained(name).to(device).eval()
    texts = list(QUERIES)
    tasks = []
    for item in json.loads(a.index.read_text(encoding='utf-8')):
        image = Image.open(a.frames / item['file']).convert('RGB')
        w, h = image.size
        inputs = processor(text=[texts], images=image, return_tensors='pt').to(device)
        with torch.no_grad():
            outputs = model(**inputs)
        # OWLv2 pads to a square; boxes are relative to the padded side.
        side = max(w, h)
        result = processor.post_process_grounded_object_detection(
            outputs, threshold=0.15, target_sizes=torch.tensor([[side, side]], device=device))[0]
        boxes = []
        for score, label, box in sorted(zip(result['scores'].tolist(), result['labels'].tolist(), result['boxes'].tolist()), reverse=True):
            cls = QUERIES[texts[label]]
            if score < THRESHOLDS.get(cls, a.default_threshold):
                continue
            x1, y1, x2, y2 = max(0, box[0]), max(0, box[1]), min(w, box[2]), min(h, box[3])
            rect = [x1, y1, x2 - x1, y2 - y1]
            if rect[2] < 4 or rect[3] < 4 or any(iou(rect, b['rect']) > 0.5 for b in boxes):
                continue
            if cls in SINGLE and any(b['cls'] in SINGLE and b['cls'][:4] == cls[:4] for b in boxes):
                continue
            if cls == 'person' and rect[3] < MIN_PERSON_HEIGHT * h:
                continue
            if cls == 'person':
                cls = 'person_standing' if rect[3] / rect[2] > 2.2 else 'person_sitting'
            boxes.append({'cls': cls, 'rect': rect, 'score': score})
        tasks.append({
            'data': {'image': a.url_prefix + item['file'], 'video_id': item['video_id'],
                     'timestamp_sec': item['timestamp_sec'], 'split': item['split']},
            'predictions': [{'model_version': 'owlv2-draft', 'result': [{
                'from_name': 'label', 'to_name': 'image', 'type': 'rectanglelabels',
                'original_width': w, 'original_height': h, 'score': round(b['score'], 3),
                'value': {'x': 100 * b['rect'][0] / w, 'y': 100 * b['rect'][1] / h,
                          'width': 100 * b['rect'][2] / w, 'height': 100 * b['rect'][3] / h,
                          'rotation': 0, 'rectanglelabels': [b['cls']]}} for b in boxes]}]})
    a.out.write_text(json.dumps(tasks, ensure_ascii=False), encoding='utf-8')
    counts = {}
    for t in tasks:
        for r in t['predictions'][0]['result']:
            counts[r['value']['rectanglelabels'][0]] = counts.get(r['value']['rectanglelabels'][0], 0) + 1
    print({'tasks': len(tasks), 'boxes': counts})


if __name__ == '__main__':
    main()
