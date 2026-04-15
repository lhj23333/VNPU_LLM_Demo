# Device Runbook

## 串口进入

Host:

```bash
sudo minicom -D /dev/ttyUSB0 -b 1500000
```

## 运行

```bash
cd /userdata/vnpu_llm
source ./env_setup.sh

# 频率设置（可选）
sudo bash scripts/fix_freq_rk3588.sh

# PyYAML（只需一次）
sudo apt-get update
sudo apt-get install -y python3-yaml

sudo python3 run_benchmark.py --model all
```

## 常见检查

- NPU 节点：`ls -l /dev/rknn`（若不存在，底层 NPU 驱动未就绪）
- 依赖缺失：`ldd bin/vlm_demo` / `ldd bin/llm_text_demo`
