#!/bin/sh
# ocr_vlm.py の実験用に、DGX Spark 上で vLLM（NGC コンテナ）を起動し、ヘルスチェックが通るまで待つ。
#
#     serve_vlm.sh <モデル> [vllm serve の追加引数...]
#     例: serve_vlm.sh zai-org/GLM-OCR
#         serve_vlm.sh RedHatAI/Qwen3.6-35B-A3B-NVFP4 --reasoning-parser qwen3
#
# ポートは Spark の localhost だけに開く（外部に公開しない）。
model=$1; shift
docker rm -f ocr-vlm >/dev/null 2>&1
# Spark は CPU と GPU でメモリを共有しており、起動時のメモリ計測が他プロセスの増減で揺れて
# 失敗するので、KV キャッシュの量を固定する。上限も NIM 等と同居できる程度に抑える
docker run -d --name ocr-vlm --gpus all --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 \
  -p 127.0.0.1:30000:30000 -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  nvcr.io/nvidia/vllm:26.10-py3 vllm serve "$model" --served-model-name default \
  --host 0.0.0.0 --port 30000 --kv-cache-memory-bytes 8G --gpu-memory-utilization 0.4 \
  --max-model-len 16384 "$@" >/dev/null
for i in $(seq 1 60); do
  sleep 10
  [ "$(curl -s localhost:30000/health -o /dev/null -w "%{http_code}")" = 200 ] && { echo "ready after $((i*10))s"; exit 0; }
  docker ps -q -f name=ocr-vlm | grep -q . || { echo exited; docker logs ocr-vlm 2>&1 | grep -v "^\s*$" | tail -15; exit 1; }
done
echo timeout; exit 1
