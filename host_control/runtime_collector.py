import argparse
import json
import threading
import time
from dataclasses import dataclass, field

import serial

# device_executor emits these when a task session ends
TASK_TERMINAL_LIFECYCLE = frozenset({"finished", "failed", "stopped"})


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
            try:
                event = json.loads(line.decode("utf-8", errors="replace").strip())
            except json.JSONDecodeError:
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

    def wait_for_task_terminal(self, task_id: str, timeout_s: float, poll_s: float = 0.2) -> bool:
        """Block until lifecycle is terminal for task_id or timeout. Returns True if terminal seen."""
        deadline = time.time() + max(0.1, timeout_s)
        while time.time() < deadline:
            if self.is_task_terminal(task_id):
                return True
            time.sleep(poll_s)
        return False


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
