import argparse
import json
import threading
import time
from dataclasses import dataclass, field

import serial

# device_executor emits these when a task session ends
TASK_TERMINAL_LIFECYCLE = frozenset({"finished", "failed", "stopped"})


def _try_parse_uart_json_line(raw: bytes) -> dict | None:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    candidates = [text]
    brace = text.find("{")
    if brace > 0:
        candidates.append(text[brace:].strip())
    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


@dataclass
class TaskRuntimeContext:
    task_id: str
    status: str = "unknown"
    stream_text: str = ""
    metrics: list[dict] = field(default_factory=list)
    logs: list[dict] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def apply_event(self, event: dict) -> None:
        event_type = event.get("type")
        if event_type == "lifecycle":
            self.status = str(event.get("status", self.status))
            if self.status in TASK_TERMINAL_LIFECYCLE:
                self.finished_at = time.time()
            return
        if event_type == "stream":
            self.stream_text += str(event.get("text", ""))
            return
        if event_type == "metric":
            self.metrics.append(event)
            return
        self.logs.append(event)


class RuntimeCollector:
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 1500000):
        self.port = port
        self.baudrate = baudrate
        self.contexts: dict[str, TaskRuntimeContext] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._shared_serial: serial.Serial | None = None
        self._decode_errors = 0
        self._lock_stats = threading.Lock()

    def _get_or_create_ctx(self, task_id: str) -> TaskRuntimeContext:
        if task_id not in self.contexts:
            self.contexts[task_id] = TaskRuntimeContext(task_id=task_id)
        return self.contexts[task_id]

    def _read_lines_from(self, ser: serial.Serial) -> None:
        while not self._stop.is_set():
            try:
                line = ser.readline()
            except serial.SerialException:
                break
            if not line:
                continue
            event = _try_parse_uart_json_line(line)
            if event is None:
                with self._lock_stats:
                    self._decode_errors += 1
                continue

            task_id = str(event.get("task_id", "")).strip()
            if not task_id:
                continue
            ctx = self._get_or_create_ctx(task_id)
            ctx.apply_event(event)

    def _reader_loop(self) -> None:
        if self._shared_serial is not None:
            self._read_lines_from(self._shared_serial)
            return
        try:
            with serial.Serial(self.port, self.baudrate, timeout=0.1, write_timeout=2.0) as ser:
                self._read_lines_from(ser)
        except serial.SerialException:
            return

    def start(self, serial_port: serial.Serial | None = None) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._shared_serial = serial_port
        self._stop.clear()
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._shared_serial = None

    def is_task_terminal(self, task_id: str) -> bool:
        ctx = self.contexts.get(task_id)
        return ctx is not None and ctx.status in TASK_TERMINAL_LIFECYCLE

    def _debug_snapshot(self, task_id: str) -> dict:
        ctx = self.contexts.get(task_id)
        with self._lock_stats:
            decode_errors = self._decode_errors
        return {
            "ctx_status": ctx.status if ctx else None,
            "metrics_n": len(ctx.metrics) if ctx else 0,
            "decode_errors": decode_errors,
        }

    def wait_for_task_terminal(
        self,
        task_id: str,
        timeout_s: float | None = None,
        poll_s: float = 0.2,
        progress_log_s: float = 30.0,
    ) -> bool:
        deadline = None if timeout_s is None else time.time() + max(0.1, float(timeout_s))
        last_prog = time.time()
        while True:
            if self.is_task_terminal(task_id):
                return True
            if deadline is not None and time.time() >= deadline:
                return False
            time.sleep(poll_s)
            if progress_log_s > 0 and time.time() - last_prog >= progress_log_s:
                last_prog = time.time()
                snap = self._debug_snapshot(task_id)
                print(
                    f"[telemetry] waiting for {task_id!r}: lifecycle={snap['ctx_status']!r} "
                    f"metrics={snap['metrics_n']} uart_skipped_nonjson_lines={snap['decode_errors']}",
                    flush=True,
                )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect telemetry JSON lines from UART")
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baudrate", type=int, default=1500000)
    parser.add_argument("--seconds", type=int, default=30, help="How long to listen before printing summary")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    collector = RuntimeCollector(port=args.port, baudrate=args.baudrate)
    collector.start()
    time.sleep(max(1, args.seconds))
    collector.stop()

    for task_id, ctx in collector.contexts.items():
        print(f"task_id={task_id} status={ctx.status} metrics={len(ctx.metrics)} logs={len(ctx.logs)}")


if __name__ == "__main__":
    main()
