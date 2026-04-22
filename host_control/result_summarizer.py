import argparse
from pathlib import Path

from .common import aggregate_dram_from_metrics, ensure_dir, read_json


class ResultSummarizer:
    def summarize_task_result(self, task_result: dict) -> dict:
        metrics = task_result.get("metrics", [])
        errors = task_result.get("errors", [])

        prefill_values = [float(m.get("prefill_tps", 0.0)) for m in metrics if "prefill_tps" in m]
        generate_values = [float(m.get("generate_tps", 0.0)) for m in metrics if "generate_tps" in m]
        host_cpu = float(task_result.get("host_cpu_percent_avg", 0.0))

        dram = aggregate_dram_from_metrics(metrics)
        init_dram = float(task_result.get("max_init_dram_weights_kv_mb", dram["max_init_dram_weights_kv_mb"]))
        runtime_buf = float(task_result.get("max_runtime_buffer_dram_mb", dram["max_runtime_buffer_dram_mb"]))
        total_peak = float(task_result.get("max_total_peak_dram_mb", dram["max_total_peak_dram_mb"]))

        return {
            "task_id": task_result.get("task_id", ""),
            "status": task_result.get("status", "unknown"),
            "subtasks_total": int(task_result.get("subtasks_total", 0)),
            "subtasks_finished": int(task_result.get("subtasks_finished", 0)),
            "duration_seconds": float(task_result.get("duration_seconds", 0.0)),
            "avg_prefill_tps": sum(prefill_values) / len(prefill_values) if prefill_values else 0.0,
            "avg_generate_tps": sum(generate_values) / len(generate_values) if generate_values else 0.0,
            "init_dram_weights_kv_mb": init_dram,
            "runtime_buffer_dram_mb": runtime_buf,
            "total_peak_dram_mb": total_peak,
            "avg_host_cpu_percent": host_cpu,
            "error_summary": errors,
        }

    def write_markdown_report(self, summary: dict, output_path: Path) -> Path:
        ensure_dir(output_path.parent)
        lines = [
            "# VNPU Task Result Summary",
            "",
            f"- Task ID: `{summary['task_id']}`",
            f"- Status: `{summary['status']}`",
            f"- Duration (s): `{summary['duration_seconds']:.2f}`",
            f"- Subtasks: `{summary['subtasks_finished']}/{summary['subtasks_total']}`",
            f"- Avg Prefill TPS: `{summary['avg_prefill_tps']:.2f}`",
            f"- Avg Generate TPS: `{summary['avg_generate_tps']:.2f}`",
            f"- Init DRAM (Weights+KV-Cache, device, MB): `{summary['init_dram_weights_kv_mb']:.2f}`",
            f"- Runtime Buffer DRAM (device, MB): `{summary['runtime_buffer_dram_mb']:.2f}`",
            f"- Total Peak DRAM (VmHWM, device, MB): `{summary['total_peak_dram_mb']:.2f}`",
            f"- Avg Host process CPU (%): `{summary['avg_host_cpu_percent']:.2f}`",
            "",
            "## Errors",
        ]
        errors = summary.get("error_summary", [])
        if errors:
            for item in errors:
                lines.append(f"- {item}")
        else:
            lines.append("- None")

        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return output_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize task result JSON into markdown report")
    parser.add_argument("--task-result", required=True, help="Path to task_result.json")
    parser.add_argument("--output", required=True, help="Path to markdown report")
    parser.add_argument(
        "--no-benchmark-report",
        action="store_true",
        help="Do not append results/benchmark_report.md",
    )
    return parser


def main() -> None:
    from .benchmark_report_reporter import append_benchmark_report_row

    parser = _build_parser()
    args = parser.parse_args()

    task_result = read_json(Path(args.task_result).resolve())
    summarizer = ResultSummarizer()
    summary = summarizer.summarize_task_result(task_result)
    report = summarizer.write_markdown_report(summary, Path(args.output).resolve())
    print(f"Report written: {report}")
    if not args.no_benchmark_report:
        br = append_benchmark_report_row(task_result, summary)
        print(f"Benchmark report updated: {br}")


if __name__ == "__main__":
    main()
