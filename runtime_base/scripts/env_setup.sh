#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

export LD_LIBRARY_PATH="$ROOT_DIR/lib:${LD_LIBRARY_PATH:-}"
export RKLLM_LOG_LEVEL="1"

echo "[env_setup] LD_LIBRARY_PATH=$LD_LIBRARY_PATH"
