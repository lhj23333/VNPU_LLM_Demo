import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class DemoLaunchSpec:
    command: List[str]
    prompt: str
    cwd: Path
    #: When True, child sees VNPU_LLM_INITDRAM_GATE and blocks until host samples VmRSS (LLM-only init).
    init_dram_gate: bool = True


class DemoLauncher:
    def __init__(self, runtime_base_dir: Path):
        self.runtime_base_dir = runtime_base_dir

    def _env(self) -> Dict[str, str]:
        env = os.environ.copy()
        lib_path = str(self.runtime_base_dir / "lib")
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{lib_path}:{existing}" if existing else lib_path
        env["RKLLM_LOG_LEVEL"] = "1"
        return env

    def build_llm(
        self,
        model_path: Path,
        max_new_tokens: int,
        max_context_len: int,
        prompt: str,
        *,
        init_dram_gate: bool = True,
    ) -> DemoLaunchSpec:
        cmd = [
            str(self.runtime_base_dir / "bin" / "llm_demo"),
            str(model_path),
            str(int(max_new_tokens)),
            str(int(max_context_len)),
        ]
        return DemoLaunchSpec(command=cmd, prompt=prompt, cwd=self.runtime_base_dir, init_dram_gate=init_dram_gate)

    def build_vlm(
        self,
        image_path: Path,
        vision_model_path: Path,
        llm_model_path: Path,
        prompt: str,
        max_new_tokens: int,
        max_context_len: int,
        rknn_core_num: int,
        img_start: str,
        img_end: str,
        img_content: str,
        *,
        init_dram_gate: bool = True,
    ) -> DemoLaunchSpec:
        cmd = [
            str(self.runtime_base_dir / "bin" / "vlm_demo"),
            str(image_path),
            str(vision_model_path),
            str(llm_model_path),
            str(int(max_new_tokens)),
            str(int(max_context_len)),
            str(int(rknn_core_num)),
            img_start,
            img_end,
            img_content,
        ]
        return DemoLaunchSpec(command=cmd, prompt=prompt, cwd=self.runtime_base_dir, init_dram_gate=init_dram_gate)

    def launch(self, spec: DemoLaunchSpec) -> subprocess.Popen:
        env = self._env()
        if spec.init_dram_gate:
            env["VNPU_LLM_INITDRAM_GATE"] = "1"
        return subprocess.Popen(
            spec.command,
            cwd=spec.cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
