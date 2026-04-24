import argparse
import os
import time
from pathlib import Path

from .common import RESULTS_DIR, aggregate_dram_from_metrics
from .process_cpu_tracker import ProcessCPUTracker
from .model_delivery import ModelDeliveryManager
from .result_summarizer import ResultSummarizer
from .runtime_base_builder import RuntimeBaseBuilder
from .task_bundle_builder import TaskBundleBuilder


def _subtask_counts_from_metrics(metrics: list, status: str) -> tuple[int, int]:
    """Infer subtask progress from metric events (benchmark uses subtask_index)."""
    rows = [m for m in metrics if m.get("type") == "metric"]
    indices: list[int] = []
    for m in rows:
        if m.get("subtask_index") is None:
            continue
        try:
            indices.append(int(m["subtask_index"]))
        except (TypeError, ValueError):
            continue
    if indices:
        return max(indices) + 1, len(set(indices))
    if rows:
        return (1, 1 if status == "finished" else 0)
    return (0, 0)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="VNPU Host Control CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    rb = subparsers.add_parser("build-runtime-base")
    rb.add_argument("--output")

    bllm = subparsers.add_parser("build-task-llm")
    bllm.add_argument("--task-id", required=True)
    bllm.add_argument("--llm-model-src", required=True)
    bllm.add_argument("--prompt", required=True)
    bllm.add_argument("--max-new-tokens", type=int, default=512)
    bllm.add_argument("--max-context-len", type=int, default=2048)

    bvlm = subparsers.add_parser("build-task-vlm")
    bvlm.add_argument("--task-id", required=True)
    bvlm.add_argument("--vision-model-src", required=True)
    bvlm.add_argument("--llm-model-src", required=True)
    bvlm.add_argument("--image-src", required=True)
    bvlm.add_argument("--prompt", required=True)
    bvlm.add_argument("--max-new-tokens", type=int, default=1024)
    bvlm.add_argument("--max-context-len", type=int, default=4096)
    bvlm.add_argument("--rknn-core-num", type=int, default=3)
    bvlm.add_argument("--img-start", default="<|vision_start|>")
    bvlm.add_argument("--img-end", default="<|vision_end|>")
    bvlm.add_argument("--img-content", default="<|image_pad|>")

    bbench = subparsers.add_parser("build-task-benchmark")
    bbench.add_argument("--task-id", required=True)
    bbench.add_argument("--llm-model-src", required=True)
    bbench.add_argument("--vision-model-src")
    bbench.add_argument(
        "--text-prompts",
        help="JSON list of text prompts; required with --include-text (omit if VLM-only)",
    )
    bbench.add_argument(
        "--vlm-tasks",
        help="JSON list of VLM tasks; required with --include-vlm (omit if text-only)",
    )
    bbench.add_argument("--images-root", required=True)
    bbench.add_argument("--include-text", action="store_true")
    bbench.add_argument("--include-vlm", action="store_true")
    bbench.add_argument("--max-new-tokens", type=int, default=1024)
    bbench.add_argument("--max-context-len", type=int, default=4096)
    bbench.add_argument("--rknn-core-num", type=int, default=3)
    bbench.add_argument("--img-start", default="<|vision_start|>")
    bbench.add_argument("--img-end", default="<|vision_end|>")
    bbench.add_argument("--img-content", default="<|image_pad|>")

    push = subparsers.add_parser("push")
    push.add_argument("--host-source", required=True)
    push.add_argument("--device-dest", required=True)

    pull = subparsers.add_parser("pull")
    pull.add_argument("--device-source", required=True)
    pull.add_argument("--host-dest", required=True)

    uart = subparsers.add_parser("uart")
    uart.add_argument("--port", default="/dev/ttyUSB0")
    uart.add_argument("--baudrate", type=int, default=1500000)
    uart.add_argument("op", choices=["run_task", "stop_task", "cleanup_task", "ping"])
    uart.add_argument("--task-id")

    exec_cmd = subparsers.add_parser("execute")
    exec_cmd.add_argument("--task-id", required=True)
    exec_cmd.add_argument("--port", default="/dev/ttyUSB0")
    exec_cmd.add_argument("--baudrate", type=int, default=1500000)
    exec_cmd.add_argument(
        "--collect-seconds",
        type=int,
        default=None,
        metavar="N",
        help="Optional cap in seconds; default is unlimited wait until device reports finished/failed/stopped",
    )
    exec_cmd.add_argument(
        "--results-dir",
        default=None,
        help="Directory for telemetry task_result.json (default: results/<task_id>/)",
    )

    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--task-result", required=True)
    summarize.add_argument("--output")
    summarize.add_argument(
        "--no-benchmark-report",
        action="store_true",
        help="Do not append a row to results/benchmark_report.md",
    )

    return parser


def main() -> None:
    args = _parser().parse_args()

    if args.command == "build-runtime-base":
        builder = RuntimeBaseBuilder(Path(args.output).resolve()) if args.output else RuntimeBaseBuilder()
        out = builder.build()
        print(f"Runtime base built: {out}")
        return

    if args.command == "build-task-llm":
        out = TaskBundleBuilder().build_llm_single(
            task_id=args.task_id,
            llm_model_src=Path(args.llm_model_src).resolve(),
            prompt=args.prompt,
            max_new_tokens=args.max_new_tokens,
            max_context_len=args.max_context_len,
        )
        print(f"Task bundle built: {out}")
        return

    if args.command == "build-task-vlm":
        out = TaskBundleBuilder().build_vlm_single(
            task_id=args.task_id,
            vision_model_src=Path(args.vision_model_src).resolve(),
            llm_model_src=Path(args.llm_model_src).resolve(),
            image_src=Path(args.image_src).resolve(),
            prompt=args.prompt,
            max_new_tokens=args.max_new_tokens,
            max_context_len=args.max_context_len,
            rknn_core_num=args.rknn_core_num,
            img_start=args.img_start,
            img_end=args.img_end,
            img_content=args.img_content,
        )
        print(f"Task bundle built: {out}")
        return

    if args.command == "build-task-benchmark":
        include_text = bool(args.include_text)
        include_vlm = bool(args.include_vlm)
        if not include_text and not include_vlm:
            include_text = True
            include_vlm = True

        text_path = Path(args.text_prompts).resolve() if args.text_prompts else None
        vlm_path = Path(args.vlm_tasks).resolve() if args.vlm_tasks else None
        out = TaskBundleBuilder().build_benchmark_batch(
            task_id=args.task_id,
            llm_model_src=Path(args.llm_model_src).resolve(),
            vision_model_src=Path(args.vision_model_src).resolve() if args.vision_model_src else None,
            text_prompts_path=text_path,
            vlm_tasks_path=vlm_path,
            images_root=Path(args.images_root).resolve(),
            include_text=include_text,
            include_vlm=include_vlm,
            max_new_tokens=args.max_new_tokens,
            max_context_len=args.max_context_len,
            rknn_core_num=args.rknn_core_num,
            img_start=args.img_start,
            img_end=args.img_end,
            img_content=args.img_content,
        )
        print(f"Task bundle built: {out}")
        return

    if args.command == "push":
        out = ModelDeliveryManager().push(Path(args.host_source).resolve(), args.device_dest)
        print(f"Pushed: {out}")
        return

    if args.command == "pull":
        out = ModelDeliveryManager().pull(args.device_source, Path(args.host_dest).resolve())
        print(f"Pulled: {out}")
        return

    if args.command == "uart":
        from .run_controller import RunController, SerialConfig

        cfg = SerialConfig(port=args.port, baudrate=args.baudrate)
        ctrl = RunController(cfg)
        try:
            if args.op == "run_task":
                if not args.task_id:
                    raise ValueError("--task-id required for run_task")
                ctrl.run_task(args.task_id)
            elif args.op == "stop_task":
                if not args.task_id:
                    raise ValueError("--task-id required for stop_task")
                ctrl.stop_task(args.task_id)
            elif args.op == "cleanup_task":
                ctrl.cleanup_task(args.task_id)
            else:
                ctrl.ping()
        finally:
            ctrl.close()
        print(f"Command sent: {args.op}")
        return

    if args.command == "execute":
        from .run_controller import RunController, SerialConfig, open_serial_port
        from .runtime_collector import RuntimeCollector

        cfg = SerialConfig(port=args.port, baudrate=args.baudrate)
        ser = open_serial_port(cfg)
        collector = RuntimeCollector(port=args.port, baudrate=args.baudrate)
        controller = RunController(cfg, serial_port=ser)
        collector.start(ser)
        host_cpu_tracker = ProcessCPUTracker()
        host_cpu_tracker.set_pid(os.getpid())
        host_cpu_tracker.start()
        try:
            controller.run_task(args.task_id)
            if args.collect_seconds is None:
                print(f"Waiting for task {args.task_id!r} (until finished/failed/stopped)...", flush=True)
                collector.wait_for_task_terminal(args.task_id, timeout_s=None)
                print("Device reported terminal lifecycle; collecting result.", flush=True)
            else:
                max_wait = max(1, args.collect_seconds)
                print(
                    f"Waiting for task {args.task_id!r} (max {max_wait}s, ends early on finished/failed/stopped)...",
                    flush=True,
                )
                if collector.wait_for_task_terminal(args.task_id, timeout_s=float(max_wait)):
                    print("Device reported terminal lifecycle; collecting result.", flush=True)
                else:
                    print("Timed out waiting for terminal lifecycle; saving partial telemetry if any.", flush=True)
        finally:
            collector.stop()
            controller.close()
            ser.close()

        host_cpu_percent_avg = host_cpu_tracker.stop()

        context = collector.contexts.get(args.task_id)
        if context is None:
            print(f"No telemetry received for task_id={args.task_id}")
            return

        subtasks_total, subtasks_finished = _subtask_counts_from_metrics(context.metrics, context.status)
        dram_agg = aggregate_dram_from_metrics(context.metrics)

        result = {
            "task_id": context.task_id,
            "status": context.status,
            "duration_seconds": (context.finished_at or time.time()) - context.started_at,
            "subtasks_total": subtasks_total,
            "subtasks_finished": subtasks_finished,
            "host_cpu_percent_avg": host_cpu_percent_avg,
            "max_init_dram_weights_kv_mb": dram_agg["max_init_dram_weights_kv_mb"],
            "max_runtime_buffer_dram_mb": dram_agg["max_runtime_buffer_dram_mb"],
            "max_total_peak_dram_mb": dram_agg["max_total_peak_dram_mb"],
            "metrics": context.metrics,
            "errors": [item.get("message", "") for item in context.logs if item.get("type") == "log" and item.get("level") == "error"],
        }
        if args.results_dir:
            out_path = Path(args.results_dir).resolve() / "task_result.json"
        else:
            out_path = RESULTS_DIR / args.task_id / "task_result.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(__import__("json").dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Result collected: {out_path}")
        return

    if args.command == "summarize":
        from .benchmark_report_reporter import append_benchmark_report_row

        summarizer = ResultSummarizer()
        task_result_path = Path(args.task_result).resolve()
        task_result = __import__("json").loads(task_result_path.read_text(encoding="utf-8"))
        summary = summarizer.summarize_task_result(task_result)
        output_path = (
            Path(args.output).resolve()
            if args.output
            else RESULTS_DIR / summary["task_id"] / "summary.md"
        )
        report = summarizer.write_markdown_report(summary, output_path)
        print(f"Summary report: {report}")
        if not args.no_benchmark_report:
            br = append_benchmark_report_row(task_result, summary)
            print(f"Benchmark report updated: {br}")


if __name__ == "__main__":
    main()
