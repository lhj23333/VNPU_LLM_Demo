import argparse
import shutil
import time
from pathlib import Path
from typing import Any

from .common import HOST_TASKS_DIR, ensure_dir, read_json, write_json


def _default_task_id(prefix: str) -> str:
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}"


class TaskBundleBuilder:
    def __init__(self, tasks_root: Path = HOST_TASKS_DIR):
        self.tasks_root = tasks_root

    def _prepare_task_dir(self, task_id: str) -> Path:
        task_dir = self.tasks_root / task_id
        if task_dir.exists():
            shutil.rmtree(task_dir)
        ensure_dir(task_dir / "models")
        ensure_dir(task_dir / "inputs")
        return task_dir

    @staticmethod
    def _copy_required(src: Path, dst: Path) -> None:
        if not src.exists():
            raise FileNotFoundError(f"Required file does not exist: {src}")
        ensure_dir(dst.parent)
        shutil.copy2(src, dst)

    def build_llm_single(
        self,
        task_id: str,
        llm_model_src: Path,
        prompt: str,
        max_new_tokens: int,
        max_context_len: int,
        llm_model_name: str | None = None,
    ) -> Path:
        task_dir = self._prepare_task_dir(task_id)
        model_name = llm_model_name or llm_model_src.name
        model_dst = task_dir / "models" / model_name
        self._copy_required(llm_model_src, model_dst)

        request = {
            "task_id": task_id,
            "mode": "llm_single",
            "model": {
                "llm_model": f"models/{model_name}",
            },
            "input": {
                "prompt": prompt,
            },
            "runtime": {
                "max_new_tokens": int(max_new_tokens),
                "max_context_len": int(max_context_len),
            },
        }
        write_json(task_dir / "request.json", request)
        return task_dir

    def build_vlm_single(
        self,
        task_id: str,
        vision_model_src: Path,
        llm_model_src: Path,
        image_src: Path,
        prompt: str,
        max_new_tokens: int,
        max_context_len: int,
        rknn_core_num: int,
        img_start: str,
        img_end: str,
        img_content: str,
        vision_model_name: str | None = None,
        llm_model_name: str | None = None,
        image_name: str | None = None,
    ) -> Path:
        task_dir = self._prepare_task_dir(task_id)
        vision_name = vision_model_name or vision_model_src.name
        llm_name = llm_model_name or llm_model_src.name
        input_image_name = image_name or image_src.name

        self._copy_required(vision_model_src, task_dir / "models" / vision_name)
        self._copy_required(llm_model_src, task_dir / "models" / llm_name)
        self._copy_required(image_src, task_dir / "inputs" / input_image_name)

        request = {
            "task_id": task_id,
            "mode": "vlm_single",
            "model": {
                "vision_model": f"models/{vision_name}",
                "llm_model": f"models/{llm_name}",
            },
            "input": {
                "image": f"inputs/{input_image_name}",
                "prompt": prompt,
            },
            "runtime": {
                "max_new_tokens": int(max_new_tokens),
                "max_context_len": int(max_context_len),
                "rknn_core_num": int(rknn_core_num),
                "img_start": img_start,
                "img_end": img_end,
                "img_content": img_content,
            },
        }
        write_json(task_dir / "request.json", request)
        return task_dir

    def build_benchmark_batch(
        self,
        task_id: str,
        llm_model_src: Path,
        text_prompts_path: Path | None,
        vlm_tasks_path: Path | None,
        images_root: Path,
        include_text: bool,
        include_vlm: bool,
        max_new_tokens: int,
        max_context_len: int,
        rknn_core_num: int,
        img_start: str,
        img_end: str,
        img_content: str,
        llm_model_name: str | None = None,
        vision_model_src: Path | None = None,
        vision_model_name: str | None = None,
    ) -> Path:
        if not include_text and not include_vlm:
            raise ValueError("At least one of include_text/include_vlm must be true")
        if include_text and text_prompts_path is None:
            raise ValueError("text_prompts_path is required when include_text=true")
        if include_vlm and vlm_tasks_path is None:
            raise ValueError("vlm_tasks_path is required when include_vlm=true")
        if include_vlm and vision_model_src is None:
            raise ValueError("vision_model_src is required when include_vlm=true")

        task_dir = self._prepare_task_dir(task_id)
        llm_name = llm_model_name or llm_model_src.name
        self._copy_required(llm_model_src, task_dir / "models" / llm_name)

        model_block: dict[str, Any] = {"llm_model": f"models/{llm_name}"}
        if include_vlm and vision_model_src is not None:
            vision_name = vision_model_name or vision_model_src.name
            self._copy_required(vision_model_src, task_dir / "models" / vision_name)
            model_block["vision_model"] = f"models/{vision_name}"

        subtasks: list[dict[str, Any]] = []
        if include_text:
            assert text_prompts_path is not None
            prompts = read_json(text_prompts_path)
            for item in prompts:
                prompt = str(item.get("prompt", "")).strip()
                if prompt:
                    subtasks.append({"type": "llm", "prompt": prompt})

        if include_vlm:
            assert vlm_tasks_path is not None
            vlm_tasks = read_json(vlm_tasks_path)
            for idx, item in enumerate(vlm_tasks, start=1):
                raw_image = str(item.get("image", "")).strip()
                prompt = str(item.get("prompt", "")).strip()
                if not raw_image or not prompt:
                    continue

                source_image = Path(raw_image)
                if not source_image.is_absolute():
                    source_image = images_root / source_image
                if not source_image.exists():
                    source_image = images_root / Path(raw_image).name
                if not source_image.exists():
                    raise FileNotFoundError(f"Benchmark image is missing: {raw_image}")

                staged_name = f"img_{idx:03d}_{source_image.name}"
                self._copy_required(source_image, task_dir / "inputs" / staged_name)
                subtasks.append(
                    {
                        "type": "vlm",
                        "image": f"inputs/{staged_name}",
                        "prompt": prompt,
                    }
                )

        request = {
            "task_id": task_id,
            "mode": "benchmark_batch",
            "model": model_block,
            "runtime": {
                "max_new_tokens": int(max_new_tokens),
                "max_context_len": int(max_context_len),
                "rknn_core_num": int(rknn_core_num),
                "img_start": img_start,
                "img_end": img_end,
                "img_content": img_content,
            },
            "subtasks": subtasks,
        }
        write_json(task_dir / "request.json", request)
        return task_dir


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build task bundle under host/tasks/")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    llm = subparsers.add_parser("llm_single")
    llm.add_argument("--task-id", default=_default_task_id("task"))
    llm.add_argument("--llm-model-src", required=True)
    llm.add_argument("--llm-model-name")
    llm.add_argument("--prompt", required=True)
    llm.add_argument("--max-new-tokens", type=int, default=512)
    llm.add_argument("--max-context-len", type=int, default=2048)

    vlm = subparsers.add_parser("vlm_single")
    vlm.add_argument("--task-id", default=_default_task_id("task"))
    vlm.add_argument("--vision-model-src", required=True)
    vlm.add_argument("--llm-model-src", required=True)
    vlm.add_argument("--vision-model-name")
    vlm.add_argument("--llm-model-name")
    vlm.add_argument("--image-src", required=True)
    vlm.add_argument("--image-name")
    vlm.add_argument("--prompt", required=True)
    vlm.add_argument("--max-new-tokens", type=int, default=1024)
    vlm.add_argument("--max-context-len", type=int, default=4096)
    vlm.add_argument("--rknn-core-num", type=int, default=3)
    vlm.add_argument("--img-start", default="<|vision_start|>")
    vlm.add_argument("--img-end", default="<|vision_end|>")
    vlm.add_argument("--img-content", default="<|image_pad|>")

    bench = subparsers.add_parser("benchmark_batch")
    bench.add_argument("--task-id", default=_default_task_id("bench"))
    bench.add_argument("--llm-model-src", required=True)
    bench.add_argument("--llm-model-name")
    bench.add_argument("--vision-model-src")
    bench.add_argument("--vision-model-name")
    bench.add_argument("--text-prompts", help="Required when --include-text (default bundle uses text+vlm)")
    bench.add_argument("--vlm-tasks", help="Required when --include-vlm (default bundle uses text+vlm)")
    bench.add_argument("--images-root", required=True)
    bench.add_argument("--include-text", action="store_true")
    bench.add_argument("--include-vlm", action="store_true")
    bench.add_argument("--max-new-tokens", type=int, default=1024)
    bench.add_argument("--max-context-len", type=int, default=4096)
    bench.add_argument("--rknn-core-num", type=int, default=3)
    bench.add_argument("--img-start", default="<|vision_start|>")
    bench.add_argument("--img-end", default="<|vision_end|>")
    bench.add_argument("--img-content", default="<|image_pad|>")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    builder = TaskBundleBuilder()

    if args.mode == "llm_single":
        output = builder.build_llm_single(
            task_id=args.task_id,
            llm_model_src=Path(args.llm_model_src).resolve(),
            llm_model_name=args.llm_model_name,
            prompt=args.prompt,
            max_new_tokens=args.max_new_tokens,
            max_context_len=args.max_context_len,
        )
    elif args.mode == "vlm_single":
        output = builder.build_vlm_single(
            task_id=args.task_id,
            vision_model_src=Path(args.vision_model_src).resolve(),
            llm_model_src=Path(args.llm_model_src).resolve(),
            vision_model_name=args.vision_model_name,
            llm_model_name=args.llm_model_name,
            image_src=Path(args.image_src).resolve(),
            image_name=args.image_name,
            prompt=args.prompt,
            max_new_tokens=args.max_new_tokens,
            max_context_len=args.max_context_len,
            rknn_core_num=args.rknn_core_num,
            img_start=args.img_start,
            img_end=args.img_end,
            img_content=args.img_content,
        )
    else:
        include_text = bool(args.include_text)
        include_vlm = bool(args.include_vlm)
        if not include_text and not include_vlm:
            include_text = True
            include_vlm = True

        vision_src = Path(args.vision_model_src).resolve() if args.vision_model_src else None
        text_path = Path(args.text_prompts).resolve() if args.text_prompts else None
        vlm_path = Path(args.vlm_tasks).resolve() if args.vlm_tasks else None
        output = builder.build_benchmark_batch(
            task_id=args.task_id,
            llm_model_src=Path(args.llm_model_src).resolve(),
            llm_model_name=args.llm_model_name,
            vision_model_src=vision_src,
            vision_model_name=args.vision_model_name,
            text_prompts_path=text_path,
            vlm_tasks_path=vlm_path,
            images_root=Path(args.images_root).resolve(),
            include_text=include_text,
            include_vlm=include_vlm,
            max_new_tokens=args.max_new_tokens,
            max_context_len=args.max_context_len,
            rknn_core_num=args.rknn_core_num,
            img_start=args.img_start,
            img_end=args.img_end,
            img_content=args.img_content,
        )

    print(f"Task bundle built at: {output}")


if __name__ == "__main__":
    main()
