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

*   **Device（执行端/板端）**: Rockchip RK3588 类型办卡，已部署 RKLLM / RKNN 运行时与 NPU 驱动。板端需能运行 Python 3 与 `device_executor`。
*   **物理内存 (RAM)**: **8 GB** 
*   **Host（控制端/上位机）**: 开发机或同一套环境中的上位机 (需 Python 环境与 PCIe/串口等外设权限)。
*   **通信链路**: 
    *   **UART**: 负责轻量级控制指令下发 (任务启停) 与实时 Telemetry 遥测。
    *   **PCIe 文件共享**: 负责大体积会话打包推送 (Task Bundle、模型依赖)。如 `pcie_file_share_rc` 工具。
*   **核心算力**: NPU **6.0 TOPS**（NPU 三核并发或单核调度）
*   **性能保障**: 跑分或对比实验前，强烈建议在板端执行 `sudo bash scripts/fix_freq_rk3588.sh`，将 CPU / DDR / NPU / GPU 置于 `performance` governor (最高性能策略)。

具体板端目录、executor 启动参数与 UART JSON 行协议，见 [docs/device_runbook.md](docs/device_runbook.md)。

---

## 3. 测试结果快速预览 (Benchmark Preview)

以下片段摘自 Host 自动汇总生成的 [results/benchmark_report.md](results/benchmark_report.md)（运行后由 `host_control` 写入；仓库内文件随本地跑分更新，**非固定成绩**）。完整表格与字段说明以该文件为准。

### 3.1 多核 NPU 性能 (3-Core)

#### 纯文本大模型 (Text-only LLM)

| 模型名称 (Model) | Context | NPU Core | 初始显存 (Weights+KV) | Runtime Buffer | 峰值显存 (Peak DRAM) | 生成速度 (TPS) | 状态 |
| :--- | :---: | :---: | :--- | :--- | :--- | :---: | :--- |
| **Qwen2-1.5B** | 4096 | 3 | ~1807.2 MB | ~5.2 MB | ~1812.5 MB | **15.62** | finished |
| **Qwen3-0.6B** | 4096 | 3 | ~1222.8 MB | ~6.0 MB | ~1228.8 MB | **31.39** | finished |
| **Qwen3-1.7B** | 4096 | 3 | ~2297.8 MB | ~6.2 MB | ~2304.0 MB | **13.86** | finished |
| **Qwen3-4B** | 4096 | 3 | ~4642.9 MB | ~6.0 MB | ~4649.0 MB | **6.66** | finished |

#### 视觉语言大模型 (Vision-Language VLM)

| 模型名称 (Model) | Context | NPU Core | 初始显存 (Weights+KV) | Runtime Buffer | 峰值显存 (Peak DRAM) | 生成速度 (TPS) | 状态 |
| :--- | :---: | :---: | :--- | :--- | :--- | :---: | :--- |
| **Qwen3-VL-2B** | 4096 | 3 | ~2301.5 MB | ~893.4 MB | ~3194.9 MB | **13.49** | finished |
| **Qwen3-VL-4B** | 4096 | 3 | ~4644.9 MB | ~915.4 MB | ~5560.3 MB | **6.52** | finished |
| **Intern3.5-VL-1B** | 4096 | 3 | ~1225.3 MB | ~679.3 MB | ~1904.6 MB | **30.34** | finished |
| **Intern3.5-VL-2B** | 4096 | 3 | ~2300.8 MB | ~699.5 MB | ~3000.3 MB | **13.44** | finished |
| **Intern3.5-VL-4B** | 4096 | 3 | ~4644.5 MB | ~721.3 MB | ~5365.8 MB | **6.51** | finished |

### 3.2 单核 NPU 性能 (1-Core)

#### 纯文本大模型 (Text-only LLM)

| 模型名称 (Model) | Context | NPU Core | 初始显存 (Weights+KV) | Runtime Buffer | 峰值显存 (Peak DRAM) | 生成速度 (TPS) | 状态 |
| :--- | :---: | :---: | :--- | :--- | :--- | :---: | :--- |
| **Qwen2-1.5B** | 4096 | 1 | ~1780.5 MB | ~11.5 MB | ~1792.0 MB | **6.47** | finished |
| **Qwen3-0.6B** | 4096 | 1 | ~1204.5 MB | ~3.8 MB | ~1208.3 MB | **14.11** | finished |
| **Qwen3-1.7B** | 4096 | 1 | ~2278.5 MB | ~5.0 MB | ~2283.5 MB | **5.77** | finished |
| **Qwen3-4B** | 4096 | 1 | ~4704.0 MB | ~6.4 MB | ~4710.4 MB | **2.58** | finished |

#### 视觉语言大模型 (Vision-Language VLM)

| 模型名称 (Model) | Context | NPU Core | 初始显存 (Weights+KV) | Runtime Buffer | 峰值显存 (Peak DRAM) | 生成速度 (TPS) | 状态 |
| :--- | :---: | :---: | :--- | :--- | :--- | :---: | :--- |
| **Qwen3-VL-2B** | 4096 | 1 | ~2281.5 MB | ~892.9 MB | ~3174.4 MB | **5.71** | finished |
| **Qwen3-VL-4B** | 4096 | 1 | ~4704.5 MB | ~887.5 MB | ~5621.8 MB | **2.65** | finished |
| **Intern3.5-VL-1B** | 4096 | 1 | ~1206.0 MB | ~678.1 MB | ~1884.2 MB | **13.76** | finished |
| **Intern3.5-VL-2B** | 4096 | 1 | ~2281.0 MB | ~698.8 MB | ~2979.8 MB | **5.74** | finished |
| **Intern3.5-VL-4B** | 4096 | 1 | ~4706.0 MB | ~731.4 MB | ~5437.4 MB | **2.56** | finished |

---

## 4. 快速开始 (Quick Start)

### 第一步：克隆仓库并初始化子模块
板端 `build_demos_on_device.sh` 依赖内部 `rknn-llm` 源码结构，请递归拉取：

```bash
git clone https://github.com/lhj23333/VNPU_LLM_Demo.git
cd VNPU_LLM_Demo

git submodule update --init --recursive
```

### 第二步：安装 Host 侧依赖
上位机控制端需要依赖 `pyserial` 等库用于串口通信及任务编排：
```bash
python3 -m pip install -r requirements.txt
```
> **注意:** 环境中需已安装并配置好大文件传输工具 **`pcie_file_share_rc`**（对应 `host_control` 的 Push/Pull 模块）。若仅使用 UART 跑小 Demo，此项可省略。

### 第三步：打包 Device Runtime Base
将板端依赖的环境脚本、可执行文件构建脚本及 `device_executor.py` 驻留控制程序打包成轻量级产物：
```bash
python3 -m host_control build-runtime-base
# 产物输出于: dist/runtime_base/
```

### 第四步：部署至板端 (Device)
将上一步生成的 runtime base 上传至板端约定路径：
```bash
python3 -m host_control push \
  --host-source dist/runtime_base \
  --device-dest vnpu_llm/runtime_base
```
登录板端后，编译 C++ 运行时的 Demo：
```bash
cd /userdata/vnpu_llm/runtime_base
bash ./scripts/build_demos_on_device.sh
```

### 第五步：板端启动 Executor 常驻进程
在 Device 侧，锁定频率策略后拉起 `device_executor` 进入监听循环：
```bash
cd /userdata/vnpu_llm/runtime_base
source ./scripts/env_setup.sh

sudo bash ./scripts/fix_freq_rk3588.sh

# stdio 形式用于测试，生产上通常依赖 UART fd 监听
python3 executor/device_executor.py --stdio-loop --sessions-root /userdata/vnpu_llm/sessions
```
详细目录规范及进程守护说明见 [docs/device_runbook.md](docs/device_runbook.md)。

### 第六步：Host 一键 E2E 任务 (推荐)
在 Host 控制端通过 `tools/run_infer_e2e.sh` 全自动走完：**解析模型配置 → 生成 Request → 通过 PCIe Push → 通过 UART 触发 Executor → 拉取 Telemetry 与 Logs → 报告汇总** 闭环流程。

运行前请确认 `host_control/benchmark_assets/configs/models_config.json` 中的 `model_id` 对应的权重文件对 Host 可见。

**执行单次 LLM 问答：**
```bash
sudo tools/run_infer_e2e.sh llm_single \
  --model-id qwen2-1.5b \
  --prompt "Hello, please introduce yourself."
```

**执行单次 VLM 图文：**
```bash
sudo tools/run_infer_e2e.sh vlm_single \
  --model-id qwen3-vl-2b \
  --image-src /abs/path/to/image.jpg \
  --prompt "Describe this image."
```

**执行全量 Benchmark 批量跑分：**
```bash
sudo tools/run_infer_e2e.sh benchmark_batch \
  --model-id qwen3-vl-2b \
  --include-vlm
```
> **排障信息:** 若发现 VLM 首图无响应或超时，请排查板端是否在修改 demo 源码后重新执行了 `build_demos_on_device.sh`。对于 OOM 及其他失败，Host 的 `summarize` 命令将如实将 Status 置为 failed。

### 第七步：等价 CLI 流程 (手动拆分)
统一入口：

```bash
python3 -m host_control --help
```

典型顺序：`build-task-llm` / `build-task-vlm` / `build-task-benchmark` → `push`（runtime_base 与 `host/tasks/<id>`）→ `uart run_task` → `pull` logs → `summarize`。UART 示例：

```bash
sudo python3 -m host_control uart --port /dev/ttyUSB0 --baudrate 1500000 ping
sudo python3 -m host_control uart --port /dev/ttyUSB0 --baudrate 1500000 run_task --task-id bench_001
sudo python3 -m host_control uart --port /dev/ttyUSB0 --baudrate 1500000 stop_task --task-id bench_001
sudo python3 -m host_control uart --port /dev/ttyUSB0 --baudrate 1500000 cleanup_task
```

采集与汇总：

```bash
sudo python3 -m host_control execute \
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

如果您需要深入了解 Host-Device 分离架构或遇到相关运维问题，请查阅 `docs/` 下的指南：

| 文档名称 | 详细说明 |
| :--- | :--- |
| 📐 [**VNPU_LLM_Demo_Host_Device_Architecture_Design.md**](docs/VNPU_LLM_Demo_Host_Device_Architecture_Design.md) | **架构设计定稿**。详细阐明了 Host 与 Device 的控制流，Runtime Base / Task Bundle / Telemetry 的边界划分，以及 Benchmark 作为 Batch Task 的 JSON 会话契约设计。 |
| 📖 [**device_runbook.md**](docs/device_runbook.md) | **板端运维手册**。包含了 NPU 开发板端的目录布局规范、`on-device` 编译 C++ Demo 的说明、启动 Executor 常驻进程的参数、会话目录状态机与 UART 协议详情。 |

---

## 6. 声明 (License & Disclaimer)

*   底层的 `librkllmrt.so`、`librknnrt.so` 等闭源 SDK 库组件的版权、解释权与使用许可均归 **Rockchip** 所有。
*   本项目仅供在 RK3588 (或 NPU 板卡) 的 Host–Device PCIe / UART 链路架构下进行大语言模型推理验证、Benchmark 采集实验以及架构学习交流。
*   出于合规与生产用途需求，请您自行评估版权方相关许可协议与可能的出口管制要求。
