import os
import subprocess
import time

from benchmark.profiler.memory_tracker import ProcessDRAMTracker
from benchmark.profiler.cpu_tracker import ProcessCPUTracker

# Substrings printed by official rknn-llm demos (see multimodal main.cpp / llm_demo.cpp).
_MILESTONE_LLM_LOADED = b"llm model loaded in"
_MILESTONE_IMGENC_LOADED = b"imgenc model loaded in"
_MILESTONE_IMGENC_INFER = b"imgenc model inference took"
_MILESTONE_RKLLM_INIT_OK = b"rkllm init success"


class BaseEngine:
    def __init__(self, config, workspace_root: str):
        self.config = config
        self.workspace_root = workspace_root
        self.env = os.environ.copy()
        self.tracker = ProcessDRAMTracker()
        self.cpu_tracker = ProcessCPUTracker()
        self.log_fn = print

        lib_dir = os.path.join(workspace_root, "lib")
        current_ld = self.env.get("LD_LIBRARY_PATH", "")
        self.env["LD_LIBRARY_PATH"] = f"{lib_dir}:{current_ld}" if current_ld else lib_dir

        self.env["RKLLM_LOG_LEVEL"] = "1"

    def _build_cmd(self, **kwargs):
        raise NotImplementedError("Subclasses should implement this method.")

    @staticmethod
    def _ends_with_user_prompt(buf: bytearray) -> bool:
        tail = bytes(buf[-64:]).lower()
        return tail.rstrip(b" \t\r\n").endswith(b"user:")

    @staticmethod
    def _model_ready_seen(buf: bytearray) -> bool:
        tail = bytes(buf[-256:]).lower()
        return tail.rstrip(b" \t\r\n").endswith(b"user:")

    def _sample_milestone_vm_mb(self, label: str) -> float:
        time.sleep(0.05)
        mb = self.tracker.get_process_dram_mb()
        self.log_fn(f"[Profiler] Milestone VmRSS ({label}): {mb:.2f} MB")
        return mb

    def _poll_load_milestones(
        self,
        output_bytes: bytearray,
        seen: dict,
    ) -> None:
        """Sample VmRSS once per milestone when the log line appears (same PID)."""
        low = bytes(output_bytes).lower()
        is_vlm = getattr(self.config, "type", "text") == "vlm"

        if not seen["llm_loaded"] and _MILESTONE_LLM_LOADED in low:
            seen["llm_loaded"] = True
            seen["vmrss_after_llm_load_mb"] = self._sample_milestone_vm_mb("LLM loaded")

        if not is_vlm and not seen["text_llm_milestone"] and _MILESTONE_RKLLM_INIT_OK in low:
            seen["text_llm_milestone"] = True
            if not seen["llm_loaded"]:
                seen["vmrss_after_llm_load_mb"] = self._sample_milestone_vm_mb("rkllm init success")

        if not seen["imgenc_loaded"] and _MILESTONE_IMGENC_LOADED in low:
            seen["imgenc_loaded"] = True
            seen["vmrss_after_imgenc_load_mb"] = self._sample_milestone_vm_mb("ImgEnc loaded")

        if not seen["imgenc_infer"] and _MILESTONE_IMGENC_INFER in low:
            seen["imgenc_infer"] = True
            seen["vmrss_after_imgenc_infer_mb"] = self._sample_milestone_vm_mb("ImgEnc first infer")

    def _send_prompt_and_wait_user(
        self,
        process: subprocess.Popen,
        prompt: str,
        output_buf: bytearray,
        start_time: float,
        timeout: int,
        stage: str,
    ) -> tuple[bool, str]:
        if process.stdin is None or process.stdout is None:
            return False, "Crash/Error: Process pipes are not available."

        process.stdin.write(f"{prompt}\n".encode("utf-8"))
        process.stdin.flush()

        while True:
            if time.time() - start_time > timeout:
                return False, f"Timeout after {timeout} seconds"

            char = process.stdout.read(1)
            if not char:
                return False, f"Crash/Error: Process exited during {stage}."

            output_buf.extend(char)
            if self._ends_with_user_prompt(output_buf):
                return True, ""

    def _empty_mem_metrics(self) -> dict:
        return {
            "vmrss_after_llm_load_mb": 0.0,
            "vmrss_after_imgenc_load_mb": 0.0,
            "vmrss_after_imgenc_infer_mb": 0.0,
            "vmrss_at_interactive_ready_mb": 0.0,
            "peak_dram_os_mb": 0.0,
            "runtime_overhead_os_mb": 0.0,
            "peak_dram_rkllm_mb": 0.0,
            "runtime_delta_rkllm_mb": 0.0,
            "model_data_mb": 0.0,
            "kv_cache_overhead_mb": 0.0,
            "total_peak_mb": 0.0,
            "peak_memory_gb": 0.0,
            "avg_cpu_usage_percent": 0.0,
            "npu_core_num": 0,
        }

    def run(self, prompt: str, timeout: int = 900, **kwargs):
        cmd = self._build_cmd(**kwargs)

        start_time = time.time()
        process = None
        milestone_seen = {
            "llm_loaded": False,
            "text_llm_milestone": False,
            "imgenc_loaded": False,
            "imgenc_infer": False,
            "vmrss_after_llm_load_mb": 0.0,
            "vmrss_after_imgenc_load_mb": 0.0,
            "vmrss_after_imgenc_infer_mb": 0.0,
        }

        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=self.env,
                cwd=self.workspace_root,
                bufsize=0,
            )

            self.tracker.set_pid(process.pid)
            self.cpu_tracker.set_pid(process.pid)
            self.cpu_tracker.start()

            output_bytes = bytearray()
            found_ready = False

            while True:
                if time.time() - start_time > timeout:
                    break

                char = process.stdout.read(1) if process.stdout else b""
                if not char:
                    break

                output_bytes.extend(char)
                self._poll_load_milestones(output_bytes, milestone_seen)

                if self._model_ready_seen(output_bytes):
                    found_ready = True
                    break

            if not found_ready:
                process.kill()
                duration = time.time() - start_time
                out_str = output_bytes.decode("utf-8", errors="replace")
                try:
                    self.cpu_tracker.stop_and_get_avg_cpu_percent()
                except Exception:
                    pass
                return False, f"Crash/Error: Did not find ready prompt.\nOutput: {out_str}", duration, self._empty_mem_metrics()

            time.sleep(0.5)
            vmrss_at_interactive_ready_mb = self.tracker.get_process_dram_mb()
            self.log_fn(
                "[Profiler] Interactive-ready VmRSS (Weights+KV+static): "
                f"{vmrss_at_interactive_ready_mb:.2f} MB"
            )

            warmup_output = bytearray()
            warmup_enabled = bool(kwargs.get("warmup", False))
            if warmup_enabled:
                ok, err = self._send_prompt_and_wait_user(
                    process=process,
                    prompt=str(kwargs.get("warmup_prompt") or prompt),
                    output_buf=warmup_output,
                    start_time=start_time,
                    timeout=timeout,
                    stage="warmup",
                )
                if not ok:
                    process.kill()
                    duration = time.time() - start_time
                    init_out = output_bytes.decode("utf-8", errors="replace")
                    warm_out = warmup_output.decode("utf-8", errors="replace")
                    try:
                        self.cpu_tracker.stop_and_get_avg_cpu_percent()
                    except Exception:
                        pass
                    return False, f"{err}\nOutput: {init_out}{warm_out}", duration, self._empty_mem_metrics()
                self.log_fn("[Profiler] Warmup completed.")

            infer_output = bytearray()
            ok, err = self._send_prompt_and_wait_user(
                process=process,
                prompt=prompt,
                output_buf=infer_output,
                start_time=start_time,
                timeout=timeout,
                stage="inference",
            )
            if not ok:
                process.kill()
                duration = time.time() - start_time
                init_out = output_bytes.decode("utf-8", errors="replace")
                warm_out = warmup_output.decode("utf-8", errors="replace") if warmup_enabled else ""
                infer_out = infer_output.decode("utf-8", errors="replace")
                try:
                    self.cpu_tracker.stop_and_get_avg_cpu_percent()
                except Exception:
                    pass
                return False, f"{err}\nOutput: {init_out}{warm_out}{infer_out}", duration, self._empty_mem_metrics()

            elapsed = time.time() - start_time
            remaining_timeout = max(1.0, float(timeout) - elapsed)
            avg_cpu_usage_percent = self.cpu_tracker.stop_and_get_avg_cpu_percent()
            # VmHWM must be read while the child is still alive. After communicate(),
            # /proc/<pid>/status is gone and VmHWM reads as 0 on many systems.
            peak_dram_os_mb = self.tracker.get_process_peak_dram_mb()
            output_exit, _ = process.communicate(input=b"exit\n", timeout=remaining_timeout)

            duration = time.time() - start_time

            full_output = output_bytes + warmup_output + infer_output + (output_exit or b"")
            out_str = full_output.decode("utf-8", errors="replace")

            from benchmark.parser import parse_rkllm_metrics

            parsed_metrics = parse_rkllm_metrics(out_str)
            peak_dram_rkllm_mb = 0.0
            if parsed_metrics.get("peak_memory_gb", 0.0) > 0:
                peak_dram_rkllm_mb = parsed_metrics["peak_memory_gb"] * 1024.0
            runtime_overhead_os_mb = max(0.0, peak_dram_os_mb - vmrss_at_interactive_ready_mb)
            runtime_delta_rkllm_mb = max(0.0, peak_dram_rkllm_mb - vmrss_at_interactive_ready_mb)

            self.log_fn(
                f"[Profiler] Peak VmHWM (OS): {peak_dram_os_mb:.2f} MB | "
                f"Runtime overhead (OS): {runtime_overhead_os_mb:.2f} MB"
            )
            self.log_fn(
                f"[Profiler] Peak RKLLM (log): {peak_dram_rkllm_mb:.2f} MB | "
                f"Delta RKLLM vs ready: {runtime_delta_rkllm_mb:.2f} MB"
            )
            self.log_fn(f"[Profiler] Avg CPU Usage: {avg_cpu_usage_percent:.2f}%")

            mem_metrics = {
                "vmrss_after_llm_load_mb": float(milestone_seen.get("vmrss_after_llm_load_mb") or 0.0),
                "vmrss_after_imgenc_load_mb": float(milestone_seen.get("vmrss_after_imgenc_load_mb") or 0.0),
                "vmrss_after_imgenc_infer_mb": float(milestone_seen.get("vmrss_after_imgenc_infer_mb") or 0.0),
                "vmrss_at_interactive_ready_mb": vmrss_at_interactive_ready_mb,
                "peak_dram_os_mb": peak_dram_os_mb,
                "runtime_overhead_os_mb": runtime_overhead_os_mb,
                "peak_dram_rkllm_mb": peak_dram_rkllm_mb,
                "runtime_delta_rkllm_mb": runtime_delta_rkllm_mb,
                "model_data_mb": vmrss_at_interactive_ready_mb,
                "kv_cache_overhead_mb": runtime_overhead_os_mb,
                "total_peak_mb": peak_dram_os_mb,
                "peak_memory_gb": parsed_metrics.get("peak_memory_gb", 0.0),
                "avg_cpu_usage_percent": avg_cpu_usage_percent,
                "npu_core_num": int(parsed_metrics.get("npu_core_num", 0) or 0),
            }

            if process.returncode != 0:
                return (
                    False,
                    f"Crash/Error (Code: {process.returncode})\nOutput: {out_str}",
                    duration,
                    mem_metrics,
                )

            return True, out_str, duration, mem_metrics

        except subprocess.TimeoutExpired:
            if process is not None:
                process.kill()
            try:
                self.cpu_tracker.stop_and_get_avg_cpu_percent()
            except Exception:
                pass
            return False, f"Timeout after {timeout} seconds", time.time() - start_time, self._empty_mem_metrics()
        except Exception as e:
            try:
                self.cpu_tracker.stop_and_get_avg_cpu_percent()
            except Exception:
                pass
            return False, f"Exception: {str(e)}", time.time() - start_time, self._empty_mem_metrics()
