import os
import subprocess
import time

from benchmark.profiler.memory_tracker import ProcessDRAMTracker


class BaseEngine:
    def __init__(self, config, workspace_root: str):
        self.config = config
        self.workspace_root = workspace_root
        self.env = os.environ.copy()
        self.tracker = ProcessDRAMTracker()
        # Log hook (e.g. GUI can inject a sink). Default preserves current behavior.
        self.log_fn = print

        # New layout: runtime shared libs are shipped in ./lib (no third_party on device).
        lib_dir = os.path.join(workspace_root, "lib")
        current_ld = self.env.get("LD_LIBRARY_PATH", "")
        self.env["LD_LIBRARY_PATH"] = f"{lib_dir}:{current_ld}" if current_ld else lib_dir

        # Keep level=1 so the parser can extract perf metrics.
        self.env["RKLLM_LOG_LEVEL"] = "1"

    def _build_cmd(self, **kwargs):
        raise NotImplementedError("Subclasses should implement this method.")

    def run(self, prompt: str, timeout: int = 900, **kwargs):
        cmd = self._build_cmd(**kwargs)

        start_time = time.time()
        process = None
        try:
            # Use unbuffered stdout to avoid deadlock while reading char by char.
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=self.env,
                cwd=self.workspace_root,
                bufsize=0,
            )

            # Bind DRAM tracker to this PID.
            self.tracker.set_pid(process.pid)

            output_bytes = bytearray()
            found_ready = False

            # Wait for "user" prompt indicating model is fully loaded and ready.
            while True:
                if time.time() - start_time > timeout:
                    break

                char = process.stdout.read(1) if process.stdout else b""
                if not char:
                    break

                output_bytes.extend(char)

                # C++ demos typically print "user:" at end of init.
                if output_bytes.lower().endswith(b"user:") or output_bytes.lower().endswith(b"user"):
                    found_ready = True
                    break

            if not found_ready:
                process.kill()
                duration = time.time() - start_time
                out_str = output_bytes.decode("utf-8", errors="replace")
                return False, f"Crash/Error: Did not find ready prompt.\nOutput: {out_str}", duration, {}

            # [T1 Stage] Model loaded, KV-Cache pre-allocated completely
            time.sleep(0.5)  # Let memory stabilize

            init_dram_mb = self.tracker.get_process_dram_mb()
            self.log_fn(f"[Profiler] Init DRAM (Weights + KV-Cache): {init_dram_mb:.2f} MB")

            # Demo apps expect questions on stdin, separated by newlines, and "exit" to quit.
            input_data = f"{prompt}\nexit\n".encode("utf-8")
            output_remainder, _ = process.communicate(input=input_data, timeout=timeout)

            duration = time.time() - start_time

            full_output = output_bytes + (output_remainder or b"")
            out_str = full_output.decode("utf-8", errors="replace")

            from benchmark.parser import parse_rkllm_metrics

            parsed_metrics = parse_rkllm_metrics(out_str)

            # Use parsed VmHWM if available; otherwise fall back.
            if parsed_metrics.get("peak_memory_gb", 0.0) > 0:
                total_peak_mb = parsed_metrics["peak_memory_gb"] * 1024.0
            else:
                total_peak_mb = init_dram_mb

            runtime_buffer_mb = max(0.0, total_peak_mb - init_dram_mb)

            self.log_fn(
                "[Profiler] Runtime Buffer: "
                f"{runtime_buffer_mb:.2f} MB | Total Peak DRAM (VmHWM): {total_peak_mb:.2f} MB"
            )

            mem_metrics = {
                "model_data_mb": init_dram_mb,
                "kv_cache_overhead_mb": runtime_buffer_mb,
                "total_peak_mb": total_peak_mb,
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
            return False, f"Timeout after {timeout} seconds", time.time() - start_time, {}
        except Exception as e:
            return False, f"Exception: {str(e)}", time.time() - start_time, {}
