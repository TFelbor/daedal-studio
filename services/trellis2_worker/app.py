"""
app.py — GPU sculptor worker.

Exposes the TRELLIS.2 backend over HTTP so the rest of the pipeline can run on a
machine without an NVIDIA GPU. Deploy this container on a GPU host (24 GB or
better) and point `P2P_SCULPTOR_REMOTE_URL` at it.

The worker returns *raw* geometry. Print post-processing — orientation, component
pruning, smoothing, decimation — stays on the client so there is exactly one
implementation of it, and so GPU seconds are not spent on CPU work. The coordinate
frame the mesh is in comes back in the `X-P2P-Up-Axis` header, which is what makes
that split safe.

Endpoints:
    GET  /health   readiness, GPU info, which model is loaded
    POST /sculpt   multipart image → raw mesh bytes

Run:
    uvicorn services.trellis2_worker.app:app --host 0.0.0.0 --port 8100
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from starlette import status

# The worker ships the project's own sculptor code rather than reimplementing it,
# so the mesh a remote job gets is produced by the same class a local job uses.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pythonsrc"))

from pythonsrc.sculptors import SculptorError, create_sculptor  # noqa: E402

logging.basicConfig(
    format="[%(levelname)s] %(name)s — %(message)s",
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
)
logger = logging.getLogger("p2p.worker")

WORKER_API_KEY = os.environ.get("P2P_WORKER_API_KEY", "").strip()
WORKER_BACKEND = os.environ.get("P2P_WORKER_BACKEND", "trellis2").strip().lower()
MESH_FORMAT = os.environ.get("P2P_WORKER_MESH_FORMAT", "obj").strip().lower()
PRELOAD = os.environ.get("P2P_WORKER_PRELOAD", "true").strip().lower() != "false"

_backend = None
_backend_error: str | None = None
_backend_lock = threading.Lock()


def _get_backend():
    """Return the loaded backend, building it on first use.

    Only one backend is served per worker process: the point of the worker is to
    keep 4B parameters resident on the GPU, and rebuilding per request would defeat
    that entirely.
    """
    global _backend, _backend_error
    if _backend is not None:
        return _backend
    logger.info("Loading sculptor backend '%s'…", WORKER_BACKEND)
    started = time.time()
    try:
        _backend = create_sculptor(WORKER_BACKEND)
    except SculptorError as exc:
        _backend_error = str(exc)
        raise
    _backend_error = None
    logger.info("Backend ready in %.1fs — %s", time.time() - started, _backend.describe())
    return _backend


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load weights at boot so the first real request is not the cold one.

    A preload failure is logged and swallowed rather than killing the process: the
    worker then answers `/health` with the reason, which is far easier to diagnose
    from the client than a container that exits on startup.
    """
    if PRELOAD:
        try:
            _get_backend()
        except Exception as exc:
            logger.error("Backend preload failed — worker will report unhealthy: %s", exc)
    else:
        logger.info("P2P_WORKER_PRELOAD=false — deferring model load to first request")
    yield


app = FastAPI(title="P2P Sculptor Worker", version="1.0.0", lifespan=lifespan)


def _check_auth(request: Request) -> None:
    """Reject requests without the bearer token, when one is configured."""
    if not WORKER_API_KEY:
        return
    header = request.headers.get("authorization", "")
    if header.removeprefix("Bearer ").strip() != WORKER_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
        )


@contextmanager
def _temporary_attrs(target, overrides: dict):
    """Apply per-request attribute overrides, restoring them afterwards.

    Sampler settings live on the backend instance, which is shared across requests.
    Held under `_backend_lock`, so no other request ever observes the swapped
    values — and a failed request cannot leave its settings behind for the next
    caller, which would silently change results long after the error.
    """
    previous = {k: getattr(target, k) for k in overrides}
    for key, value in overrides.items():
        setattr(target, key, value)
    try:
        yield
    finally:
        for key, value in previous.items():
            setattr(target, key, value)


def _request_overrides(backend, pipeline_type: str | None, seed: int | None) -> dict:
    """Collect per-request settings the loaded backend actually supports."""
    overrides: dict = {}
    if pipeline_type and hasattr(backend, "pipeline_type"):
        from pythonsrc.sculptors.trellis2 import PIPELINE_TYPES

        if pipeline_type not in PIPELINE_TYPES:
            raise HTTPException(
                # Literal 422: starlette renamed the constant and deprecated the
                # old spelling, so naming it either way warns on some versions.
                status_code=422,
                detail=(
                    f"Invalid pipeline_type '{pipeline_type}' — expected one of "
                    f"{', '.join(PIPELINE_TYPES)}"
                ),
            )
        overrides["pipeline_type"] = pipeline_type
    if seed is not None and seed >= 0 and hasattr(backend, "seed"):
        overrides["seed"] = seed
    return overrides


@app.get("/health")
def health() -> dict:
    """Report readiness, the loaded backend, and the visible GPU."""
    info: dict = {
        "status": "ready" if _backend is not None else "loading",
        "backend": WORKER_BACKEND,
        "mesh_format": MESH_FORMAT,
    }
    if _backend is not None:
        info["describes"] = _backend.describe()
        info["model"] = _backend.MODEL_NAME
        info["up_axis"] = _backend.up_axis
    if _backend_error:
        info["error"] = _backend_error
    try:
        import torch

        info["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["gpu"] = torch.cuda.get_device_name(0)
            free, total = torch.cuda.mem_get_info()
            info["vram_free_gb"] = round(free / 1024**3, 1)
            info["vram_total_gb"] = round(total / 1024**3, 1)
    except Exception as exc:
        info["cuda_error"] = str(exc)
    return info


@app.post("/sculpt")
async def sculpt(
    request: Request,
    image: UploadFile = File(...),
    backend: str | None = Form(None),
    pipeline_type: str | None = Form(None),
    seed: int | None = Form(None),
) -> Response:
    """Reconstruct raw geometry from an uploaded blueprint image.

    Args:
        request: Used only to check the bearer token.
        image: The blueprint image (PNG/JPEG).
        backend: Backend the caller expects; must match the loaded one.
        pipeline_type: TRELLIS.2 voxel resolution override for this request.
        seed: Sampling seed; negative or absent keeps the backend default.

    Returns:
        The raw mesh bytes, with `X-P2P-Up-Axis`, `X-P2P-Model`,
        `X-P2P-Model-Version` and `X-P2P-Mesh-Format` describing what was produced.
    """
    _check_auth(request)

    if backend and backend.strip().lower() != WORKER_BACKEND:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This worker serves the '{WORKER_BACKEND}' backend; "
                f"'{backend}' was requested. Deploy a separate worker for it."
            ),
        )

    payload = await image.read()
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty image upload"
        )

    try:
        loaded = _get_backend()
    except SculptorError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    overrides = _request_overrides(loaded, pipeline_type, seed)
    started = time.time()
    logger.info(
        "Reconstructing %s (%.1f KB) with %s%s",
        image.filename or "blueprint",
        len(payload) / 1024,
        WORKER_BACKEND,
        f" overrides={overrides}" if overrides else "",
    )

    with TemporaryDirectory(prefix="p2p-worker-") as tmpdir:
        source = Path(tmpdir) / (image.filename or "blueprint.png")
        source.write_bytes(payload)
        target = Path(tmpdir) / f"raw.{MESH_FORMAT}"

        try:
            # One inference at a time: the GPU cannot serve two 4B-parameter
            # reconstructions concurrently, and the overrides below are per-instance.
            with _backend_lock, _temporary_attrs(loaded, overrides):
                mesh = loaded.reconstruct(source)
                mesh.export(str(target))
        except SculptorError as exc:
            logger.error("Reconstruction failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            ) from exc
        except Exception as exc:
            logger.exception("Reconstruction failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Reconstruction failed: {exc}",
            ) from exc

        body = target.read_bytes()

    logger.info(
        "Done in %.1fs — %d faces, %.1f KB %s",
        time.time() - started,
        len(mesh.faces),
        len(body) / 1024,
        MESH_FORMAT,
    )
    return Response(
        content=body,
        media_type="application/octet-stream",
        headers={
            "X-P2P-Mesh-Format": MESH_FORMAT,
            # The client rotates to Z-up using this, so it is not optional
            # metadata — omit it and meshes arrive lying on their side.
            "X-P2P-Up-Axis": loaded.up_axis,
            "X-P2P-Backend": WORKER_BACKEND,
            "X-P2P-Model": loaded.MODEL_NAME,
            "X-P2P-Model-Version": str(loaded.MODEL_VERSION or ""),
        },
    )
