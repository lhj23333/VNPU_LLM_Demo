#!/usr/bin/env bash
# Build llm_demo / vlm_demo on the device from staged third-party sources (_build_src).
# Host `build-runtime-base` (without --llm-demo/--vlm-demo) packs sources + aarch64 libs;
# run this script once on the board before starting device_executor.
# Rebuild after changing demo sources (e.g. VNPU_LLM_INITDRAM_GATE in main.cpp / llm_demo.cpp for Init DRAM sampling).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_ROOT="$ROOT_DIR/_build_src/rknn-llm"
NATIVE_ROOT="$ROOT_DIR/_native_build"

if [[ ! -d "$SRC_ROOT/examples/rkllm_api_demo/deploy" ]]; then
  echo "error: missing $SRC_ROOT — deploy a fresh runtime_base from host (python3 -m host_control build-runtime-base)." >&2
  exit 1
fi

arch="$(uname -m)"
if [[ "$arch" != "aarch64" && "$arch" != "arm64" ]]; then
  echo "error: this script must run on the device (aarch64). Current machine: $arch" >&2
  exit 1
fi

mkdir -p "$ROOT_DIR/bin" "$NATIVE_ROOT"

echo "[build_demos] LLM demo (rkllm_api_demo)..."
LLM_SRC="$SRC_ROOT/examples/rkllm_api_demo/deploy"
LLM_B="$NATIVE_ROOT/llm_demo"
cmake -S "$LLM_SRC" -B "$LLM_B" -DCMAKE_BUILD_TYPE=Release
cmake --build "$LLM_B" -j"$(nproc)"
install -m0755 "$LLM_B/llm_demo" "$ROOT_DIR/bin/llm_demo"

echo "[build_demos] VLM demo (multimodal_model_demo → vlm_demo)..."
VLM_SRC="$SRC_ROOT/examples/multimodal_model_demo/deploy"
VLM_B="$NATIVE_ROOT/multimodal_demo"
cmake -S "$VLM_SRC" -B "$VLM_B" -DCMAKE_BUILD_TYPE=Release
cmake --build "$VLM_B" -j"$(nproc)"
# Upstream target name is "demo" (see deploy/CMakeLists project(demo))
install -m0755 "$VLM_B/demo" "$ROOT_DIR/bin/vlm_demo"

echo "[build_demos] done: $ROOT_DIR/bin/llm_demo $ROOT_DIR/bin/vlm_demo"
