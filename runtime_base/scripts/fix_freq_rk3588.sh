#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

for policy in /sys/devices/system/cpu/cpufreq/policy*; do
  echo performance > "$policy/scaling_governor"
done

if [ -e /sys/class/devfreq/dmc/governor ]; then
  echo performance > /sys/class/devfreq/dmc/governor
fi

if [ -e /sys/class/devfreq/fdab0000.npu/governor ]; then
  echo performance > /sys/class/devfreq/fdab0000.npu/governor
fi

if [ -e /sys/class/devfreq/fb000000.gpu/governor ]; then
  echo performance > /sys/class/devfreq/fb000000.gpu/governor
fi

echo "rk3588 frequency governors set to performance"
