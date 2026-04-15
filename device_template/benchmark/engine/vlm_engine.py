import os

from .base_engine import BaseEngine


class VLMEngine(BaseEngine):
    def _build_cmd(self, **kwargs):
        bin_path = os.path.join(self.workspace_root, self.config.binary_path)
        vision_model = os.path.join(self.workspace_root, self.config.vision_model_path)
        llm_model = os.path.join(self.workspace_root, self.config.llm_model_path)

        image_path = kwargs.get("image_path")
        if not image_path:
            raise ValueError("VLM requires 'image_path' to be provided.")

        img_abs = os.path.join(self.workspace_root, image_path)
        if not os.path.isfile(img_abs):
            raise FileNotFoundError(f"Image not found: {img_abs}")

        # Official rknn-llm multimodal demo:
        #   ./demo image_path encoder_model_path llm_model_path max_new_tokens max_context_len rknn_core_num
        #       [img_start] [img_end] [img_content]
        cmd = [
            bin_path,
            img_abs,
            vision_model,
            llm_model,
            str(self.config.max_new_tokens),
            str(self.config.max_context_len),
            str(self.config.rknn_core_num),
        ]

        # Pass img token markers if provided.
        if self.config.img_start or self.config.img_end or self.config.img_content:
            cmd.append(str(self.config.img_start))
            cmd.append(str(self.config.img_end))
            cmd.append(str(self.config.img_content))

        return cmd

    def run(self, prompt: str, timeout: int = 300, image_path: str = "", **kwargs):
        if not image_path:
            raise ValueError("VLMEngine.run requires an 'image_path'.")

        return super().run(prompt, timeout=timeout, image_path=image_path, **kwargs)
