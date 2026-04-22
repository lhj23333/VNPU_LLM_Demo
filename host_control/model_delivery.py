import argparse
import os
import subprocess
from pathlib import Path

from .common import normalize_device_rel_path


class ModelDeliveryManager:
    def __init__(self, pcie_cmd: str = "pcie_file_share_rc"):
        self.pcie_cmd = pcie_cmd

    def _run_pcie(self, args: list[str]) -> None:
        index = os.environ.get("PCIE_DEVICE_SELECT", "1").strip() or "1"
        completed = subprocess.run(
            args,
            check=False,
            input=(index + "\n").encode(),
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "pcie transfer failed: "
                f"{' '.join(args)}\n"
                "See messages printed above by pcie_file_share_rc."
            )

    def push(self, host_source: Path, device_dest: str) -> str:
        if not host_source.exists():
            raise FileNotFoundError(f"Host source does not exist: {host_source}")

        device_rel = normalize_device_rel_path(device_dest)
        if not device_rel:
            raise ValueError(f"Invalid device destination: {device_dest}")

        self._run_pcie([self.pcie_cmd, "--set", str(host_source), device_rel])
        return f"/userdata/{device_rel}"

    def pull(self, device_source: str, host_dest: Path) -> Path:
        device_rel = normalize_device_rel_path(device_source)
        if not device_rel:
            raise ValueError(f"Invalid device source: {device_source}")
        host_dest.mkdir(parents=True, exist_ok=True)
        self._run_pcie([self.pcie_cmd, "--get", device_rel, str(host_dest)])
        return host_dest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transfer runtime base or task bundles via pcie_file_share_rc")
    subparsers = parser.add_subparsers(dest="direction", required=True)

    push = subparsers.add_parser("push")
    push.add_argument("--host-source", required=True)
    push.add_argument("--device-dest", required=True)

    pull = subparsers.add_parser("pull")
    pull.add_argument("--device-source", required=True)
    pull.add_argument("--host-dest", required=True)

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    manager = ModelDeliveryManager()
    if args.direction == "push":
        device_path = manager.push(Path(args.host_source).resolve(), args.device_dest)
        print(f"Pushed to: {device_path}")
    else:
        host_path = manager.pull(args.device_source, Path(args.host_dest).resolve())
        print(f"Pulled to: {host_path}")


if __name__ == "__main__":
    main()
