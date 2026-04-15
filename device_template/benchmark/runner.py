import datetime
import os

from .config import load_config
from .dataset import BenchmarkDataset
from .engine import create_engine
from .parser import parse_rkllm_metrics
from .reporter import MarkdownReporter


class BenchmarkRunner:
    def __init__(self, workspace_root: str, config_path: str, warmup: bool = False, warmup_prompt: str = ""):
        self.workspace_root = workspace_root
        self.models_config = load_config(config_path)
        self.dataset = BenchmarkDataset(workspace_root)
        self.reporter = MarkdownReporter(workspace_root)
        self.warmup = bool(warmup)
        self.warmup_prompt = str(warmup_prompt or "")

        self.logs_dir = os.path.join(self.workspace_root, "logs")
        os.makedirs(self.logs_dir, exist_ok=True)

    @staticmethod
    def _kv_cache_estimate_mb(config) -> float:
        """Upper-bound style KV estimate: 2 * L * n_kv * head_dim * seq * bytes/8."""
        if config is None:
            return 0.0
        L = getattr(config, "kv_num_hidden_layers", None)
        kv_h = getattr(config, "kv_num_key_value_heads", None)
        hd = getattr(config, "kv_head_dim", None)
        if L is None or kv_h is None or hd is None:
            return 0.0
        seq = int(getattr(config, "max_context_len", 0) or 0)
        bpe = float(getattr(config, "kv_bytes_per_element", 2) or 2)
        bytes_total = 2.0 * float(L) * float(kv_h) * float(hd) * float(seq) * (bpe / 8.0)
        return bytes_total / (1024.0 * 1024.0)

    @staticmethod
    def _index_worst_runtime_os(metrics_list: list) -> int:
        if not metrics_list:
            return 0
        best_i = 0
        best_v = float(metrics_list[0].get("runtime_overhead_os_mb", 0.0))
        for i, m in enumerate(metrics_list):
            v = float(m.get("runtime_overhead_os_mb", 0.0))
            if v > best_v:
                best_v = v
                best_i = i
        return best_i

    def run_all(self, target_models=None, event_sink=None, cancel_event=None):
        results = []
        models_to_run = target_models if target_models else list(self.models_config.keys())

        def _emit_log(msg: str):
            print(msg)
            if event_sink is not None and hasattr(event_sink, "on_log"):
                try:
                    event_sink.on_log(msg)
                except Exception:
                    pass

        def _is_cancelled() -> bool:
            if cancel_event is None:
                return False
            try:
                return bool(cancel_event.is_set())
            except Exception:
                return False

        for model_name in models_to_run:
            if _is_cancelled():
                _emit_log("[Info] Cancel requested, stopping benchmark before next model.")
                break

            if model_name not in self.models_config:
                _emit_log(f"[Warn] Model {model_name} not found in config, skipping.")
                continue

            config = self.models_config[model_name]
            _emit_log("")
            _emit_log("==========================================")
            _emit_log(f"Running benchmark for: {model_name} ({config.type})")
            _emit_log("==========================================")

            try:
                config.validate(self.workspace_root)
            except Exception as e:
                _emit_log(f"Validation failed: {e}")
                results.append(self._create_empty_result(model_name, config.type, f"Failed: {e}", config))
                continue

            engine = create_engine(config, self.workspace_root)
            try:
                engine.log_fn = _emit_log
            except Exception:
                pass

            model_metrics = []
            status = "Success"
            log_file_path = os.path.join(self.logs_dir, f"{model_name}.log")

            if config.type == "text":
                total_tasks_for_model = len(self.dataset.get_text_prompts())
            elif config.type == "vlm":
                total_tasks_for_model = len(self.dataset.get_vlm_tasks())
            else:
                total_tasks_for_model = 0

            if event_sink is not None and hasattr(event_sink, "on_model_start"):
                try:
                    event_sink.on_model_start(model_name, config.type, total_tasks_for_model, log_file_path)
                except Exception:
                    pass

            with open(log_file_path, "w", encoding="utf-8") as log_f:
                log_f.write(f"=== Benchmark Run: {model_name} ===\n")
                log_f.write(f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

                if config.type == "text":
                    for task in self.dataset.get_text_prompts():
                        if _is_cancelled():
                            status = "Cancelled"
                            _emit_log("[Info] Cancel requested, stopping before next task.")
                            break

                        task_dict = {"id": task.get("id"), "prompt": task.get("prompt", "")}
                        if event_sink is not None and hasattr(event_sink, "on_task_start"):
                            try:
                                event_sink.on_task_start(model_name, task_dict)
                            except Exception:
                                pass

                        _emit_log(f"Task {task.get('id')}: {str(task.get('prompt', ''))[:20]}...")
                        success, output, duration, mem_metrics = engine.run(
                            task.get("prompt", ""),
                            warmup=self.warmup,
                            warmup_prompt=self.warmup_prompt,
                        )

                        log_f.write(
                            f"--- Task {task.get('id')} (Prompt: {task.get('prompt', '')}) ---\n"
                            f"Duration: {duration:.2f}s\n"
                            f"Output:\n{output}\n" + ("-" * 50) + "\n\n"
                        )

                        parsed = parse_rkllm_metrics(output) if success else {}
                        if event_sink is not None and hasattr(event_sink, "on_task_end"):
                            try:
                                event_sink.on_task_end(model_name, task_dict, success, output, duration, mem_metrics, parsed)
                            except Exception:
                                pass

                        if not success:
                            status = "Crash/Error"
                            break

                        metrics = dict(parsed)
                        metrics.update(mem_metrics)
                        model_metrics.append(metrics)

                elif config.type == "vlm":
                    for task in self.dataset.get_vlm_tasks():
                        if _is_cancelled():
                            status = "Cancelled"
                            _emit_log("[Info] Cancel requested, stopping before next task.")
                            break

                        raw_prompt = task.get("prompt", "") or ""
                        prompt = raw_prompt
                        if "<image>" not in prompt:
                            prompt = "<image>" + prompt.lstrip()

                        task_dict = {"id": task.get("id"), "prompt": prompt, "image": task.get("image", "")}
                        if event_sink is not None and hasattr(event_sink, "on_task_start"):
                            try:
                                event_sink.on_task_start(model_name, task_dict)
                            except Exception:
                                pass

                        _emit_log(
                            f"Task {task.get('id')}: image={os.path.basename(str(task.get('image','')))}, prompt='{prompt[:20]}...'"
                        )
                        success, output, duration, mem_metrics = engine.run(
                            prompt,
                            image_path=task.get("image", ""),
                            warmup=self.warmup,
                            warmup_prompt=self.warmup_prompt,
                        )

                        log_f.write(
                            f"--- Task {task.get('id')} (Image: {task.get('image','')} | Prompt: {prompt}) ---\n"
                            f"Duration: {duration:.2f}s\n"
                            f"Output:\n{output}\n" + ("-" * 50) + "\n\n"
                        )

                        parsed = parse_rkllm_metrics(output) if success else {}
                        if event_sink is not None and hasattr(event_sink, "on_task_end"):
                            try:
                                event_sink.on_task_end(model_name, task_dict, success, output, duration, mem_metrics, parsed)
                            except Exception:
                                pass

                        if not success:
                            status = "Crash/Error"
                            break

                        metrics = dict(parsed)
                        metrics.update(mem_metrics)
                        model_metrics.append(metrics)

            _emit_log(f"Detailed raw log saved to: {log_file_path}")
            results.append(self._aggregate_metrics(model_name, config.type, model_metrics, status, config))

            if event_sink is not None and hasattr(event_sink, "on_model_end"):
                try:
                    event_sink.on_model_end(model_name, status)
                except Exception:
                    pass

        self.reporter.generate_report(results)
        report_path = getattr(self.reporter, "report_path", "")
        if event_sink is not None and hasattr(event_sink, "on_run_end"):
            try:
                event_sink.on_run_end(report_path)
            except Exception:
                pass

    def _create_empty_result(self, model_name: str, model_type: str, status: str, config=None):
        return {
            "model_name": model_name,
            "type": model_type,
            "max_context": config.max_context_len if config else 0,
            "prompts_tested": 0,
            "avg_prefill_tps": 0.0,
            "avg_generate_tps": 0.0,
            "peak_memory_rkllm": 0.0,
            "model_data_mb": 0.0,
            "kv_cache_overhead_mb": 0.0,
            "total_peak_mb": 0.0,
            "vmrss_after_llm_load_mb": 0.0,
            "vmrss_after_imgenc_load_mb": 0.0,
            "vmrss_after_imgenc_infer_mb": 0.0,
            "vmrss_at_interactive_ready_mb": 0.0,
            "peak_dram_os_mb": 0.0,
            "runtime_overhead_os_mb": 0.0,
            "peak_dram_rkllm_mb": 0.0,
            "runtime_delta_rkllm_mb": 0.0,
            "kv_cache_estimate_mb": 0.0,
            "memory_worst_task_index": 0,
            "per_task_runtime_overhead_os": [],
            "avg_cpu_usage_percent": 0.0,
            "npu_core_num": 0,
            "status": status,
        }

    def _aggregate_metrics(self, model_name: str, model_type: str, metrics_list: list, status: str, config=None):
        if not metrics_list:
            return self._create_empty_result(model_name, model_type, status, config)

        total_prefill = sum(m.get("prefill_tps", 0.0) for m in metrics_list)
        total_gen = sum(m.get("generate_tps", 0.0) for m in metrics_list)
        count = len(metrics_list)

        worst_i = self._index_worst_runtime_os(metrics_list)
        w = metrics_list[worst_i]

        per_task_os = [float(m.get("runtime_overhead_os_mb", 0.0)) for m in metrics_list]

        peak_memories = [m.get("peak_memory_gb", 0.0) for m in metrics_list]
        max_peak_memory = max(peak_memories) if peak_memories else 0.0

        npu_cores = [m.get("npu_core_num", 0) for m in metrics_list]
        max_npu_core = max(npu_cores) if npu_cores else 0

        avg_cpu = sum(m.get("avg_cpu_usage_percent", 0.0) for m in metrics_list) / count if count > 0 else 0.0
        kv_est = self._kv_cache_estimate_mb(config)

        return {
            "model_name": model_name,
            "type": model_type,
            "max_context": config.max_context_len if config else 0,
            "prompts_tested": count,
            "avg_prefill_tps": total_prefill / count if count > 0 else 0.0,
            "avg_generate_tps": total_gen / count if count > 0 else 0.0,
            "peak_memory_rkllm": max_peak_memory,
            "memory_worst_task_index": worst_i + 1,
            "per_task_runtime_overhead_os": per_task_os,
            "vmrss_after_llm_load_mb": float(w.get("vmrss_after_llm_load_mb", 0.0)),
            "vmrss_after_imgenc_load_mb": float(w.get("vmrss_after_imgenc_load_mb", 0.0)),
            "vmrss_after_imgenc_infer_mb": float(w.get("vmrss_after_imgenc_infer_mb", 0.0)),
            "vmrss_at_interactive_ready_mb": float(w.get("vmrss_at_interactive_ready_mb", 0.0)),
            "peak_dram_os_mb": float(w.get("peak_dram_os_mb", 0.0)),
            "runtime_overhead_os_mb": float(w.get("runtime_overhead_os_mb", 0.0)),
            "peak_dram_rkllm_mb": float(w.get("peak_dram_rkllm_mb", 0.0)),
            "runtime_delta_rkllm_mb": float(w.get("runtime_delta_rkllm_mb", 0.0)),
            "kv_cache_estimate_mb": kv_est,
            "model_data_mb": float(w.get("model_data_mb", 0.0)),
            "kv_cache_overhead_mb": float(w.get("kv_cache_overhead_mb", 0.0)),
            "total_peak_mb": float(w.get("total_peak_mb", 0.0)),
            "avg_cpu_usage_percent": avg_cpu,
            "npu_core_num": max_npu_core,
            "status": status,
        }
