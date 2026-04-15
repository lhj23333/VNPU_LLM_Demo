#!/usr/bin/env bash
set -e

# Use local runtime libs first.
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

export LD_LIBRARY_PATH="$ROOT_DIR/lib:${LD_LIBRARY_PATH:-}"
export RKLLM_LOG_LEVEL="1"

# Some demos use OpenCV and may need plugin/config paths. Keep it minimal.
export OPENCV_LOG_LEVEL="ERROR"

echo "[env_setup] LD_LIBRARY_PATH=$LD_LIBRARY_PATH"
