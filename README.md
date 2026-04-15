# VNPU LLM/VLM Host-Device Workspace

本项目从 `RK3588_LLM/` 拆解重构而来，目标是在 **Host(x86)** 上完成构建与打包，在 **Device(RK3588 aarch64)** 上仅部署最小运行包（落盘到 `/userdata`），完成 LLM/VLM 推理与 Benchmark。

## 目录说明

- `device_template/`: 将被打包并部署到 Device 的最小运行目录模板（Python benchmark + 配置 + 数据 + 脚本）。
- `host_tools/`: Host 侧的交叉编译、打包、（占位）部署脚本。
- `dist/device_root/`: 由 `host_tools/build_and_stage.sh` 生成的最终部署目录（不入 git）。

## 快速开始 (Host)

1. 初始化子模块（后续会在 `third_party/` 下维护）

2. 交叉编译 + 组装部署目录：

```bash
bash host_tools/build_and_stage.sh
```

生成：`dist/device_root/`。

3. 部署（当前 `pcie_file_share_rc` 有问题，脚本保留占位）：

```bash
bash host_tools/deploy_to_device.sh
```

## Device 侧运行 (串口进入后)

假设已把 `dist/device_root/` 部署到 Device 的 `/userdata/vnpu_llm/`：

```bash
cd /userdata/vnpu_llm
source ./env_setup.sh

# 可选：锁频
sudo bash scripts/fix_freq_rk3588.sh

# 可选：如使用 YAML 配置才需要 PyYAML
sudo apt-get update
sudo apt-get install -y python3-yaml

sudo python3 run_benchmark.py --model all
```

## 约束与原则

- Device 侧不包含 `third_party/`。
- Device 运行时仅依赖 `./lib` 内的 `librkllmrt.so`、`librknnrt.so` 与必要的 OpenCV 动态库。
- VLM 采用路线 A：统一使用 `rknn-llm` 官方 `multimodal_model_demo/deploy` demo 作为执行器。
