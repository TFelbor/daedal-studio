"""Utility functions for platform and execution strategy detection."""

import sys
import shutil
import subprocess
from typing import Literal

def _docker_has_nvidia_runtime() -> bool:
    """Check if Docker has the NVIDIA runtime available."""
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.Runtimes}}"],
            capture_output=True,
            text=True,
            check=True,
            timeout=3.0
        )
        return "nvidia" in result.stdout.lower()
    except Exception:
        return False

def get_execution_strategy() -> Literal["mps_native", "nvidia_docker", "cpu_docker"]:
    """Detect the best available execution strategy for Phase 1.

    Evaluates system capabilities to choose between native Apple Silicon MPS,
    NVIDIA GPU Docker, or CPU Docker fallback.

    This does *not* decide where Phase 2 runs. TRELLIS.2 is CUDA-only, so
    `cpu_docker` and `mps_native` hosts cannot run it in-process at all and reach
    it through the GPU worker instead. That choice belongs to
    `sculptors.resolve_backend_name`, which reads a worker URL this function knows
    nothing about.

    Returns:
        The selected execution strategy ("mps_native", "nvidia_docker", or "cpu_docker").
    """
    if sys.platform == "darwin":
        try:
            import torch
            if torch.backends.mps.is_available():
                return "mps_native"
        except ImportError:
            pass

    if shutil.which("nvidia-smi") is not None and _docker_has_nvidia_runtime():
        return "nvidia_docker"

    return "cpu_docker"

def get_phase1_command(prompt: str, output_path: str, steps: int = 4) -> list[str]:
    """Return the correct shell command for Phase 1 based on execution strategy.

    Args:
        prompt: The text prompt for generation.
        output_path: Path where the output image should be saved.
        steps: Number of inference steps for the model.

    Returns:
        A list of command-line arguments to execute Phase 1.
    """
    strategy = get_execution_strategy()
    
    if strategy == "mps_native":
        return ["bash", "run_phase1_native.sh", prompt]
    elif strategy == "nvidia_docker":
        # Docker compose run command with GPU override for the full pipeline
        return [
            "docker", "compose", 
            "-f", "infra/docker-compose.yml", 
            "-f", "infra/docker-compose.gpu.yml",
            "run", "--rm", "pipeline-runner", 
            "python", "pythonsrc/pipeline.py", prompt
        ]
    else:
        # Docker compose run command without GPU override for the full pipeline
        return [
            "docker", "compose", 
            "-f", "infra/docker-compose.yml",
            "run", "--rm", "pipeline-runner", 
            "python", "pythonsrc/pipeline.py", prompt
        ]
