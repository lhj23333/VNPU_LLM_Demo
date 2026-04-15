import json
import os


class ModelConfig:
    def __init__(self, name: str, data: dict):
        self.name = name
        self.type = data.get("type", "text")
        self.binary_path = data.get("binary_path", "")
        self.max_new_tokens = data.get("max_new_tokens", 512)
        self.max_context_len = data.get("max_context_len", 4096)

        # Text specific
        self.model_path = data.get("model_path", "")

        # VLM specific
        self.vision_model_path = data.get("vision_model_path", "")
        self.llm_model_path = data.get("llm_model_path", "")
        self.rknn_core_num = int(data.get("rknn_core_num", 3))
        self.img_start = data.get("img_start", "")
        self.img_end = data.get("img_end", "")
        self.img_content = data.get("img_content", "")

        # Optional: analytical KV size upper bound (see README / benchmark report footnote).
        self.kv_num_hidden_layers = data.get("kv_num_hidden_layers")
        self.kv_num_key_value_heads = data.get("kv_num_key_value_heads")
        self.kv_head_dim = data.get("kv_head_dim")
        self.kv_bytes_per_element = int(data.get("kv_bytes_per_element", 2))

    def validate(self, workspace_root: str):
        bin_path = os.path.join(workspace_root, self.binary_path)
        if not os.path.isfile(bin_path):
            raise FileNotFoundError(f"Binary not found: {bin_path}")

        if self.type == "text":
            m_path = os.path.join(workspace_root, self.model_path)
            if not os.path.isfile(m_path):
                print(f"[Warning] Model file not found (might need download): {m_path}")
        elif self.type == "vlm":
            v_path = os.path.join(workspace_root, self.vision_model_path)
            l_path = os.path.join(workspace_root, self.llm_model_path)
            if not os.path.isfile(v_path):
                print(f"[Warning] Vision model not found (might need download): {v_path}")
            if not os.path.isfile(l_path):
                print(f"[Warning] LLM model not found (might need download): {l_path}")


def load_config(config_path: str) -> dict:
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    ext = os.path.splitext(config_path)[1].lower()
    with open(config_path, "r", encoding="utf-8") as f:
        if ext == ".json":
            data = json.load(f)
        elif ext in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
            except Exception as e:
                raise RuntimeError(
                    "YAML config requires PyYAML. Install python3-yaml, or use a .json config instead."
                ) from e
            data = yaml.safe_load(f)
        else:
            # Default to JSON to avoid non-stdlib dependencies.
            data = json.load(f)

    models_data = data.get("models", {})
    models = {}
    for name, config_data in models_data.items():
        models[name] = ModelConfig(name, config_data)

    return models
