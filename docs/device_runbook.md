# 📖 板端运维手册 (Device Runbook: Runtime Base + Sessions)

## 1. 运行时底座布局 (Device Runtime Base Layout)

在 Host 控制端将打包好的 `dist/runtime_base/` 部署至 Device (板端) 指定路径 (例如 `vnpu_llm/runtime_base`) 后，期望的目录结构如下：

```text
/userdata/vnpu_llm/runtime_base/
  bin/
  lib/
    librkllmrt.so
    librknnrt.so
  executor/
    device_executor.py
    task_loader.py
    demo_launcher.py
    runtime_probe.py
    rkllm_output_parser.py
    telemetry_emitter.py
  scripts/
    env_setup.sh
    fix_freq_rk3588.sh
    build_demos_on_device.sh
  _build_src/
    rknn-llm/   # staged sources + headers for on-device cmake build
```
推送完 runtime base 后，请务必在板端手动执行以下命令，在目标机器上本地编译出 `bin/llm_demo` 与 `bin/vlm_demo` C++ 运行时：

```bash
cd /userdata/vnpu_llm/runtime_base
bash ./scripts/build_demos_on_device.sh
```

**前置依赖**: 需要 `cmake`，C++ 工具链，以及与您的 OS 镜像匹配的 OpenMP 开发包（如 Ubuntu/Debian 下的 `libomp-dev`）。

## 2. 启动 Executor 常驻服务 (Start Executor Service Loop)

```bash
cd /userdata/vnpu_llm/runtime_base
source ./scripts/env_setup.sh

# 强烈建议执行：锁定 NPU/CPU 频率以保证 benchmark 跑分稳定性
sudo bash ./scripts/fix_freq_rk3588.sh

python3 executor/device_executor.py \
  --stdio-loop \
  --sessions-root /userdata/vnpu_llm/sessions
```

启动后，该 Python 进程将持续从标准输入 (或串口) 读取 JSON 格式的指令，并将 Telemetry 遥测数据以 JSON Lines 的形式发射至标准输出。

## 3. 会话目录契约 (Session Directory Contract)

Host 控制端在下发任务前，必须将 Task Bundle 按以下结构推送到板端：

```text
/userdata/vnpu_llm/sessions/<task_id>/
  request.json
  models/
  inputs/
```

Executor 运行期间，会将运行时产生的日志与输出产物写入：

```text
/userdata/vnpu_llm/sessions/<task_id>/
  logs/
    run_output.log
    subtask_0000.log   # 仅在 benchmark_batch 模式下生成，每个 subtask 对应一个 log
```

## 4. UART 控制指令契约 (UART Command Contract)

系统接受的 JSON 指令格式如下：

```json
{"cmd":"run_task","task_id":"task_001"}
{"cmd":"stop_task","task_id":"task_001"}
{"cmd":"cleanup_task","task_id":"task_001"}
{"cmd":"cleanup_task"}
{"cmd":"ping"}
```

> **提示:** 如果调用 `cleanup_task` 但未指定 `task_id`，系统将在停止当前正在运行的任务后，强制清空 `--sessions-root` 目录下的所有子文件夹。

## 5. 健康检查 (Health Checks)

- **检查 NPU 节点挂载状态**:

```bash
ls -l /dev/rknn
```

- **检查运行时动态库依赖 (依赖 `librkllmrt.so` 等是否正常链接)**:

```bash
ldd /userdata/vnpu_llm/runtime_base/bin/llm_demo
ldd /userdata/vnpu_llm/runtime_base/bin/vlm_demo
```
