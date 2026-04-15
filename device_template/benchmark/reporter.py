import os


class MarkdownReporter:
    """Writes benchmark_report.md with OS-primary DRAM columns + RKLLM aux + milestones."""

    _HEADER = (
        "| Model | Ctx | NPU | ReadyVmRSS | VmHWM | RtOS | RkPeak | RkDlt | "
        "mLLM | mImgL | mImgI | KvEst | CPU% | TPS | Status |\n"
    )
    _SEP = (
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | "
        ":---: | :---: | :---: | :---: | :---: | :---: | :--- |\n"
    )

    def __init__(self, workspace_root: str):
        self.output_dir = os.path.join(workspace_root, "results")
        os.makedirs(self.output_dir, exist_ok=True)
        self.report_path = os.path.join(self.output_dir, "benchmark_report.md")

    def _fmt_milestone(self, v: float, model_type: str, col: str) -> str:
        if model_type != "vlm" and col in ("mImgL", "mImgI"):
            return "—"
        if v <= 0.0:
            if col == "mLLM":
                return "—"
            if model_type == "vlm" and col in ("mImgL", "mImgI"):
                return "—"
            return f"{v:.1f}"
        return f"{v:.1f}"

    def _row(self, res: dict) -> str:
        t = res.get("type", "text")
        m_llm = float(res.get("vmrss_after_llm_load_mb", 0.0))
        m_img_l = float(res.get("vmrss_after_imgenc_load_mb", 0.0))
        m_img_i = float(res.get("vmrss_after_imgenc_infer_mb", 0.0))
        kv_est = float(res.get("kv_cache_estimate_mb", 0.0))
        kv_cell = f"~{kv_est:.1f}" if kv_est > 0 else "—"

        return (
            f"| {res['model_name']} | {res.get('max_context', 0)} | {res.get('npu_core_num', 0)} | "
            f"~{res.get('vmrss_at_interactive_ready_mb', 0.0):.1f} | "
            f"~{res.get('peak_dram_os_mb', 0.0):.1f} | "
            f"~{res.get('runtime_overhead_os_mb', 0.0):.1f} | "
            f"~{res.get('peak_dram_rkllm_mb', 0.0):.1f} | "
            f"~{res.get('runtime_delta_rkllm_mb', 0.0):.1f} | "
            f"{self._fmt_milestone(m_llm, t, 'mLLM')} | "
            f"{self._fmt_milestone(m_img_l, t, 'mImgL')} | "
            f"{self._fmt_milestone(m_img_i, t, 'mImgI')} | "
            f"{kv_cell} | "
            f"{res.get('avg_cpu_usage_percent', 0.0):.2f} | "
            f"{res.get('avg_generate_tps', 0.0):.2f} | "
            f"{res['status']} |\n"
        )

    def _appendix(self, results: list) -> str:
        lines = [
            "\n## Per-task Runtime overhead (OS), MB\n\n",
            "| Model | WorstTask# | RtOS per task (comma) |\n",
            "| :--- | :---: | :--- |\n",
        ]
        for res in results:
            idx = int(res.get("memory_worst_task_index", 0) or 0)
            pts = res.get("per_task_runtime_overhead_os") or []
            s = ", ".join(f"{x:.2f}" for x in pts) if pts else "—"
            lines.append(f"| {res['model_name']} | {idx} | {s} |\n")
        return "".join(lines)

    def generate_report(self, results: list):
        new_rows = [self._row(res) for res in results]
        appendix = self._appendix(results)

        note = (
            "\n_Note: **ReadyVmRSS** = VmRSS after `user:` + stabilization; **VmHWM** = process peak RSS (OS); "
            "**RtOS** = VmHWM − ReadyVmRSS (same source). **RkPeak/RkDlt** = RKLLM log peak vs Ready (mixed source). "
            "**mLLM/mImgL/mImgI** = milestone VmRSS from demo stdout (not pure Model/KV split). "
            "**KvEst** = optional analytical upper bound if `kv_num_hidden_layers`, `kv_num_key_value_heads`, "
            "`kv_head_dim` are set in model config. "
            "Main-row memory columns come from the task with largest **RtOS** (coherent tuple)._\n"
        )

        with open(self.report_path, "w", encoding="utf-8") as f:
            f.write("# VNPU LLM/VLM Benchmark Report\n\n")
            f.write("## Performance and memory (OS-primary)\n\n")
            f.write(self._HEADER)
            f.write(self._SEP)
            for row in new_rows:
                f.write(row)
            f.write(appendix)
            f.write(note)

        print(f"Report successfully generated/updated at: {self.report_path}")
