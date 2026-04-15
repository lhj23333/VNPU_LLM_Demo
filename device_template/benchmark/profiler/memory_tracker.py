import os


class ProcessDRAMTracker:
    """Read process DRAM usage from /proc/<pid>/status VmRSS."""

    def __init__(self):
        self.pid = None

    def set_pid(self, pid: int):
        self.pid = pid

    def _read_status_kb(self, field: str) -> int:
        if not self.pid:
            return 0

        status_file = f"/proc/{self.pid}/status"
        if not os.path.exists(status_file):
            return 0

        try:
            with open(status_file, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith(field):
                        return int(line.split()[1])
        except Exception:
            return 0

        return 0

    def get_process_dram_mb(self) -> float:
        """Read /proc/<pid>/status VmRSS (MB)."""
        rss_kb = self._read_status_kb("VmRSS:")
        return rss_kb / 1024.0 if rss_kb > 0 else 0.0

    def get_process_peak_dram_mb(self) -> float:
        """Read /proc/<pid>/status VmHWM (MB)."""
        hwm_kb = self._read_status_kb("VmHWM:")
        return hwm_kb / 1024.0 if hwm_kb > 0 else 0.0
