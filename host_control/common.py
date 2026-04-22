import json
import os
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist"
HOST_DIR = REPO_ROOT / "host"
HOST_TASKS_DIR = HOST_DIR / "tasks"
RESULTS_DIR = REPO_ROOT / "results"
HOST_RUNTIME_BASE_DIR = DIST_DIR / "runtime_base"
RUNTIME_BASE_SRC_DIR = REPO_ROOT / "runtime_base"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def derive_result_model_label_from_llm_path(llm_model_src: Path) -> str:
    """Host results folder name, e.g. Qwen3-0.6B-w8a8_rk3588.rkllm -> Qwen3-0.6B."""
    stem = llm_model_src.name
    lower = stem.lower()
    for suffix in (".rkllm",):
        if lower.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    else:
        stem = llm_model_src.stem
    stem = re.sub(r"-w\d+a\d+(_rk\d+)?$", "", stem, flags=re.IGNORECASE)
    stem = stem.replace("/", "_").replace("\\", "_").strip(" .")
    return stem or "model"


def normalize_device_rel_path(path: str) -> str:
    normalized = path.strip().strip("/")
    if normalized.startswith("userdata/"):
        normalized = normalized[len("userdata/") :]
    elif normalized == "userdata":
        normalized = ""
    return normalized.strip("/")


def to_serializable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: to_serializable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_serializable(v) for v in value]
    return value


def aggregate_dram_from_metrics(metrics: list) -> dict[str, float]:
    """Align with RK3588_LLM: init (first non-zero) + max total peak; runtime = peak - init."""
    rows = [m for m in metrics if m.get("type") == "metric"]
    init_ref = 0.0
    for m in rows:
        v = m.get("init_dram_weights_kv_mb")
        if v is not None and float(v) > 0.0:
            init_ref = float(v)
            break
    peaks: list[float] = []
    for m in rows:
        v = m.get("total_peak_dram_mb")
        if v is not None:
            peaks.append(float(v))
    max_peak = max(peaks) if peaks else 0.0
    if init_ref <= 0.0:
        for m in rows:
            v = m.get("vmrss_mb")
            if v is not None and float(v) > 0.0:
                init_ref = float(v)
                break
    if max_peak <= 0.0:
        hwms = [float(m["vmhwm_mb"]) for m in rows if m.get("vmhwm_mb") is not None]
        max_peak = max(hwms) if hwms else 0.0
    runtime = max(0.0, max_peak - init_ref) if max_peak >= init_ref else 0.0
    return {
        "max_init_dram_weights_kv_mb": init_ref,
        "max_runtime_buffer_dram_mb": runtime,
        "max_total_peak_dram_mb": max_peak,
    }


def getenv_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} is not an integer: {raw}") from exc
