#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEVICE_PATH_RAW="${1:-vnpu_llm/results}"
HOST_PATH="${2:-$ROOT/dist/device_fetch}"

normalize_device_path() {
  local p="$1"
  p="${p#/}"
  p="${p#userdata/}"
  p="${p#userdata}"
  p="${p#/}"
  printf '%s' "$p"
}

DEVICE_PATH="$(normalize_device_path "$DEVICE_PATH_RAW")"
DEVICE_ABS_PATH="/userdata/$DEVICE_PATH"

if [ -z "$DEVICE_PATH" ]; then
  echo "Error: invalid device path: '$DEVICE_PATH_RAW'" >&2
  exit 1
fi

if ! command -v pcie_file_share_rc >/dev/null 2>&1; then
  echo "Error: pcie_file_share_rc not found in PATH." >&2
  exit 1
fi

mkdir -p "$HOST_PATH"

echo "[fetch] src(arg)=$DEVICE_PATH_RAW"
echo "[fetch] src(pcie)=$DEVICE_PATH"
echo "[fetch] src(device)=$DEVICE_ABS_PATH"
echo "[fetch] dst(host)=$HOST_PATH"

if pcie_file_share_rc get "$DEVICE_PATH" "$HOST_PATH"; then
  echo "[fetch] done (pcie_file_share_rc get, normalized path)"
  exit 0
fi

echo "[fetch] WARN: normalized 'get' failed, retry with '--get'." >&2
if pcie_file_share_rc --get "$DEVICE_PATH" "$HOST_PATH"; then
  echo "[fetch] done (pcie_file_share_rc --get, normalized path)"
  exit 0
fi

if [ "$DEVICE_PATH_RAW" != "$DEVICE_PATH" ]; then
  echo "[fetch] WARN: normalized path failed, retry with raw arg='$DEVICE_PATH_RAW'." >&2
  if pcie_file_share_rc get "$DEVICE_PATH_RAW" "$HOST_PATH"; then
    echo "[fetch] done (pcie_file_share_rc get, raw path)"
    exit 0
  fi

  echo "[fetch] WARN: raw 'get' failed, retry with '--get'." >&2
  if pcie_file_share_rc --get "$DEVICE_PATH_RAW" "$HOST_PATH"; then
    echo "[fetch] done (pcie_file_share_rc --get, raw path)"
    exit 0
  fi
fi

echo "[fetch] Error: pcie_file_share_rc get failed for both normalized and raw paths." >&2
exit 1
