#!/bin/bash

echo "=================================================="
echo "  RK3588 RAM & NPU Monitor"
echo "  Press Ctrl+C to stop"
echo "=================================================="

while true; do
  echo "--- $(date '+%Y-%m-%d %H:%M:%S') ---"

  free -h | grep -E "total|Mem"

  if [ -e /sys/kernel/debug/rknpu/load ]; then
    echo "NPU Load:"
    cat /sys/kernel/debug/rknpu/load
  else
    echo "NPU Load: [Unavailable - requires root or debugfs]"
  fi

  echo ""
  sleep 2
done
