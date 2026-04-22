#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  tools/run_infer_e2e.sh <mode> [options]

Modes:
  llm_single
  vlm_single
  benchmark_batch

Common options:
  --task-id <id>                 Task id (default: <mode>_YYYYmmdd_HHMMSS)
  --port <uart_port>             UART device (default: /dev/ttyUSB0)
  --baudrate <int>               UART baudrate (default: 1500000)
  --collect-seconds <int>        Max wait for task terminal lifecycle (default: 180)
  --max-new-tokens <int>         Runtime max_new_tokens (mode default)
  --max-context-len <int>        Runtime max_context_len (mode default)
  --no-summarize                 Skip summary report generation
  --cleanup-on-device            Send cleanup_task after pull
  --result-label <name>          Host results folder name (default: derived from --llm-model-src basename)

Environment:
  PCIE_DEVICE_SELECT             pcie_file_share_rc menu index when multiple EPs exist (default: 1)

LLM mode options:
  --llm-model-src <path>         Required
  --prompt <text>                Required

VLM mode options:
  --llm-model-src <path>         Required
  --vision-model-src <path>      Required
  --image-src <path>             Required
  --prompt <text>                Required
  --rknn-core-num <int>          Default: 3
  --img-start <token>            Default: <|vision_start|>
  --img-end <token>              Default: <|vision_end|>
  --img-content <token>          Default: <|image_pad|>

Benchmark mode options:
  --llm-model-src <path>         Required
  --vision-model-src <path>      Required when --include-vlm is set
  --include-text                 Include text prompts
  --include-vlm                  Include vlm tasks
                                 (if neither include flag is set, both are enabled)
  --text-prompts <json>          Default: host_control/benchmark_assets/prompts/text_prompts.json
  --vlm-tasks <json>             Default: host_control/benchmark_assets/prompts/vlm_tasks.json
  --images-root <dir>            Default: host_control/benchmark_assets
  --rknn-core-num <int>          Default: 3
  --img-start <token>            Default: <|vision_start|>
  --img-end <token>              Default: <|vision_end|>
  --img-content <token>          Default: <|image_pad|>

Examples:
  tools/run_infer_e2e.sh llm_single \
    --llm-model-src /abs/path/to/model.rkllm \
    --prompt "Please introduce yourself."

  tools/run_infer_e2e.sh vlm_single \
    --llm-model-src /abs/path/to/model.rkllm \
    --vision-model-src /abs/path/to/vision.rknn \
    --image-src /abs/path/to/image.jpg \
    --prompt "Describe this image."

  tools/run_infer_e2e.sh benchmark_batch \
    --llm-model-src /abs/path/to/model.rkllm \
    --vision-model-src /abs/path/to/vision.rknn \
    --include-text --include-vlm
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
PORT="/dev/ttyUSB0"
BAUDRATE="1500000"
COLLECT_SECONDS="180"
MAX_NEW_TOKENS=""
MAX_CONTEXT_LEN=""
RKNN_CORE_NUM="3"
IMG_START="<|vision_start|>"
IMG_END="<|vision_end|>"
IMG_CONTENT="<|image_pad|>"
NO_SUMMARIZE="0"
CLEANUP_ON_DEVICE="0"
RESULT_MODEL_LABEL=""

LLM_MODEL_SRC=""
VISION_MODEL_SRC=""
IMAGE_SRC=""
PROMPT=""

INCLUDE_TEXT="0"
INCLUDE_VLM="0"
TEXT_PROMPTS="${REPO_ROOT}/host_control/benchmark_assets/prompts/text_prompts.json"
VLM_TASKS="${REPO_ROOT}/host_control/benchmark_assets/prompts/vlm_tasks.json"
IMAGES_ROOT="${REPO_ROOT}/host_control/benchmark_assets"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task-id)
      TASK_ID="$2"
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
    --max-new-tokens)
      MAX_NEW_TOKENS="$2"
      shift 2
      ;;
    --max-context-len)
      MAX_CONTEXT_LEN="$2"
      shift 2
      ;;
    --rknn-core-num)
      RKNN_CORE_NUM="$2"
      shift 2
      ;;
    --img-start)
      IMG_START="$2"
      shift 2
      ;;
    --img-end)
      IMG_END="$2"
      shift 2
      ;;
    --img-content)
      IMG_CONTENT="$2"
      shift 2
      ;;
    --llm-model-src)
      LLM_MODEL_SRC="$2"
      shift 2
      ;;
    --vision-model-src)
      VISION_MODEL_SRC="$2"
      shift 2
      ;;
    --image-src)
      IMAGE_SRC="$2"
      shift 2
      ;;
    --prompt)
      PROMPT="$2"
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
    --no-summarize)
      NO_SUMMARIZE="1"
      shift
      ;;
    --cleanup-on-device)
      CLEANUP_ON_DEVICE="1"
      shift
      ;;
    --result-label)
      RESULT_MODEL_LABEL="$2"
      shift 2
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

if [[ -z "${TASK_ID}" ]]; then
  TASK_ID="${MODE}_$(date +%Y%m%d_%H%M%S)"
fi

if [[ -z "${MAX_NEW_TOKENS}" ]]; then
  if [[ "${MODE}" == "llm_single" ]]; then
    MAX_NEW_TOKENS="512"
  else
    MAX_NEW_TOKENS="1024"
  fi
fi

if [[ -z "${MAX_CONTEXT_LEN}" ]]; then
  if [[ "${MODE}" == "llm_single" ]]; then
    MAX_CONTEXT_LEN="2048"
  else
    MAX_CONTEXT_LEN="4096"
  fi
fi

case "${MODE}" in
  llm_single)
    if [[ -z "${LLM_MODEL_SRC}" || -z "${PROMPT}" ]]; then
      echo "llm_single requires --llm-model-src and --prompt" >&2
      exit 1
    fi
    ;;
  vlm_single)
    if [[ -z "${LLM_MODEL_SRC}" || -z "${VISION_MODEL_SRC}" || -z "${IMAGE_SRC}" || -z "${PROMPT}" ]]; then
      echo "vlm_single requires --llm-model-src --vision-model-src --image-src --prompt" >&2
      exit 1
    fi
    ;;
  benchmark_batch)
    if [[ -z "${LLM_MODEL_SRC}" ]]; then
      echo "benchmark_batch requires --llm-model-src" >&2
      exit 1
    fi
    if [[ "${INCLUDE_TEXT}" == "0" && "${INCLUDE_VLM}" == "0" ]]; then
      INCLUDE_TEXT="1"
      INCLUDE_VLM="1"
    fi
    if [[ "${INCLUDE_VLM}" == "1" && -z "${VISION_MODEL_SRC}" ]]; then
      echo "benchmark_batch with --include-vlm requires --vision-model-src" >&2
      exit 1
    fi
    ;;
esac

if [[ -z "${RESULT_MODEL_LABEL}" ]]; then
  export _E2E_LLM_MODEL_SRC="${LLM_MODEL_SRC}"
  RESULT_MODEL_LABEL="$(
    PYTHONPATH="${REPO_ROOT}" python3 -c \
      'from pathlib import Path; import os; from host_control.common import derive_result_model_label_from_llm_path; print(derive_result_model_label_from_llm_path(Path(os.environ["_E2E_LLM_MODEL_SRC"]).resolve()))'
  )"
  unset _E2E_LLM_MODEL_SRC
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found" >&2
  exit 1
fi
if ! command -v pcie_file_share_rc >/dev/null 2>&1; then
  echo "pcie_file_share_rc not found" >&2
  exit 1
fi

cd "${REPO_ROOT}"

TMP_DIR="$(mktemp -d -t vnpu_e2e_XXXXXX)"
cleanup_tmp() {
  rm -rf "${TMP_DIR}"
}
trap cleanup_tmp EXIT

REQUEST_JSON_PATH="${TMP_DIR}/request.json"
MANIFEST_TSV_PATH="${TMP_DIR}/upload_manifest.tsv"
DEVICE_SESSION_REL="vnpu_llm/sessions/${TASK_ID}"
PCIE_DEVICE_SELECT="${PCIE_DEVICE_SELECT:-1}"

export MODE
export TASK_ID
export REQUEST_JSON_PATH
export MANIFEST_TSV_PATH
export DEVICE_SESSION_REL
export PCIE_DEVICE_SELECT
export LLM_MODEL_SRC
export VISION_MODEL_SRC
export IMAGE_SRC
export PROMPT
export MAX_NEW_TOKENS
export MAX_CONTEXT_LEN
export RKNN_CORE_NUM
export IMG_START
export IMG_END
export IMG_CONTENT
export INCLUDE_TEXT
export INCLUDE_VLM
export TEXT_PROMPTS
export VLM_TASKS
export IMAGES_ROOT

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
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{field} does not exist: {path}")
    return path


def resolve_dir(raw: str, field: str) -> Path:
    value = raw.strip()
    if not value:
        raise ValueError(f"Missing required field: {field}")
    path = Path(value).expanduser().resolve()
    if not path.exists() or not path.is_dir():
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
manifest_path = Path(env("MANIFEST_TSV_PATH"))
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
    llm_model = resolve_file(env("LLM_MODEL_SRC"), "--llm-model-src")
    prompt = env("PROMPT")
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
    llm_model = resolve_file(env("LLM_MODEL_SRC"), "--llm-model-src")
    vision_model = resolve_file(env("VISION_MODEL_SRC"), "--vision-model-src")
    image_src = resolve_file(env("IMAGE_SRC"), "--image-src")
    prompt = env("PROMPT")

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
    include_text = env("INCLUDE_TEXT") == "1"
    include_vlm = env("INCLUDE_VLM") == "1"
    if not include_text and not include_vlm:
        include_text = True
        include_vlm = True

    llm_model = resolve_file(env("LLM_MODEL_SRC"), "--llm-model-src")
    llm_name = llm_model.name
    add_upload(llm_model, f"{device_session_rel}/models/{llm_name}")

    model_block = {"llm_model": f"models/{llm_name}"}
    if include_vlm:
        vision_model = resolve_file(env("VISION_MODEL_SRC"), "--vision-model-src")
        vision_name = vision_model.name
        add_upload(vision_model, f"{device_session_rel}/models/{vision_name}")
        model_block["vision_model"] = f"models/{vision_name}"

    subtasks: list[dict] = []
    if include_text:
        text_prompts = resolve_file(env("TEXT_PROMPTS"), "--text-prompts")
        for item in read_json_list(text_prompts, "--text-prompts"):
            prompt = str(item.get("prompt", "")).strip()
            if prompt:
                subtasks.append({"type": "llm", "prompt": prompt})

    if include_vlm:
        vlm_tasks = resolve_file(env("VLM_TASKS"), "--vlm-tasks")
        images_root = resolve_dir(env("IMAGES_ROOT"), "--images-root")
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
            if not source_image.exists() or not source_image.is_file():
                raise FileNotFoundError(f"Benchmark image is missing: {raw_image}")

            staged_name = f"img_{idx:03d}_{source_image.name}"
            add_upload(source_image, f"{device_session_rel}/inputs/{staged_name}")
            subtasks.append({
                "type": "vlm",
                "image": f"inputs/{staged_name}",
                "prompt": prompt,
            })

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
        },
        "subtasks": subtasks,
    }
    if not subtasks:
        raise ValueError("benchmark_batch generated empty subtasks; check prompt/task JSON inputs")
else:
    raise ValueError(f"Unsupported mode: {mode}")

request_json_path.parent.mkdir(parents=True, exist_ok=True)
request_json_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
add_upload(request_json_path, f"{device_session_rel}/request.json")

manifest_path.parent.mkdir(parents=True, exist_ok=True)
with manifest_path.open("w", encoding="utf-8") as fp:
    for src, dst in uploads:
        fp.write(f"{src}\t{dst}\n")

print(f"Prepared request + upload manifest: {request_json_path}")
print(f"Upload files: {len(uploads)}")
PY

echo "Submitting task '${TASK_ID}' to '${DEVICE_SESSION_REL}' via PCIe..."
echo "  pcie device index (PCIE_DEVICE_SELECT): ${PCIE_DEVICE_SELECT}"
exec 3< "${MANIFEST_TSV_PATH}"
while IFS=$'\t' read -r -u3 src dst; do
  if [[ -z "${src}" || -z "${dst}" ]]; then
    continue
  fi
  echo "  pcie set -> ${dst}"
  printf '%s\n' "${PCIE_DEVICE_SELECT}" | pcie_file_share_rc --set "${src}" "${dst}"
done
exec 3<&-

RESULT_TASK_DIR="${REPO_ROOT}/results/${RESULT_MODEL_LABEL}/${TASK_ID}"
mkdir -p "${RESULT_TASK_DIR}"

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
if [[ "${NO_SUMMARIZE}" == "0" ]]; then
  echo "- summary: ${RESULT_TASK_DIR}/summary.md"
fi
