# VNPU LLM / VLM Host–Device 推理与 Benchmark 框架

本仓库在 **RK3588 等板端 NPU** 上，以 **Host 控制端 / Device 执行端** 分离架构运行 RKLLM / RKNN 推理：Device 侧仅保留最小 **Runtime Base**（`llm_demo`、`vlm_demo`、运行时库与 `device_executor`），Host 侧负责任务编排、资源下发（PCIe 文件通道）、UART 粗粒度指令、遥测采集与 **Benchmark 报告** 生成。架构契约与模块边界以 [docs/VNPU_LLM_Demo_Host_Device_Architecture_Design.md](docs/VNPU_LLM_Demo_Host_Device_Architecture_Design.md) 为唯一标准。

---

## 1. 项目结构 (Project Structure)

```text
VNPU_LLM_Demo/
├── README.md                 # 本说明与快速开始
├── requirements.txt          # Host 侧 Python 依赖（pyserial 等）
├── tools/
│   └── run_infer_e2e.sh      # 一键 E2E：组 request、上传会话、UART 触发、拉日志、汇总
├── host_control/             # Host 控制面：CLI、任务包构造、推送/拉取、UART、采集与报告
│   ├── benchmark_assets/     # Host 持有的 prompts、图片、模型配置模板等
│   │   ├── prompts/
│   │   ├── configs/
│   │   └── images/
│   └── …                     # cli.py、task_bundle_builder、runtime_collector 等
├── runtime_base/             # Device Runtime Base 源码树，打包输出到 dist/runtime_base/
│   ├── executor/             # device_executor、task_loader、telemetry 等
│   └── scripts/              # env_setup.sh、fix_freq_rk3588.sh、build_demos_on_device.sh
├── docs/
│   ├── VNPU_LLM_Demo_Host_Device_Architecture_Design.md  # Host/Device 架构设计（定稿）
│   └── device_runbook.md     # 板端目录布局、executor 启动、会话契约、UART 协议摘要
├── third_party/
│   └── rknn-llm/             # Git 子模块：板端 CMake 构建 demo 所需源码与头文件
├── dist/                     # `build-runtime-base` 产物（默认被 .gitignore，仅本地存在）
├── host/tasks/               # `build-task-*` 生成的任务包目录（默认不进版本库）
└── results/                  # 采集的 task_result.json、logs、summary、benchmark_report.md（默认不进版本库）
```

---

## 2. 硬件与链路环境 (Environment)

*   **Device（执行端）**: 典型为 **Rockchip RK3588** 类开发板，已部署 RKLLM / RKNN 运行时与 NPU 驱动；板端需能运行 Python 3 与 `device_executor`。
*   **Host（控制端）**: 与板端通过 **UART**（任务启停与遥测）及 **PCIe 文件共享**（如 `pcie_file_share_rc`，会话目录 `vnpu_llm/sessions/<task_id>` 与 `vnpu_llm/runtime_base`）交互的开发机或同一套环境中的上位机。
*   **性能建议**: 跑分或对比实验前，可在板端执行 `sudo bash scripts/fix_freq_rk3588.sh`，将 CPU / DDR / NPU / GPU 置于稳定高性能策略（与 RK3588_LLM 仓库习惯一致）。

具体板端目录、executor 启动参数与 UART JSON 行协议，见 [docs/device_runbook.md](docs/device_runbook.md)。

---

## 3. 测试结果快速预览 (Benchmark Preview)

以下片段摘自 Host 自动汇总生成的 [results/benchmark_report.md](results/benchmark_report.md)（运行后由 `host_control` 写入；仓库内文件随本地跑分更新，**非固定成绩**）。完整表格与字段说明以该文件为准。

<!-- | 模型名称 (Model) | Context | NPU Core | 初始显存 (Weights+KV) | Runtime Buffer | 峰值显存 (Peak) | 生成速度 (TPS) | 状态 |
| :--- | :---: | :---: | :--- | :--- | :--- | :---: | :--- |
| **Qwen3-0.6B** | 4096 | 3 | ~1223.6 MB | ~5.2 MB | ~1228.8 MB | **29.43** | finished |
| **Intern3.5-VL-1B** | 4096 | 3 | ~1875.8 MB | ~8.3 MB | ~1884.2 MB | **13.76** | finished | -->

---

## 4. 快速开始 (Quick Start)

### 第一步：克隆仓库并初始化子模块

板端 `build_demos_on_device.sh` 依赖 staged 的 `rknn-llm` 源码，请递归拉取子模块：

```bash
git clone https://github.com/lhj23333/VNPU_LLM_Demo.git
cd VNPU_LLM_Demo

git submodule update --init --recursive
```

### 第二步：安装 Host 侧依赖

```bash
python3 -m pip install -r requirements.txt
```

另需环境中已安装并可调用 **`pcie_file_share_rc`**（与 `host_control` 推送/拉取会话目录配套）。仅使用 `uart` 子命令、且不依赖 PCIe 的流程时，可按需省略。

### 第三步：打包 Device Runtime Base

默认不嵌入预编译 demo，仅打包库、executor、脚本与 `_build_src`；**首次**在板端进入 `runtime_base` 执行 `scripts/build_demos_on_device.sh` 生成 `bin/llm_demo` 与 `bin/vlm_demo`。

```bash
python3 -m host_control build-runtime-base
```

若本机已有交叉编译产物，可显式嵌入（路径须真实存在）：

```bash
python3 -m host_control build-runtime-base \
  --llm-demo /abs/path/to/llm_demo \
  --vlm-demo /abs/path/to/vlm_demo
```

产物目录：**`dist/runtime_base/`**。

### 第四步：板端启动 Executor（Device）

将 `dist/runtime_base/` 部署到板端约定路径（如 `/userdata/vnpu_llm/runtime_base`），然后：

```bash
cd /userdata/vnpu_llm/runtime_base
source ./scripts/env_setup.sh
python3 executor/device_executor.py --stdio-loop --sessions-root /userdata/vnpu_llm/sessions
```

详细布局与可选 `fix_freq_rk3588.sh` 步骤见 [docs/device_runbook.md](docs/device_runbook.md)。

### 第五步：Host 一键 E2E（推荐）

通过 **`tools/run_infer_e2e.sh`** 完成：生成 `request.json`、经 PCIe 上传到 `vnpu_llm/sessions/<task_id>`、UART `run_task`、采集遥测、拉回 `logs/`、可选生成 Markdown 报告（避免在 `host/tasks/` 下重复暂存大模型/图片的纯手动流程）。

**LLM 单次：**

```bash
tools/run_infer_e2e.sh llm_single \
  --llm-model-src /abs/path/to/model.rkllm \
  --prompt "你好，请自我介绍一下。"
```

**VLM 单次：**

```bash
tools/run_infer_e2e.sh vlm_single \
  --llm-model-src /abs/path/to/model.rkllm \
  --vision-model-src /abs/path/to/vision.rknn \
  --image-src /abs/path/to/image.jpg \
  --prompt "Describe this image."
```

**Benchmark 批任务（Host 侧构造 `benchmark_batch`）：**

```bash
tools/run_infer_e2e.sh benchmark_batch \
  --llm-model-src /abs/path/to/model.rkllm \
  --vision-model-src /abs/path/to/vision.rknn \
  --include-text --include-vlm
```

常用参数：`--task-id`、`--port /dev/ttyUSB0 --baudrate 1500000`、`--collect-seconds 240`、`--cleanup-on-device`、`--no-summarize`。完整说明：

```bash
tools/run_infer_e2e.sh --help
```

### 第六步：等价 CLI 流程（手动拆分）

统一入口：

```bash
python3 -m host_control --help
```

典型顺序：`build-task-llm` / `build-task-vlm` / `build-task-benchmark` → `push`（runtime_base 与 `host/tasks/<id>`）→ `uart run_task` → `pull` logs → `summarize`。UART 示例：

```bash
python3 -m host_control uart --port /dev/ttyUSB0 --baudrate 1500000 ping
python3 -m host_control uart --port /dev/ttyUSB0 --baudrate 1500000 run_task --task-id bench_001
python3 -m host_control uart --port /dev/ttyUSB0 --baudrate 1500000 stop_task --task-id bench_001
python3 -m host_control uart --port /dev/ttyUSB0 --baudrate 1500000 cleanup_task --task-id bench_001
```

采集与汇总：

```bash
python3 -m host_control execute \
  --task-id bench_001 \
  --port /dev/ttyUSB0 \
  --baudrate 1500000 \
  --collect-seconds 240

python3 -m host_control summarize \
  --task-result results/bench_001/task_result.json
```

**指标说明**：`task_result.json` 中的 `host_cpu_percent_avg` 表示运行 **`execute` 的 Python 进程**在整段 run/wait 窗口内的平均 CPU（与 `ProcessCPUTracker` 口径一致）；板端内存等指标仍来自 UART 遥测中的 `metric` 行。

---

## 5. 核心文档指引 (Documentation Index)

| 文档 | 说明 |
| :--- | :--- |
| [VNPU_LLM_Demo_Host_Device_Architecture_Design.md](docs/VNPU_LLM_Demo_Host_Device_Architecture_Design.md) | **架构设计定稿**：Runtime Base / Task Bundle / Telemetry 边界，Benchmark 作为 Host 构造的 batch task，`request.json` 与会话契约。 |
| [device_runbook.md](docs/device_runbook.md) | **板端运维手册**：目录布局、on-device 编译 demo、启动 executor、会话目录与 UART 命令 JSON 格式。 |

---

## 6. 声明 (License & Disclaimer)

*   `librkllmrt.so`、`librknnrt.so` 等闭源组件的版权与许可归 **Rockchip** 及相应 SDK 条款所有。
*   本仓库用于 Host–Device 链路上的 LLM/VLM 推理验证、Benchmark 采集与研究学习；生产与合规用途请自行评估许可与出口管制要求。
