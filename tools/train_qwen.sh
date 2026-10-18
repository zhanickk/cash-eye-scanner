#!/usr/bin/env bash
# LoRA for Qwen3-VL-2B on windows built by tools/build_sft_clips.py, then merge for vLLM.
# Usage: QWEN_HF_MODEL_DIR=/workspace/models/hf/Qwen3-VL-2B-Instruct tools/train_qwen.sh private/sft private/qwen-lora
set -euo pipefail
dataset_dir="${1:-private/sft}"
output_dir="${2:-private/qwen-lora}"
model_dir="${QWEN_HF_MODEL_DIR:?Укажите каталог исходных HF-весов через QWEN_HF_MODEL_DIR}"
swift_bin="${SWIFT_BIN:-swift}"
for file in "$dataset_dir/train.jsonl" "$dataset_dir/validation.jsonl"; do
  test -s "$file" || { printf 'Нет набора %s; сначала tools/build_sft_clips.py\n' "$file" >&2; exit 1; }
done
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
# 464x848 frames are ~364 visual tokens; the cap keeps any other resolution in budget.
export IMAGE_MAX_TOKEN_NUM="${IMAGE_MAX_TOKEN_NUM:-400}"
"$swift_bin" sft \
  --model "$model_dir" \
  --tuner_type lora \
  --torch_dtype bfloat16 \
  --dataset "$dataset_dir/train.jsonl" \
  --val_dataset "$dataset_dir/validation.jsonl" \
  --split_dataset_ratio 0 \
  --num_train_epochs "${EPOCHS:-3}" \
  --per_device_train_batch_size 1 \
  --per_device_eval_batch_size 1 \
  --gradient_accumulation_steps 8 \
  --learning_rate "${LR:-1e-4}" \
  --warmup_ratio 0.05 \
  --lora_rank 16 --lora_alpha 32 --lora_dropout 0.05 \
  --target_modules all-linear \
  --freeze_vit true \
  --freeze_aligner true \
  --gradient_checkpointing true \
  --max_length 10240 \
  --eval_steps 20 --save_steps 20 --save_total_limit 4 --logging_steps 5 \
  --load_best_model_at_end true --metric_for_best_model loss \
  --dataloader_num_workers 4 \
  --output_dir "$output_dir"
best="$(ls -d "$output_dir"/*/checkpoint-* | sort -V | tail -1)"
best="$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1]+"/trainer_state.json")); print(s.get("best_model_checkpoint") or sys.argv[1])' "$best")"
"$swift_bin" export --adapters "$best" --merge_lora true --output_dir "$output_dir/merged"
printf 'Готово: %s\n' "$output_dir/merged"
