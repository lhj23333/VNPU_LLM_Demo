import json
import sys
import threading
import time
from typing import Any


class TelemetryEmitter:
    def __init__(self):
        self._lock = threading.Lock()

    def emit(self, event_type: str, task_id: str, **payload: Any) -> None:
        event = {
            "type": event_type,
            "task_id": task_id,
            "ts": time.time(),
        }
        event.update(payload)
        line = json.dumps(event, ensure_ascii=False)
        with self._lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def lifecycle(self, task_id: str, status: str, **payload: Any) -> None:
        self.emit("lifecycle", task_id, status=status, **payload)

    def stream(self, task_id: str, seq: int, text: str, **payload: Any) -> None:
        self.emit("stream", task_id, seq=seq, text=text, **payload)

    def metric(self, task_id: str, **payload: Any) -> None:
        self.emit("metric", task_id, **payload)

    def log(self, task_id: str, message: str, level: str = "info", **payload: Any) -> None:
        self.emit("log", task_id, level=level, message=message, **payload)
