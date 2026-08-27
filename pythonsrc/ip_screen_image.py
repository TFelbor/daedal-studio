"""Screening the generated blueprint, before Phase 2 is billed for reconstructing it.

`ip_screen` reads the prompt. This reads the picture, because prompt filtering leaks:
"a chunky yellow lightning-mouse figurine, anime style" names nothing on the blocklist
and still renders something recognisable. The published work on this is unambiguous —
prompt rewriting is not an effective standalone guardrail and has to be paired with
something that inspects the output.

**No reference images are stored anywhere in this repo.** The comparison is
image-against-*text*: the curated terms from `ip_screen`'s blocklist are embedded as
strings and scored against the rendered image by a zero-shot vision-language model.
Caching reference crops of protected characters would improve recall and would mean
shipping the exact material this screen exists to keep out.

**Control labels are not optional.** A softmax over protected terms alone has no way to
say "this is just a vase" — every image matches whichever term is least wrong. The
neutral candidates are what let an ordinary object win.

**Licensing.** The weights carry a licence independent of the loader, and independent of
the repo's own tag. `openai/clip-vit-base-patch32` is the trap this project has already
walked into once in another form: the HF tag reads MIT, while the model card's
out-of-scope section says *"Any deployed use case of the model — whether commercial or
not — is currently out of scope."* Reading the tag is not reading the licence. The
default here is `google/siglip-base-patch16-224` — Apache-2.0, no out-of-scope clause,
natively supported by the pinned `transformers` so no `trust_remote_code`, and no new
dependency in `requirements-base.txt`. SigLIP **2** was considered and rejected for now:
transformers issue #43994 reports nonsensical `AutoModel`/pipeline output for
`siglip2-base-patch16-224`.

**Advisory by default.** The threshold has not been calibrated against real renders, and
a false positive that fails Phase 1 has no appeal — the person has already waited for
the blueprint. So the default is to *flag* for the human blueprint gate, and enforcing
is an explicit `$DS_IP_IMAGE_ENFORCEMENT=enforce`.

**Import placement matters.** This module is imported by the pipeline and the
visualizer, never at module scope in `server/app.py`: `infra/docker/server.Dockerfile`
installs no torch, no transformers and no numpy on a `python:3.10-slim` base, so an
import there takes the api-server image down at start-up. The heavy imports are inside
`_load_model` for the same reason, and because `PYTORCH_ENABLE_MPS_FALLBACK=1` must be
set before any `import torch` — a module that lands earlier in the import graph than
`pipeline.py`'s preamble breaks Phase 1 on Apple Silicon.
"""

from __future__ import annotations

import dataclasses
import functools
import logging
import os
import re
from typing import Any, List, Optional

from pythonsrc.ip_screen import load_blocklist

logger = logging.getLogger("ds.ip_screen_image")

#: Apache-2.0, commercial use permitted, no out-of-scope deployment clause, and
#: supported by the pinned transformers without `trust_remote_code`.
DEFAULT_MODEL_ID = "google/siglip-base-patch16-224"

#: Checkpoints that must never be loaded, with the reason. Matched after normalising,
#: so a revision pin, a host prefix or a case change cannot slip one past — the
#: licensing guard in this repo was already defeated once by a `repo@sha` spelling.
DENIED_MODEL_REPOS = {
    "openai/clip-vit-base-patch32":
        "the model card places all deployed use, commercial or not, out of scope",
    "openai/clip-vit-base-patch16":
        "the model card places all deployed use, commercial or not, out of scope",
    "openai/clip-vit-large-patch14":
        "the model card places all deployed use, commercial or not, out of scope",
    "openai/clip-vit-large-patch14-336":
        "the model card places all deployed use, commercial or not, out of scope",
    "briaai/rmbg-2.0": "CC BY-NC 4.0; a paid BRIA agreement is required",
    "briaai/rmbg-1.4": "CC BY-NC 4.0; a paid BRIA agreement is required",
}

#: Neutral candidates. Without something to lose against, every image "matches".
CONTROL_LABELS = (
    "a plain 3d clay render of an original object",
    "a 3d clay render of a vase",
    "a 3d clay render of a mechanical part",
    "a 3d clay render of an animal figurine",
    "a 3d clay render of a human figurine",
    "a 3d clay render of a geometric ornament",
    "a 3d clay render of a container or organiser",
    "a photograph of a room",
)

#: How the candidate is phrased. The blueprint is a clay render of one object, so the
#: candidates are phrased the same way — comparing a clay render against "a photo of
#: Pikachu" measures render style as much as subject.
_CANDIDATE_TEMPLATE = "a 3d clay render of {term}"

#: Score above which a protected candidate is acted on. Uncalibrated; see the module
#: docstring. Overridable so it can be tuned from pilot data without a redeploy.
SCORE_THRESHOLD = float(os.environ.get("DS_IP_IMAGE_THRESHOLD", "0.45"))

#: "advisory" flags; "enforce" refuses. Advisory until the threshold is calibrated.
DEFAULT_ENFORCEMENT = "advisory"


class BlueprintRefused(Exception):
    """Raised when a rendered blueprint is refused by the image screen.

    A distinct exception so `pipeline.py`'s Phase 1 handler can report it as a refusal
    rather than as a crash — `_phase_fail(1, ...)` turns it into a phase-1 error banner
    either way, but the message a person sees should say which happened.
    """


@dataclasses.dataclass(frozen=True)
class ImageVerdict:
    """What the image screen concluded about one render."""

    action: str
    """"allow", "flag", "block" or "not_checked"."""

    term: Optional[str]
    """The candidate that won, when it was a protected one."""

    score: float
    """Its score. 0.0 when nothing was measured."""

    reason: Optional[str]
    """Why the screen abstained, or what it saw. Always set for `not_checked` —
    an unexplained abstention is indistinguishable from a pass."""


def _normalise_repo(model_id: str) -> str:
    """Reduce a checkpoint reference to the repo it actually names.

    Strips a `@revision` pin, any host prefix, surrounding whitespace and case. The
    revision is deliberately discarded *for the licence check only*: pinning a commit
    does not change what the weights are.
    """
    candidate = (model_id or "").strip().casefold()
    candidate = candidate.split("@", 1)[0]
    candidate = re.sub(r"^(https?://)?(huggingface\.co|hf\.co)/", "", candidate)
    return candidate.strip("/")


def assert_permissive_vision_model(model_id: str) -> bool:
    """Refuse a checkpoint whose *weights* are not permissively licensed.

    Checks the outcome rather than the mechanism, the way `assert_permissive_matte`
    does: an upstream reshuffle or a well-meant config edit should fail the load rather
    than silently reverting to something encumbered.

    Args:
        model_id: The checkpoint reference, optionally `repo@revision`.

    Returns:
        True when the repo is not on the deny list.

    Raises:
        ValueError: If it is, naming the repo and the reason.
    """
    repo = _normalise_repo(model_id)
    if repo in DENIED_MODEL_REPOS:
        raise ValueError(
            f"{model_id!r} is not permissively licensed and must not be loaded: "
            f"{DENIED_MODEL_REPOS[repo]}. See THIRD-PARTY-NOTICES.md."
        )
    return True


def resolve_model_id() -> str:
    """The checkpoint to use, from `$DS_IP_MODEL_ID` or the permissive default.

    The override exists so a deployment can pin a revision; it is not a way to opt out
    of the licence check, so the configured value is checked rather than trusted.

    Returns:
        The model id, revision pin intact.

    Raises:
        ValueError: If the configured repo is on the deny list.
    """
    model_id = os.environ.get("DS_IP_MODEL_ID") or DEFAULT_MODEL_ID
    assert_permissive_vision_model(model_id)
    return model_id


@functools.lru_cache(maxsize=1)
def _protected_terms() -> tuple[str, ...]:
    return tuple(e["term"] for e in load_blocklist() if e.get("term"))


@functools.lru_cache(maxsize=1)
def candidate_labels() -> tuple[str, ...]:
    """Every text candidate the image is scored against, protected ones first.

    One source of truth with `ip_screen`: the terms Tier 1 refuses are the terms this
    looks for. All strings — a bytes or Path candidate here would mean someone had
    started caching reference images.
    """
    protected = tuple(_CANDIDATE_TEMPLATE.format(term=t) for t in _protected_terms())
    return protected + CONTROL_LABELS


_MODEL: Any = None
_MODEL_FAILED: Optional[str] = None


def reset_model_cache() -> None:
    """Drop the cached model handle. For tests, and for a deliberate reload."""
    global _MODEL, _MODEL_FAILED
    _MODEL = None
    _MODEL_FAILED = None


def _load_model():
    """Build the scorer. Heavy imports are deliberately inside this function.

    Returns:
        An object with `score(image) -> list[float]`, one score per candidate label,
        in `candidate_labels()` order.

    Raises:
        ImportError: When transformers or torch are unavailable.
    """
    import torch  # noqa: PLC0415
    from transformers import AutoModel, AutoProcessor  # noqa: PLC0415

    model_id = resolve_model_id()
    repo, _, revision = model_id.partition("@")
    kwargs = {"revision": revision} if revision else {}

    processor = AutoProcessor.from_pretrained(repo, **kwargs)
    model = AutoModel.from_pretrained(repo, **kwargs).eval()
    labels = list(candidate_labels())

    class _Scorer:
        def score(self, image) -> List[float]:
            inputs = processor(
                text=labels, images=image, padding="max_length", return_tensors="pt",
            )
            with torch.no_grad():
                outputs = model(**inputs)
            # SigLIP is trained with a sigmoid loss, so each candidate is an
            # independent probability rather than a distribution over the set. Taking
            # a softmax here would make the verdict depend on how many candidates are
            # in the list, which is a property of the blocklist's length and not of
            # the image.
            return torch.sigmoid(outputs.logits_per_image[0]).tolist()

    logger.info("Blueprint IP screen loaded %s (%d candidates).", model_id, len(labels))
    return _Scorer()


def _scorer():
    """The cached scorer, or None with the reason recorded."""
    global _MODEL, _MODEL_FAILED
    if _MODEL is not None:
        return _MODEL
    if _MODEL_FAILED is not None:
        return None
    try:
        _MODEL = _load_model()
        return _MODEL
    except Exception as exc:  # noqa: BLE001
        _MODEL_FAILED = str(exc)
        logger.warning(
            "Blueprint IP screen unavailable (%s) — renders will be reported as "
            "not checked rather than as clean.", exc,
        )
        return None


def enforcement() -> str:
    """"advisory" or "enforce", from `$DS_IP_IMAGE_ENFORCEMENT`."""
    value = (os.environ.get("DS_IP_IMAGE_ENFORCEMENT") or DEFAULT_ENFORCEMENT).strip().lower()
    return "enforce" if value == "enforce" else "advisory"


def screen_image(image) -> ImageVerdict:
    """Score one rendered blueprint against the protected-term candidates.

    Args:
        image: A PIL image, in memory. Screened *before* it is written: the path it
            would go to is the shared `data/inputs/blueprint.png`, which Phase 2 reads
            and which `resolve_job_artifact` serves as the blueprint for any job.

    Returns:
        An `ImageVerdict`. `not_checked` when the model is unavailable — never `allow`,
        because "nothing looked at this" and "this looks fine" are different facts and
        an empty result that reads as clean is the mistake the printability error
        envelope exists to prevent.
    """
    scorer = _scorer()
    if scorer is None:
        return ImageVerdict(
            action="not_checked", term=None, score=0.0,
            reason=_MODEL_FAILED or "The image screen model is not available.",
        )

    try:
        scores = list(scorer.score(image))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Blueprint IP screen failed while scoring: %s", exc)
        return ImageVerdict("not_checked", None, 0.0, f"Scoring failed: {exc}")

    labels = candidate_labels()
    if len(scores) != len(labels):
        return ImageVerdict(
            "not_checked", None, 0.0,
            f"The model returned {len(scores)} scores for {len(labels)} candidates.",
        )

    best_index = max(range(len(scores)), key=lambda i: scores[i])
    best_label, best_score = labels[best_index], float(scores[best_index])

    if best_label in CONTROL_LABELS:
        return ImageVerdict("allow", None, best_score, "Closest match is a neutral subject.")

    term = _protected_terms()[best_index]
    if best_score < SCORE_THRESHOLD:
        return ImageVerdict(
            "allow", None, best_score,
            f"Closest protected match was {term!r} at {best_score:.2f}, "
            f"below the {SCORE_THRESHOLD:.2f} threshold.",
        )

    action = "block" if enforcement() == "enforce" else "flag"
    return ImageVerdict(
        action=action,
        term=term,
        score=best_score,
        reason=(
            f"The rendered blueprint resembles {term!r} ({best_score:.2f}). "
            + ("Refused before reconstruction." if action == "block"
               else "Flagged for review before reconstruction.")
        ),
    )


def save_screened(image, output_path) -> ImageVerdict:
    """Screen a rendered blueprint, then write it — in that order, always.

    The order is the point. The path a blueprint is written to is the *shared*
    `data/inputs/blueprint.png`: it is what Phase 2 reads, what
    `server.app` checks for existence after native Phase 1, and what
    `resolve_job_artifact` falls back to as "the blueprint" for any job. A refused
    render saved "so we can look at it later" therefore becomes some other job's
    input. Nothing here writes before the verdict is in.

    A `flag` still writes. The threshold is uncalibrated, and a false positive that
    fails Phase 1 has no appeal — the flag travels with the image to the human
    blueprint gate instead. Only `enforce` mode raises.

    Args:
        image: The in-memory rendered image, anything with `.save(path)`.
        output_path: Where it goes if it is allowed.

    Returns:
        The verdict, so the caller can record it alongside the image's provenance.

    Raises:
        BlueprintRefused: When the screen is enforcing and the render is refused.
    """
    verdict = screen_image(image)
    if verdict.action == "block":
        logger.error("Blueprint refused by the image screen: %s", verdict.reason)
        raise BlueprintRefused(verdict.reason or "The rendered blueprint was refused.")

    if verdict.action == "flag":
        logger.warning("Blueprint flagged by the image screen: %s", verdict.reason)
    elif verdict.action == "not_checked":
        logger.info("Blueprint not screened: %s", verdict.reason)

    image.save(str(output_path))
    return verdict
