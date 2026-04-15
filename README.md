# VNPU LLM/VLM Host-Device Workspace

本项目从 `RK3588_LLM/` 拆解重构而来，目标是在 **Host(x86)** 上只做最小包组装，在 **Device(RK3588 aarch64)** 上离线本地编译并运行 benchmark（落盘到 `/userdata`）。

## 目录说明

- `device_template/`: 将被打包并部署到 Device 的最小运行目录模板（Python benchmark + 配置 + 数据 + 脚本）。
- `host_tools/`: Host 侧打包、部署、回传脚本。
- `dist/device_root/`: 由 `host_tools/build_and_stage.sh` 生成的最终部署目录（不入 git）。

## 快速开始 (Host)

1. 初始化子模块（后续会在 `third_party/` 下维护）

```bash
git submodule update --init --recursive
```

2. 组装 Device 本地编译最小包：

```bash
bash host_tools/build_and_stage.sh
```

生成：`dist/device_root/`（包含 `_build_src/`，用于 Device 本地编译官方 demo）。

3. 部署到 Device：

```bash
# 默认部署到 Device 的 /userdata/vnpu_llm
bash host_tools/deploy_to_device.sh

# 或指定 Device 目标目录（传给 pcie_file_share_rc 的路径）
bash host_tools/deploy_to_device.sh vnpu_llm
```

说明：`pcie_file_share_rc set` 的目标路径相对 `/userdata` 解析，
例如传 `vnpu_llm`，Device 实际落盘为 `/userdata/vnpu_llm`。

4. 回传结果到 Host（可选）：

```bash
# 默认拉取 Device 的 /userdata/vnpu_llm/results 到 dist/device_fetch/
bash host_tools/fetch_from_device.sh

# 自定义 device 源目录与 host 目标目录（device 路径同样相对 /userdata）
bash host_tools/fetch_from_device.sh vnpu_llm/logs /tmp/vnpu_logs
```

## Device 侧运行 (串口进入后)

假设已把 `dist/device_root/` 部署到 Device 的 `/userdata/vnpu_llm/`：

```bash
cd /userdata/vnpu_llm

# Device 本地编译官方 demo（默认编译后会删除 _build_src）
bash scripts/build_native_demos.sh

source ./env_setup.sh

# 可选：锁频
sudo bash scripts/fix_freq_rk3588.sh

python3 run_benchmark.py --model all
```

如需保留源码用于二次调试：

```bash
CLEAN_BUILD_SRC=0 bash scripts/build_native_demos.sh
```

## 约束与原则

- Host 侧完全不做交叉编译，仅打包 Device 本地可编译运行最小集。
- Device 运行时不依赖 `third_party/`；仅依赖 `./lib` 内的 `librkllmrt.so`、`librknnrt.so`。
- VLM 采用路线 A：统一使用 `rknn-llm` 官方 `multimodal_model_demo/deploy` demo 作为执行器。
- `rknn_server` 不是本项目 Device 推理必要项。
