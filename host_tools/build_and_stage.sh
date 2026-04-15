#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

OUT="$ROOT/out"
DIST="$ROOT/dist/device_root"

echo "[build] root=$ROOT"

mkdir -p "$OUT" "$DIST"

rm -rf "$DIST"
mkdir -p "$DIST/bin" "$DIST/lib" "$DIST/models"

# Stage device runtime tree from this repo only.
if [ ! -d "$ROOT/device_template" ]; then
  echo "Error: device_template missing: $ROOT/device_template" >&2
  exit 1
fi

cp -a "$ROOT/device_template/." "$DIST/"

chmod +x "$DIST/run_benchmark.py" "$DIST/env_setup.sh" 2>/dev/null || true
chmod +x "$DIST/scripts"/*.sh 2>/dev/null || true

# Build/copy demo executables + runtime libs (Host side)
BUILD_DEMOS_DEFAULT=1
BUILD_DEMOS="${BUILD_DEMOS:-$BUILD_DEMOS_DEFAULT}"

# Optional: provide a checkout of rknn-llm sources to cross-build demo binaries.
# Default to third_party in THIS repo (recommended once submodule/vendor lands).
RKNN_LLM_SRC_DEFAULT="$ROOT/third_party/rknn-llm"
RKNN_LLM_SRC="${RKNN_LLM_SRC:-$RKNN_LLM_SRC_DEFAULT}"

TOOLCHAIN_FILE="$ROOT/host_tools/toolchain-aarch64.cmake"

if [ "$BUILD_DEMOS" = "1" ]; then
  if [ ! -f "$TOOLCHAIN_FILE" ]; then
    echo "Error: toolchain file not found: $TOOLCHAIN_FILE" >&2
    exit 1
  fi

  if [ ! -d "$RKNN_LLM_SRC" ]; then
    echo "[build] WARN: RKNN_LLM_SRC not found: $RKNN_LLM_SRC"
    echo "[build]       Set RKNN_LLM_SRC=/path/to/rknn-llm to enable cross-build of demo binaries."
  else
    echo "[build] building demos from: $RKNN_LLM_SRC"

    # Text LLM demo (official rkllm_api_demo)
    LLM_SRC="$RKNN_LLM_SRC/examples/rkllm_api_demo/deploy"
    LLM_BUILD="$OUT/build_rkllm_api_demo"
    if [ -d "$LLM_SRC" ]; then
      rm -rf "$LLM_BUILD"
      cmake -S "$LLM_SRC" -B "$LLM_BUILD" \
        -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_POSITION_INDEPENDENT_CODE=ON
      cmake --build "$LLM_BUILD" --parallel
      if [ -f "$LLM_BUILD/llm_demo" ]; then
        cp -f "$LLM_BUILD/llm_demo" "$DIST/bin/llm_demo"
      fi
    else
      echo "[build] WARN: LLM demo source not found: $LLM_SRC"
    fi

    # VLM demo (official multimodal_model_demo)
    VLM_SRC="$RKNN_LLM_SRC/examples/multimodal_model_demo/deploy"
    VLM_BUILD="$OUT/build_multimodal_model_demo"
    if [ -d "$VLM_SRC" ]; then
      rm -rf "$VLM_BUILD"
      cmake -S "$VLM_SRC" -B "$VLM_BUILD" \
        -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_POSITION_INDEPENDENT_CODE=ON
      cmake --build "$VLM_BUILD" --parallel
      if [ -f "$VLM_BUILD/demo" ]; then
        cp -f "$VLM_BUILD/demo" "$DIST/bin/vlm_demo"
      fi
      if [ -f "$VLM_BUILD/imgenc" ]; then
        cp -f "$VLM_BUILD/imgenc" "$DIST/bin/imgenc"
      fi
    else
      echo "[build] WARN: VLM demo source not found: $VLM_SRC"
    fi

    # Runtime shared libs (ship in ./lib on device)
    RKLLM_RT="$RKNN_LLM_SRC/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so"
    RKNN_RT="$RKNN_LLM_SRC/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64/librknnrt.so"
    if [ -f "$RKLLM_RT" ]; then
      cp -f "$RKLLM_RT" "$DIST/lib/"
    else
      echo "[build] WARN: missing librkllmrt.so at: $RKLLM_RT"
    fi
    if [ -f "$RKNN_RT" ]; then
      cp -f "$RKNN_RT" "$DIST/lib/"
    else
      echo "[build] WARN: missing librknnrt.so at: $RKNN_RT"
    fi

    # Strip binaries if possible (reduces device footprint)
    if command -v aarch64-linux-gnu-strip >/dev/null 2>&1; then
      aarch64-linux-gnu-strip "$DIST/bin"/* 2>/dev/null || true
    fi

    # Make the staged binaries prefer ./lib at runtime.
    # This avoids embedding build-machine paths in RUNPATH/RPATH.
    if command -v patchelf >/dev/null 2>&1; then
      for b in "$DIST/bin"/*; do
        [ -f "$b" ] || continue
        patchelf --set-rpath '\$ORIGIN/../lib' "$b" 2>/dev/null || true
      done
    fi
  fi
fi

echo "[build] staged: $DIST"
if [ ! -f "$DIST/bin/llm_demo" ] || [ ! -f "$DIST/bin/vlm_demo" ]; then
  echo "[build] NOTE: demo binaries not staged (missing rknn-llm sources)." >&2
  echo "[build]       Provide RKNN_LLM_SRC or add third_party/rknn-llm to this repo." >&2
fi
