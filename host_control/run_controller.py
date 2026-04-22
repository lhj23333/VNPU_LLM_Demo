import argparse
import json
import threading
from dataclasses import dataclass

import serial


@dataclass(frozen=True)
class SerialConfig:
    port: str = "/dev/ttyUSB0"
    baudrate: int = 1500000
    bytesize: int = serial.EIGHTBITS
    parity: str = serial.PARITY_NONE
    stopbits: int = serial.STOPBITS_ONE
    read_timeout_s: float = 0.1
    write_timeout_s: float = 2.0


def open_serial_port(config: SerialConfig) -> serial.Serial:
    """Open one UART handle (use a single instance for read + write on Linux)."""
    return serial.Serial(
        port=config.port,
        baudrate=config.baudrate,
        bytesize=config.bytesize,
        parity=config.parity,
        stopbits=config.stopbits,
        timeout=config.read_timeout_s,
        write_timeout=config.write_timeout_s,
    )


class RunController:
    def __init__(self, config: SerialConfig, serial_port: serial.Serial | None = None):
        self.config = config
        self._lock = threading.Lock()
        if serial_port is not None:
            self._serial = serial_port
            self._owns_serial = False
        else:
            self._serial = open_serial_port(config)
            self._owns_serial = True

    def close(self) -> None:
        if self._owns_serial:
            self._serial.close()

    def send_command(self, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._lock:
            self._serial.write(encoded.encode("utf-8"))
            self._serial.flush()

    def run_task(self, task_id: str) -> None:
        self.send_command({"cmd": "run_task", "task_id": task_id})

    def stop_task(self, task_id: str) -> None:
        self.send_command({"cmd": "stop_task", "task_id": task_id})

    def cleanup_task(self, task_id: str | None = None) -> None:
        payload: dict = {"cmd": "cleanup_task"}
        if task_id:
            payload["task_id"] = task_id
        self.send_command(payload)

    def ping(self) -> None:
        self.send_command({"cmd": "ping"})


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send coarse-grained control commands over UART")
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baudrate", type=int, default=1500000)
    parser.add_argument("command", choices=["run_task", "stop_task", "cleanup_task", "ping"])
    parser.add_argument("--task-id")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command != "ping" and not args.task_id and args.command != "cleanup_task":
        raise ValueError("--task-id is required for run_task/stop_task")

    controller = RunController(SerialConfig(port=args.port, baudrate=args.baudrate))
    try:
        if args.command == "run_task":
            controller.run_task(args.task_id)
        elif args.command == "stop_task":
            controller.stop_task(args.task_id)
        elif args.command == "cleanup_task":
            controller.cleanup_task(args.task_id)
        else:
            controller.ping()
    finally:
        controller.close()

    print(f"Sent command: {args.command}")


if __name__ == "__main__":
    main()
