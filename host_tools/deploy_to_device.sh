#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/dist/device_root"
DEST_PATH_RAW="${1:-vnpu_llm}"

normalize_device_path() {
  local p="$1"
  p="${p#/}"
  p="${p#userdata/}"
  p="${p#userdata}"
  p="${p#/}"
  printf '%s' "$p"
}

DEST_PATH="$(normalize_device_path "$DEST_PATH_RAW")"
DEVICE_ABS_PATH="/userdata/$DEST_PATH"

if [ -z "$DEST_PATH" ]; then
  echo "Error: invalid destination path: '$DEST_PATH_RAW'" >&2
  exit 1
fi

if [ ! -d "$SRC" ]; then
  echo "Error: staging dir not found: $SRC" >&2
  echo "Run: bash host_tools/build_and_stage.sh" >&2
  exit 1
fi

if ! command -v pcie_file_share_rc >/dev/null 2>&1; then
  echo "Error: pcie_file_share_rc not found in PATH." >&2
  exit 1
fi

echo "[deploy] src=$SRC"
echo "[deploy] dst(arg)=$DEST_PATH_RAW"
echo "[deploy] dst(pcie)=$DEST_PATH"
echo "[deploy] dst(device)=$DEVICE_ABS_PATH"

if pcie_file_share_rc set "$SRC" "$DEST_PATH"; then
  echo "[deploy] done (pcie_file_share_rc set, normalized path)"
  exit 0
fi

echo "[deploy] WARN: normalized 'set' failed, retry with '--set'." >&2
if pcie_file_share_rc --set "$SRC" "$DEST_PATH"; then
  echo "[deploy] done (pcie_file_share_rc --set, normalized path)"
  exit 0
fi

if [ "$DEST_PATH_RAW" != "$DEST_PATH" ]; then
  echo "[deploy] WARN: normalized path failed, retry with raw arg='$DEST_PATH_RAW'." >&2
  if pcie_file_share_rc set "$SRC" "$DEST_PATH_RAW"; then
    echo "[deploy] done (pcie_file_share_rc set, raw path)"
    exit 0
  fi

  echo "[deploy] WARN: raw 'set' failed, retry with '--set'." >&2
  if pcie_file_share_rc --set "$SRC" "$DEST_PATH_RAW"; then
    echo "[deploy] done (pcie_file_share_rc --set, raw path)"
    exit 0
  fi
fi

echo "[deploy] Error: pcie_file_share_rc set failed for both normalized and raw paths." >&2
exit 1
