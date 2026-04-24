import argparse
import shutil
from pathlib import Path
import re

from .common import HOST_RUNTIME_BASE_DIR, REPO_ROOT, RUNTIME_BASE_SRC_DIR, ensure_dir


class RuntimeBaseBuilder:
    def __init__(self, output_dir: Path = HOST_RUNTIME_BASE_DIR):
        self.output_dir = output_dir
        self.third_party_root = REPO_ROOT / "third_party" / "rknn-llm"

    def _copy_tree(self, src: Path, dst: Path) -> None:
        if not src.exists() or not src.is_dir():
            raise FileNotFoundError(f"Required source directory is missing: {src}")
        ensure_dir(dst)
        shutil.copytree(src, dst, dirs_exist_ok=True)

    def _copy_required(self, src: Path, dst: Path) -> None:
        if not src.exists():
            raise FileNotFoundError(f"Required source is missing: {src}")
        ensure_dir(dst.parent)
        shutil.copy2(src, dst)

    def _resolve_runtime_libs(self) -> tuple[Path, Path]:
        librkllmrt = (
            self.third_party_root
            / "rkllm-runtime"
            / "Linux"
            / "librkllm_api"
            / "aarch64"
            / "librkllmrt.so"
        )
        librknnrt = (
            self.third_party_root
            / "examples"
            / "multimodal_model_demo"
            / "deploy"
            / "3rdparty"
            / "librknnrt"
            / "Linux"
            / "librknn_api"
            / "aarch64"
            / "librknnrt.so"
        )
        return librkllmrt, librknnrt

    def _patch_multimodal_cmake_include(self, cmake_file: Path) -> None:
        if not cmake_file.exists():
            return
        content = cmake_file.read_text(encoding="utf-8", errors="replace")
        patched = re.sub(
            r"include_directories\(src/image_enc\.h\s+\$\{LIBRKNNRT_INCLUDES\}\)",
            "include_directories(src ${LIBRKNNRT_INCLUDES})",
            content,
        )
        if patched != content:
            cmake_file.write_text(patched, encoding="utf-8")

    def build(self) -> Path:
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)

        ensure_dir(self.output_dir / "bin")
        ensure_dir(self.output_dir / "lib")
        ensure_dir(self.output_dir / "executor")
        ensure_dir(self.output_dir / "scripts")

        librkllmrt, librknnrt = self._resolve_runtime_libs()
        self._copy_required(librkllmrt, self.output_dir / "lib" / "librkllmrt.so")
        self._copy_required(librknnrt, self.output_dir / "lib" / "librknnrt.so")

        for src in (RUNTIME_BASE_SRC_DIR / "executor").glob("*.py"):
            self._copy_required(src, self.output_dir / "executor" / src.name)
        for src in (RUNTIME_BASE_SRC_DIR / "scripts").glob("*.sh"):
            self._copy_required(src, self.output_dir / "scripts" / src.name)

        # Stage minimal build sources to allow device-native compilation.
        build_src_root = self.output_dir / "_build_src" / "rknn-llm"
        ensure_dir(build_src_root)

        # 1) Text demo source (official rkllm_api_demo/deploy)
        self._copy_required(
            self.third_party_root / "examples" / "rkllm_api_demo" / "deploy" / "CMakeLists.txt",
            build_src_root / "examples" / "rkllm_api_demo" / "deploy" / "CMakeLists.txt",
        )
        self._copy_tree(
            self.third_party_root / "examples" / "rkllm_api_demo" / "deploy" / "src",
            build_src_root / "examples" / "rkllm_api_demo" / "deploy" / "src",
        )

        # 2) Multimodal demo source (official multimodal_model_demo/deploy)
        multimodal_deploy = self.third_party_root / "examples" / "multimodal_model_demo" / "deploy"
        self._copy_required(
            multimodal_deploy / "CMakeLists.txt",
            build_src_root / "examples" / "multimodal_model_demo" / "deploy" / "CMakeLists.txt",
        )
        self._copy_required(
            multimodal_deploy / "c_export.map",
            build_src_root / "examples" / "multimodal_model_demo" / "deploy" / "c_export.map",
        )
        self._copy_tree(
            multimodal_deploy / "src",
            build_src_root / "examples" / "multimodal_model_demo" / "deploy" / "src",
        )

        # 3) Runtime/build dependencies required by deploy CMakeLists
        self._copy_tree(
            multimodal_deploy / "3rdparty" / "opencv" / "opencv-linux-aarch64",
            build_src_root
            / "examples"
            / "multimodal_model_demo"
            / "deploy"
            / "3rdparty"
            / "opencv"
            / "opencv-linux-aarch64",
        )
        self._copy_tree(
            multimodal_deploy / "3rdparty" / "librknnrt" / "Linux" / "librknn_api" / "include",
            build_src_root
            / "examples"
            / "multimodal_model_demo"
            / "deploy"
            / "3rdparty"
            / "librknnrt"
            / "Linux"
            / "librknn_api"
            / "include",
        )
        self._copy_tree(
            multimodal_deploy / "3rdparty" / "librknnrt" / "Linux" / "librknn_api" / "aarch64",
            build_src_root
            / "examples"
            / "multimodal_model_demo"
            / "deploy"
            / "3rdparty"
            / "librknnrt"
            / "Linux"
            / "librknn_api"
            / "aarch64",
        )

        self._copy_tree(
            self.third_party_root / "rkllm-runtime" / "Linux" / "librkllm_api" / "include",
            build_src_root / "rkllm-runtime" / "Linux" / "librkllm_api" / "include",
        )
        self._copy_tree(
            self.third_party_root / "rkllm-runtime" / "Linux" / "librkllm_api" / "aarch64",
            build_src_root / "rkllm-runtime" / "Linux" / "librkllm_api" / "aarch64",
        )

        # Patch upstream multimodal CMake warning (header passed as include dir)
        self._patch_multimodal_cmake_include(
            build_src_root / "examples" / "multimodal_model_demo" / "deploy" / "CMakeLists.txt"
        )

        device_executor = self.output_dir / "executor" / "device_executor.py"
        device_executor.chmod(0o755)
        for script in (self.output_dir / "scripts").glob("*.sh"):
            script.chmod(0o755)

        return self.output_dir


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build dist/runtime_base for Device deployment")
    parser.add_argument(
        "--output",
        default=str(HOST_RUNTIME_BASE_DIR),
        help="Output runtime base directory (default: dist/runtime_base)",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    builder = RuntimeBaseBuilder(Path(args.output).resolve())
    built_path = builder.build()
    print(f"Runtime base built at: {built_path}")


if __name__ == "__main__":
    main()
