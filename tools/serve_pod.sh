#!/usr/bin/env bash
# Start (or restart) vLLM with the given Qwen3-VL weights and the Forte API on :8000.
# Usage: tools/serve_pod.sh /path/to/model-dir
# Keeps the jury API key and job history in FORTE_DATA_DIR (default: the original runtime dir).
set -euo pipefail
cd "$(dirname "$0")/.."
model="${1:?Укажите каталог весов модели}"
venv="${QWEN_VENV:-/workspace/.venvs/qwen}"
logs="${LOG_DIR:-/workspace/logs}"
export FORTE_DATA_DIR="${FORTE_DATA_DIR:-/workspace/cash-eye-scanner/runtime}"
export QWEN_CHAT_URL="http://127.0.0.1:18081/v1/chat/completions" QWEN_MODEL_NAME="qwen3-vl-local"
export FORTE_MAX_DURATION_SEC="${FORTE_MAX_DURATION_SEC:-180}" FORTE_MAX_UPLOAD_BYTES="${FORTE_MAX_UPLOAD_BYTES:-67108864}"
export FORTE_WORKERS=1 FORTE_ALLOWED_ORIGINS="${FORTE_ALLOWED_ORIGINS:-https://cash-eye-scanner.lovable.app}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
# vLLM compiles kernels with ninja from the same venv.
export PATH="$venv/bin:$PATH"

pkill -f "vllm serve" || true
pkill -f "uvicorn forte.app:app" || true
sleep 5
nohup "$venv/bin/vllm" serve "$model" --served-model-name qwen3-vl-local --host 127.0.0.1 --port 18081 \
  --dtype bfloat16 --max-model-len 16384 --gpu-memory-utilization 0.80 \
  > "$logs/qwen-vllm.log" 2>&1 < /dev/null &
echo $! > "$logs/qwen-vllm.pid"
for _ in $(seq 120); do
  curl -sf http://127.0.0.1:18081/health >/dev/null && break
  sleep 5
done
curl -sf http://127.0.0.1:18081/health >/dev/null || { echo "vLLM не поднялся, см. $logs/qwen-vllm.log" >&2; exit 1; }
nohup "$venv/bin/uvicorn" forte.app:app --app-dir backend --host 0.0.0.0 --port 8000 \
  > "$logs/forte-api.log" 2>&1 < /dev/null &
echo $! > "$logs/forte-api.pid"
sleep 5
curl -s http://127.0.0.1:8000/health
echo
