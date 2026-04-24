#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
MODELS_CONFIG_PATH="${REPO_ROOT}/host_control/benchmark_assets/configs/models_config.json"

usage() {
  cat <<'EOF'
Usage:
  tools/run_infer_e2e.sh <mode> --model-id <id> [options]

Modes:
  llm_single
  vlm_single
  benchmark_batch

Minimal common options:
  --model-id <id>                 Required, models_config.json key
  --task-id <id>                  Optional task id (default: <mode>_YYYYmmdd_HHMMSS)
  --result-label <name>           Optional result model label override
  --port <uart_port>              UART device (default: /dev/ttyUSB0)
  --baudrate <int>                UART baudrate (default: 1500000)
  --collect-seconds <int>         Max wait for task terminal lifecycle over UART (default: 1800)
  --no-summarize                  Skip summary report generation
  --cleanup-on-device             Send cleanup_task after pull

Business input options:
  --prompt <text>                 Required for llm_single / vlm_single unless provided by config defaults
  --image-src <path>              Required for vlm_single
  --include-text                  benchmark_batch include text prompts
  --include-vlm                   benchmark_batch include vlm tasks
                                  (if neither include flag is set, both are enabled)
  --round <n>                     benchmark_batch: repeat full subtask suite n times (default: 1)
  --text-prompts <json>           Optional override for benchmark text prompts list
  --vlm-tasks <json>              Optional override for benchmark VLM tasks list
  --images-root <dir>             Optional override for benchmark image root

Environment:
  PCIE_DEVICE_SELECT              pcie_file_share_rc menu index when multiple EPs exist (default: 1)

Notes:
  - Runtime and model paths are loaded from host_control/benchmark_assets/configs/models_config.json
  - request.json is rendered directly to results/<model_label>/<task_id>/request.json
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

if [[ "$1" == "-h" || "$1" == "--help" ]]; then
  usage
  exit 0
fi

MODE="$1"
shift

if [[ "${MODE}" != "llm_single" && "${MODE}" != "vlm_single" && "${MODE}" != "benchmark_batch" ]]; then
  echo "Unsupported mode: ${MODE}" >&2
  usage
  exit 1
fi

TASK_ID=""
MODEL_ID=""
RESULT_MODEL_LABEL=""
PORT="/dev/ttyUSB0"
BAUDRATE="1500000"
COLLECT_SECONDS="1800"
NO_SUMMARIZE="0"
CLEANUP_ON_DEVICE="0"

PROMPT=""
IMAGE_SRC=""
INCLUDE_TEXT="0"
INCLUDE_VLM="0"
TEXT_PROMPTS=""
VLM_TASKS=""
IMAGES_ROOT=""
BENCHMARK_ROUND="1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model-id)
      MODEL_ID="$2"
      shift 2
      ;;
    --task-id)
      TASK_ID="$2"
      shift 2
      ;;
    --result-label)
      RESULT_MODEL_LABEL="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --baudrate)
      BAUDRATE="$2"
      shift 2
      ;;
    --collect-seconds)
      COLLECT_SECONDS="$2"
      shift 2
      ;;
    --prompt)
      PROMPT="$2"
      shift 2
      ;;
    --image-src)
      IMAGE_SRC="$2"
      shift 2
      ;;
    --include-text)
      INCLUDE_TEXT="1"
      shift
      ;;
    --include-vlm)
      INCLUDE_VLM="1"
      shift
      ;;
    --text-prompts)
      TEXT_PROMPTS="$2"
      shift 2
      ;;
    --vlm-tasks)
      VLM_TASKS="$2"
      shift 2
      ;;
    --images-root)
      IMAGES_ROOT="$2"
      shift 2
      ;;
    --round)
      BENCHMARK_ROUND="$2"
      shift 2
      ;;
    --no-summarize)
      NO_SUMMARIZE="1"
      shift
      ;;
    --cleanup-on-device)
      CLEANUP_ON_DEVICE="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ "${MODE}" != "benchmark_batch" && "${BENCHMARK_ROUND}" != "1" ]]; then
  echo "--round is only supported for benchmark_batch mode" >&2
  exit 1
fi
if ! [[ "${BENCHMARK_ROUND}" =~ ^[1-9][0-9]*$ ]]; then
  echo "--round must be a positive integer (got: ${BENCHMARK_ROUND})" >&2
  exit 1
fi
if ! [[ "${COLLECT_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "--collect-seconds must be a positive integer (got: ${COLLECT_SECONDS})" >&2
  exit 1
fi

if [[ -z "${MODEL_ID}" ]]; then
  echo "--model-id is required" >&2
  exit 1
fi

if [[ -z "${TASK_ID}" ]]; then
  TASK_ID="${MODE}_$(date +%Y%m%d_%H%M%S)"
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found" >&2
  exit 1
fi
if [[ ! -f "${MODELS_CONFIG_PATH}" ]]; then
  echo "models config not found: ${MODELS_CONFIG_PATH}" >&2
  exit 1
fi

cd "${REPO_ROOT}"

export REPO_ROOT MODELS_CONFIG_PATH MODEL_ID MODE PROMPT IMAGE_SRC INCLUDE_TEXT INCLUDE_VLM TEXT_PROMPTS VLM_TASKS IMAGES_ROOT BENCHMARK_ROUND
CONFIG_EXPORTS="$(
  python3 - <<'PY'
import json
import os
import shlex
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"]).resolve()
config_path = Path(os.environ["MODELS_CONFIG_PATH"]).resolve()
model_id = os.environ["MODEL_ID"]
mode = os.environ["MODE"]
prompt_cli = os.environ.get("PROMPT", "").strip()
image_cli = os.environ.get("IMAGE_SRC", "").strip()
include_text = os.environ.get("INCLUDE_TEXT", "0") == "1"
include_vlm = os.environ.get("INCLUDE_VLM", "0") == "1"
text_prompts_cli = os.environ.get("TEXT_PROMPTS", "").strip()
vlm_tasks_cli = os.environ.get("VLM_TASKS", "").strip()
images_root_cli = os.environ.get("IMAGES_ROOT", "").strip()

def die(msg: str) -> None:
    raise SystemExit(msg)

def resolve_path(raw: str) -> str:
    value = str(raw).strip()
    if not value:
        return ""
    p = Path(value).expanduser()
    return str((repo_root / p).resolve()) if not p.is_absolute() else str(p.resolve())

def resolve_file(raw: str, field: str) -> str:
    path = resolve_path(raw)
    if not path:
        die(f"Missing required field: {field}")
    p = Path(path)
    if not p.is_file():
        die(f"{field} does not exist: {p}")
    return str(p)

def resolve_dir(raw: str, field: str) -> str:
    path = resolve_path(raw)
    if not path:
        die(f"Missing required field: {field}")
    p = Path(path)
    if not p.is_dir():
        die(f"{field} does not exist: {p}")
    return str(p)

try:
    data = json.loads(config_path.read_text(encoding="utf-8"))
except Exception as exc:
    die(f"Failed to read models config: {config_path}: {exc}")

models = data.get("models")
if not isinstance(models, dict):
    die(f"Invalid models config: missing object field 'models': {config_path}")
if model_id not in models:
    die(f"model_id '{model_id}' not found in config")
cfg = models[model_id]
if not isinstance(cfg, dict):
    die(f"Invalid model config for '{model_id}': expected object")

defaults = data.get("defaults", {}) if isinstance(data.get("defaults", {}), dict) else {}
prompts_defaults = defaults.get("prompts", {}) if isinstance(defaults.get("prompts", {}), dict) else {}
benchmark_defaults = defaults.get("benchmark", {}) if isinstance(defaults.get("benchmark", {}), dict) else {}
runtime_defaults = defaults.get("runtime", {}) if isinstance(defaults.get("runtime", {}), dict) else {}

model_type = str(cfg.get("type", "")).strip().lower()
if model_type not in {"text", "vlm"}:
    die(f"Invalid type for '{model_id}': {model_type!r} (expected 'text' or 'vlm')")

if mode == "llm_single" and model_type != "text":
    die(f"llm_single requires model type 'text'; got '{model_type}' for model-id '{model_id}'")
if mode == "vlm_single" and model_type != "vlm":
    die(f"vlm_single requires model type 'vlm'; got '{model_type}' for model-id '{model_id}'")

llm_field = "model_path" if model_type == "text" else "llm_model_path"
llm_model_src = resolve_file(cfg.get(llm_field, ""), llm_field)
vision_model_src = ""
if model_type == "vlm":
    vision_model_src = resolve_file(cfg.get("vision_model_path", ""), "vision_model_path")

max_new_tokens = cfg.get("max_new_tokens")
max_context_len = cfg.get("max_context_len")
if max_new_tokens is None or max_context_len is None:
    die(f"Model '{model_id}' must define max_new_tokens and max_context_len")

# Per-model rknn_core_num overrides defaults.runtime (path name "single_core" is not parsed).
if cfg.get("rknn_core_num") is not None:
    rknn_core_num = int(cfg["rknn_core_num"])
else:
    rknn_core_num = int(runtime_defaults.get("rknn_core_num", 3))
img_start = str(cfg.get("img_start", "<|vision_start|>"))
img_end = str(cfg.get("img_end", "<|vision_end|>"))
img_content = str(cfg.get("img_content", "<|image_pad|>"))

prompt_final = prompt_cli
if mode == "llm_single" and not prompt_final:
    prompt_final = str(prompts_defaults.get("llm_single", "")).strip()
if mode == "vlm_single" and not prompt_final:
    prompt_final = str(prompts_defaults.get("vlm_single", "")).strip()

if mode in {"llm_single", "vlm_single"} and not prompt_final:
    die(f"{mode} requires --prompt or defaults.prompts.{mode} in models_config.json")

image_final = ""
if mode == "vlm_single":
    if not image_cli:
        die("vlm_single requires --image-src")
    image_final = resolve_file(image_cli, "--image-src")

if mode == "benchmark_batch" and not include_text and not include_vlm:
    include_text = True
    include_vlm = True
if mode == "benchmark_batch" and include_vlm and model_type != "vlm":
    die(f"benchmark_batch with --include-vlm requires model type 'vlm'; got '{model_type}'")

text_prompts = ""
vlm_tasks = ""
images_root = ""
if mode == "benchmark_batch":
    if include_text:
        raw = text_prompts_cli or str(benchmark_defaults.get("text_prompts_path", "")).strip() or "host_control/benchmark_assets/prompts/text_prompts.json"
        text_prompts = resolve_file(raw, "--text-prompts")
    if include_vlm:
        raw_tasks = vlm_tasks_cli or str(benchmark_defaults.get("vlm_tasks_path", "")).strip() or "host_control/benchmark_assets/prompts/vlm_tasks.json"
        raw_images = images_root_cli or str(benchmark_defaults.get("images_root", "")).strip() or "host_control/benchmark_assets"
        vlm_tasks = resolve_file(raw_tasks, "--vlm-tasks")
        images_root = resolve_dir(raw_images, "--images-root")

exports = {
    "CONFIG_MODEL_TYPE": model_type,
    "LLM_MODEL_SRC": llm_model_src,
    "VISION_MODEL_SRC": vision_model_src,
    "PROMPT_FINAL": prompt_final,
    "IMAGE_SRC_FINAL": image_final,
    "INCLUDE_TEXT_FINAL": "1" if include_text else "0",
    "INCLUDE_VLM_FINAL": "1" if include_vlm else "0",
    "TEXT_PROMPTS_FINAL": text_prompts,
    "VLM_TASKS_FINAL": vlm_tasks,
    "IMAGES_ROOT_FINAL": images_root,
    "MAX_NEW_TOKENS": str(int(max_new_tokens)),
    "MAX_CONTEXT_LEN": str(int(max_context_len)),
    "RKNN_CORE_NUM": str(int(rknn_core_num)),
    "IMG_START": img_start,
    "IMG_END": img_end,
    "IMG_CONTENT": img_content,
}
for k, v in exports.items():
    print(f"{k}={shlex.quote(v)}")
PY
)"
eval "${CONFIG_EXPORTS}"

if [[ -z "${RESULT_MODEL_LABEL}" ]]; then
  export _E2E_LLM_MODEL_SRC="${LLM_MODEL_SRC}"
  RESULT_MODEL_LABEL="$(
    PYTHONPATH="${REPO_ROOT}" python3 -c \
      'from pathlib import Path; import os; from host_control.common import derive_result_model_label_from_llm_path; print(derive_result_model_label_from_llm_path(Path(os.environ["_E2E_LLM_MODEL_SRC"]).resolve()))'
  )"
  unset _E2E_LLM_MODEL_SRC
fi

RESULT_TASK_DIR="${REPO_ROOT}/results/${RESULT_MODEL_LABEL}/${TASK_ID}"
mkdir -p "${RESULT_TASK_DIR}"
REQUEST_JSON_PATH="${RESULT_TASK_DIR}/request.json"
UPLOAD_MANIFEST_PATH="${RESULT_TASK_DIR}/upload_manifest.tsv"
DEVICE_SESSION_REL="vnpu_llm/sessions/${TASK_ID}"
PCIE_DEVICE_SELECT="${PCIE_DEVICE_SELECT:-1}"

export TASK_ID MODE DEVICE_SESSION_REL REQUEST_JSON_PATH UPLOAD_MANIFEST_PATH
export LLM_MODEL_SRC VISION_MODEL_SRC IMAGE_SRC_FINAL PROMPT_FINAL
export MAX_NEW_TOKENS MAX_CONTEXT_LEN RKNN_CORE_NUM IMG_START IMG_END IMG_CONTENT
export INCLUDE_TEXT_FINAL INCLUDE_VLM_FINAL TEXT_PROMPTS_FINAL VLM_TASKS_FINAL IMAGES_ROOT_FINAL
python3 - <<'PY'
import json
import os
from pathlib import Path

def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)

def resolve_file(raw: str, field: str) -> Path:
    value = raw.strip()
    if not value:
        raise ValueError(f"Missing required field: {field}")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{field} does not exist: {path}")
    return path

def resolve_dir(raw: str, field: str) -> Path:
    value = raw.strip()
    if not value:
        raise ValueError(f"Missing required field: {field}")
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"{field} does not exist: {path}")
    return path

def read_json_list(path: Path, field: str) -> list:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{field} must be a JSON list: {path}")
    return data

mode = env("MODE")
task_id = env("TASK_ID")
request_json_path = Path(env("REQUEST_JSON_PATH"))
manifest_path = Path(env("UPLOAD_MANIFEST_PATH"))
device_session_rel = env("DEVICE_SESSION_REL")

max_new_tokens = int(env("MAX_NEW_TOKENS"))
max_context_len = int(env("MAX_CONTEXT_LEN"))
rknn_core_num = int(env("RKNN_CORE_NUM"))
img_start = env("IMG_START", "<|vision_start|>")
img_end = env("IMG_END", "<|vision_end|>")
img_content = env("IMG_CONTENT", "<|image_pad|>")

uploads: list[tuple[str, str]] = []

def add_upload(local_path: Path, device_rel: str) -> None:
    uploads.append((str(local_path.resolve()), device_rel))

if mode == "llm_single":
    llm_model = resolve_file(env("LLM_MODEL_SRC"), "LLM_MODEL_SRC")
    prompt = env("PROMPT_FINAL")
    llm_name = llm_model.name
    add_upload(llm_model, f"{device_session_rel}/models/{llm_name}")
    request = {
        "task_id": task_id,
        "mode": "llm_single",
        "model": {"llm_model": f"models/{llm_name}"},
        "input": {"prompt": prompt},
        "runtime": {
            "max_new_tokens": max_new_tokens,
            "max_context_len": max_context_len,
        },
    }
elif mode == "vlm_single":
    llm_model = resolve_file(env("LLM_MODEL_SRC"), "LLM_MODEL_SRC")
    vision_model = resolve_file(env("VISION_MODEL_SRC"), "VISION_MODEL_SRC")
    image_src = resolve_file(env("IMAGE_SRC_FINAL"), "IMAGE_SRC_FINAL")
    prompt = env("PROMPT_FINAL")

    llm_name = llm_model.name
    vision_name = vision_model.name
    image_name = image_src.name
    add_upload(llm_model, f"{device_session_rel}/models/{llm_name}")
    add_upload(vision_model, f"{device_session_rel}/models/{vision_name}")
    add_upload(image_src, f"{device_session_rel}/inputs/{image_name}")

    request = {
        "task_id": task_id,
        "mode": "vlm_single",
        "model": {
            "vision_model": f"models/{vision_name}",
            "llm_model": f"models/{llm_name}",
        },
        "input": {
            "image": f"inputs/{image_name}",
            "prompt": prompt,
        },
        "runtime": {
            "max_new_tokens": max_new_tokens,
            "max_context_len": max_context_len,
            "rknn_core_num": rknn_core_num,
            "img_start": img_start,
            "img_end": img_end,
            "img_content": img_content,
        },
    }
elif mode == "benchmark_batch":
    bench_round_raw = env("BENCHMARK_ROUND", "1").strip() or "1"
    try:
        bench_round = int(bench_round_raw)
    except ValueError as exc:
        raise ValueError(f"Invalid BENCHMARK_ROUND: {bench_round_raw!r}") from exc
    if bench_round < 1:
        bench_round = 1

    include_text = env("INCLUDE_TEXT_FINAL") == "1"
    include_vlm = env("INCLUDE_VLM_FINAL") == "1"
    llm_model = resolve_file(env("LLM_MODEL_SRC"), "LLM_MODEL_SRC")
    llm_name = llm_model.name
    add_upload(llm_model, f"{device_session_rel}/models/{llm_name}")
    model_block = {"llm_model": f"models/{llm_name}"}

    if include_vlm:
        vision_model = resolve_file(env("VISION_MODEL_SRC"), "VISION_MODEL_SRC")
        vision_name = vision_model.name
        add_upload(vision_model, f"{device_session_rel}/models/{vision_name}")
        model_block["vision_model"] = f"models/{vision_name}"

    subtasks: list[dict] = []
    if include_text:
        text_prompts = resolve_file(env("TEXT_PROMPTS_FINAL"), "TEXT_PROMPTS_FINAL")
        for item in read_json_list(text_prompts, "--text-prompts"):
            prompt = str(item.get("prompt", "")).strip()
            if prompt:
                subtasks.append({"type": "llm", "prompt": prompt})

    if include_vlm:
        vlm_tasks = resolve_file(env("VLM_TASKS_FINAL"), "VLM_TASKS_FINAL")
        images_root = resolve_dir(env("IMAGES_ROOT_FINAL"), "IMAGES_ROOT_FINAL")
        for idx, item in enumerate(read_json_list(vlm_tasks, "--vlm-tasks"), start=1):
            raw_image = str(item.get("image", "")).strip()
            prompt = str(item.get("prompt", "")).strip()
            if not raw_image or not prompt:
                continue

            source_image = Path(raw_image)
            if not source_image.is_absolute():
                source_image = images_root / source_image
            if not source_image.exists():
                source_image = images_root / Path(raw_image).name
            source_image = source_image.resolve()
            if not source_image.is_file():
                raise FileNotFoundError(f"Benchmark image is missing: {raw_image}")

            staged_name = f"img_{idx:03d}_{source_image.name}"
            add_upload(source_image, f"{device_session_rel}/inputs/{staged_name}")
            subtasks.append(
                {
                    "type": "vlm",
                    "image": f"inputs/{staged_name}",
                    "prompt": prompt,
                }
            )

    if not subtasks:
        raise ValueError("benchmark_batch generated empty subtasks; check prompt/task JSON inputs")

    request = {
        "task_id": task_id,
        "mode": "benchmark_batch",
        "model": model_block,
        "runtime": {
            "max_new_tokens": max_new_tokens,
            "max_context_len": max_context_len,
            "rknn_core_num": rknn_core_num,
            "img_start": img_start,
            "img_end": img_end,
            "img_content": img_content,
            "round": bench_round,
        },
        "subtasks": subtasks,
    }
else:
    raise ValueError(f"Unsupported mode: {mode}")

request_json_path.parent.mkdir(parents=True, exist_ok=True)
request_json_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
add_upload(request_json_path, f"{device_session_rel}/request.json")

manifest_path.parent.mkdir(parents=True, exist_ok=True)
with manifest_path.open("w", encoding="utf-8") as fp:
    for src, dst in uploads:
        fp.write(f"{src}\t{dst}\n")
PY

echo "Prepared request at: ${REQUEST_JSON_PATH}"
if ! command -v pcie_file_share_rc >/dev/null 2>&1; then
  echo "pcie_file_share_rc not found" >&2
  exit 1
fi
echo "Submitting task '${TASK_ID}' to '${DEVICE_SESSION_REL}' via PCIe..."
echo "  pcie device index (PCIE_DEVICE_SELECT): ${PCIE_DEVICE_SELECT}"

exec 3< "${UPLOAD_MANIFEST_PATH}"
while IFS=$'\t' read -r -u3 src dst; do
  if [[ -z "${src}" || -z "${dst}" ]]; then
    continue
  fi
  echo "  pcie set -> ${dst}"
  printf '%s\n' "${PCIE_DEVICE_SELECT}" | pcie_file_share_rc --set "${src}" "${dst}"
done
exec 3<&-

echo "Running task and collecting telemetry..."
python3 -m host_control execute \
  --task-id "${TASK_ID}" \
  --results-dir "${RESULT_TASK_DIR}" \
  --port "${PORT}" \
  --baudrate "${BAUDRATE}" \
  --collect-seconds "${COLLECT_SECONDS}"

export RESULT_TASK_DIR RESULT_MODEL_LABEL MAX_CONTEXT_LEN RKNN_CORE_NUM
python3 - <<'PY'
import json
import os
from pathlib import Path

p = Path(os.environ["RESULT_TASK_DIR"]) / "task_result.json"
if not p.is_file():
    raise SystemExit(0)
data = json.loads(p.read_text(encoding="utf-8"))
data["report_meta"] = {
    "model_name": os.environ.get("RESULT_MODEL_LABEL", ""),
    "max_context_len": int(os.environ.get("MAX_CONTEXT_LEN", "0")),
    "rknn_core_num": int(os.environ.get("RKNN_CORE_NUM", "0")),
}
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
PY

echo "Pulling logs to '${RESULT_TASK_DIR}/logs'..."
if ! python3 -m host_control pull \
  --device-source "${DEVICE_SESSION_REL}/logs" \
  --host-dest "${RESULT_TASK_DIR}/logs"; then
  echo "Warning: failed to pull logs for ${TASK_ID}" >&2
fi

TASK_RESULT_PATH="${RESULT_TASK_DIR}/task_result.json"
if [[ "${NO_SUMMARIZE}" == "0" ]]; then
  if [[ -f "${TASK_RESULT_PATH}" ]]; then
    echo "Generating summary report..."
    python3 -m host_control summarize \
      --task-result "${TASK_RESULT_PATH}" \
      --output "${RESULT_TASK_DIR}/summary.md"
  else
    echo "Warning: task_result.json not found, skip summarize: ${TASK_RESULT_PATH}" >&2
  fi
fi

if [[ "${CLEANUP_ON_DEVICE}" == "1" ]]; then
  echo "Cleaning up task session on device..."
  python3 -m host_control uart \
    --port "${PORT}" \
    --baudrate "${BAUDRATE}" \
    cleanup_task --task-id "${TASK_ID}"
fi

echo "Done."
echo "- task_id: ${TASK_ID}"
echo "- result model label: ${RESULT_MODEL_LABEL}"
echo "- result dir: ${RESULT_TASK_DIR}"
echo "- request: ${REQUEST_JSON_PATH}"
if [[ "${NO_SUMMARIZE}" == "0" ]]; then
  echo "- summary: ${RESULT_TASK_DIR}/summary.md"
fi
