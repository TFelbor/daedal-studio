"""How a blueprint is specified: its prompt, its seed, and what to record about it.

Split out of `visualizer.py` because none of it needs torch or diffusers. The pipeline,
the server and the test suite all have reason to reason about seeds and prompts, and
importing a 4B-parameter model's dependency stack to compute a random integer makes
that impossible on any machine without the Phase 1 environment installed.
"""

from __future__ import annotations

import dataclasses
import random
from pathlib import Path
from typing import Any, Dict

# Upper bound for a generated seed. torch accepts a much wider range, but 2**32 keeps
# the value readable, JSON-safe and re-enterable by hand.
SEED_SPACE = 2 ** 32


def engineer_prompt(prompt: str) -> str:
    """Wrap a user prompt in the clay-render keywords Phase 2 depends on.

    TripoSR infers shape from shading, so the blueprint has to look like a matte studio
    render rather than a photograph. The user never sees this string, which is exactly
    why it has to be recorded: the prompt on the telemetry row is not the prompt the
    model received, and a change to this wrapper would otherwise be invisible in the
    dataset — every result before and after it would look like the same experiment.

    Args:
        prompt: The user's prompt.

    Returns:
        The full prompt sent to the diffusion model.
    """
    return (
        f"3d blender render of {prompt}, "
        "neutral background, high fidelity, 8k, soft studio lighting, "
        "solid object, thick solid geometry, smooth curves, clay material"
    )


def resolve_seed(seed: int | None = None) -> int:
    """Return the seed to generate with, drawing one if none was supplied.

    Drawn from `SystemRandom` rather than the wall clock. The previous implementation
    used ``int(time.time())``, which hands every job started in the same second the
    same image and makes the seed useless both as an identifier and as a control.

    Args:
        seed: An explicit seed, or None to draw one.

    Returns:
        The seed to use.
    """
    if seed is not None:
        return int(seed)
    return random.SystemRandom().randrange(SEED_SPACE)


@dataclasses.dataclass
class BlueprintResult:
    """Everything needed to reproduce a blueprint, returned alongside the image."""

    path: Path
    """Where the image was written."""

    seed: int
    """The seed used. Reusing it with the same prompt and params repeats the image."""

    prompt: str
    """The user's prompt."""

    engineered_prompt: str
    """The full string actually fed to the model."""

    params: Dict[str, Any]
    """Conditioning settings: steps, guidance scale, width, height."""

    duration_s: float
    """Wall-clock generation seconds."""

    model_id: str
    """The model that produced the image."""
