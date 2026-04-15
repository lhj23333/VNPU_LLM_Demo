from .text_engine import TextEngine
from .vlm_engine import VLMEngine


def create_engine(config, workspace_root):
    if config.type == "text":
        return TextEngine(config, workspace_root)
    if config.type == "vlm":
        return VLMEngine(config, workspace_root)
    raise ValueError(f"Unknown engine type: {config.type}")
