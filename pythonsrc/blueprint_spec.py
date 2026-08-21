"""How a blueprint is specified: its prompt, its seed, and what to record about it.

Split out of `visualizer.py` because none of it needs torch or diffusers. The pipeline,
the server and the test suite all have reason to reason about seeds and prompts, and
importing a 4B-parameter model's dependency stack to compute a random integer makes
that impossible on any machine without the Phase 1 environment installed.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import random
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("p2p.blueprint_spec")

# Upper bound for a generated seed. torch accepts a much wider range, but 2**32 keeps
# the value readable, JSON-safe and re-enterable by hand.
SEED_SPACE = 2 ** 32


def engineer_prompt(prompt: str) -> str:
    """Wrap a user prompt in the clay-render keywords Phase 2 depends on.

    Phase 2 reconstructs a single object cut out from its background, so the blueprint
    has to look like one matte studio render rather than a photograph of a scene. This
    wrapper survived the move from TripoSR to TRELLIS.2 but the reason changed:
    TripoSR needed the shading, whereas TRELLIS.2 needs a clean subject its background
    remover can isolate and no second object to choose between.

    The user never sees this string, which is exactly why it has to be recorded: the
    prompt on the telemetry row is not the prompt the model received, and a change to
    this wrapper would otherwise be invisible in the dataset — every result before and
    after it would look like the same experiment.

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


# ── Provenance sidecar ────────────────────────────────────────────────────────
#
# The primary Mac workflow runs Phase 1 as its own native process and the rest of
# the pipeline in Docker with --skip-visualizer. The BlueprintResult — seed,
# engineered prompt, conditioning — used to die with the visualizer process, so
# every job on that path recorded only an image hash. The sidecar is how the
# result crosses the process boundary: the visualizer writes it next to the PNG,
# the pipeline reads it back and records it as if Phase 1 had run in-process.

SIDECAR_SUFFIX = ".provenance.json"


def sidecar_path_for(image_path: str | Path) -> Path:
    """Where an image's provenance sidecar lives.

    Args:
        image_path: The blueprint PNG.

    Returns:
        The sidecar path, e.g. `blueprint.provenance.json` beside `blueprint.png`.
    """
    image_path = Path(image_path)
    return image_path.with_name(image_path.stem + SIDECAR_SUFFIX)


def file_sha256(path: str | Path) -> str | None:
    """Hash a file's contents, or None when it cannot be read."""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        logger.warning("Could not hash %s: %s", path, exc)
        return None


def write_sidecar(result: BlueprintResult) -> Path | None:
    """Write a blueprint's provenance next to its image.

    The image's hash is stored inside, because the blueprint path is *shared*:
    the next run may overwrite the PNG and leave the sidecar behind, and a seed
    attributed to an image it did not produce is worse than no seed at all.

    Args:
        result: The visualizer's result for the image at `result.path`.

    Returns:
        The sidecar path written, or None when writing failed (best-effort:
        provenance must never fail a generation that succeeded).
    """
    sidecar = sidecar_path_for(result.path)
    try:
        payload = {
            "image_sha256": file_sha256(result.path),
            "seed": result.seed,
            "prompt": result.prompt,
            "engineered_prompt": result.engineered_prompt,
            "params": result.params,
            "duration_s": result.duration_s,
            "model_id": result.model_id,
        }
        with open(sidecar, "w") as handle:
            json.dump(payload, handle, indent=2)
        return sidecar
    except OSError as exc:
        logger.warning("Could not write the blueprint sidecar %s: %s", sidecar, exc)
        return None


def read_sidecar(image_path: str | Path) -> BlueprintResult | None:
    """Read an image's provenance sidecar, if it describes *this* image.

    Args:
        image_path: The blueprint PNG.

    Returns:
        The reconstructed BlueprintResult, or None when there is no sidecar,
        it is unreadable, or it was written for a different image than the one
        now sitting at the path.
    """
    sidecar = sidecar_path_for(image_path)
    if not sidecar.exists():
        return None
    try:
        with open(sidecar) as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable blueprint sidecar %s: %s", sidecar, exc)
        return None

    recorded = payload.get("image_sha256")
    if not recorded or recorded != file_sha256(image_path):
        logger.warning(
            "Ignoring stale blueprint sidecar %s — it describes a different image.",
            sidecar,
        )
        return None

    try:
        return BlueprintResult(
            path=Path(image_path),
            seed=int(payload["seed"]),
            prompt=payload.get("prompt", ""),
            engineered_prompt=payload.get("engineered_prompt", ""),
            params=payload.get("params") or {},
            duration_s=float(payload.get("duration_s") or 0.0),
            model_id=payload.get("model_id", ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Ignoring malformed blueprint sidecar %s: %s", sidecar, exc)
        return None
