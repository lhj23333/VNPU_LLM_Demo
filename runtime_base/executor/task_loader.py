from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class LoadedTask:
    raw: Dict[str, Any]

    @property
    def task_id(self) -> str:
        return str(self.raw["task_id"])

    @property
    def mode(self) -> str:
        return str(self.raw["mode"])

    @property
    def model(self) -> Dict[str, Any]:
        return dict(self.raw.get("model", {}))

    @property
    def input(self) -> Dict[str, Any]:
        return dict(self.raw.get("input", {}))

    @property
    def runtime(self) -> Dict[str, Any]:
        return dict(self.raw.get("runtime", {}))

    @property
    def subtasks(self) -> List[Dict[str, Any]]:
        raw_subtasks = self.raw.get("subtasks", [])
        return [dict(item) for item in raw_subtasks]


class TaskLoader:
    REQUIRED_FIELDS = {
        "llm_single": ("task_id", "mode", "model", "input", "runtime"),
        "vlm_single": ("task_id", "mode", "model", "input", "runtime"),
        "benchmark_batch": ("task_id", "mode", "model", "runtime", "subtasks"),
    }

    def __init__(self, session_dir: Path):
        self.session_dir = session_dir

    def _validate_common(self, data: Dict[str, Any]) -> None:
        mode = data.get("mode")
        if mode not in self.REQUIRED_FIELDS:
            raise ValueError(f"Unsupported task mode: {mode}")
        for field in self.REQUIRED_FIELDS[mode]:
            if field not in data:
                raise ValueError(f"request.json missing required field '{field}'")

    def _validate_model_paths(self, data: Dict[str, Any]) -> None:
        model = data["model"]
        mode = data["mode"]
        if mode == "llm_single":
            if "llm_model" not in model:
                raise ValueError("llm_single requires model.llm_model")
        elif mode == "vlm_single":
            if "vision_model" not in model or "llm_model" not in model:
                raise ValueError("vlm_single requires model.vision_model and model.llm_model")
        elif mode == "benchmark_batch":
            if "llm_model" not in model:
                raise ValueError("benchmark_batch requires model.llm_model")

        for key, rel_path in model.items():
            path = self.session_dir / str(rel_path)
            if not path.exists():
                raise FileNotFoundError(f"Model path does not exist ({key}): {path}")

    def _validate_inputs(self, data: Dict[str, Any]) -> None:
        mode = data["mode"]
        if mode == "vlm_single":
            image_rel = str(data["input"].get("image", "")).strip()
            if not image_rel:
                raise ValueError("vlm_single requires input.image")
            image_path = self.session_dir / image_rel
            if not image_path.exists():
                raise FileNotFoundError(f"input.image does not exist: {image_path}")
        if mode == "benchmark_batch":
            subtasks = data.get("subtasks", [])
            if not isinstance(subtasks, list) or not subtasks:
                raise ValueError("benchmark_batch requires non-empty subtasks[]")
            for index, subtask in enumerate(subtasks):
                sub_type = subtask.get("type")
                if sub_type == "llm":
                    if not str(subtask.get("prompt", "")).strip():
                        raise ValueError(f"subtasks[{index}] llm requires prompt")
                elif sub_type == "vlm":
                    image_rel = str(subtask.get("image", "")).strip()
                    prompt = str(subtask.get("prompt", "")).strip()
                    if not image_rel or not prompt:
                        raise ValueError(f"subtasks[{index}] vlm requires image and prompt")
                    image_path = self.session_dir / image_rel
                    if not image_path.exists():
                        raise FileNotFoundError(f"subtasks[{index}] image does not exist: {image_path}")
                else:
                    raise ValueError(f"subtasks[{index}] unsupported type: {sub_type}")

    def load(self) -> LoadedTask:
        request_path = self.session_dir / "request.json"
        if not request_path.exists():
            raise FileNotFoundError(f"request.json does not exist: {request_path}")
        with request_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        if not isinstance(data, dict):
            raise ValueError("request.json must be a JSON object")

        self._validate_common(data)
        self._validate_model_paths(data)
        self._validate_inputs(data)
        return LoadedTask(raw=data)
