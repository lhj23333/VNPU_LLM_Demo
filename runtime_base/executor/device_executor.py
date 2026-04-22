#!/usr/bin/env python3
"""Device-side task executor: UART/stdin JSON commands, telemetry on stdout."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

EXECUTOR_DIR = Path(__file__).resolve().parent
RUNTIME_BASE_DIR = EXECUTOR_DIR.parent

if __package__ in (None, ""):
    sys.path.insert(0, str(EXECUTOR_DIR))
    from demo_launcher import DemoLauncher  # type: ignore
    from runtime_probe import RuntimeProbe  # type: ignore
    from task_loader import TaskLoader  # type: ignore
    from telemetry_emitter import TelemetryEmitter  # type: ignore
else:
    from .demo_launcher import DemoLauncher
    from .runtime_probe import RuntimeProbe
    from .task_loader import TaskLoader
    from .telemetry_emitter import TelemetryEmitter


class DeviceExecutor:
    def __init__(self, sessions_root: Path):
        self.sessions_root = sessions_root.resolve()
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._active_task_id: Optional[str] = None

    def _ensure_session_workspace(self, session_dir: Path) -> None:
        (session_dir / "logs").mkdir(parents=True, exist_ok=True)

    def _append_log_file(self, session_dir: Path, name: str, text: str) -> None:
        path = session_dir / "logs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", errors="replace")

    def _run_llm_single(self, session_dir: Path, task: Any, emitter: TelemetryEmitter) -> None:
        task_id = task.task_id
        raw = task.raw
        model = task.model
        inp = task.input
        runtime = task.runtime

        llm_bin = RUNTIME_BASE_DIR / "bin" / "llm_demo"
        if not llm_bin.exists():
            emitter.log(
                task_id,
                "bin/llm_demo not found; on device run scripts/build_demos_on_device.sh",
                level="error",
            )
            emitter.lifecycle(task_id, "failed")
            return

        model_path = session_dir / model["llm_model"]
        prompt = str(inp.get("prompt", "")).strip()
        max_new_tokens = int(runtime.get("max_new_tokens", 512))
        max_context_len = int(runtime.get("max_context_len", 2048))

        launcher = DemoLauncher(RUNTIME_BASE_DIR)
        spec = launcher.build_llm(model_path, max_new_tokens, max_context_len, prompt)
        proc = launcher.launch(spec)
        probe = RuntimeProbe(emitter)
        try:
            result = probe.run(task_id, proc, prompt, subtask_index=None, cancel_event=self._cancel)
        finally:
            if proc.poll() is None:
                proc.kill()

        self._append_log_file(session_dir, "run_output.log", result.full_output)

        if result.cancelled:
            emitter.lifecycle(task_id, "stopped")
        elif result.success:
            emitter.lifecycle(task_id, "finished")
        else:
            emitter.log(
                task_id,
                f"llm_demo exited with code {result.returncode}",
                level="error",
            )
            emitter.lifecycle(task_id, "failed")

    def _run_vlm_single(self, session_dir: Path, task: Any, emitter: TelemetryEmitter) -> None:
        task_id = task.task_id
        model = task.model
        inp = task.input
        runtime = task.runtime

        vlm_bin = RUNTIME_BASE_DIR / "bin" / "vlm_demo"
        if not vlm_bin.exists():
            emitter.log(
                task_id,
                "bin/vlm_demo not found; on device run scripts/build_demos_on_device.sh",
                level="error",
            )
            emitter.lifecycle(task_id, "failed")
            return

        image_path = session_dir / str(inp["image"])
        vision_path = session_dir / model["vision_model"]
        llm_path = session_dir / model["llm_model"]
        prompt = str(inp.get("prompt", "")).strip()
        max_new_tokens = int(runtime.get("max_new_tokens", 1024))
        max_context_len = int(runtime.get("max_context_len", 4096))
        rknn_core_num = int(runtime.get("rknn_core_num", 3))
        img_start = str(runtime.get("img_start", "<|vision_start|>"))
        img_end = str(runtime.get("img_end", "<|vision_end|>"))
        img_content = str(runtime.get("img_content", "<|image_pad|>"))

        launcher = DemoLauncher(RUNTIME_BASE_DIR)
        spec = launcher.build_vlm(
            image_path,
            vision_path,
            llm_path,
            prompt,
            max_new_tokens,
            max_context_len,
            rknn_core_num,
            img_start,
            img_end,
            img_content,
        )
        proc = launcher.launch(spec)
        probe = RuntimeProbe(emitter)
        try:
            result = probe.run(task_id, proc, prompt, subtask_index=None, cancel_event=self._cancel)
        finally:
            if proc.poll() is None:
                proc.kill()

        self._append_log_file(session_dir, "run_output.log", result.full_output)

        if result.cancelled:
            emitter.lifecycle(task_id, "stopped")
        elif result.success:
            emitter.lifecycle(task_id, "finished")
        else:
            emitter.log(
                task_id,
                f"vlm_demo exited with code {result.returncode}",
                level="error",
            )
            emitter.lifecycle(task_id, "failed")

    def _run_benchmark_batch(self, session_dir: Path, task: Any, emitter: TelemetryEmitter) -> None:
        task_id = task.task_id
        model = task.model
        runtime = task.runtime
        subtasks = task.subtasks

        llm_bin = RUNTIME_BASE_DIR / "bin" / "llm_demo"
        vlm_bin = RUNTIME_BASE_DIR / "bin" / "vlm_demo"
        launcher = DemoLauncher(RUNTIME_BASE_DIR)
        probe = RuntimeProbe(emitter)

        llm_model_path = session_dir / model["llm_model"]
        vision_path: Optional[Path] = None
        if "vision_model" in model:
            vision_path = session_dir / model["vision_model"]

        max_new_tokens = int(runtime.get("max_new_tokens", 512))
        max_context_len = int(runtime.get("max_context_len", 2048))
        rknn_core_num = int(runtime.get("rknn_core_num", 3))
        img_start = str(runtime.get("img_start", "<|vision_start|>"))
        img_end = str(runtime.get("img_end", "<|vision_end|>"))
        img_content = str(runtime.get("img_content", "<|image_pad|>"))

        combined_log: list[str] = []
        for index, st in enumerate(subtasks):
            if self._cancel.is_set():
                emitter.lifecycle(task_id, "stopped")
                return
            stype = str(st.get("type", ""))
            if stype == "llm":
                if not llm_bin.exists():
                    emitter.log(task_id, "bin/llm_demo not found", level="error", subtask_index=index)
                    emitter.lifecycle(task_id, "failed")
                    return
                prompt = str(st["prompt"]).strip()
                spec = launcher.build_llm(llm_model_path, max_new_tokens, max_context_len, prompt)
                proc = launcher.launch(spec)
                try:
                    result = probe.run(
                        task_id, proc, prompt, subtask_index=index, cancel_event=self._cancel
                    )
                finally:
                    if proc.poll() is None:
                        proc.kill()
                combined_log.append(f"=== subtask {index} llm ===\n{result.full_output}\n")
                self._append_log_file(session_dir, f"subtask_{index:04d}.log", result.full_output)
                if result.cancelled:
                    emitter.lifecycle(task_id, "stopped")
                    return
                if not result.success:
                    emitter.log(
                        task_id,
                        f"subtask {index} llm failed (code {result.returncode})",
                        level="error",
                        subtask_index=index,
                    )
                    emitter.lifecycle(task_id, "failed")
                    return
            elif stype == "vlm":
                if not vlm_bin.exists():
                    emitter.log(task_id, "bin/vlm_demo not found", level="error", subtask_index=index)
                    emitter.lifecycle(task_id, "failed")
                    return
                if vision_path is None:
                    emitter.log(task_id, "benchmark vlm requires vision_model", level="error")
                    emitter.lifecycle(task_id, "failed")
                    return
                image_path = session_dir / str(st["image"])
                prompt = str(st["prompt"]).strip()
                spec = launcher.build_vlm(
                    image_path,
                    vision_path,
                    llm_model_path,
                    prompt,
                    max_new_tokens,
                    max_context_len,
                    rknn_core_num,
                    img_start,
                    img_end,
                    img_content,
                )
                proc = launcher.launch(spec)
                try:
                    result = probe.run(
                        task_id, proc, prompt, subtask_index=index, cancel_event=self._cancel
                    )
                finally:
                    if proc.poll() is None:
                        proc.kill()
                combined_log.append(f"=== subtask {index} vlm ===\n{result.full_output}\n")
                self._append_log_file(session_dir, f"subtask_{index:04d}.log", result.full_output)
                if result.cancelled:
                    emitter.lifecycle(task_id, "stopped")
                    return
                if not result.success:
                    emitter.log(
                        task_id,
                        f"subtask {index} vlm failed (code {result.returncode})",
                        level="error",
                        subtask_index=index,
                    )
                    emitter.lifecycle(task_id, "failed")
                    return
            else:
                emitter.log(task_id, f"unsupported subtask type: {stype}", level="error")
                emitter.lifecycle(task_id, "failed")
                return

        self._append_log_file(session_dir, "run_output.log", "".join(combined_log))
        emitter.lifecycle(task_id, "finished")

    def _run_task_impl(self, task_id: str) -> None:
        session_dir = self.sessions_root / task_id
        emitter = TelemetryEmitter()
        try:
            if not session_dir.is_dir():
                emitter.log(task_id, f"session directory missing: {session_dir}", level="error")
                emitter.lifecycle(task_id, "failed")
                return

            self._ensure_session_workspace(session_dir)
            task = TaskLoader(session_dir).load()
            if task.task_id != task_id:
                emitter.log(
                    task_id,
                    f"request.json task_id mismatch (expected {task_id!r}, got {task.task_id!r})",
                    level="error",
                )
                emitter.lifecycle(task_id, "failed")
                return

            mode = task.mode
            if mode == "llm_single":
                self._run_llm_single(session_dir, task, emitter)
            elif mode == "vlm_single":
                self._run_vlm_single(session_dir, task, emitter)
            elif mode == "benchmark_batch":
                self._run_benchmark_batch(session_dir, task, emitter)
            else:
                emitter.log(task_id, f"unsupported mode: {mode}", level="error")
                emitter.lifecycle(task_id, "failed")
        except Exception as exc:  # noqa: BLE001 — top-level task guard
            emitter.log(task_id, f"executor error: {exc}", level="error")
            emitter.lifecycle(task_id, "failed")

    def _worker_main(self, task_id: str) -> None:
        self._run_task_impl(task_id)
        with self._lock:
            self._worker = None
            self._active_task_id = None
            self._cancel = threading.Event()

    def handle_run_task(self, task_id: str) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                TelemetryEmitter().log(
                    task_id,
                    "executor busy with another task",
                    level="error",
                )
                TelemetryEmitter().lifecycle(task_id, "failed")
                return
            self._cancel = threading.Event()
            self._active_task_id = task_id
            self._worker = threading.Thread(target=self._worker_main, args=(task_id,), daemon=True)
            self._worker.start()

    def handle_stop_task(self, task_id: str) -> None:
        with self._lock:
            if self._active_task_id == task_id:
                self._cancel.set()

    def _cleanup_all_sessions(self) -> None:
        """Delete every subdirectory under sessions_root (after stopping any running task)."""
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                self._cancel.set()
                worker = self._worker
            else:
                worker = None
        if worker is not None:
            worker.join(timeout=5.0)

        root = self.sessions_root
        if not root.is_dir():
            TelemetryEmitter().log("_executor_", "cleanup_all: bad sessions_root", level="warning")
            return
        removed = 0
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
        TelemetryEmitter().log("_executor_", f"cleanup_all: removed={removed}", level="info")

    def handle_cleanup_task(self, task_id: Optional[str]) -> None:
        if not task_id:
            self._cleanup_all_sessions()
            return
        session_dir = self.sessions_root / task_id
        with self._lock:
            if self._active_task_id == task_id and self._worker is not None and self._worker.is_alive():
                self._cancel.set()
                worker = self._worker
            else:
                worker = None
        if worker is not None:
            worker.join(timeout=5.0)
        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)

    def handle_ping(self) -> None:
        emitter = TelemetryEmitter()
        emitter.lifecycle("_ping_", "pong")

    def handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            msg: Dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            return
        cmd = str(msg.get("cmd", "")).strip()
        task_id = str(msg.get("task_id", "")).strip()
        if cmd == "ping":
            self.handle_ping()
        elif cmd == "run_task":
            if not task_id:
                return
            self.handle_run_task(task_id)
        elif cmd == "stop_task":
            if not task_id:
                return
            self.handle_stop_task(task_id)
        elif cmd == "cleanup_task":
            self.handle_cleanup_task(task_id or None)
        else:
            if task_id:
                TelemetryEmitter().log(task_id, f"unknown cmd: {cmd}", level="error")

    def stdio_loop(self) -> None:
        for line in sys.stdin:
            self.handle_line(line)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="VNPU LLM device executor")
    p.add_argument(
        "--sessions-root",
        type=Path,
        required=True,
        help="Directory containing per-task session folders (each with request.json)",
    )
    p.add_argument(
        "--stdio-loop",
        action="store_true",
        help="Read JSON control lines from stdin until EOF",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()
    exe = DeviceExecutor(args.sessions_root)
    if args.stdio_loop:
        exe.stdio_loop()
    else:
        print("Nothing to do: pass --stdio-loop", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
