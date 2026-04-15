#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_ROOT="$ROOT_DIR/_build_src/rknn-llm"
BUILD_ROOT="$ROOT_DIR/.build"

export LD_LIBRARY_PATH="$ROOT_DIR/lib:${LD_LIBRARY_PATH:-}"

JOBS="${JOBS:-$(nproc 2>/dev/null || echo 4)}"
CLEAN_BUILD_DIR="${CLEAN_BUILD_DIR:-1}"
CLEAN_BUILD_SRC="${CLEAN_BUILD_SRC:-1}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: command not found: $cmd" >&2
    exit 1
  fi
}

copy_file() {
  local src="$1"
  local dst="$2"
  if [ ! -f "$src" ]; then
    echo "Error: missing file: $src" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$dst")"
  cp -f "$src" "$dst"
}

build_one() {
  local name="$1"
  local src="$2"
  local build="$3"

  if [ ! -d "$src" ]; then
    echo "Error: source dir not found for $name: $src" >&2
    exit 1
  fi

  if [ "$CLEAN_BUILD_DIR" = "1" ]; then
    rm -rf "$build"
  fi

  cmake -S "$src" -B "$build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON

  cmake --build "$build" --parallel "$JOBS"
}

fix_multimodal_cmake() {
  local cmake_file="$SRC_ROOT/examples/multimodal_model_demo/deploy/CMakeLists.txt"
  if [ ! -f "$cmake_file" ]; then
    return 0
  fi

  # Upstream file contains `include_directories(src/image_enc.h ...)`.
  # `src/image_enc.h` is a file path, not an include directory.
  if grep -q "include_directories(src/image_enc.h" "$cmake_file"; then
    perl -0pi -e 's@include_directories\(src/image_enc\.h\s+\$\{LIBRKNNRT_INCLUDES\}\)@include_directories(src ${LIBRKNNRT_INCLUDES})@g' "$cmake_file"
    echo "[device-build] patched multimodal CMake include path"
  fi
}

require_cmd cmake
require_cmd make
require_cmd g++

if [ ! -d "$SRC_ROOT" ]; then
  echo "Error: build source bundle not found: $SRC_ROOT" >&2
  echo "Run host staging and redeploy first." >&2
  exit 1
fi

mkdir -p "$ROOT_DIR/bin" "$ROOT_DIR/lib" "$BUILD_ROOT"

echo "[device-build] root=$ROOT_DIR"
echo "[device-build] jobs=$JOBS"

LLM_SRC="$SRC_ROOT/examples/rkllm_api_demo/deploy"
LLM_BUILD="$BUILD_ROOT/rkllm_api_demo"
build_one "llm_demo" "$LLM_SRC" "$LLM_BUILD"
copy_file "$LLM_BUILD/llm_demo" "$ROOT_DIR/bin/llm_demo"

VLM_SRC="$SRC_ROOT/examples/multimodal_model_demo/deploy"
VLM_BUILD="$BUILD_ROOT/multimodal_model_demo"
fix_multimodal_cmake
build_one "vlm_demo" "$VLM_SRC" "$VLM_BUILD"
copy_file "$VLM_BUILD/demo" "$ROOT_DIR/bin/vlm_demo"
if [ -f "$VLM_BUILD/imgenc" ]; then
  copy_file "$VLM_BUILD/imgenc" "$ROOT_DIR/bin/imgenc"
fi

copy_file \
  "$SRC_ROOT/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so" \
  "$ROOT_DIR/lib/librkllmrt.so"
copy_file \
  "$SRC_ROOT/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64/librknnrt.so" \
  "$ROOT_DIR/lib/librknnrt.so"

if command -v strip >/dev/null 2>&1; then
  strip "$ROOT_DIR/bin/llm_demo" 2>/dev/null || true
  strip "$ROOT_DIR/bin/vlm_demo" 2>/dev/null || true
  if [ -f "$ROOT_DIR/bin/imgenc" ]; then
    strip "$ROOT_DIR/bin/imgenc" 2>/dev/null || true
  fi
fi

if [ "$CLEAN_BUILD_DIR" = "1" ]; then
  rm -rf "$BUILD_ROOT"
fi

if [ "$CLEAN_BUILD_SRC" = "1" ]; then
  rm -rf "$ROOT_DIR/_build_src"
fi

echo "[device-build] done"
echo "[device-build] binaries: $ROOT_DIR/bin/llm_demo, $ROOT_DIR/bin/vlm_demo"
echo "[device-build] runtime libs: $ROOT_DIR/lib/librkllmrt.so, $ROOT_DIR/lib/librknnrt.so"
