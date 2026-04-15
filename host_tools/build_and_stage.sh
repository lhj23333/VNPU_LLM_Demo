#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist/device_root"
BUILD_SRC_ROOT="$DIST/_build_src/rknn-llm"

# Host only stages a minimal device-native build package.
# No host-side cross compilation is performed.
RKNN_LLM_SRC_DEFAULT="$ROOT/third_party/rknn-llm"
RKNN_LLM_SRC="${RKNN_LLM_SRC:-$RKNN_LLM_SRC_DEFAULT}"

echo "[stage] root=$ROOT"
echo "[stage] dist=$DIST"

copy_tree() {
  local src="$1"
  local dst="$2"
  if [ ! -d "$src" ]; then
    echo "Error: source directory missing: $src" >&2
    exit 1
  fi
  mkdir -p "$dst"
  cp -a "$src/." "$dst/"
}

copy_file() {
  local src="$1"
  local dst="$2"
  if [ ! -f "$src" ]; then
    echo "Error: source file missing: $src" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$dst")"
  cp -a "$src" "$dst"
}

patch_multimodal_cmake_include() {
  local cmake_file="$1"
  if [ ! -f "$cmake_file" ]; then
    echo "Error: CMake file missing for patch: $cmake_file" >&2
    exit 1
  fi

  # Upstream uses `include_directories(src/image_enc.h ...)`,
  # which passes a header file as an include directory and causes warnings.
  perl -0pi -e 's@include_directories\(src/image_enc\.h\s+\$\{LIBRKNNRT_INCLUDES\}\)@include_directories(src \${LIBRKNNRT_INCLUDES})@g' "$cmake_file"
}

rm -rf "$DIST"
mkdir -p "$DIST/bin" "$DIST/lib" "$DIST/models"

# Stage device runtime tree from this repo only.
if [ ! -d "$ROOT/device_template" ]; then
  echo "Error: device_template missing: $ROOT/device_template" >&2
  exit 1
fi

if [ ! -d "$RKNN_LLM_SRC" ]; then
  echo "Error: RKNN LLM source not found: $RKNN_LLM_SRC" >&2
  echo "Hint: init submodule first: git submodule update --init --recursive" >&2
  exit 1
fi

cp -a "$ROOT/device_template/." "$DIST/"

chmod +x "$DIST/run_benchmark.py" "$DIST/env_setup.sh" 2>/dev/null || true
chmod +x "$DIST/scripts"/*.sh 2>/dev/null || true

echo "[stage] collecting minimal device build sources from: $RKNN_LLM_SRC"

# 1) Text demo source (official rkllm_api_demo/deploy)
copy_file \
  "$RKNN_LLM_SRC/examples/rkllm_api_demo/deploy/CMakeLists.txt" \
  "$BUILD_SRC_ROOT/examples/rkllm_api_demo/deploy/CMakeLists.txt"
copy_tree \
  "$RKNN_LLM_SRC/examples/rkllm_api_demo/deploy/src" \
  "$BUILD_SRC_ROOT/examples/rkllm_api_demo/deploy/src"

# 2) Multimodal demo source (official multimodal_model_demo/deploy)
copy_file \
  "$RKNN_LLM_SRC/examples/multimodal_model_demo/deploy/CMakeLists.txt" \
  "$BUILD_SRC_ROOT/examples/multimodal_model_demo/deploy/CMakeLists.txt"
patch_multimodal_cmake_include \
  "$BUILD_SRC_ROOT/examples/multimodal_model_demo/deploy/CMakeLists.txt"
copy_file \
  "$RKNN_LLM_SRC/examples/multimodal_model_demo/deploy/c_export.map" \
  "$BUILD_SRC_ROOT/examples/multimodal_model_demo/deploy/c_export.map"
copy_tree \
  "$RKNN_LLM_SRC/examples/multimodal_model_demo/deploy/src" \
  "$BUILD_SRC_ROOT/examples/multimodal_model_demo/deploy/src"

# 3) Runtime/build dependencies required by deploy CMakeLists
copy_tree \
  "$RKNN_LLM_SRC/examples/multimodal_model_demo/deploy/3rdparty/opencv/opencv-linux-aarch64" \
  "$BUILD_SRC_ROOT/examples/multimodal_model_demo/deploy/3rdparty/opencv/opencv-linux-aarch64"
copy_tree \
  "$RKNN_LLM_SRC/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/include" \
  "$BUILD_SRC_ROOT/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/include"
copy_tree \
  "$RKNN_LLM_SRC/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64" \
  "$BUILD_SRC_ROOT/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64"
copy_tree \
  "$RKNN_LLM_SRC/rkllm-runtime/Linux/librkllm_api/include" \
  "$BUILD_SRC_ROOT/rkllm-runtime/Linux/librkllm_api/include"
copy_tree \
  "$RKNN_LLM_SRC/rkllm-runtime/Linux/librkllm_api/aarch64" \
  "$BUILD_SRC_ROOT/rkllm-runtime/Linux/librkllm_api/aarch64"

# Pre-stage runtime shared libraries to ./lib for device runtime.
copy_file \
  "$BUILD_SRC_ROOT/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so" \
  "$DIST/lib/librkllmrt.so"
copy_file \
  "$BUILD_SRC_ROOT/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64/librknnrt.so" \
  "$DIST/lib/librknnrt.so"

echo "[stage] staged minimal package: $DIST"
echo "[stage] next on device: bash scripts/build_native_demos.sh"
