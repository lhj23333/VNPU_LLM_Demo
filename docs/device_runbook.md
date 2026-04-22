# Device Runbook (Runtime Base + Sessions)

## 1. Device Runtime Base Layout

After Host deploys `dist/runtime_base/` to Device path `vnpu_llm/runtime_base`, expected tree:

```text
/userdata/vnpu_llm/runtime_base/
  bin/
    llm_demo
    vlm_demo
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

If `bin/llm_demo` and `bin/vlm_demo` are missing (typical when Host did not pass `--llm-demo` / `--vlm-demo`), compile them on the device once:

```bash
cd /userdata/vnpu_llm/runtime_base
sudo bash ./scripts/build_demos_on_device.sh
```

Requires: `cmake`, a C++ toolchain, and OpenMP dev package matching your OS image (e.g. `libomp-dev` or distro equivalent).

## 2. Start Executor Service Loop

```bash
cd /userdata/vnpu_llm/runtime_base
source ./scripts/env_setup.sh

# Optional for benchmark consistency
sudo bash ./scripts/fix_freq_rk3588.sh

python3 executor/device_executor.py \
  --stdio-loop \
  --sessions-root /userdata/vnpu_llm/sessions
```

The process continuously reads command JSON lines from stdin and emits telemetry JSON lines to stdout.

## 3. Session Directory Contract

Host must stage each task bundle to:

```text
/userdata/vnpu_llm/sessions/<task_id>/
  request.json
  models/
  inputs/
```

Executor writes runtime artifacts to:

```text
/userdata/vnpu_llm/sessions/<task_id>/
  logs/
    run_output.log
    subtask_0000.log   # benchmark_batch only, one per subtask
```

## 4. UART Command Contract

Accepted commands:

```json
{"cmd":"run_task","task_id":"task_001"}
{"cmd":"stop_task","task_id":"task_001"}
{"cmd":"cleanup_task","task_id":"task_001"}
{"cmd":"cleanup_task"}
{"cmd":"ping"}
```

`cleanup_task` without `task_id` removes every subdirectory under `--sessions-root` (after stopping the current task if one is running).

## 5. Health Checks

- NPU node:

```bash
ls -l /dev/rknn
```

- Runtime dependencies:

```bash
ldd /userdata/vnpu_llm/runtime_base/bin/llm_demo
ldd /userdata/vnpu_llm/runtime_base/bin/vlm_demo
```
