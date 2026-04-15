# Architecture

## 目标

- Host(x86): 拉取完整源码与 third_party，交叉编译生成 aarch64 可执行文件，打包最小运行目录。
- Device(RK3588 aarch64): 仅运行最小包，落盘到 `/userdata`，不编译、不携带 third_party。

## 运行时目录（Device）

`device_root/`（部署后目录）包含：

- `bin/`: aarch64 可执行文件
  - `llm_text_demo`
  - `vlm_demo` (来自 `rknn-llm/examples/multimodal_model_demo/deploy`)
- `lib/`: 运行时动态库
  - `librkllmrt.so`
  - `librknnrt.so`
  - `libopencv_*.so.*`（仅 VLM 需要）
- `models/`: 模型文件（`.rkllm` / `.rknn`）
- `benchmark/` + `conf/` + `data/` + `scripts/` + `run_benchmark.py`

## Benchmark 引擎改造点

- 旧仓库在 Python 侧硬编码从 `third_party/.../aarch64` 加载 `.so`。
- 新仓库改为默认从部署目录 `./lib` 加载：
  - `LD_LIBRARY_PATH=$PWD/lib:$LD_LIBRARY_PATH`
  - 运行时不依赖 third_party。
