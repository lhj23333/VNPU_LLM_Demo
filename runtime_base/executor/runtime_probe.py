import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from rkllm_output_parser import parse_peak_memory_gb  # type: ignore
    from telemetry_emitter import TelemetryEmitter  # type: ignore
else:
    from .rkllm_output_parser import parse_peak_memory_gb
    from .telemetry_emitter import TelemetryEmitter


READY_TAIL = b"user:"
LLM_LOADED = b"llm model loaded in"
IMGENC_LOADED = b"imgenc model loaded in"
IMGENC_INFER = b"imgenc model inference took"
RKLLM_INIT_OK = b"rkllm init success"
INITDRAM_GATE_MARKER = b"VNPU_LLM_INITDRAM_GATE"


def _read_proc_status_value_mb(pid: int, key: str) -> float:
    status_file = f"/proc/{pid}/status"
    if not os.path.exists(status_file):
        return 0.0
    try:
        with open(status_file, "r", encoding="utf-8", errors="replace") as fp:
            for line in fp:
                if line.startswith(key):
                    kb = float(line.split()[1])
                    return kb / 1024.0
    except ProcessLookupError:
        pass
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[Probe Warning] Unable to read process status, Error: {e}", file=sys.stderr)
    return 0.0


def _extract_tps(text: str) -> Tuple[float, float]:
    """Match RK3588_LLM benchmark/parser.py: table row last column, then legacy token/s lines."""
    prefill = 0.0
    generate = 0.0
    prefill_matches = re.findall(r"Prefill\s+[\d.]+\s+\d+\s+[\d.]+\s+([\d.]+)", text, re.IGNORECASE)
    generate_matches = re.findall(r"Generate\s+[\d.]+\s+\d+\s+[\d.]+\s+([\d.]+)", text, re.IGNORECASE)
    if prefill_matches:
        prefill = float(prefill_matches[-1])
    if generate_matches:
        generate = float(generate_matches[-1])
    if prefill <= 0.0:
        m = re.search(r"Prefill Speed\s*:\s*([\d.]+)\s*token/s", text, re.IGNORECASE)
        if m:
            prefill = float(m.group(1))
    if generate <= 0.0:
        m = re.search(r"Generate Speed\s*:\s*([\d.]+)\s*token/s", text, re.IGNORECASE)
        if m:
            generate = float(m.group(1))
    return prefill, generate


@dataclass
class ProbeResult:
    success: bool
    cancelled: bool
    returncode: int
    full_output: str
    duration_seconds: float


class RuntimeProbe:
    def __init__(self, emitter: TelemetryEmitter):
        self.emitter = emitter

    @staticmethod
    def _is_ready(buffer: bytearray) -> bool:
        tail = bytes(buffer[-128:]).lower().rstrip(b" \t\r\n")
        return tail.endswith(READY_TAIL)

    @staticmethod
    def _write_prompt(process: subprocess.Popen, prompt: str) -> None:
        if process.stdin is None:
            raise RuntimeError("Process stdin is not available")
        try:
            process.stdin.write((prompt + "\n").encode("utf-8"))
            process.stdin.flush()
        except BrokenPipeError:
            print("[Probe Warning] Attempting to write prompt to closed process pipe.", file=sys.stderr)
        except Exception as e:
            print(f"[Probe Warning] Failed to write prompt: {e}", file=sys.stderr)

    @staticmethod
    def _unlock_init_dram_gate(process: subprocess.Popen) -> None:
        if process.stdin is None:
            return
        try:
            process.stdin.write(b"\n")
            process.stdin.flush()
        except BrokenPipeError:
            print("[Probe Warning] Attempting to write data to closed process pipe (init_dram_gate).", file=sys.stderr)
        except Exception as e:
            print(f"[Probe Warning] Failed to write command: {e}", file=sys.stderr)

    def run(
        self,
        task_id: str,
        process: subprocess.Popen,
        prompt: str,
        subtask_index: Optional[int] = None,
        cancel_event: Optional[threading.Event] = None,
        init_dram_gate: bool = True,
    ) -> ProbeResult:
        start = time.time()
        seq = 0
        output = bytearray()
        milestone_flags = {
            "llm_loaded": False,
            "imgenc_loaded": False,
            "imgenc_infer": False,
            "rkllm_init": False,
        }

        self.emitter.lifecycle(task_id, "running", subtask_index=subtask_index)

        assert process.stdout is not None
        ready_before_prompt = False
        init_dram_weights_kv_mb = 0.0
        init_sampled = False
        while True:
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                return ProbeResult(
                    success=False,
                    cancelled=True,
                    returncode=-15,
                    full_output=output.decode("utf-8", errors="replace"),
                    duration_seconds=time.time() - start,
                )
            ch = process.stdout.read(1)
            if not ch:
                break
            output.extend(ch)
            low = bytes(output).lower()
            if (not milestone_flags["llm_loaded"]) and LLM_LOADED in low:
                milestone_flags["llm_loaded"] = True
                self.emitter.log(task_id, "llm model loaded milestone", subtask_index=subtask_index)
            if (not milestone_flags["imgenc_loaded"]) and IMGENC_LOADED in low:
                milestone_flags["imgenc_loaded"] = True
                self.emitter.log(task_id, "imgenc model loaded milestone", subtask_index=subtask_index)
            if (not milestone_flags["imgenc_infer"]) and IMGENC_INFER in low:
                milestone_flags["imgenc_infer"] = True
                self.emitter.log(task_id, "imgenc first infer milestone", subtask_index=subtask_index)
            if (not milestone_flags["rkllm_init"]) and RKLLM_INIT_OK in low:
                milestone_flags["rkllm_init"] = True
                self.emitter.log(task_id, "rkllm init success milestone", subtask_index=subtask_index)

            if init_dram_gate and (not init_sampled) and (INITDRAM_GATE_MARKER in output):
                time.sleep(0.5)
                init_dram_weights_kv_mb = _read_proc_status_value_mb(process.pid, "VmRSS:")
                init_sampled = True
                self._unlock_init_dram_gate(process)
            elif (not init_dram_gate) and (not init_sampled) and (RKLLM_INIT_OK in low):
                time.sleep(0.5)
                init_dram_weights_kv_mb = _read_proc_status_value_mb(process.pid, "VmRSS:")
                init_sampled = True

            if self._is_ready(output):
                if not init_sampled:
                    time.sleep(0.5)
                    init_dram_weights_kv_mb = _read_proc_status_value_mb(process.pid, "VmRSS:")
                    init_sampled = True
                    if init_dram_gate and INITDRAM_GATE_MARKER not in output:
                        self.emitter.log(
                            task_id,
                            "init_dram sampled at first user (no VNPU_LLM_INITDRAM_GATE in output; rebuild demos for LLM-only init)",
                            subtask_index=subtask_index,
                        )
                ready_before_prompt = True
                break

        if not ready_before_prompt:
            rc = process.poll()
            return ProbeResult(
                success=False,
                cancelled=False,
                returncode=int(rc) if rc is not None else -1,
                full_output=output.decode("utf-8", errors="replace"),
                duration_seconds=time.time() - start,
            )

        # Init DRAM: VmRSS after rkllm_init (+ optional stdin gate before vision) or fallback at first user:

        self._write_prompt(process, prompt)
        max_vmhwm_mb = 0.0
        while True:
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                return ProbeResult(
                    success=False,
                    cancelled=True,
                    returncode=-15,
                    full_output=output.decode("utf-8", errors="replace"),
                    duration_seconds=time.time() - start,
                )
            ch = process.stdout.read(1)
            if not ch:
                break
            output.extend(ch)
            seq += 1
            self.emitter.stream(task_id, seq, ch.decode("utf-8", errors="replace"), subtask_index=subtask_index)
            if seq % 120 == 0:
                vmrss_mb = _read_proc_status_value_mb(process.pid, "VmRSS:")
                vmhwm_mb = _read_proc_status_value_mb(process.pid, "VmHWM:")
                max_vmhwm_mb = max(max_vmhwm_mb, vmhwm_mb)
                self.emitter.metric(
                    task_id,
                    vmrss_mb=vmrss_mb,
                    vmhwm_mb=vmhwm_mb,
                    subtask_index=subtask_index,
                )
            if self._is_ready(output):
                break

        infer_duration_s = time.time() - start
        # Sample while the demo child is still alive; after communicate() the PID is gone.
        vmrss_mb = _read_proc_status_value_mb(process.pid, "VmRSS:")
        vmhwm_mb = _read_proc_status_value_mb(process.pid, "VmHWM:")
        max_vmhwm_mb = max(max_vmhwm_mb, vmhwm_mb)

        try:
            if process.stdin is not None:
                process.stdin.write(b"exit\n")
                process.stdin.flush()
        except BrokenPipeError:
            print("[Probe Warning] Attempting to write data to closed process pipe (exit).", file=sys.stderr)
        except Exception as e:
            print(f"[Probe Warning] Failed to write exit command: {e}", file=sys.stderr)

        try:
            remainder, _ = process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            process.kill()
            remainder, _ = process.communicate()

        if remainder:
            output.extend(remainder)

        total_duration_s = time.time() - start
        full_text = output.decode("utf-8", errors="replace")
        prefill_tps, generate_tps = _extract_tps(full_text)
        peak_gb = parse_peak_memory_gb(full_text)
        if peak_gb > 0.0:
            total_peak_dram_mb = peak_gb * 1024.0
        else:
            total_peak_dram_mb = max(max_vmhwm_mb, init_dram_weights_kv_mb)
        runtime_buffer_dram_mb = max(0.0, total_peak_dram_mb - init_dram_weights_kv_mb)

        self.emitter.metric(
            task_id,
            prefill_tps=prefill_tps,
            generate_tps=generate_tps,
            vmrss_mb=vmrss_mb,
            vmhwm_mb=vmhwm_mb,
            init_dram_weights_kv_mb=init_dram_weights_kv_mb,
            runtime_buffer_dram_mb=runtime_buffer_dram_mb,
            total_peak_dram_mb=total_peak_dram_mb,
            duration_seconds=infer_duration_s,
            subtask_index=subtask_index,
        )

        return ProbeResult(
            success=process.returncode == 0,
            cancelled=False,
            returncode=int(process.returncode or 0),
            full_output=full_text,
            duration_seconds=total_duration_s,
        )
