#!/usr/bin/env python3
import os
import argparse

from benchmark.runner import BenchmarkRunner


def setup_environment(workspace_root: str):
    """Device-side runtime env.

    New layout: runtime shared libraries live in ./lib (no third_party on device).
    """
    lib_dir = os.path.join(workspace_root, "lib")

    current_ld = os.environ.get("LD_LIBRARY_PATH", "")
    new_ld = lib_dir
    if current_ld:
        new_ld = f"{new_ld}:{current_ld}"

    os.environ["LD_LIBRARY_PATH"] = new_ld
    os.environ["RKLLM_LOG_LEVEL"] = os.environ.get("RKLLM_LOG_LEVEL", "1")


def main():
    parser = argparse.ArgumentParser(description="VNPU LLM/VLM Benchmark Framework")
    parser.add_argument(
        "--model",
        nargs="+",
        default=["all"],
        help="Specify models to benchmark. Use 'all' for all models.",
    )
    parser.add_argument(
        "--config",
        default="conf/models_config.json",
        help="Path to models configuration file.",
    )

    args = parser.parse_args()

    workspace_root = os.path.dirname(os.path.abspath(__file__))
    setup_environment(workspace_root)

    config_path = os.path.join(workspace_root, args.config)
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found at {config_path}")
        return

    runner = BenchmarkRunner(workspace_root, config_path)
    if "all" in args.model:
        runner.run_all()
    else:
        runner.run_all(args.model)


if __name__ == "__main__":
    main()
