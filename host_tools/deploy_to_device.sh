#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/dist/device_root"

if [ ! -d "$SRC" ]; then
  echo "Error: staging dir not found: $SRC" >&2
  echo "Run: bash host_tools/build_and_stage.sh" >&2
  exit 1
fi

# TODO: pcie_file_share_rc currently unreliable; keep as placeholder.
# Replace <dst_path> once EP-relative mapping is confirmed.
DEST_PLACEHOLDER="<dst_path>/userdata/vnpu_llm"

echo "[deploy] pcie_file_share_rc --set $SRC $DEST_PLACEHOLDER"
echo "[deploy] (placeholder)" 
