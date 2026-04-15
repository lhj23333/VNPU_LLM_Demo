import re


def parse_rkllm_metrics(output_text: str) -> dict:
    metrics = {"peak_memory_gb": 0.0, "prefill_tps": 0.0, "generate_tps": 0.0, "npu_core_num": 0}

    # Peak Memory Usage (GB)
    mem_match = re.search(r"Peak Memory Usage.*?\(GB\)[^\d]+([\d.]+)", output_text, re.IGNORECASE)
    if mem_match:
        metrics["peak_memory_gb"] = float(mem_match.group(1))

    # Table format:
    prefill_match = re.search(r"Prefill\s+[\d.]+\s+\d+\s+[\d.]+\s+([\d.]+)", output_text, re.IGNORECASE)
    if prefill_match:
        metrics["prefill_tps"] = float(prefill_match.group(1))

    gen_match = re.search(r"Generate\s+[\d.]+\s+\d+\s+[\d.]+\s+([\d.]+)", output_text, re.IGNORECASE)
    if gen_match:
        metrics["generate_tps"] = float(gen_match.group(1))

    # Old format fallbacks
    if not prefill_match:
        prefill_match = re.search(r"Prefill Speed\s*:\s*([\d.]+)\s*token/s", output_text, re.IGNORECASE)
        if prefill_match:
            metrics["prefill_tps"] = float(prefill_match.group(1))

    if not gen_match:
        gen_match = re.search(r"Generate Speed\s*:\s*([\d.]+)\s*token/s", output_text, re.IGNORECASE)
        if gen_match:
            metrics["generate_tps"] = float(gen_match.group(1))

    # npu_core_num: 3
    npu_match = re.search(r"npu_core_num\s*:\s*(\d+)", output_text, re.IGNORECASE)
    if npu_match:
        metrics["npu_core_num"] = int(npu_match.group(1))

    return metrics
