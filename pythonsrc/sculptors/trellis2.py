"""
trellis2.py — Phase 2 reconstruction with TRELLIS.2-4B (image → 3D).

TRELLIS.2 reconstructs geometry into a sparse "O-Voxel" latent rather than an
iso-surface field, so it keeps the sharp edges and thin walls that a
marching-cubes model smears away. Its native frame is already Z-up (see
`up_axis` below), which is what the Engineer and CuraEngine expect.

## Shape-only path

The upstream `Trellis2ImageTo3DPipeline.run()` always samples a *texture* latent
as well and returns a `MeshWithVoxel` carrying PBR attributes, which callers then
hand to `o_voxel.postprocess.to_glb()` for UV unwrapping and texture baking. An
FDM printer consumes geometry alone, so this backend drives the pipeline stages
itself and stops after shape decoding. That buys four things:

  * roughly 40% less GPU time per job (no texture flow model, no texture decode),
  * markedly less VRAM, and a smaller download — the texture DiT and decoder are
    never fetched, because `model_names_to_load` omits them,
  * no dependency on a rasterizer: `to_glb()` needs one and this path never
    touches it,
  * decimation on the GPU via `cumesh`, before the mesh is ever materialised as
    NumPy. A 1024³ reconstruction is millions of faces; handing that to trimesh
    first and decimating on the CPU afterwards costs minutes.

## Requirements

CUDA only, and not optional: `o_voxel`, `flex_gemm` and `cumesh` are compiled CUDA
extensions and the mesh helpers call `.cuda()` unconditionally. There is no CPU
fallback. On a machine without an NVIDIA GPU use the `remote` backend to reach a
GPU worker — see `services/trellis2_worker/`.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from .base import SculptorBackend, SculptorError

logger = logging.getLogger("p2p.sculptor.trellis2")

DEFAULT_MODEL_ID = "microsoft/TRELLIS.2-4B"

#: Voxel resolutions the upstream pipeline supports, in ascending cost order.
PIPELINE_TYPES = ("512", "1024", "1024_cascade", "1536_cascade")

#: Weights the shape-only path needs. Omitting the `tex_slat_*` entries is what
#: keeps the texture DiT and decoder from being downloaded or loaded at all —
#: `Pipeline.from_pretrained` skips any model not named here.
SHAPE_ONLY_MODELS = (
    "sparse_structure_flow_model",
    "sparse_structure_decoder",
    "shape_slat_flow_model_512",
    "shape_slat_flow_model_1024",
    "shape_slat_decoder",
)

#: Sparse-structure grid resolution per pipeline type, mirroring upstream `run()`.
_SS_RESOLUTION = {"512": 32, "1024": 64, "1024_cascade": 32, "1536_cascade": 32}


def _sampler_params(steps: int | None, guidance: float | None) -> dict:
    """Build a sampler-params dict containing only the knobs that were set."""
    params: dict = {}
    if steps is not None:
        params["steps"] = int(steps)
    if guidance is not None:
        params["guidance_strength"] = float(guidance)
    return params


class Trellis2Backend(SculptorBackend):
    """Reconstructs a mesh from a single image with TRELLIS.2-4B.

    Args:
        model_dir: Local weights directory or HuggingFace repo id. Defaults to
            `$TRELLIS2_MODEL_PATH` if it holds weights, else the HF repo.
        repo_path: Path to the TRELLIS.2 source checkout. Defaults to
            `$TRELLIS2_REPO_PATH`.
        pipeline_type: One of `PIPELINE_TYPES`. Higher resolutions capture finer
            detail at more GPU time; `1024_cascade` is upstream's default.
        seed: Sampling seed. The same seed and image reproduce the same mesh.
        ss_steps: Sparse-structure sampler steps, or None for the model default.
        shape_steps: Shape-latent sampler steps, or None for the model default.
        ss_guidance: Classifier-free guidance strength for the sparse structure,
            or None for the model default.
        shape_guidance: Classifier-free guidance strength for the shape latent, or
            None for the model default.
        gpu_simplify_target: Face budget applied on the GPU before the mesh leaves
            CUDA. Set 0 to hand the full-resolution mesh to trimesh.
        max_num_tokens: Token ceiling for cascade sampling. Upstream lowers the
            output resolution rather than exceeding it.

    Note:
        Background removal is upstream's: `preprocess_image` runs BiRefNet
        (`ZhengPeng7/BiRefNet`, MIT) and premultiplies the cut-out, which is how
        the model was trained. Phase 2 therefore no longer uses `rembg`/u2net —
        that was a TripoSR-specific grey-composite trick for shape-from-shading
        and it would fight this model's own preprocessing. BiRefNet is loaded with
        `trust_remote_code=True` by upstream; see THIRD-PARTY-NOTICES.md.
    """

    name = "trellis2"

    # TRELLIS.2 works in a Z-up frame: its orbit cameras use [0, 0, 1] as the up
    # vector, and `o_voxel.postprocess.to_glb` swaps Y/Z on the way out precisely
    # because glTF is Y-up and the model's own frame is not. So no rotation here.
    up_axis = "z"

    # Sharp features are the reason to run this model. Taubin smoothing would
    # round exactly the edges it recovers, so smoothing is off unless asked for.
    default_smooth_iterations = 0

    MODEL_NAME = "TRELLIS.2"
    BACKEND = "local"

    def __init__(
        self,
        model_dir: str | Path | None = None,
        repo_path: str | Path | None = None,
        *,
        pipeline_type: str | None = None,
        seed: int = 42,
        ss_steps: int | None = None,
        shape_steps: int | None = None,
        ss_guidance: float | None = None,
        shape_guidance: float | None = None,
        gpu_simplify_target: int = 200_000,
        max_num_tokens: int = 49_152,
    ) -> None:
        # Backstop for callers that reach this backend without going through
        # `pipeline.py` — the worker and the standalone CLI. `pipeline.py` sets both
        # at the top of the module instead, because the CUDA caching allocator reads
        # PYTORCH_CUDA_ALLOC_CONF when it initialises on the *first* CUDA
        # allocation, which in a full run is Phase 1. By the time this constructor
        # runs in that process, setting it here would already be too late.
        os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
        os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

        pipeline_type = pipeline_type or os.environ.get(
            "TRELLIS2_PIPELINE_TYPE", "1024_cascade"
        )
        if pipeline_type not in PIPELINE_TYPES:
            raise SculptorError(
                f"Invalid pipeline_type '{pipeline_type}' — expected one of "
                f"{', '.join(PIPELINE_TYPES)}"
            )

        self.pipeline_type = pipeline_type
        self.seed = seed
        self.ss_steps = ss_steps
        self.shape_steps = shape_steps
        self.ss_guidance = ss_guidance
        self.shape_guidance = shape_guidance
        self.gpu_simplify_target = gpu_simplify_target
        self.max_num_tokens = max_num_tokens

        self._ensure_importable(repo_path)

        import torch

        if not torch.cuda.is_available():
            raise SculptorError(
                "The 'trellis2' backend requires an NVIDIA GPU (~24 GB VRAM) and "
                "compiled CUDA extensions (o_voxel, flex_gemm, cumesh). No CUDA "
                "device is visible. Use the 'remote' backend to reach a GPU worker "
                "instead — see services/trellis2_worker/."
            )

        self.model_dir = self._resolve_model_dir(model_dir)
        self.MODEL_VERSION = str(self.model_dir)
        self.pipeline = self._load_pipeline()

    def describe(self) -> str:
        return f"trellis2 (pipeline_type={self.pipeline_type}, seed={self.seed})"

    def generation_params(self) -> dict:
        return {
            "sculptor_backend": self.name,
            "pipeline_type": self.pipeline_type,
            "mesh_seed": self.seed,
            "ss_steps": self.ss_steps,
            "shape_steps": self.shape_steps,
            "ss_guidance": self.ss_guidance,
            "shape_guidance": self.shape_guidance,
            "gpu_simplify_target": self.gpu_simplify_target,
            "max_num_tokens": self.max_num_tokens,
        }

    # ── Setup ────────────────────────────────────────────────────────────────

    @staticmethod
    def _ensure_importable(repo_path: str | Path | None) -> None:
        """Put the TRELLIS.2 checkout on sys.path and fail loudly if it is absent.

        The upstream repo is not pip-installable, so it is checked out alongside
        this project and located via `$TRELLIS2_REPO_PATH`.

        An explicitly configured path is authoritative: if it does not hold a
        checkout that is an error, not a cue to go looking elsewhere. Silently
        loading a different copy of a 4B-parameter model's source than the one that
        was named is the kind of thing nobody notices until the output is wrong.
        """
        configured = repo_path or os.environ.get("TRELLIS2_REPO_PATH")
        if configured:
            candidates = [Path(configured)]
        else:
            # Sibling checkout (../TRELLIS.2) is the layout the README documents.
            project_root = Path(__file__).resolve().parents[2]
            candidates = [
                project_root / "TRELLIS.2",
                project_root.parent / "TRELLIS.2",
                Path("/opt/TRELLIS.2"),
            ]

        for candidate in candidates:
            if (candidate / "trellis2" / "pipelines").is_dir():
                if str(candidate) not in sys.path:
                    sys.path.insert(0, str(candidate))
                    logger.debug("Added TRELLIS.2 checkout to sys.path: %s", candidate)
                return

        searched = ", ".join(str(c) for c in candidates)
        raise SculptorError(
            "Could not find a TRELLIS.2 checkout. Set TRELLIS2_REPO_PATH to the "
            f"directory containing trellis2/. Searched: {searched}"
        )

    @staticmethod
    def _resolve_model_dir(model_dir: str | Path | None) -> str | Path:
        """Prefer local weights (Docker volume / NVMe) over the HuggingFace repo."""
        if model_dir is not None:
            return model_dir
        env_path = os.environ.get("TRELLIS2_MODEL_PATH")
        if env_path and Path(env_path).is_dir() and any(Path(env_path).iterdir()):
            return Path(env_path)
        return DEFAULT_MODEL_ID

    def _load_pipeline(self):
        """Load the image-to-3D pipeline with the texture models left out."""
        from trellis2.pipelines import Trellis2ImageTo3DPipeline

        class _ShapeOnlyPipeline(Trellis2ImageTo3DPipeline):
            """Loads only the weights the shape path reads.

            `Pipeline.from_pretrained` consults `model_names_to_load` to decide what
            to fetch, so narrowing it here is what makes the texture DiT and decoder
            free rather than merely unused.
            """

            model_names_to_load = list(SHAPE_ONLY_MODELS)

        logger.info("Loading TRELLIS.2 (shape-only) from %s…", self.model_dir)
        pipeline = _ShapeOnlyPipeline.from_pretrained(str(self.model_dir))
        pipeline.cuda()
        return pipeline

    # ── Inference ────────────────────────────────────────────────────────────

    def reconstruct(self, image_path: str | Path) -> trimesh.Trimesh:
        import torch

        image = Image.open(image_path)
        with torch.no_grad():
            mesh = self._run_shape_only(image)
            if self.gpu_simplify_target and mesh.faces.shape[0] > self.gpu_simplify_target:
                logger.info(
                    "Simplifying on GPU %d → %d faces…",
                    mesh.faces.shape[0],
                    self.gpu_simplify_target,
                )
                mesh.simplify(self.gpu_simplify_target)
            result = self._to_trimesh(mesh)
        torch.cuda.empty_cache()
        logger.info(
            "Raw TRELLIS.2 geometry — %d vertices, %d faces",
            len(result.vertices),
            len(result.faces),
        )
        return result

    def _run_shape_only(self, image: Image.Image):
        """Drive the pipeline stages directly, stopping after shape decoding.

        Mirrors `Trellis2ImageTo3DPipeline.run()` minus the texture branch:
        image conditioning → sparse structure → shape latent → mesh.
        """
        import torch

        pipeline = self.pipeline
        pt = self.pipeline_type

        image = pipeline.preprocess_image(image)
        torch.manual_seed(self.seed)

        # Only keys the caller actually set are passed; the pipeline merges these
        # over the checkpoint's own sampler params, so an unset knob must be absent
        # rather than None.
        ss_params = _sampler_params(self.ss_steps, self.ss_guidance)
        shape_params = _sampler_params(self.shape_steps, self.shape_guidance)

        cond_512 = pipeline.get_cond([image], 512)
        cond_1024 = pipeline.get_cond([image], 1024) if pt != "512" else None

        coords = pipeline.sample_sparse_structure(
            cond_512, _SS_RESOLUTION[pt], 1, ss_params
        )

        if pt == "512":
            slat = pipeline.sample_shape_slat(
                cond_512,
                pipeline.models["shape_slat_flow_model_512"],
                coords,
                shape_params,
            )
            resolution = 512
        elif pt == "1024":
            slat = pipeline.sample_shape_slat(
                cond_1024,
                pipeline.models["shape_slat_flow_model_1024"],
                coords,
                shape_params,
            )
            resolution = 1024
        else:
            target = 1024 if pt == "1024_cascade" else 1536
            slat, resolution = pipeline.sample_shape_slat_cascade(
                cond_512,
                cond_1024,
                pipeline.models["shape_slat_flow_model_512"],
                pipeline.models["shape_slat_flow_model_1024"],
                512,
                target,
                coords,
                shape_params,
                self.max_num_tokens,
            )

        torch.cuda.empty_cache()
        logger.info("Decoding shape latent at %d³…", resolution)
        meshes, _subs = pipeline.decode_shape_slat(slat, resolution)
        if not meshes:
            raise SculptorError("TRELLIS.2 shape decoder returned no meshes")

        mesh = meshes[0]
        # O-Voxel handles open surfaces by design, but an FDM slicer needs a closed
        # solid, so boundary loops are stitched here rather than left to Phase 3.
        logger.info("Filling holes (CUDA)…")
        mesh.fill_holes()
        return mesh

    @staticmethod
    def _to_trimesh(mesh) -> trimesh.Trimesh:
        """Convert a TRELLIS.2 mesh's vertex/face tensors into a trimesh mesh."""
        vertices = mesh.vertices.detach().cpu().numpy().astype(np.float64)
        faces = mesh.faces.detach().cpu().numpy().astype(np.int64)
        return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
