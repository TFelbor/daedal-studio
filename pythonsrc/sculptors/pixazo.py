"""
pixazo.py — Sculptor backend that runs TRELLIS.2 on Pixazo's hosted API.

The same model as the `trellis2` and `remote` backends, reached as a paid endpoint
instead of a GPU this project has to own. That makes it the only backend that works
on an Apple Silicon Mac: TRELLIS.2's CUDA extensions have no CPU or MPS kernels, so
without either a CUDA host or a self-hosted worker, a hosted call is the only path
to Phase 2.

It is also the only backend that costs money — €0,32 per generation — which is why
`BACKEND` is `hosted_api` and `last_generation_cost_eur` is set after every
successful call. Once a print is finished nothing else records what its mesh cost,
so the charge is written at the one moment it is knowable.

## Two things differ from the self-hosted backends

**The API takes a URL, not a file.** `image_url` must be something Pixazo's gateway
can fetch, and the blueprint is on local disk. `_resolve_image_url` inlines it as a
`data:` URI by default, which needs no infrastructure; set
`$P2P_PIXAZO_IMAGE_BASE_URL` to serve blueprints from somewhere public instead.

**The output is GLB, so the frame is glTF's, not TRELLIS.2's.** Upstream's
`to_glb()` swaps Y/Z on the way out precisely because glTF is Y-up while the model's
own frame is Z-up — so unlike `trellis2`, this backend's raw output needs the
rotation that `SculptorBackend.postprocess` applies. See `up_axis` below.
"""

from __future__ import annotations

import base64
import io
import logging
import mimetypes
import os
import time
from pathlib import Path

import trimesh

from .base import SculptorBackend, SculptorError

logger = logging.getLogger("p2p.sculptor.pixazo")

DEFAULT_GATEWAY = "https://gateway.pixazo.ai"
MODEL_SLUG = "trellis-2-image-to-3d"

#: Published list price, in euro, at the time this backend was written. Recorded per
#: job rather than looked up later: a price change would otherwise silently rewrite
#: what every historical job claims to have cost.
PRICE_EUR_PER_GENERATION = 0.32

#: The gateway's own guidance is 60-180s. The ceiling is generous because a queued
#: request that is abandoned client-side is still billed — waiting is cheaper than
#: paying twice.
DEFAULT_TIMEOUT = 600.0
POLL_INTERVAL_SECONDS = 5.0

#: Face budget requested from the endpoint, mirroring `Trellis2Backend`'s
#: `gpu_simplify_target`. The API's own default is 500_000, and a mesh that size is
#: what killed a real job: it arrived at 462_352 faces, and post-processing plus
#: Phase 3's repair and the printability voxel pass never finished. Asking the
#: endpoint to decimate costs nothing extra and happens before the download.
DEFAULT_DECIMATION_TARGET = 200_000

#: Per-request HTTP timeout. Submit and poll are both small JSON calls; only the
#: *job* is slow, and that is handled by polling rather than one long request.
HTTP_TIMEOUT = 60.0

TERMINAL_OK = "COMPLETED"
TERMINAL_BAD = ("ERROR", "FAILED", "CANCELLED")

#: `pipeline_type` is this project's vocabulary, shared across all three backends.
#: The hosted API has no cascade sampler, so both cascade settings collapse onto
#: their target resolution. The mapping is lossy in one direction only — a
#: `1024_cascade` job here is not the same experiment as a `1024_cascade` job on the
#: worker, which is why `generation_params()` records the resolution actually sent
#: alongside the requested pipeline type rather than just one of them.
_RESOLUTION_FOR_PIPELINE_TYPE = {
    "512": 512,
    "1024": 1024,
    "1024_cascade": 1024,
    "1536_cascade": 1536,
}


class PixazoBackend(SculptorBackend):
    """Reconstructs a mesh by calling Pixazo's hosted TRELLIS.2 endpoint.

    Args:
        api_key: Pixazo subscription key. Defaults to `$PIXAZO_API_KEY`.
        gateway: API root. Defaults to `$P2P_PIXAZO_GATEWAY`, else the public
            gateway.
        pipeline_type: One of `_RESOLUTION_FOR_PIPELINE_TYPE`, mapped to the API's
            `resolution`. Defaults to `$TRELLIS2_PIPELINE_TYPE`, else
            `1024_cascade`, matching the other backends.
        seed: Sampling seed, or None for the endpoint's default.
        ss_steps: Sparse-structure sampler steps, or None for the API default.
        shape_steps: Shape-latent sampler steps, or None for the API default.
        ss_guidance: Sparse-structure guidance strength, or None for the default.
        shape_guidance: Shape-latent guidance strength, or None for the default.
        decimation_target: Face budget applied server-side before the GLB is
            written. The shared CPU pass then takes it down to `--faces`.
        timeout: Total seconds to wait for a generation before giving up.
    """

    name = "pixazo"

    # glTF is Y-up, and upstream's exporter swaps Y/Z on the way out — so a GLB from
    # this endpoint arrives Y-up even though the model's native frame is Z-up.
    # trimesh does not apply that convention for us, so the rotation in
    # `postprocess` is load-bearing here in a way it is not for `trellis2`.
    #
    # Overridable per instance from $P2P_PIXAZO_UP_AXIS (see __init__) because
    # getting it wrong is silent — the part simply prints lying on its side — and
    # flipping a variable is faster than editing and redeploying when the first real
    # mesh settles the question.
    up_axis = "y"

    # Sharp features are the reason to run TRELLIS.2 at all, hosted or not.
    default_smooth_iterations = 0

    MODEL_NAME = "TRELLIS.2"
    MODEL_VERSION = MODEL_SLUG
    BACKEND = "hosted_api"

    #: Environment kill switch. Any truthy value refuses to construct this backend,
    #: which is what keeps a test run — or a stray automated trigger — from spending
    #: money. It is an environment variable rather than a Python-level patch on
    #: purpose: the API server launches Phase 2 as a *subprocess* (and on a Mac, inside
    #: a container), so a monkeypatch in the parent process would not reach the code
    #: that actually places the call. `server.app` forwards this variable across both
    #: boundaries.
    KILL_SWITCH_ENV = "P2P_DISABLE_PAID_BACKENDS"

    def __init__(
        self,
        api_key: str | None = None,
        gateway: str | None = None,
        *,
        pipeline_type: str | None = None,
        seed: int | None = None,
        ss_steps: int | None = None,
        shape_steps: int | None = None,
        ss_guidance: float | None = None,
        shape_guidance: float | None = None,
        decimation_target: int | None = DEFAULT_DECIMATION_TARGET,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        disabled = os.environ.get(self.KILL_SWITCH_ENV, "").strip().lower()
        if disabled and disabled not in ("0", "false", "no"):
            raise SculptorError(
                f"The 'pixazo' backend is disabled by {self.KILL_SWITCH_ENV}="
                f"{disabled!r}. It bills €"
                f"{PRICE_EUR_PER_GENERATION:.2f} per generation, so it refuses to run "
                "rather than spend money in an environment that asked it not to. "
                f"Unset {self.KILL_SWITCH_ENV} to allow paid generations."
            )

        self.api_key = api_key or os.environ.get("PIXAZO_API_KEY")
        if not self.api_key:
            raise SculptorError(
                "The 'pixazo' sculptor backend needs a subscription key — set "
                "PIXAZO_API_KEY or pass api_key."
            )

        self.gateway = (
            gateway or os.environ.get("P2P_PIXAZO_GATEWAY") or DEFAULT_GATEWAY
        ).rstrip("/")

        pipeline_type = pipeline_type or os.environ.get(
            "TRELLIS2_PIPELINE_TYPE", "1024_cascade"
        )
        if pipeline_type not in _RESOLUTION_FOR_PIPELINE_TYPE:
            raise SculptorError(
                f"Invalid pipeline_type '{pipeline_type}' — expected one of "
                f"{', '.join(_RESOLUTION_FOR_PIPELINE_TYPE)}"
            )
        self.pipeline_type = pipeline_type
        self.resolution = _RESOLUTION_FOR_PIPELINE_TYPE[pipeline_type]

        self.seed = seed
        self.ss_steps = ss_steps
        self.shape_steps = shape_steps
        self.ss_guidance = ss_guidance
        self.shape_guidance = shape_guidance
        self.decimation_target = decimation_target
        self.timeout = float(timeout)

        # Read here rather than at class-definition time so the override works
        # whatever order imports happen in, and so a test can set it per instance.
        self.up_axis = (
            os.environ.get("P2P_PIXAZO_UP_AXIS") or type(self).up_axis
        ).strip().lower()

        #: Set after each successful generation, read off the instance by
        #: `pipeline._record_generation`.
        self.last_generation_cost_eur: float | None = None
        self.last_request_id: str | None = None

    def describe(self) -> str:
        return f"pixazo ({MODEL_SLUG}, resolution={self.resolution})"

    def generation_params(self) -> dict:
        """Report what was actually sent, plus the vocabulary it was asked for.

        Both halves are needed. `resolution` is what the endpoint sampled with;
        `pipeline_type` is what the operator (or the UI) requested, and the two are
        not interchangeable because the cascade settings collapse. Recording only
        the request would overstate what ran; recording only the resolution would
        make a hosted job impossible to line up against a worker job.
        """
        params = {
            "sculptor_backend": self.name,
            "gateway": self.gateway,
            "model_slug": MODEL_SLUG,
            "pipeline_type": self.pipeline_type,
            "resolution": self.resolution,
            "mesh_seed": self.seed,
            "ss_sampling_steps": self.ss_steps,
            "shape_slat_sampling_steps": self.shape_steps,
            "ss_guidance_strength": self.ss_guidance,
            "shape_slat_guidance_strength": self.shape_guidance,
            "decimation_target": self.decimation_target,
            "price_eur": PRICE_EUR_PER_GENERATION,
        }
        if self.last_request_id:
            params["request_id"] = self.last_request_id
        return params

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"Ocp-Apim-Subscription-Key": self.api_key}

    def _payload(self, image_url: str) -> dict:
        """Build the submit body, omitting every knob the caller left unset.

        An unset knob must be *absent* rather than null: the endpoint applies its
        own documented default for a missing field, and sending null would either
        be rejected or override the default with nothing.
        """
        payload: dict = {"image_url": image_url, "resolution": self.resolution}
        optional = {
            "seed": self.seed,
            "ss_sampling_steps": self.ss_steps,
            "shape_slat_sampling_steps": self.shape_steps,
            "ss_guidance_strength": self.ss_guidance,
            "shape_slat_guidance_strength": self.shape_guidance,
            "decimation_target": self.decimation_target,
        }
        payload.update({k: v for k, v in optional.items() if v is not None})
        return payload

    def _resolve_image_url(self, image_path: Path) -> str:
        """Turn a local blueprint into something the gateway can fetch.

        Two strategies, because the right one depends on infrastructure this
        backend should not assume:

        * `$P2P_PIXAZO_IMAGE_BASE_URL` — the blueprint is already reachable at a
          public URL (an R2 bucket, a tunnel to the API server). The file's name is
          appended to the base.
        * otherwise a `data:` URI — no infrastructure at all, at the cost of sending
          the image inline. This is the default because a working Phase 2 with no
          setup beats a faster one that needs a bucket first.
        """
        base = os.environ.get("P2P_PIXAZO_IMAGE_BASE_URL", "").strip()
        if base:
            url = f"{base.rstrip('/')}/{image_path.name}"
            logger.info("Submitting blueprint by URL: %s", url)
            return url

        mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        logger.info(
            "Submitting blueprint inline as a data URI (%.1f KB encoded). Set "
            "P2P_PIXAZO_IMAGE_BASE_URL to send a URL instead.",
            len(encoded) / 1024,
        )
        return f"data:{mime};base64,{encoded}"

    def _submit(self, image_url: str) -> str:
        """Queue a generation and return its request id."""
        import requests

        endpoint = f"{self.gateway}/{MODEL_SLUG}/v1/{MODEL_SLUG}-request"
        try:
            response = requests.post(
                endpoint,
                json=self._payload(image_url),
                headers=self._headers(),
                timeout=HTTP_TIMEOUT,
            )
        except requests.exceptions.RequestException as exc:
            raise SculptorError(f"Could not reach the Pixazo gateway: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500]
            if image_url.startswith("data:"):
                # The most likely cause of a 4xx on the very first call, and the
                # one the operator cannot guess from the gateway's own message.
                detail += (
                    "\n\nThe blueprint was sent inline as a data URI. If the gateway "
                    "rejects that, host the image somewhere it can fetch and set "
                    "P2P_PIXAZO_IMAGE_BASE_URL."
                )
            raise SculptorError(
                f"Pixazo submit failed with HTTP {response.status_code}: {detail}"
            )

        body = response.json()
        request_id = body.get("request_id")
        if not request_id:
            raise SculptorError(f"Pixazo submit returned no request_id: {body}")
        logger.info("Queued Pixazo generation %s (status=%s)", request_id, body.get("status"))
        return request_id

    def _await_result(self, request_id: str) -> str:
        """Poll until the generation finishes and return the output mesh URL."""
        import requests

        status_url = f"{self.gateway}/v2/requests/status/{request_id}"
        deadline = time.monotonic() + self.timeout
        last_status = None

        while True:
            try:
                response = requests.get(
                    status_url, headers=self._headers(), timeout=HTTP_TIMEOUT
                )
                response.raise_for_status()
            except requests.exceptions.RequestException as exc:
                raise SculptorError(
                    f"Polling Pixazo generation {request_id} failed: {exc}"
                ) from exc

            body = response.json()
            status = (body.get("status") or "").upper()
            if status != last_status:
                logger.info("Pixazo generation %s — %s", request_id, status or "?")
                last_status = status

            if status == TERMINAL_OK:
                media = (body.get("output") or {}).get("media_url") or []
                if not media:
                    raise SculptorError(
                        f"Pixazo reported COMPLETED but returned no media_url: {body}"
                    )
                return media[0]

            if status in TERMINAL_BAD:
                raise SculptorError(
                    f"Pixazo generation {request_id} ended as {status}: "
                    f"{body.get('error') or body}"
                )

            if time.monotonic() >= deadline:
                raise SculptorError(
                    f"Pixazo generation {request_id} did not finish within "
                    f"{self.timeout:.0f}s (last status: {status or 'unknown'}). The "
                    "job may still complete and still be billed."
                )
            time.sleep(POLL_INTERVAL_SECONDS)

    def _download_mesh(self, url: str) -> trimesh.Trimesh:
        """Fetch the generated GLB and load it as a single mesh."""
        import requests

        try:
            response = requests.get(url, timeout=HTTP_TIMEOUT * 5)
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise SculptorError(f"Could not download the generated mesh: {exc}") from exc

        self._cache_glb(response.content)

        loaded = trimesh.load(
            io.BytesIO(response.content), file_type="glb", process=False
        )
        # The endpoint returns a textured GLB, so the scene may carry more than one
        # geometry. Concatenating before `postprocess` runs is what lets the shared
        # largest-component pass see the whole thing.
        if isinstance(loaded, trimesh.Scene):
            loaded = loaded.to_mesh()
        if loaded is None or len(getattr(loaded, "faces", ())) == 0:
            raise SculptorError(
                f"Generated GLB held no usable geometry ({len(response.content)} bytes)"
            )
        return loaded

    def _cache_glb(self, payload: bytes) -> None:
        """Write the purchased GLB to the job's artifact directory, if there is one.

        Called the instant the bytes arrive, before parsing or post-processing. Those
        steps can fail — a real job died in post-processing holding a COMPLETED,
        already-billed 462k-face mesh that existed only in memory, and re-running it
        meant paying again. Caching first turns that into a retry from disk.

        Never raises: a cache miss must not cost the caller the mesh it just bought.
        """
        if not self.artifact_dir:
            return
        name = f"pixazo_{self.last_request_id or 'generation'}.glb"
        try:
            target = Path(self.artifact_dir) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            logger.info("Cached purchased GLB (%.1f KB) to %s", len(payload) / 1024, target)
        except Exception as exc:
            logger.warning("Could not cache the generated GLB: %s", exc)

    # ── Reconstruction ───────────────────────────────────────────────────────

    def reconstruct(self, image_path: str | Path) -> trimesh.Trimesh:
        image_path = Path(image_path)
        logger.info(
            "Delegating reconstruction to Pixazo (%s, resolution=%d) — €%.2f per "
            "generation",
            MODEL_SLUG,
            self.resolution,
            PRICE_EUR_PER_GENERATION,
        )

        started = time.time()
        request_id = self._submit(self._resolve_image_url(image_path))
        self.last_request_id = request_id

        # Booked here, at the moment the gateway accepts the request — not after the
        # mesh arrives. The charge is incurred on acceptance: a generation that is
        # queued and then times out, or whose download fails, has still been paid
        # for. Recording the cost only on success made every such job read as free
        # and understated real spend, which is the opposite of what a column named
        # `generation_cost_eur` is for. What was *delivered* is answered by whether
        # the job has a mesh, not by whether it has a cost.
        self.last_generation_cost_eur = PRICE_EUR_PER_GENERATION

        mesh_url = self._await_result(request_id)
        mesh = self._download_mesh(mesh_url)

        logger.info(
            "Received %d faces from Pixazo in %.1fs (request=%s, up_axis=%s)",
            len(mesh.faces),
            time.time() - started,
            request_id,
            self.up_axis,
        )
        return mesh
