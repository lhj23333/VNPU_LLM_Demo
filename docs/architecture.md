# Architecture

## 目标

- Host(x86): 拉取完整源码与 third_party，打包 Device 本地可编译最小目录。
- Device(RK3588 aarch64): 在 `/userdata` 离线本地编译官方 demo 并运行 benchmark。

## 运行时目录（Device）

`device_root/`（部署后目录）包含：

- `bin/`: 编译后产物
  - `llm_demo`
  - `vlm_demo`（来自 `rknn-llm/examples/multimodal_model_demo/deploy`）
- `lib/`: 运行时动态库（`librkllmrt.so`、`librknnrt.so`）
- `_build_src/`: Device 本地编译最小源码集（`scripts/build_native_demos.sh` 使用，默认编译后删除）
- `models/`: 模型文件（`.rkllm` / `.rknn`）
- `benchmark/` + `conf/` + `data/` + `scripts/` + `run_benchmark.py`

## Benchmark 引擎改造点

- 旧仓库在 Python 侧硬编码从 `third_party/.../aarch64` 加载 `.so`。
- 新仓库改为默认从部署目录 `./lib` 加载：
  - `LD_LIBRARY_PATH=$PWD/lib:$LD_LIBRARY_PATH`
  - 运行时不依赖 third_party。

## 编译策略

- 完全废弃 Host 交叉编译流程。
- Host 只打包 Device 所需最小源码与依赖。
- Device 使用本地 `g++/cmake/make` 编译官方 demo，规避 glibc 版本不匹配。
