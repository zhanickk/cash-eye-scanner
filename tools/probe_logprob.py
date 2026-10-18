"""Score each SFT window by the model's probability of a non-empty list after '{"events":'.

'[]' is a single token, so the decision is ' []' (empty) versus ' [' / ' [{' (an event follows).
"""

import base64
import json
import math
import sys

import httpx

URL = 'http://127.0.0.1:18081/v1/chat/completions'
PREFIX = '{"events":'


def score(row):
    system, user, gold = (m['content'] for m in row['messages'])
    parts = user.split('<image>')
    content = []
    for i, path in enumerate(row['images']):
        content.append({'type': 'text', 'text': parts[i]})
        content.append({'type': 'image_url', 'image_url': {
            'url': 'data:image/jpeg;base64,' + base64.b64encode(open(path, 'rb').read()).decode()}})
    body = httpx.post(URL, json={
        'model': 'qwen3-vl-local', 'max_tokens': 1, 'temperature': 0, 'logprobs': True, 'top_logprobs': 20,
        'add_generation_prompt': False, 'continue_final_message': True,
        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content},
                     {'role': 'assistant', 'content': PREFIX}]}, timeout=180).json()
    top = body['choices'][0]['logprobs']['content'][0]['top_logprobs']
    tokens = [(t['token'].lstrip(), math.exp(t['logprob'])) for t in top]
    p_close = sum(p for tok, p in tokens if tok.startswith('[]'))
    p_open = sum(p for tok, p in tokens if tok.startswith('[') and not tok.startswith('[]'))
    return p_open / (p_open + p_close + 1e-12), bool(json.loads(gold)['events'])


if __name__ == '__main__':
    rows = [json.loads(line) for line in open(sys.argv[1], encoding='utf-8')]
    seen, scored = set(), []
    for row in rows:
        key = tuple(row['images'])
        if key in seen:
            continue
        seen.add(key)
        s, positive = score(row)
        scored.append((s, positive, row['images'][0].split('/frames/')[1].split('/')[0]))
    pos = [s for s, p, _ in scored if p]
    neg = [s for s, p, _ in scored if not p]
    auc = sum((a > b) + 0.5 * (a == b) for a in pos for b in neg) / max(1, len(pos) * len(neg))
    print(json.dumps({'windows': len(scored), 'positives': len(pos), 'auc': round(auc, 3),
                      'pos_scores': sorted(round(s, 4) for s in pos),
                      'neg_top': sorted((round(s, 4) for s in neg), reverse=True)[:10]}))
    json.dump(scored, open(sys.argv[2], 'w'))
