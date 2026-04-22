"""Host-side process CPU average (%) via /proc/<pid>/stat — benchmark-aligned."""

from __future__ import annotations

import os
import time
from typing import Optional


class ProcessCPUTracker:
    """Track process average CPU usage (%) via /proc/<pid>/stat."""

    def __init__(self) -> None:
        self.pid: int | None = None
        self._clk_tck = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        self._start_wall: float | None = None
        self._start_ticks: int | None = None
        self._last_ticks = 0

    def set_pid(self, pid: int) -> None:
        self.pid = pid

    def sample(self) -> None:
        """Call periodically while the process is alive; refreshes last ticks for stop() if /proc is gone."""
        self._read_process_total_cpu_ticks()

    def _read_process_total_cpu_ticks(self) -> int:
        if self.pid is None:
            return 0

        stat_file = f"/proc/{self.pid}/stat"
        if not os.path.exists(stat_file):
            return 0

        try:
            with open(stat_file, encoding="utf-8", errors="replace") as f:
                raw = f.read().strip()
            right_paren = raw.rfind(")")
            if right_paren <= 0:
                return 0

            fields = raw[right_paren + 2 :].split()
            if len(fields) < 15:
                return 0

            utime = int(fields[11])
            stime = int(fields[12])
            total_ticks = utime + stime
            self._last_ticks = total_ticks
            return total_ticks
        except OSError:
            return 0

    def start(self) -> None:
        self._start_wall = time.time()
        self._start_ticks = self._read_process_total_cpu_ticks()

    def stop_and_get_avg_cpu_percent(
        self, end_ticks: Optional[int] = None, end_wall: Optional[float] = None
    ) -> float:
        if self._start_wall is None or self._start_ticks is None:
            return 0.0

        if end_wall is None:
            end_wall = time.time()
        if end_ticks is None:
            end_ticks = self._read_process_total_cpu_ticks()
        if end_ticks <= 0 and self._last_ticks > 0:
            end_ticks = self._last_ticks

        elapsed = max(0.0, end_wall - self._start_wall)
        delta_ticks = max(0, end_ticks - self._start_ticks)

        self._start_wall = None
        self._start_ticks = None

        if elapsed <= 0.0 or delta_ticks <= 0:
            return 0.0

        cpu_seconds = float(delta_ticks) / float(self._clk_tck)
        return max(0.0, (cpu_seconds / elapsed) * 100.0)

    def stop(self) -> float:
        """Same as stop_and_get_avg_cpu_percent()."""
        return self.stop_and_get_avg_cpu_percent()
