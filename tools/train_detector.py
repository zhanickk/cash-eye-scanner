"""Training entry point requires real COCO labels and a separate validation set."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('private/detector-training'))
    parser.add_argument('--epochs', type=int, default=20)
    args = parser.parse_args()
    for split in ['train', 'valid']:
        path = args.dataset / split / '_annotations.coco.json'
        if not path.exists() or not json.loads(path.read_text()).get('images'):
            raise SystemExit(f'Нет размеченного {split}; сначала выполните COCO-экспорт')
    try:
        from rfdetr import RFDETRNano
    except ImportError as exc:
        raise SystemExit('Установите проверенную версию rfdetr в отдельное окружение обучения; см. docs/training.md') from exc
    model = RFDETRNano()
    model.train(dataset_dir=str(args.dataset.resolve()), epochs=args.epochs,
                batch_size=1, grad_accum_steps=4, lr=1e-4, output_dir=str(args.output.resolve()))


if __name__ == '__main__':
    main()
