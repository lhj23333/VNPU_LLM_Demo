"""Parse RKLLM demo stdout fields (aligned with RK3588_LLM benchmark/parser.py)."""

from __future__ import annotations

import re


def parse_peak_memory_gb(output_text: str) -> float:
    """Return Peak Memory Usage (GB) from log text, or 0.0 if absent."""
    mem_match = re.search(r"Peak Memory Usage.*?\(GB\)[^\d]+([\d.]+)", output_text, re.IGNORECASE)
    if mem_match:
        return float(mem_match.group(1))
    return 0.0
