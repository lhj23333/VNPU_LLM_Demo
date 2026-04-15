import re


def parse_rkllm_metrics(output_text: str) -> dict:
    metrics = {
        "peak_memory_gb": 0.0,
        "prefill_tps": 0.0,
        "generate_tps": 0.0,
        "npu_core_num": 0,
        "imgenc_core_num": 0,
    }

    def _last_float(pattern: str) -> float:
        matches = re.findall(pattern, output_text, re.IGNORECASE)
        return float(matches[-1]) if matches else 0.0

    def _last_positive_float(pattern: str) -> float:
        matches = re.findall(pattern, output_text, re.IGNORECASE)
        values = [float(v) for v in matches]
        positives = [v for v in values if v > 0]
        return positives[-1] if positives else 0.0

    def _last_int(pattern: str) -> int:
        matches = re.findall(pattern, output_text, re.IGNORECASE)
        return int(matches[-1]) if matches else 0

    # Peak Memory Usage (GB)
    metrics["peak_memory_gb"] = _last_float(r"Peak Memory Usage.*?\(GB\)[^\d]+([\d.]+)")

    # Table format:
    prefill_tps = _last_positive_float(r"Prefill\s+[\d.]+\s+\d+\s+[\d.]+\s+([\d.]+)")
    if prefill_tps > 0:
        metrics["prefill_tps"] = prefill_tps

    gen_tps = _last_positive_float(r"Generate\s+[\d.]+\s+\d+\s+[\d.]+\s+([\d.]+)")
    if gen_tps > 0:
        metrics["generate_tps"] = gen_tps

    # Old format fallbacks
    if metrics["prefill_tps"] <= 0:
        legacy_prefill_tps = _last_positive_float(r"Prefill Speed\s*:\s*([\d.]+)\s*token/s")
        if legacy_prefill_tps > 0:
            metrics["prefill_tps"] = legacy_prefill_tps

    if metrics["generate_tps"] <= 0:
        legacy_gen_tps = _last_positive_float(r"Generate Speed\s*:\s*([\d.]+)\s*token/s")
        if legacy_gen_tps > 0:
            metrics["generate_tps"] = legacy_gen_tps

    # Runtime LLM NPU core from RKLLM logs.
    # Intentionally do not use ImgEnc-specific logs (e.g. "core num is X") for this field.
    npu_patterns = [
        r"\bnpu_core_num\s*[:=]\s*(\d+)",
        r"\bnpu\s*core\s*num\s*[:=]\s*(\d+)",
    ]
    for pattern in npu_patterns:
        npu_core = _last_int(pattern)
        if npu_core > 0:
            metrics["npu_core_num"] = npu_core
            break

    # Optional: keep ImgEnc core separately for debugging.
    imgenc_core = _last_int(r"core\s*num\s*is\s*(\d+)")
    if imgenc_core > 0:
        metrics["imgenc_core_num"] = imgenc_core

    return metrics
