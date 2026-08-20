"""
remote.py — Sculptor backend that delegates reconstruction to a GPU worker.

TRELLIS.2 needs an NVIDIA GPU with roughly 24 GB of VRAM and four compiled CUDA
extensions, which the machine running the rest of the pipeline generally is not and
does not have. This backend posts the blueprint to a worker (see
`services/trellis2_worker/`) and receives raw geometry back.

The worker returns the mesh *before* print post-processing, and the shared
`SculptorBackend.postprocess` runs locally on CPU. Orientation, component pruning
and decimation therefore have exactly one implementation regardless of where
inference happened, and no GPU time is spent on work a CPU does fine.
"""

from __future__ import annotations

import io
import logging
import os
import time
from pathlib import Path

import trimesh

from .base import SculptorBackend, SculptorError

logger = logging.getLogger("p2p.sculptor.remote")

#: Generous by HTTP standards, but a 1536³ reconstruction on a cold worker is
#: minutes of real work, and a timeout here throws all of it away.
DEFAULT_TIMEOUT = 900.0

#: A worker on a serverless GPU host may not be accepting connections yet.
DEFAULT_CONNECT_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5.0


class RemoteSculptorBackend(SculptorBackend):
    """Sends the blueprint to a GPU sculptor worker and loads the mesh it returns.

    Args:
        base_url: Worker root URL, e.g. `http://gpu-host:8100`. Defaults to
            `$P2P_SCULPTOR_REMOTE_URL`.
        api_key: Optional bearer token, sent as `Authorization: Bearer …`.
            Defaults to `$P2P_SCULPTOR_REMOTE_KEY`.
        timeout: Per-request timeout in seconds.
        connect_retries: How many times to retry a worker that is not yet
            accepting connections (serverless cold start).
        params: Extra form fields forwarded to the worker, e.g.
            `{"pipeline_type": "1024_cascade", "seed": 42}`.
    """

    name = "remote"

    # Overwritten from the worker's response headers. The default matches the
    # worker's own backend, so a worker too old to send the header still lands
    # right side up.
    up_axis = "z"
    default_smooth_iterations = 0

    MODEL_NAME = "TRELLIS.2"

    # Not `hosted_api`: nothing is billed per call, so `generation_cost_eur` stays
    # None while latency legitimately includes network time. Telling the two apart
    # in the dataset is the whole point of a separate value.
    BACKEND = "remote_worker"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        connect_retries: int = DEFAULT_CONNECT_RETRIES,
        params: dict | None = None,
    ) -> None:
        base_url = base_url or os.environ.get("P2P_SCULPTOR_REMOTE_URL")
        if not base_url:
            raise SculptorError(
                "The 'remote' sculptor backend needs a worker URL — set "
                "P2P_SCULPTOR_REMOTE_URL or pass base_url."
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("P2P_SCULPTOR_REMOTE_KEY")
        self.timeout = float(timeout)
        self.connect_retries = int(connect_retries)
        self.params = dict(params or {})
        self.MODEL_VERSION = self.base_url

    def describe(self) -> str:
        return f"remote ({self.base_url})"

    def generation_params(self) -> dict:
        # The forwarded params are what the worker actually sampled with, so they
        # belong on the row exactly as a local run's own knobs would — under the
        # same names. `seed` is the worker's *form field*; the column this lands in
        # is shared with local runs, and one field under two names is a dataset
        # nobody can query.
        params = {
            "sculptor_backend": self.name,
            "worker_url": self.base_url,
            **self.params,
        }
        if "seed" in params:
            params["mesh_seed"] = params.pop("seed")
        return params

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        if not self.api_key:
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}

    def health(self) -> dict:
        """Query the worker's `/health` endpoint. Useful for pre-flight checks."""
        import requests

        try:
            response = requests.get(
                f"{self.base_url}/health", headers=self._headers(), timeout=30
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise SculptorError(f"Worker health check failed: {exc}") from exc

    def _post_with_retries(self, image_path: Path):
        """POST the image, retrying only connection failures (cold starts).

        A worker that answers with an error status is not retried — that is a real
        failure, and retrying a multi-minute inference request would just multiply
        the wait.
        """
        import requests

        data = {k: str(v) for k, v in self.params.items()}
        last_exc: Exception | None = None

        for attempt in range(1, self.connect_retries + 1):
            try:
                with open(image_path, "rb") as handle:
                    return requests.post(
                        f"{self.base_url}/sculpt",
                        files={"image": (image_path.name, handle, "image/png")},
                        data=data,
                        headers=self._headers(),
                        timeout=self.timeout,
                    )
            except requests.exceptions.ConnectionError as exc:
                last_exc = exc
                if attempt < self.connect_retries:
                    logger.warning(
                        "Worker unreachable (attempt %d/%d) — retrying in %.0fs…",
                        attempt,
                        self.connect_retries,
                        RETRY_BACKOFF_SECONDS,
                    )
                    time.sleep(RETRY_BACKOFF_SECONDS)
            except requests.exceptions.Timeout as exc:
                raise SculptorError(
                    f"Worker did not respond within {self.timeout:.0f}s — raise the "
                    "timeout or check the worker logs."
                ) from exc

        raise SculptorError(
            f"Could not reach sculptor worker at {self.base_url}: {last_exc}"
        ) from last_exc

    # ── Reconstruction ───────────────────────────────────────────────────────

    def reconstruct(self, image_path: str | Path) -> trimesh.Trimesh:
        image_path = Path(image_path)
        logger.info("Delegating reconstruction to %s", self.base_url)

        started = time.time()
        response = self._post_with_retries(image_path)
        if response.status_code != 200:
            raise SculptorError(
                f"Worker returned HTTP {response.status_code}: {response.text[:500]}"
            )

        mesh_format = response.headers.get("X-P2P-Mesh-Format", "obj")
        up_axis = response.headers.get("X-P2P-Up-Axis")
        if up_axis:
            self.up_axis = up_axis
        else:
            logger.warning(
                "Worker did not report X-P2P-Up-Axis — assuming '%s'. If the model "
                "comes out lying on its side, the worker is out of date.",
                self.up_axis,
            )

        model = response.headers.get("X-P2P-Model")
        if model:
            self.MODEL_NAME = model
        version = response.headers.get("X-P2P-Model-Version")
        if version:
            self.MODEL_VERSION = f"{self.base_url} ({version})"

        mesh = trimesh.load(
            io.BytesIO(response.content), file_type=mesh_format, process=False
        )
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.to_mesh()
        if mesh is None or len(getattr(mesh, "faces", ())) == 0:
            raise SculptorError(
                f"Worker returned no usable geometry ({len(response.content)} bytes)"
            )

        logger.info(
            "Received %d faces from worker in %.1fs (format=%s, up_axis=%s)",
            len(mesh.faces),
            time.time() - started,
            mesh_format,
            self.up_axis,
        )
        return mesh
