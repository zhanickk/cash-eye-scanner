#!/usr/bin/env bash
set -euo pipefail
dataset_dir="${1:-private/exports/sft}"
model_dir="${QWEN_HF_MODEL_DIR:?Укажите каталог исходных HF-весов через QWEN_HF_MODEL_DIR; GGUF для этого обучения не используется}"
for file in "$dataset_dir/train.jsonl" "$dataset_dir/validation.jsonl"; do
  test -s "$file" || { printf 'Нет подтверждённого набора %s\n' "$file" >&2; exit 1; }
done
command -v swift >/dev/null || { printf 'Нужен CLI ms-swift из Python-окружения обучения\n' >&2; exit 1; }
# macOS also has a compiler named swift; this entry point runs on the training pod.
swift sft --help >/dev/null
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
IMAGE_MAX_TOKEN_NUM=1024 swift sft \
  --model "$model_dir" \
  --tuner_type lora \
  --torch_dtype bfloat16 \
  --dataset "$dataset_dir/train.jsonl" \
  --val_dataset "$dataset_dir/validation.jsonl" \
  --num_train_epochs 2 \
  --per_device_train_batch_size 1 \
  --per_device_eval_batch_size 1 \
  --gradient_accumulation_steps 8 \
  --learning_rate 1e-4 \
  --lora_rank 8 --lora_alpha 16 \
  --target_modules all-linear \
  --freeze_vit true \
  --freeze_aligner true \
  --gradient_checkpointing true \
  --max_length 8192 \
  --eval_steps 20 --save_steps 20 \
  --output_dir private/qwen-lora
