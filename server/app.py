"""FastAPI application for Daedal Studio pipeline orchestration.

This module defines the REST API for creating, monitoring, and retrieving
results from the 3D printing pipeline, as well as managing telemetry.
"""
import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import platform
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlparse, urlunparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator

# Raised instead of a bare ValueError for one reason: its `ctx` survives into the 422
# body, so a spec refusal arrives as a list of `{path, message}` the composer can put
# on the control that caused it — see `JobRequest._spec_is_valid`.
from pydantic_core import PydanticCustomError

# Add pythonsrc to sys.path so we can import telemetry modules
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import httpx
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from pythonsrc.api_token import default_api_token_path, resolve_api_token
from pythonsrc.ip_screen import screen_prompt
from pythonsrc.operators import PrinterFactory
from pythonsrc.operators.bambu_operator import BambuOperator
from pythonsrc.operators.base import PrinterConnectionError
from pythonsrc.operators.printer_state import canonical_firmware

# The organizer *schema* only. `pythonsrc.organizer` exports nothing that needs trimesh
# or manifold3d, which is what lets the api-server image validate a spec without the
# kernel; the compiler stays behind `pythonsrc.organizer.archetypes`, never imported here.
#
# The font half of the decorative tier (F13, issue #157) comes in under the same rule and
# is the case that proves it holds: `lettering` imports fontTools and the standard
# library and nothing else, which is the whole reason this process can tell somebody the
# font cannot set their name while they are still typing it. It is aliased rather than
# imported as `lettering` because `resolve_organizer_spec` has a local list of the same
# noun, and the shadowing would be silent.
#
# The seed dimensions come in for the same reason: `resolve_stack` is arithmetic over a
# table of sourced millimetres and imports nothing. It is what `POST /organizer/resolve`
# answers with, and the only figures the composer may show.
from pythonsrc.organizer import (
    CardStack,
    OrganizerSpec,
    SpecError,
    dump_spec,
    game_box_record,
    problems_with_paths,
    spec_hash,
)
from pythonsrc.organizer import lettering as organizer_lettering

# The curated box interiors, under the same rule again: `box_kb` reads one committed JSON
# file and imports nothing outside the stdlib. It reaches no network — BoardGameGeek has
# no client here and must not get one (issue #154) — so the composer can offer the curated
# list and the typed fallback from the same process that validates the spec.
from pythonsrc.organizer.box_kb import kb as game_box_kb

# The seed dimensions, for the same reason and under the same rule: `resolve_stack` is
# arithmetic over a table of sourced millimetres and imports nothing. It is what
# `POST /organizer/resolve` answers with, and the only figures the composer may show.
from pythonsrc.organizer.dimensions import resolve_stack
from pythonsrc.platform_utils import get_execution_strategy
from pythonsrc.size_hint import parse_size_hint
from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.detector import attach_detector
from pythonsrc.telemetry.moonraker_collector import MoonrakerCollector
from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector
from pythonsrc.telemetry.run_context import resolve_git_sha
from pythonsrc.telemetry.schema import VALID_FAILURE_TYPES, FailureEvent, PrintJob
from server import push
from server.activity import activity
from server.auth import SharedSecretAuth, public
from server.config_store import (
    CONFIG_KEYS,
    INTERNAL_CONFIG_KEYS,
    PRINTER_CREDENTIAL_HOSTS,
    SUBPROCESS_ENV_KEYS,
    BoundCredential,
    ConfigStore,
    bound_printer_credential,
)
from server.job_broadcaster import broadcaster
from server.logging_config import configure_logging, is_high_frequency_path
from server.simulator_manager import SimulatorAvailabilityError, simulator_manager

# At import time, not in a startup event: uvicorn imports this module and runs
# module-level code (config store, strategy resolution) before any startup hook
# fires, and those lines are worth keeping.
configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI(title="Daedal Studio API", version="1.0.0")

#: The shared secret every route but `GET /health` and the SPA is checked against, and
#: the one this server hands the pipeline container and the dispatch operator. Resolved
#: once, at import, so the middleware that checks it and `subprocess_env` — which sends
#: it — cannot disagree: re-resolving in each place would read the file twice and, on
#: the first start of a host where the token had to be generated in memory because the
#: path was unwritable, would come back with two different answers.
API_TOKEN = resolve_api_token(create=True)

# Before `log_requests`, and that ordering is load-bearing: Starlette builds the stack
# inner-first, so the middleware added first runs *inside* the ones added after it. A
# 401 therefore still reaches the request log and the activity feed, which is where an
# operator would look to find out that something is knocking.
app.add_middleware(SharedSecretAuth, fastapi_app=app, token=API_TOKEN)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log one line per request: method, path, status and how long it took.

    There was no request log at all, so a failing UI action left no trace on the
    server side and had to be reproduced with a browser open. Duration is included
    because the slow paths here are slow for structural reasons — a slice, a printer
    probe — and knowing which endpoint blocked is most of the diagnosis.

    Status decides the level, so a 500 is visible without turning on DEBUG. Polled
    endpoints drop to DEBUG regardless: the job detail page alone would otherwise
    emit a line every second.
    """
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        # FastAPI's own handler logs this too, but without the path or the timing,
        # and this is the line that says which request died.
        logger.exception(
            "%s %s — unhandled exception after %.0f ms",
            request.method, request.url.path, elapsed_ms,
        )
        raise

    elapsed_ms = (time.perf_counter() - started) * 1000

    if response.status_code >= 500:
        level = logging.ERROR
    elif response.status_code >= 400:
        level = logging.WARNING
    elif is_high_frequency_path(request.url.path):
        level = logging.DEBUG
    else:
        level = logging.INFO

    logger.log(
        level,
        "%s %s → %d (%.0f ms)",
        request.method, request.url.path, response.status_code, elapsed_ms,
    )

    # Every request that failed reaches the activity feed as a one-liner, whether or
    # not its handler knows how to describe itself. A 4xx or 5xx the handler swallowed
    # was previously invisible to anyone watching the feed, which is the case where
    # watching is most worth doing.
    # The polled-path demotion applies to GET only. A failed POST or DELETE is never a
    # poll, and `/jobs/{id}` matches the high-frequency prefix — so a rejected
    # `DELETE /jobs/{id}` was being suppressed by the heuristic meant for the detail
    # page's read timer, which is the exact failure someone would be watching for.
    if response.status_code >= 400 and (
        request.method != "GET" or not is_high_frequency_path(request.url.path)
    ):
        activity.event(
            f"{request.method} {request.url.path} → {response.status_code} "
            f"({elapsed_ms:.0f} ms)",
            level="ERROR" if response.status_code >= 500 else "WARNING",
            source="http",
        )
    return response

config_store = ConfigStore()

active_collectors = {}
active_detectors: dict[str, asyncio.Task] = {}
active_pipelines: dict[str, asyncio.subprocess.Process] = {}
# Jobs a human has stopped.
#
# A cancelled pipeline dies with a non-zero exit code, which is indistinguishable
# from a crash at the point where `_run_pipeline` decides what to record. Without
# this set the cancel endpoint wrote "cancelled" and `_run_pipeline` overwrote it
# with "failure" a second later — both are machine-sourced writes, so the
# precedence rule in `update_job_outcome_verdict` does not stop it. The user saw
# their stop turn into a failure, and the dataset recorded a crash that never
# happened.
cancelled_jobs: set[str] = set()


#: The built SPA. Resolved once, at import, so every containment check below compares
#: against the same absolute directory rather than re-deriving `server/../web/dist` and
#: hoping the two spellings agree.
DIST_DIR = Path(__file__).resolve().parent.parent / "web" / "dist"

#: Everything the pipeline reads and writes: `inputs/`, `outputs/`, `logs/`.
#:
#: A module constant rather than a re-derived `Path(__file__).parent.parent / "data"`
#: for the same reason `DIST_DIR` is one — every containment check under it compares
#: against the same absolute directory — and because the fit-photo route is the first
#: one that *writes* here from a request, which a test has to be able to redirect
#: somewhere it may safely fill with bytes.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: `.webmanifest`, spelled out rather than inherited.
#:
#: The SPA catch-all answers with a `FileResponse`, whose media type comes from
#: `mimetypes.guess_type`, whose table comes from the interpreter *and the host*.
#: CPython learned `.webmanifest` in 3.11; the server image is `python:3.10-slim`, where
#: the guess is `None` and Starlette falls back to `text/plain`. Chrome then warns and
#: still installs; Safari does not, so the app is installable in CI and on a developer's
#: 3.11 machine and silently is not on the one platform half the pilot is holding.
#: `add_type` is idempotent, so this is a floor rather than an override.
mimetypes.add_type("application/manifest+json", ".webmanifest")


def contained_path(base: Path, *parts: str) -> Path | None:
    """Join request-controlled `parts` onto `base`, refusing anything that leaves it.

    Three separate mechanisms escape a path join, and each has its own way in here.

    A `..` segment walks up, and **nothing between the socket and the handler collapses
    dot segments**: uvicorn percent-decodes the request target straight into
    `scope["path"]`, and Starlette's `{...:path}` converter matches `/` and `..` alike.
    So `/%2e%2e/%2e%2e/.env` — or a literal `../` from `curl --path-as-is` — arrives at
    a route as `../../.env`.

    An **absolute** part discards the base outright, with no `..` at all:
    `os.path.join("web/dist", "/etc/passwd")` and `Path("web/dist") / "/etc/passwd"` are
    both `/etc/passwd`.

    And a symlink inside `base` can point anywhere, which is why containment is decided
    after `resolve()` rather than by inspecting the string — a lexical check passes a
    path whose every component is innocent and whose target is not.

    This matters more here than a generic traversal would: there is no end-user
    authentication in this server, and the api-server process is the one with
    `~/.ds-mvp/.config_key` bind-mounted — the Fernet key for the encrypted config store
    that holds printer API keys. An unauthenticated arbitrary read is a credential
    disclosure.

    Args:
        base: The directory the result must stay inside. Need not exist.
        *parts: Untrusted path components, joined in order.

    Returns:
        The resolved path, or None when it lands outside `base` — including when a part
        is absolute, or when the join cannot be resolved at all.
    """
    root = base.resolve()
    try:
        candidate = root.joinpath(*parts).resolve()
    except (OSError, ValueError, RuntimeError):
        # ValueError: an embedded NUL byte. RuntimeError: a symlink loop, on the
        # resolve() implementations that report one that way. OSError: a component
        # that cannot be stat'ed. None of them is a path we may serve.
        return None
    if not candidate.is_relative_to(root):
        return None
    return candidate


#: The only directory a printer profile may come from. Confined here rather than to the
#: checkout because every other JSON file in the repo would otherwise be an accepted
#: profile: `web/package.json`, `licenses/*.json` and `tsconfig.json` all resolve, parse,
#: and land in `process_params` — an in-repo existence oracle, and `run_operator.py`
#: handed `package.json` as a printer.
PROFILES_DIR = Path(__file__).resolve().parent.parent / "pythonsrc" / "profiles"

#: How the Settings UI writes a profile and how every stored `profile_name` spells one.
#: Accepted alongside a bare filename so existing rows and the four values in
#: `PrinterSetup`'s datalist keep working untouched.
_PROFILES_PREFIX = "pythonsrc/profiles/"

#: The profile used when none was named. Also what an escaping path falls back to at the
#: call sites that are not request boundaries — see `profile_path_or_default`.
DEFAULT_PROFILE_NAME = "ender3.json"


class ProfileOutsideProfilesDir(ValueError):
    """A profile path that resolves outside `pythonsrc/profiles`.

    Deliberately distinct from "no such profile", which is an ordinary tolerated
    condition: a `profile` of `"default"` or `"test"` names nothing, correctly disables
    printing, and `POST /jobs` answers 202 — `tests/test_server.py` pins that. A path
    that *leaves* the directory has no legitimate reading, so it is refused rather than
    quietly disabling the print.
    """


def resolve_profile_path(candidate: str | None) -> Path | None:
    """The absolute path of a printer profile, or None when none was named.

    Both spellings are accepted: `pythonsrc/profiles/ender3.json`, which is what the
    Settings UI writes and what `profile_name` rows hold, and a bare `ender3.json`.

    Args:
        candidate: A profile as submitted or stored. None and "" mean "none named".

    Returns:
        The absolute path, which **need not exist** — a merely missing profile is
        tolerated, and each caller's own `exists()` check handles it.

    Raises:
        ProfileOutsideProfilesDir: The path resolves outside `pythonsrc/profiles`.
    """
    if not candidate:
        return None
    relative = (
        candidate[len(_PROFILES_PREFIX):]
        if candidate.startswith(_PROFILES_PREFIX)
        else candidate
    )
    path = contained_path(PROFILES_DIR, relative)
    if path is None:
        raise ProfileOutsideProfilesDir(candidate)
    return path


def profile_path_or_default(candidate: str | None) -> Path:
    """`candidate`'s profile path, falling back to the bundled Ender 3.

    For the call sites that are not request boundaries and have nowhere to put a 422.
    An escaping path resolves to the bundled default rather than being honoured, which
    is strictly safer than the alternative: honouring it meant reading `firmware`,
    `base_url` and `api_key` out of a file the caller chose, i.e. redirecting a print.
    `POST /jobs` refuses such a path outright, before any of these run.

    Args:
        candidate: A profile as submitted or stored.

    Returns:
        An absolute path, which need not exist.
    """
    try:
        path = resolve_profile_path(candidate)
    except ProfileOutsideProfilesDir:
        logger.warning(
            "Ignoring a printer profile outside %s: %r", PROFILES_DIR, candidate,
        )
        path = None
    return path or PROFILES_DIR / DEFAULT_PROFILE_NAME


def profile_pipeline_argument(candidate: str | None) -> str | None:
    """The `--profile` value to hand the pipeline, or None to let it use its own.

    A profile is a **name** at this boundary — `POST /jobs` accepts `ender3.json` and
    `pythonsrc/profiles/ender3.json` alike, and `DEFAULT_PROFILE` is written in either
    spelling — but it is a **path** to `pipeline.py`, resolved against that process's
    working directory (`/app` in the container, the repository root natively). Forwarding
    the name verbatim handed Phase 4 `ender3.json`, which is nothing relative to `/app`:
    `CuraSlicer.__init__` raises `FileNotFoundError: Printer definition not found` and the
    job fails at the slicer having already compiled, asserted and scored its mesh. The
    repository-relative spelling is the one that means the same thing on both sides of
    the boundary, and it is what the pipeline's own default (`pythonsrc/profiles/
    ender3.json`) already uses.

    A profile that is merely absent returns None rather than a path that cannot be
    opened. `"default"` and `"test"` are submitted by name in the suite and name no file;
    forwarding them is a certain Phase 4 crash, while omitting the flag leaves the
    pipeline's own default in force — which is exactly what "no profile was named" has
    always meant. An escaping path falls back the same way, warned about, as in
    `profile_path_or_default`; `POST /jobs` refuses one outright, but `DEFAULT_PROFILE`
    reaches here from the config store without passing that boundary.

    Args:
        candidate: A profile as submitted or stored.

    Returns:
        A repository-relative POSIX path, or None.
    """
    if not candidate:
        return None
    try:
        path = resolve_profile_path(candidate)
    except ProfileOutsideProfilesDir:
        logger.warning(
            "Ignoring a printer profile outside %s: %r", PROFILES_DIR, candidate,
        )
        return None
    if path is None or not path.exists():
        logger.warning(
            "No printer profile named %r in %s — the pipeline's own default applies.",
            candidate, PROFILES_DIR,
        )
        return None
    return path.relative_to(PROFILES_DIR.parent.parent).as_posix()


def resolve_job_artifact(
    job_id: str, filename: str, *, per_job_only: bool = False,
) -> Path | None:
    """Locate a job's artifact, preferring its per-job directory.

    The pipeline writes artifacts to ``data/outputs/{job_id}/`` so that jobs cannot
    overwrite each other. Older jobs wrote to the flat ``data/outputs/`` layout, so that
    path is still accepted as a fallback for rows created before the change.

    A debugging run that stood a bundled fixture in for Phase 1 or Phase 2 writes to
    ``dev-{job_id}`` instead, so that directory is searched too — the prefix exists to
    keep fabricated inputs out of the real namespace, not to hide the artifacts from the
    endpoints that serve them.

    Args:
        job_id: The job whose artifact is wanted.
        filename: Artifact filename — `engineered_mesh.gcode`, `engineered_mesh.stl`,
            `engineered_mesh.3mf` (the three `?format=` serves, see
            `DOWNLOAD_FORMATS`), `engineered_mesh.obj`, `blueprint.png` or
            `printability.json`. Any name is accepted and every join is contained,
            so a new artifact needs nothing here.
        per_job_only: Skip the flat-layout and shared-input fallbacks and answer only
            from this job's own directory. The blueprint gate needs this: the flat
            `data/inputs/blueprint.png` is written by whichever skip-Phase-1 run put it
            there and by no particular job, so a parked job asked about it would show a
            *different* job's image, or none, and a person would approve something that
            was never theirs.

    Returns:
        The path to the artifact, or None if no location has it.
    """
    # `job_id` comes straight off the URL and `filename` is a parameter, so every join
    # below goes through `contained_path`. `job_id` reaches here as `..` via
    # `/jobs/%2e%2e/blueprint`: the route's `[^/]+` group matches a decoded `..` exactly
    # as it matches a UUID, and `data/outputs/../blueprint.png` is `data/blueprint.png`.
    data = DATA_DIR
    outputs = data / "outputs"
    for directory in (job_id, f"dev-{job_id}"):
        candidate = contained_path(outputs, directory, filename)
        if candidate is not None and candidate.exists():
            return candidate

    if per_job_only:
        return None

    legacy = contained_path(outputs, filename)
    if legacy is not None and legacy.exists():
        return legacy

    if filename == "blueprint.png":
        inputs = data / "inputs"

        per_job = contained_path(inputs, job_id, filename)
        if per_job is not None and per_job.exists():
            return per_job

        # The shared path, for rows written before inputs were per-job and for the
        # skip-Phase-1 configuration, which reuses whatever is sitting there. Offered
        # only when this job has no input directory of its own: if it does, it rendered
        # into it, and the shared file demonstrably belongs to some other run. Serving
        # it would be the same mis-attribution the per-job path exists to prevent,
        # committed by the endpoint instead of by the pipeline.
        job_inputs = contained_path(inputs, job_id)
        if job_inputs is not None and not job_inputs.exists():
            shared_input = contained_path(inputs, filename)
            if shared_input is not None and shared_input.exists():
                return shared_input

    return None


# ── The fit photo ─────────────────────────────────────────────────────────────
# `POST /jobs/{id}/photo` is the first route in this application that accepts bytes
# from a browser, so the four properties below are stated as data and each one is
# tested: it is authenticated (by wearing no `@public`), capped, type-checked, and
# written through `contained_path`.

#: The largest fit photo that will be stored, in bytes.
#:
#: 10 MiB. A 12 MP phone JPEG is 3–6 MB and an HDR one can pass 8, so a 5 MiB cap
#: would refuse photographs people actually take; above 10 the only thing that fits is
#: something that is not a phone photo. The client checks the same figure before
#: uploading — that check is a courtesy, this one is the rule.
FIT_PHOTO_MAX_BYTES = 10 * 1024 * 1024

#: The image types accepted, and the suffix each is stored under.
#:
#: Three, all of which every browser this app supports can *display* as well as
#: produce. HEIC is deliberately absent: iOS transcodes a file-input upload to JPEG,
#: and the residue that still arrives as `image/heic` cannot be rendered by two of the
#: three desktop browsers, so accepting it would store evidence nobody could look at.
FIT_PHOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

#: The stored name, which the server chooses. The client never supplies one: a filename
#: from a browser is request-controlled data, and one photo per job is the whole record
#: we want anyway.
FIT_PHOTO_STEM = "fit_photo"


def sniff_image_type(head: bytes) -> str | None:
    """Identify an image from its first bytes, or None if it is not one we accept.

    A prefix check rather than a decode. The api-server image has no imaging library,
    and handing untrusted bytes to one is how a decompression bomb gets in; what this
    has to stop is a caller labelling something `image/jpeg` to get it written under a
    name the browser will later be asked to render. It is not a validity proof — a
    JPEG header over garbage is stored — and nothing but a browser ever consumes the
    result.

    Args:
        head: The first bytes of the body. Twelve are enough for all three types.

    Returns:
        The content type the bytes actually are, or None.
    """
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    # RIFF····WEBP — the four size bytes in between are the container's, not a magic.
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def fit_photo_target(job_id: str, suffix: str) -> Path | None:
    """Where this job's photo is written, or None if the join escapes `data/outputs`.

    `job_id` arrives straight off the URL, and nothing between the socket and the
    handler collapses dot segments — `/jobs/%2e%2e/photo` reaches here as `..`, which
    would put a request-supplied file in `data/`. `contained_path` is what refuses it.
    The suffix is ours, from `FIT_PHOTO_TYPES`, and never the client's.

    Args:
        job_id: The job the photo belongs to.
        suffix: `.jpg`, `.png` or `.webp`.

    Returns:
        The absolute path to write, or None.
    """
    return contained_path(DATA_DIR / "outputs", job_id, f"{FIT_PHOTO_STEM}{suffix}")


def fit_photo_on_disk(job) -> Path | None:
    """The stored photo for a job, re-confined on read, or None if there is not one.

    Deliberately not `resolve_job_artifact`: its flat-layout and `dev-` fallbacks exist
    so an old job's G-code can still be found, and applied to a photo they would answer
    one job's request with another job's evidence. The row's own path is the only
    source, and it is put back through `contained_path` because a value in a database
    is data too — a row edited by hand, or written by an older build, must not be able
    to name `/etc/passwd`.

    Args:
        job: A PrintJob row.

    Returns:
        The path to the image, or None when the row has none, it escapes the outputs
        tree, or the file is gone.
    """
    stored = getattr(job, "fit_photo_path", None)
    if not stored:
        return None
    path = contained_path(DATA_DIR.parent, stored)
    if path is None or not path.is_relative_to((DATA_DIR / "outputs").resolve()):
        return None
    return path if path.is_file() else None


def resolve_job_profile(job) -> tuple[str, str | None]:
    """Find the printer profile a job's Phase 5 would use.

    The job's own `profile_name` wins when it names a file that still exists, because
    that is what the job was created against; the configured default is the fallback for
    rows that stored "default". Returns the repo-relative name (what a person sees in
    Settings) and the absolute path (what a subprocess needs).

    Args:
        job: A PrintJob row.

    Returns:
        A (relative_profile, absolute_path) tuple. The path is None when nothing exists.
    """
    # `profile_name` is free text the client sent to `POST /jobs`, and the resolved path
    # is `json.load`ed by `dispatch_target` and handed to `run_operator.py` as the
    # profile to print with. A candidate that leaves `pythonsrc/profiles` is skipped
    # rather than raising: this is a read path with two more candidates behind the bad
    # one, and the refusal that matters already happened at `POST /jobs`.
    for candidate in (job.profile_name, config_store.get("DEFAULT_PROFILE"),
                      _PROFILES_PREFIX + DEFAULT_PROFILE_NAME):
        if not candidate or candidate == "default":
            continue
        try:
            path = resolve_profile_path(candidate)
        except ProfileOutsideProfilesDir:
            continue
        if path is not None and path.exists():
            return candidate, str(path)
    return "", None


def dispatch_target(job) -> dict:
    """Describe, as of now, what pressing "Send to printer" would send this job to.

    Resolved on read rather than frozen at job creation on purpose: the whole point of
    showing it is that the person confirming can see the *current* target, including one
    that changed in Settings since the job started.

    Args:
        job: A PrintJob row.

    Returns:
        A dict with the profile name, firmware, base URL and machine name.
    """
    profile, profile_path = resolve_job_profile(job)
    firmware, base_url, _api_key = resolve_printer_target(profile_path)
    machine_name = None
    if profile_path:
        try:
            with open(profile_path, "r") as f:
                machine_name = json.load(f).get("machine_name")
        except Exception:  # noqa: BLE001
            pass
    return {
        "profile": profile,
        "firmware": firmware,
        "base_url": base_url,
        "machine_name": machine_name,
    }


def dispatch_state(job, db: TelemetryDB) -> str:
    """Where a job stands with respect to Phase 5.

    Three states, and the middle one is the point: **a print does not leave for a
    machine until a person confirms the target.** The pipeline is launched without
    `--print`, so it stops after slicing; the job then sits in `awaiting_confirmation`
    until `POST /jobs/{id}/print-dispatch` arrives with an explicit confirmation.

    Derived rather than stored. The outcome column says what the software did, and a
    job waiting on a human has not changed what the software did — the decision itself
    is a `dispatch_confirmed` job event, which is where decisions live.

    Args:
        job: A PrintJob row.
        db: An open database handle, used to look for the confirmation event.

    Returns:
        "dispatched", "awaiting_confirmation" or "not_ready".
    """
    if job.outcome == "awaiting_verdict":
        return "dispatched"
    try:
        if db.get_job_events(job.job_id, kind="dispatch_confirmed"):
            return "dispatched"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read dispatch events for %s: %s", job.job_id, exc)

    # Only once nothing else is going to print it: a pipeline still running may have
    # been launched with --print and would dispatch itself.
    if job.outcome == "success" and job.slice_status == "success":
        if resolve_job_artifact(job.job_id, "engineered_mesh.gcode") is not None:
            return "awaiting_confirmation"
    return "not_ready"


def _file_sha256(path: Path) -> str:
    """The hash of a file on disk, streamed.

    Used to bind an approval to the exact image that was displayed. Streamed rather
    than read whole because the caller is an endpoint and a blueprint is a megabyte
    of PNG per request.

    Args:
        path: The file to hash.

    Returns:
        The lowercase hex digest, or "" if it could not be read.
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not hash %s: %s", path, exc)
        return ""
    return digest.hexdigest()


def blueprint_gate_state(job, db: TelemetryDB) -> str:
    """Where a job stands with respect to Phase 2.

    Four states. The one that matters is `awaiting_approval`: **Phase 2 does not start
    until a person has looked at the blueprint.** That is a legal control — an
    automated screen cannot be the last word on whether a render reproduces someone
    else's character — and, more often, a product one: the honest answer to many
    prompts is a rough, unpainted approximation, and the requester should see that in
    thirty seconds rather than after four minutes and a paid reconstruction.

    Derived, exactly like `dispatch_state`, and for the same reasons: no new outcome
    value, no migration, and the decision lives in `job_event` because that is where
    decisions live. Deriving it also makes it survive a server restart, which a gate
    that parked by awaiting inside `_run_pipeline` could not.

    Args:
        job: A PrintJob row.
        db: An open database handle, used to look for the decision events.

    Returns:
        "approved", "rejected", "awaiting_approval" or "not_ready".
    """
    try:
        if db.get_job_events(job.job_id, kind="blueprint_approved"):
            return "approved"
        if db.get_job_events(job.job_id, kind="blueprint_rejected"):
            return "rejected"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read blueprint gate events for %s: %s", job.job_id, exc)
        return "not_ready"

    # A settled row is not waiting for anything, whatever is on disk. Mirrors
    # `dispatch_state`'s insistence on `outcome == "success"`: the point of checking
    # the outcome is that a pipeline which has moved on must not be re-entered.
    if job.outcome != "unknown":
        return "not_ready"

    # And the run must actually have stopped. Derived from the *event*, not from the
    # presence of an image: `pipeline.py` snapshots a blueprint into the per-job
    # directory on every run with a `--job-id`, so an ungated run — anything with
    # SKIP_VISUALIZER or `print: true` — used to report itself as awaiting approval
    # seconds in, and approving it started a second pipeline for the same job.
    try:
        if not db.get_job_events(job.job_id, kind="blueprint_gate_parked"):
            return "not_ready"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read blueprint park events for %s: %s", job.job_id, exc)
        return "not_ready"

    # This job's *own* blueprint, not the flat `data/inputs/blueprint.png`: that path
    # belongs to no particular job — it is what the skip-Phase-1 configuration reuses —
    # so a parked job asked about it would show a different job's image, or none.
    if resolve_job_artifact(job.job_id, "blueprint.png", per_job_only=True) is not None:
        return "awaiting_approval"
    return "not_ready"


def job_spec_summary(job) -> dict:
    """The parametric facts about a job, for the polled detail endpoint.

    Four values, all None for a prompt job: the spec itself, the hash Phase 2
    compiled, the archetype (and the version of it that compiled), and the
    dimension check Phase 3 measured. Together they are everything the spec panel
    and the Fits Check need, and nothing they do not — the designed feature table
    and the full dimension report are on `GET /jobs/{id}/spec`, which nothing polls.

    **The row is authoritative, not the file.** `POST /jobs` normalises the submitted
    spec to its canonical form on the request model, stores it in `request_params`
    and *then* writes `data/inputs/{job_id}/spec.json` from it, and Phase 2 copies
    that into the output directory — so the file cannot disagree with the row, and
    the row is the copy that survives someone clearing `data/outputs/`. It is also
    the copy this endpoint already has in hand: `db.get_job` fetched it, so a spec
    job costs one dict lookup and one sha256 over ~600 bytes rather than a stat, an
    open and a parse on every tick of a one-second poll.

    The file is consulted only when the row says "spec job" and carries no spec —
    a row whose `request_params` predates the field, or one a CLI `--spec` run
    attached itself to. That read is `resolve_job_artifact`'s, so it finds the
    per-job directory and the `dev-` variant alike.

    `spec_hash` prefers `generation_params["spec_sha256"]`, because that is the hash
    of the spec the compiler actually received. It falls back to hashing the row's
    spec, which is the only answer available before Phase 2 has run.

    Args:
        job: A PrintJob row.

    Returns:
        `{"spec", "spec_hash", "archetype", "archetype_version", "dimension_check",
        "game_box"}`, every value None when the job is not a spec job.
    """
    empty = {
        "spec": None,
        "spec_hash": None,
        "archetype": None,
        "archetype_version": None,
        "dimension_check": None,
        "game_box": None,
    }

    request_params = job.request_params or {}
    generation_params = job.generation_params or {}
    spec = request_params.get("spec")
    compiled_hash = generation_params.get("spec_sha256")

    if spec is None and not compiled_hash:
        return empty

    if spec is None:
        artifact = resolve_job_artifact(job.job_id, "spec.json")
        if artifact is not None:
            try:
                spec = json.loads(artifact.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 — a missing spec is not a 500
                logger.warning("Could not read spec.json for %s: %s", job.job_id, exc)
        if spec is None:
            return empty

    if not isinstance(spec, dict):
        logger.warning("Job %s has a spec that is not an object; ignoring", job.job_id)
        return empty

    spec_sha = compiled_hash
    if not spec_sha:
        try:
            spec_sha = spec_hash(OrganizerSpec.from_dict(spec))
        except SpecError as exc:  # noqa: PERF203 — one row, one message
            logger.warning("Job %s carries a spec the schema refuses: %s", job.job_id, exc)

    # The archetype the *compiler* named wins over the one the spec asked for: they
    # agree today, and if they ever do not, what ran is the fact worth showing.
    archetype = generation_params.get("archetype") or spec.get("archetype")

    return {
        "spec": spec,
        "spec_hash": spec_sha,
        "archetype": archetype,
        # None until Phase 2 has compiled. The panel renders the archetype alone
        # rather than inventing a version for a job that has not been compiled yet.
        "archetype_version": generation_params.get("archetype_version"),
        # Written by Phase 3 onto `repair_report` (the `achieved_extent_mm`
        # precedent — no new column). None until Phase 3 has measured.
        "dimension_check": (job.repair_report or {}).get("dimension_check"),
        # The curated box the compiler recorded, with the source behind each of its
        # three numbers. Read off `generation_params` rather than resolved from
        # `spec.box` here, and the difference matters: this is **what that run was
        # built against**, sources and capture dates as they stood on the day, so a
        # later correction to the KB cannot rewrite the provenance of a finished part.
        # None both for a job with no box and for one compiled before Phase 2 ran —
        # the spec still carries `box.id`, and no provenance is claimed for it.
        "game_box": generation_params.get("game_box"),
    }


#: The stored credential each firmware authenticates with. `klipper` and `moonraker`
#: are the same machine seen from the profile and from the HTTP API in front of it.
#: Bambu's is `BAMBU_CODE`, which is what the wizard writes — reading
#: `BAMBU_ACCESS_CODE`, as the old code did, always resolved to None.
FIRMWARE_CREDENTIAL_KEYS = {
    "octoprint": "OCTOPRINT_API_KEY",
    "klipper": "MOONRAKER_API_KEY",
    "moonraker": "MOONRAKER_API_KEY",
    "bambu": "BAMBU_CODE",
}

#: The stored address each firmware is reached at, in the same terms.
FIRMWARE_URL_KEYS = {
    "octoprint": "OCTOPRINT_URL",
    "klipper": "MOONRAKER_URL",
    "moonraker": "MOONRAKER_URL",
    "bambu": "BAMBU_IP",
}


def printer_credential(firmware: str, read=None) -> BoundCredential:
    """The credential a firmware may send to the address configured for it *now*.

    One gate in front of every outbound printer secret — the connection test, the
    job's own probe, `resolve_printer_target` and the dispatch gate all ask here. A
    key is sent only to the host it was saved beside, because the address is a stored
    value `POST /config` can change and the key is not, so the two together were a
    way to have this server hand a printer key to a chosen third party.

    Args:
        firmware: A firmware name; anything unrecognised is read as OctoPrint, which
            is `resolve_printer_target`'s fallback too.
        read: How to read a stored value, defaulting to the config store. Pass
            `stored.get` where the whole store has already been read once.

    Returns:
        A `BoundCredential`; `.value` is None when there is no key *or* when the key
        is being withheld, and `.reason` distinguishes the two.
    """
    credential_key = FIRMWARE_CREDENTIAL_KEYS.get(firmware, "OCTOPRINT_API_KEY")
    return bound_printer_credential(credential_key, read or config_store.get)


def resolve_printer_target(profile_path: str | None = None) -> tuple[str, str | None, str | None]:
    """Resolve which printer a job talks to, from one place.

    Precedence is split deliberately:

    * **firmware** — the profile wins when it names one, because a job asks for a
      specific profile explicitly, which is more specific than a global default.
    * **base_url / api_key** — the config store wins, because those are what the user
      typed into Printer Setup; the values in the bundled profiles are dev defaults
      (and their ``api_key`` is usually null).

    Resolving this in one place stops the telemetry collector from watching a different
    printer than the pipeline is printing to.

    The stored key is subject to the host binding — `printer_credential` — so a
    dispatch to an address that changed after the key was saved goes out without it,
    and the profile's own `api_key` is only ever paired with the profile's own
    `base_url`. A profile is a file in `pythonsrc/profiles`; the store is an
    unauthenticated endpoint, and the two must not be mixed to make a credentialled
    request to an address one side chose and the other did not.

    Args:
        profile_path: Optional path to a printer profile JSON.

    Returns:
        A (firmware, base_url, api_key) tuple. Firmware falls back to "octoprint";
        `api_key` is None when the stored key is bound to another host.
    """
    profile_data: dict = {}
    if profile_path:
        try:
            with open(profile_path, "r") as f:
                profile_data = json.load(f)
        except Exception as e:
            logger.warning(f"Could not read printer profile {profile_path}: {e}")

    firmware = profile_data.get("firmware") or config_store.get("DEFAULT_PRINTER_FIRMWARE") or "octoprint"

    base_url = config_store.get(FIRMWARE_URL_KEYS.get(firmware, "OCTOPRINT_URL"))
    api_key = printer_credential(firmware).value

    if not base_url:
        # No stored address, so the profile's is the target — and only then is the
        # profile's own key the right one to pair with it.
        base_url = profile_data.get("base_url")
        if api_key is None:
            api_key = profile_data.get("api_key")

    return firmware, base_url, api_key

def container_reachable_url(url: str | None) -> str | None:
    """Rewrite a host-local printer URL so it also works from inside a container.

    ``localhost`` is the one address whose meaning depends on which side of the
    container boundary is reading it. The config store holds what a person typed
    into Printer Setup and what a native process needs — ``http://localhost:5001``
    for the dockerised OctoPrint simulator — and that is also the value the
    telemetry row records, which is what distinguishes a simulator print from real
    hardware. So it must stay as it is on read; only the moment an outbound
    connection is opened is it translated.

    `pipeline.py` and `run_operator.py` have done exactly this since they were
    written, guarded on ``/.dockerenv``. The server did not, on the assumption that
    it always ran natively — but `docker compose up api-server` is the documented
    way to start it, and there ``localhost:5001`` is the api-server container
    itself. Every probe answered "All connection attempts failed" and the printer
    badge read Offline beside a simulator that was Operational.

    Args:
        url: A base URL, or None.

    Returns:
        The URL unchanged when it names no loopback address or when this process is
        not containerised; otherwise the same URL via ``host.docker.internal``.
    """
    if not url or not os.path.exists("/.dockerenv"):
        return url
    if "localhost" not in url and "127.0.0.1" not in url:
        return url

    # The simulator is a container this server manages, so when the loopback URL is
    # its published port the shared compose network is the better route: it needs
    # neither the host gateway nor the host firewall to permit a bridge to reach a
    # published port, which on Fedora firewalld does not.
    try:
        port = urlparse(url).port or 80
        internal = simulator_manager.internal_url(port)
        if internal:
            return internal
    except Exception as exc:  # noqa: BLE001 — never let a lookup break a dispatch
        logger.debug("Could not resolve a container route to the simulator: %s", exc)

    return url.replace("localhost", "host.docker.internal").replace(
        "127.0.0.1", "host.docker.internal"
    )

# How long a stopped pipeline gets to exit on SIGTERM before it is killed outright.
PIPELINE_TERM_GRACE_S = 10


def _read_current_phase(job_id: str) -> dict | None:
    """The last phase line the pipeline wrote to its `.status` file, or None.

    Shared by `GET /jobs/{id}` and the cancel endpoint so there is one reader of the
    `.status` protocol. The file is append-only and one JSON object per line; the last
    line is the pipeline's most recent word on where it got to.
    """
    status_file = Path(__file__).parent.parent / "data" / "logs" / f"{job_id}.status"
    if not status_file.exists():
        return None
    try:
        with open(status_file, "r") as f:
            lines = [line.strip() for line in f if line.strip()]
    except OSError:
        return None
    if not lines:
        return None
    try:
        parsed = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


#: Phase names as `pipeline._write_status` writes them, so a record appended by the
#: server and one written by the pipeline agree about what a phase is called. The last
#: line of the `.status` file *is* `current_phase`, so a disagreement here shows up in
#: the UI as a phase that changed its name mid-run.
_PHASE_STATUS_NAMES = {
    1: "visualizer",
    2: "sculptor",
    3: "engineer",
    4: "slicer",
    5: "operator",
}


def _append_phase_status(job_id: str, phase: int, status: str, error: str | None = None) -> None:
    """Append one phase record to a job's `.status` file.

    The pipeline owns this file for phases 1–4; Phase 5 now runs from the server, and
    without a record here the rail would show phase 05 pending while a printer was
    already extruding. Same shape as `pipeline._write_status` writes — the last line of
    this file *is* `current_phase`.

    Args:
        job_id: The job the record belongs to.
        phase: Phase number.
        status: "running", "complete" or "error".
        error: Optional failure detail.
    """
    log_dir = Path(__file__).parent.parent / "data" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "phase": phase,
            # The pipeline writes the phase's *name* here ("visualizer", "sculptor",
            # …); this wrote the number as a string for anything but Phase 5, so a
            # record appended by the server disagreed with one written by the
            # pipeline about what the same phase is called. `operator` is kept for
            # Phase 5 because that is what the pipeline writes and what the dispatch
            # gate's test pins.
            "name": _PHASE_STATUS_NAMES.get(phase, str(phase)),
            "status": status,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if error is not None:
            record["error"] = error
        with open(log_dir / f"{job_id}.status", "a") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.warning("Could not write phase status for %s: %s", job_id, exc)


def _container_database_url(dsn: str) -> str:
    """`dsn` as the pipeline container must see it.

    A PostgreSQL on this host's loopback is `host.docker.internal` from inside the
    container; a Supabase URL passes through unchanged. Parsed rather than
    string-replaced so a password containing "localhost" is left alone.
    """
    try:
        parts = conninfo_to_dict(dsn)
    except Exception:  # noqa: BLE001 — an unparseable URL fails later, with its own message
        return dsn
    if parts.get("host") in ("localhost", "127.0.0.1"):
        parts["host"] = "host.docker.internal"
        return make_conninfo(**parts)
    return dsn


#: This server's own address, as a process running *beside* it sees it: the native
#: Phase 1 subprocess on the mps_native path, and `run_operator.py`, which runs in
#: this process's own container. The port is the one `ports:` publishes in
#: infra/docker-compose.yml and the one `make start-native` gives uvicorn;
#: `DS_API_BIND` moves the bind address, never the port.
NATIVE_API_URL = "http://127.0.0.1:8000"

#: Hostnames that mean "the machine reading this", and therefore mean something
#: different on each side of a container boundary.
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")

#: The compose file every pipeline launch names, relative to the repo root. Kept as
#: a constant because the *project name* is derived from its directory when
#: `COMPOSE_PROJECT_NAME` is unset, so the two cannot be allowed to drift;
#: `tests/test_api_url_routing.py` asserts the launched command names this file.
COMPOSE_FILE = Path("infra") / "docker-compose.yml"


def _compose_project_name() -> str:
    """The compose project the pipeline container this server launches will join.

    `docker compose run pipeline-runner` is launched with this process's environment
    (`subprocess_env`), so `COMPOSE_PROJECT_NAME` decides it when it is set — and
    `infra/docker-compose.yml` sets it in the api-server's own environment, so in a
    container it always is. Unset, compose falls back to the name of the directory
    holding the first `-f` file, which is what this mirrors.
    """
    return os.environ.get("COMPOSE_PROJECT_NAME") or COMPOSE_FILE.parent.name


def _container_api_url(url: str) -> str:
    """`url` as the pipeline container must see this server.

    The pipeline runs as `docker compose run --rm pipeline-runner` on **every**
    execution strategy, mps_native included — that strategy runs Phase 1 natively
    and everything after it in the container. So `DS_API_URL` used to be chosen by
    strategy, `127.0.0.1:8000` for mps_native, and the container was handed the
    address of *itself*: on a Mac the collector's
    `internal_telemetry.send_internal_telemetry` POSTed into the void and live print
    telemetry never reached the WebSocket fan-out. Silent, because the relay falls
    back to a local broadcaster the container does not have, and invisible until the
    pipeline reaches Phase 5 itself (`--print`), which the web app never asks for.

    One value is set for the native side and translated here, at the one boundary
    that needs it — the `_container_database_url` shape, and for the same reason:
    the host is parsed rather than string-replaced, so a path or query containing
    "localhost" is left alone.

    `container_reachable_url` is the wrong tool for this, close as the two look. It
    declines to translate anything unless *this* process is containerised, which is
    right for a URL this process is about to open and wrong here, where the process
    that opens it is the pipeline container — containerised however this server is
    running. And the compose route it prefers is the OctoPrint simulator's, which
    has nothing to do with the API server; the equivalent route for this server is
    `SimulatorManager.own_internal_url`, preferred below for the same reason and one
    more, given there.

    Args:
        url: The API server's address as the host sees it.

    Returns:
        A container-to-container route over the compose network when this server is
        itself a container in the project the pipeline will join; else the same URL
        via `host.docker.internal` when it names a loopback host —
        `pipeline-runner` carries the `host.docker.internal:host-gateway` extra
        host; else the URL unchanged, since a routable address means the same thing
        from either side.
    """
    parsed = urlparse(url)
    if parsed.hostname not in _LOOPBACK_HOSTS:
        return url

    # The compose network is preferred over the host gateway, for the reason
    # `container_reachable_url` prefers it for the simulator — and here it is not
    # only faster but the *only* route that works. `host.docker.internal` reaches
    # the host's gateway address, while `ports:` publishes this server on
    # `${DS_API_BIND:-127.0.0.1}`: a socket bound to loopback does not accept a
    # connection arriving on another interface, so a containerised api-server on the
    # default bind is unreachable that way however well the name resolves.
    if os.path.exists("/.dockerenv"):
        try:
            route = simulator_manager.own_internal_url(
                parsed.port or 80, _compose_project_name(),
            )
        except Exception as exc:  # noqa: BLE001 — never let a lookup break a launch
            logger.debug("Could not resolve a container route to this server: %s", exc)
            route = None
        if route:
            # Only the address is taken from the route; the scheme and any path stay
            # the caller's.
            return urlunparse(parsed._replace(netloc=urlparse(route).netloc))

    netloc = "host.docker.internal"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    if parsed.username:
        credentials = parsed.username
        if parsed.password:
            credentials = f"{credentials}:{parsed.password}"
        netloc = f"{credentials}@{netloc}"
    return urlunparse(parsed._replace(netloc=netloc))


def _iso(value) -> Optional[str]:
    """A timestamp column as ISO 8601 text, whether it arrived as datetime or text."""
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


def job_status_from_outcome(outcome: str | None, started_at) -> str:
    """Map a stored outcome onto the synthetic status the API exposes.

    One function for every endpoint: the list and detail views previously mapped
    `failure` to opposite statuses ("completed" vs "failed"). A job awaiting a
    human verdict has finished as far as the software is concerned, so it maps to
    "completed" — the pending state is carried by `awaiting_verdict` rather than
    by overloading a status string every consumer already switches on.
    """
    if outcome == "unknown":
        return "running" if started_at else "queued"
    # `dev` and `declined` are settled rows: the print ran and the question has been
    # closed out. They map to "completed" because that is what the software did — the
    # distinction they carry is about the *data*, not about the run, and lives in the
    # outcome column where a query can see it.
    if outcome in ("success", "awaiting_verdict", "dev", "declined"):
        return "completed"
    if outcome == "cancelled":
        return "cancelled"
    return "failed"


def get_resolved_strategy() -> str:
    override = config_store.get("EXECUTION_STRATEGY_OVERRIDE")
    if override and override in ("mps_native", "nvidia_docker", "cpu_docker"):
        return override
    return get_execution_strategy()

#: How a spec's sleeving reads inside the label a spec job is given.
#:
#: The same three *keys* as `SLEEVING_NOTE` in `web/src/organizer/spec.ts`, which
#: captions the same field — `test_composer_options.py` binds the two key sets, and
#: has to, because a sleeving one side knows and the other does not is a caption that
#: silently falls back. The wording differs on purpose and only here: this one goes
#: inside a noun phrase ("100 double-sleeved standard cards"), where the compound
#: adjective takes a hyphen, and the panel's caption stands alone after a comma
#: ("standard, double sleeved"), where it does not.
SLEEVING_WORDS: Dict[str, str] = {
    "none": "unsleeved",
    "single": "single-sleeved",
    "double": "double-sleeved",
}


def spec_label(spec: Dict[str, Any]) -> str:
    """A one-line description of a spec, for the `prompt` column of a spec job.

    A spec job has no prompt: nobody typed words, and the geometry is a function of
    the spec alone. But `print_job.prompt` is what every list, feed line and history
    row titles a job with, so leaving it empty makes a spec job unreadable everywhere
    a job is named, and inventing a sentence about a box nobody described would put
    prose in the column the generative path fills with the *actual* input.

    So the label is derived, strictly, from the spec itself — the archetype and what
    its compartments were asked to hold, nothing else — and the server writes it rather
    than the client, for the reason the canonical spec is stored rather than the
    submitted bytes: a second copy of this sentence in the browser would drift from the
    spec it claims to describe. A person who *does* type a line keeps it; a name
    somebody chose beats a generated one, and the spec is still the whole input either
    way.

    A compartment holds a card stack **or** a pocket (`Compartment` in
    `pythonsrc/organizer/spec.py`, issue #84), so there are two sentences. The pocket
    one names the grid rather than the count, because six identical 20 mm pockets read
    as "2 × 3 pockets 20 × 20 × 15 mm" and not as "6 pockets": a tray is the grid.

    **A box insert's compartments are not all the same shape**, which is the thing this
    function assumed until issue #152 and would have got silently wrong: it read
    `compartments[0]` and described the whole part with it, so an insert holding a deck
    and two pockets would have been titled "box insert · 60 double-sleeved standard
    cards" — a true sentence about one third of the part, in the column a person scans to
    tell two jobs apart. An insert is therefore listed rather than summarised: every
    compartment, in order, each in its own shape's words. There is no grid to collapse
    them into, which is exactly what makes it the archetype it is.
    """
    archetype = str(spec.get("archetype") or "organizer").replace("_", " ")
    compartments = spec.get("compartments") or []
    contents = (compartments[0] or {}).get("contents") if compartments else None
    if not isinstance(contents, dict):
        return archetype + _lettering_phrase(spec)
    if spec.get("insert") is not None:
        shapes = [_contents_phrase((c or {}).get("contents")) for c in compartments]
        shapes = [s for s in shapes if s]
        if not shapes:
            return archetype + _lettering_phrase(spec)
        return (
            f"{archetype} · {len(shapes)} compartments: " + ", ".join(shapes)
            + _lettering_phrase(spec)
        )
    if "count" in contents:
        return f"{archetype} · {_contents_phrase(contents)}" + _lettering_phrase(spec)
    # A pocket. `tray.columns` is the only layout field and the rows follow from the
    # compartment count — the same derivation `token_tray.derive` does, and the only
    # arithmetic in this function, because a label that said "6 pockets" for a 2 × 3
    # tray would describe a shape the engine does not build.
    total = len(compartments)
    columns = (spec.get("tray") or {}).get("columns")
    grid = f"{total // columns} × {columns}" if isinstance(columns, int) and columns > 0 and not total % columns else str(total)
    return (
        f"{archetype} · {grid} pockets {_pocket_size(contents)} mm"
        + _lettering_phrase(spec)
    )


def _lettering_phrase(spec: Dict[str, Any]) -> str:
    """What a decorated spec adds to its own title, or "" for an undecorated one.

    Two boxes for the same deck, one of them with a name cut into the lid, are two
    different parts and eight hours of printing apart — and until this, the job list
    called them the same thing. The words are the *spec's* own (issue #157), like every
    other part of this label, so a title cannot say something the geometry does not.

    Reads defensively: this runs on the canonical spec from `POST /jobs`, but
    `POST /organizer/resolve` labels while somebody is still editing.
    """
    emboss = spec.get("emboss")
    if not isinstance(emboss, dict):
        return ""
    text = emboss.get("text")
    if not isinstance(text, str) or not text.strip():
        return ""
    face = str(emboss.get("face") or "").replace("_", " ").strip()
    mode = str(emboss.get("mode") or "").strip()
    where = f" on the {face}" if face else ""
    return f" · {mode or 'lettered'} “{text.strip()}”{where}".rstrip()


def _pocket_size(contents: Dict[str, Any]) -> str:
    """A pocket's three millimetres, as `W × D × H`. Non-numbers print as typed — this
    runs on the canonical spec, but `POST /organizer/resolve` labels while somebody is
    still editing, and a half-typed field must not raise here."""
    return " × ".join(
        f"{contents[key]:g}" if isinstance(contents.get(key), (int, float)) else str(contents.get(key))
        for key in ("width_mm", "depth_mm", "height_mm")
    )


def _contents_phrase(contents: Any) -> str:
    """One compartment in the words of whichever shape it is, or "" for neither.

    The `Compartment.contents` union told apart the way the schema tells it apart —
    `count` against the three millimetres, no `kind` discriminator — so a label and a
    spec cannot disagree about what a compartment holds.
    """
    if not isinstance(contents, dict):
        return ""
    if "count" in contents:
        card = contents.get("card", "standard")
        sleeving = SLEEVING_WORDS.get(str(contents.get("sleeving")), str(contents.get("sleeving")))
        return f"{contents.get('count')} {sleeving} {card} cards"
    return f"{_pocket_size(contents)} mm"


class JobRequest(BaseModel):
    """Pydantic model representing a new print job request."""
    # Not `min_length=1`: a spec job has no prompt, and `_a_job_always_has_a_label`
    # below both enforces the old rule for a prompt job and writes the spec's own
    # label for a spec one. See `spec_label`.
    prompt: str = ""
    printer_id: str = Field(..., min_length=1)
    profile: str = ""
    skip_visualizer: bool = False
    skip_sculptor: bool = False
    blueprint_path: Optional[str] = None
    print: bool = False
    start_print: bool = False
    # What the user was aiming at. Material is not decoration: it sets the density
    # behind the filament mass estimate and is the likeliest explanation for a bed
    # adhesion failure, and nothing else in the system records it.
    material_type: Optional[str] = None
    material_brand: Optional[str] = None
    # Bounded for the same reasons as the prompt, and because it is interpolated
    # into the string sent to the image model — an unbounded second prompt channel.
    material_colour: Optional[str] = Field(None, max_length=64)
    # F13's decorative layer: the words raised on a face of the part. The **third**
    # prompt channel, and the most exposed of the three, because what is typed here
    # is reproduced on the object rather than described to a model — so it is
    # screened as its own channel, and the functional-article rule does not reach it
    # (`ip_screen.DEPICTION_ONLY_CHANNELS`). Bounded like the colour box.
    #
    # It compiles to nothing yet, deliberately: the geometry is issue #157, and PRD
    # F13 says do not ship the decorative layer before this screen exists. So the
    # channel and its refusal land first, and no composer sends the field until the
    # thing that builds it does.
    embossing_text: Optional[str] = Field(None, max_length=64)
    # Reproducibility and lineage.
    seed: Optional[int] = None
    parent_job_id: Optional[str] = None
    regeneration_reason: Optional[str] = None
    # Phase 2 reconstruction settings. Both change the geometry, so both are
    # recorded onto the job's `generation_params` rather than staying implicit.
    pipeline_type: Optional[str] = Field(
        None, pattern="^(512|1024|1024_cascade|1536_cascade)$"
    )
    mesh_seed: Optional[int] = None
    # How big the finished part should be. Validated on the model rather than in the
    # handler: `OutcomeRequest` made that mistake once and wrote the row before
    # refusing the request. `None` means "nobody chose", and the flag is then not
    # forwarded at all so `pipeline.py`'s own 50.0 stays the single default — a
    # second copy in the server would drift the first time either moved. The ceiling
    # is a sanity bound, not a build volume; the real limit is the printer profile's,
    # and it is enforced where the profile is known.
    target_mm: Optional[float] = Field(None, gt=0, le=1000)
    # Which extent `target_mm` describes, as it was labelled for the requester. The
    # pattern is the enforcement: an axis the Engineer does not implement must not
    # reach the subprocess, and a typo must not fall back to the other convention.
    scale_axis: Optional[str] = Field(None, pattern="^(height|longest)$")
    # Whether the person typed the size or accepted a suggestion parsed out of their
    # prompt. Only the client knows, so only the client can say — but "default" is
    # not the client's to claim: the server writes that itself when no size arrived,
    # and "spec" when a spec did (below).
    size_source: Optional[str] = Field(None, pattern="^(user|prompt_hint)$")
    # The parametric path. An organizer spec (`pythonsrc/organizer/spec.py`) as JSON;
    # the pipeline compiles it in place of Phases 1–2 and asserts its dimensions after
    # Phase 3. Validated on the model with the stdlib-only schema, so a bad spec is a
    # 422 listing every problem and no row is ever written for it.
    spec: Optional[Dict[str, Any]] = None
    # Where `POST /jobs` wrote the spec, as the *container* sees it — the
    # `blueprint_path` precedent. Server-populated; a client value is overwritten.
    spec_path: Optional[str] = None

    @field_validator("spec")
    @classmethod
    def _spec_is_valid(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Run the schema, and make its problem list the 422 detail.

        Only the schema: the archetype's own rules (`deck_box.validate`) need the
        kernel, which the api-server image does not have, so those refusals arrive
        as a failed Phase 2. What the schema refuses — unknown keys, a bad archetype
        name, a negative millimetre — must not become a job.

        **The canonical form is what is kept**, not the bytes that arrived. A request
        may omit `process` and `constraints` entirely and mean the schema's defaults
        by it; storing the submitted dict put a spec in `request_params` that named a
        wall thickness nowhere while the mesh was compiled with one, so the row and
        the `spec.json` written from it described the same job differently and
        `GET /jobs/{id}` served a spec with holes in it. Normalising here — on the
        model, before the value is used for anything — means the row, the file and
        the compiler all see one spec, and `spec_hash` over the row equals the
        `spec_sha256` Phase 2 records.

        **The refusal is structured, not only prose.** A `PydanticCustomError`'s
        context is carried into the 422 body by FastAPI's validation handler, so the
        detail entry holds `ctx.problems` — one `{path, message}` per problem, with
        the dotted path the schema already names (`spec.lid.clearance_mm`). Without
        it the only route from a refusal to the field that caused it was splitting
        the joined sentence in the browser, on a separator the client cannot test.
        The joined summary stays in `msg`, because a caller that reads nothing else
        must still get the whole refusal.
        """
        if value is None:
            return None
        try:
            return OrganizerSpec.from_dict(value).to_dict()
        except SpecError as exc:
            raise PydanticCustomError(
                "spec_invalid",
                "invalid spec: {summary}",
                {
                    "summary": "; ".join(exc.problems),
                    "problems": problems_with_paths(exc.problems),
                },
            ) from None

    @model_validator(mode="after")
    def _spec_decides_the_size(self) -> "JobRequest":
        """A spec and a requested size are two deciders for one dimension.

        `size_source` exists so the row can say who chose the size; a request naming
        both would make it lie whichever way it answered. Refuse the combination.
        """
        if self.spec is not None:
            named = [
                name for name in ("target_mm", "scale_axis", "size_source")
                if getattr(self, name) is not None
            ]
            if named:
                raise ValueError(
                    f"a spec decides every dimension; {', '.join(named)} cannot be "
                    "combined with spec"
                )
        return self

    @model_validator(mode="after")
    def _the_screened_text_is_the_compiled_text(self) -> "JobRequest":
        """A spec's emboss text **is** `embossing_text`, so the screen reads what is cut.

        Issue #156 built `embossing_text` as the third screened prompt channel and left
        it compiling to nothing, because the geometry was #157 and PRD F13 says do not
        ship the decorative layer before the screen exists. This is the join, and it is
        one line of consequence: the string the IP screen reads and the string the
        compiler cuts into the part have to be the same string, or the screen watches a
        field nobody sent while a blocked name goes onto a lid.

        So a spec's `emboss.text` is **copied into** `embossing_text` when the request
        does not carry one, and a request carrying both with different values is refused
        naming both — there is no rule that could pick the right one, and picking either
        would either screen a string that is not cut or cut a string that was not
        screened. Identical values are fine and are what a client that fills both sends.

        Runs after `_spec_is_valid`, so `self.spec` is the canonical form: the text here
        is the stripped, schema-validated one the compiler will read. And it runs on the
        *model*, so it is done before `job_id` exists and before anything is written —
        `screen_prompt` in `POST /jobs` then refuses a blocked emboss with no row, no
        directory and no file, which is the acceptance criterion "a spec whose emboss
        text is blocked creates no job".
        """
        emboss = (self.spec or {}).get("emboss") if self.spec is not None else None
        text = emboss.get("text") if isinstance(emboss, dict) else None
        if not isinstance(text, str) or not text:
            return self
        if self.embossing_text is None:
            self.embossing_text = text
        elif self.embossing_text != text:
            raise ValueError(
                f"embossing_text {self.embossing_text!r} and spec.emboss.text {text!r} "
                "are two different strings for one piece of lettering; the field that "
                "is screened and the field that is cut into the part must be the same. "
                "Send the text in the spec only, or send the same string in both"
            )
        return self

    @model_validator(mode="after")
    def _a_job_always_has_a_label(self) -> "JobRequest":
        """Every job is titled by its `prompt`; a spec job's title comes from the spec.

        Runs after `_spec_is_valid`, so `self.spec` is the canonical form and the
        label describes the spec that will actually be compiled rather than the bytes
        that arrived. A request with neither a prompt nor a spec has nothing to build
        and nothing to call itself, and is refused exactly as `min_length=1` refused
        it before.
        """
        if self.prompt.strip():
            return self
        if self.spec is None:
            raise ValueError("prompt must not be empty unless a spec is supplied")
        self.prompt = spec_label(self.spec)
        return self


class OutcomeRequest(BaseModel):
    """A human's verdict on whether a print actually succeeded.

    Five values, and two of them exist to keep the dataset honest rather than to
    describe a part:

    - `dev` — a developer's test run. Answers the prompt so the job stops being asked
      about, and marks the row as **not real data**. Without it, every pipeline change
      verified by printing a cube lands in the same column the pilot's results are
      measured from.
    - `declined` — the user was asked, asked again, and said don't ask again. Distinct
      from never being asked (which is the absence of an `outcome_prompt_shown` event)
      and from a single skip (`outcome_prompt_dismissed`). Deliberately **not**
      `unknown`: that string is the sentinel for "the pipeline has not finished", so
      writing it here would make a settled job read as running again.
    """
    verdict: str = Field(..., pattern="^(success|failure|cancelled|dev|declined)$")
    failure_type: Optional[str] = None
    notes: Optional[str] = None
    layer_pct: Optional[float] = None

    @field_validator("failure_type")
    @classmethod
    def _known_failure_type(cls, value: Optional[str]) -> Optional[str]:
        """Reject an unknown failure type before anything is written.

        `FailureEvent.__post_init__` validates this too, but by the time the handler
        constructs one the verdict has already been saved — so a typo produced a 500,
        or later a 422, with the job left marked `failure` regardless. Validating on the
        request model means the handler never runs and the row is untouched.
        """
        if value is None or value in VALID_FAILURE_TYPES:
            return value
        raise ValueError(
            f"Unknown failure_type '{value}'. Expected one of: "
            f"{', '.join(sorted(VALID_FAILURE_TYPES))}."
        )

class JobResponse(BaseModel):
    """Pydantic model representing the immediate response to a job creation."""
    job_id: str
    status: str

class JobStatusResponse(BaseModel):
    """Pydantic model representing the detailed status of a print job."""
    job_id: str
    status: str
    prompt: str
    completed_at: Optional[str]
    started_at: Optional[str] = None
    outcome: str
    log_tail: List[str]
    current_phase: Optional[dict] = None
    printer_id: Optional[str] = None
    printer_firmware: Optional[str] = None
    profile_name: Optional[str] = None
    machine_name: Optional[str] = None
    #: [width, depth, height] in mm, for drawing the build envelope in the G-code
    #: preview. None when the profile does not declare one.
    build_volume_mm: Optional[list[float]] = None
    nozzle_diameter_mm: Optional[float] = None
    layer_height_mm: Optional[float] = None
    printability_score: Optional[float] = None
    printability_verdict: Optional[str] = None
    material_type: Optional[str] = None
    material_brand: Optional[str] = None
    material_colour: Optional[str] = None
    #: The size the requester asked for, in mm, or None when they did not choose one.
    #: Returned so a regeneration can echo the same size back: `JobDetail` rebuilds
    #: the request from this row, so a size that is not here silently resets to the
    #: pipeline default on every regenerate and misattributes the change to the model.
    requested_size_mm: Optional[float] = None
    #: "default" | "user" | "prompt_hint" | "spec". See `VALID_SIZE_SOURCES`.
    size_source: Optional[str] = None
    #: "height" | "longest" — which extent `requested_size_mm` described.
    requested_scale_axis: Optional[str] = None
    blueprint_seed: Optional[int] = None
    parent_job_id: Optional[str] = None
    download_count: int = 0
    slice_status: Optional[str] = None
    estimated_print_time_s: Optional[int] = None
    filament_used_mm3: Optional[float] = None
    filament_used_g: Optional[float] = None
    support_filament_mm3: Optional[float] = None
    layer_count: Optional[int] = None
    outcome_source: Optional[str] = None
    #: True when a photo of the printed part has been stored, so the page knows to ask
    #: `GET /jobs/{id}/photo` for it. A boolean rather than the path: the path is a
    #: server-side location, and the client has exactly one thing to do with it.
    has_fit_photo: bool = False
    awaiting_verdict: bool = False
    #: True when a bundled fixture stood in for Phase 1 or Phase 2. Carried out to the
    #: UI, not only to the dataset: the running view captions the blueprint "drawn from
    #: the prompt" and shows the mesh as this job's reconstruction, and for a fixture run
    #: both statements are false. None on rows written before the column existed, which
    #: is deliberately distinct from a verified False.
    used_reference_assets: Optional[bool] = None
    #: "not_ready" | "awaiting_confirmation" | "dispatched". See `dispatch_state`.
    dispatch_state: str = "not_ready"
    #: "not_ready" | "awaiting_approval" | "approved" | "rejected". See
    #: `blueprint_gate_state`. Phase 2 does not run until this is "approved".
    blueprint_gate_state: str = "not_ready"
    #: What the person is being asked to approve: the blueprint's own sha256 and the
    #: url it is served from. Sent back with the approval so the server can refuse an
    #: approval of an image that has since changed.
    blueprint_gate_subject: Optional[dict] = None
    #: The printer this job's Phase 5 would go to, resolved now — the thing a person is
    #: being asked to confirm. See `dispatch_target`.
    dispatch_target: Optional[dict] = None
    #: The organizer spec this job was compiled from, canonical, or None for a prompt
    #: job. See `job_spec_summary` — the row is authoritative and the whole group costs
    #: one dict lookup, because this endpoint is polled.
    spec: Optional[Dict[str, Any]] = None
    #: sha256 of the canonical spec — what Phase 2 recorded as `spec_sha256`.
    spec_hash: Optional[str] = None
    #: The archetype that compiled it, and the version of that archetype. The version
    #: is None until Phase 2 has run: nothing has compiled the spec yet.
    archetype: Optional[str] = None
    archetype_version: Optional[str] = None
    #: Phase 3's measurement of the compiled mesh against the spec — the only fit
    #: verdict on this endpoint, and the only one the UI may show, because it is the
    #: only one that was measured. None until Phase 3 has run. See
    #: `pythonsrc/organizer/compiler.py::DimensionReport.to_dict`.
    dimension_check: Optional[Dict[str, Any]] = None
    #: The curated box interior this part was compiled against, as Phase 2 recorded it —
    #: the entry, the KB version and the source behind each of its three numbers. Read off
    #: `generation_params`, so it is what that run was built against rather than what the
    #: KB says now. None for a part built to typed millimetres, which is the degraded mode
    #: and not a gap: `spec.box` is what says which of the two this job is.
    game_box: Optional[Dict[str, Any]] = None


def _profile_build_volume(source: dict) -> Optional[List[float]]:
    """[width, depth, height] in mm from a profile dict, or None if it does not say.

    Module level and single-implementation on purpose. It answers two questions that
    must not diverge: the G-code preview draws the build envelope around the toolpath,
    and the composer clamps a requested size before any job exists. A wrong envelope
    is worse than none — a part that fits reads as overflowing a machine it was never
    sliced for — and a clamp derived from a second reader of the same keys would
    disagree with `printability`'s own `build_volume_fit` check.

    "The profile does not say" is a first-class answer, not a zero: `bambu_test.json`
    declares no machine dimensions at all, and a caller that assumed a number would
    clamp every size to nothing for that printer.

    Args:
        source: A parsed printer profile, or a job's frozen `process_params`.

    Returns:
        The three dimensions as floats, or None when any is missing or unparseable.
    """
    keys = ("machine_width", "machine_depth", "machine_height")
    if not all(source.get(k) is not None for k in keys):
        return None
    try:
        return [float(source[k]) for k in keys]
    except (TypeError, ValueError):
        return None


def _profile_snapshot(profile_path: str) -> tuple[Optional[dict], Optional[float]]:
    """Read a printer profile and pull out the nozzle diameter.

    The snapshot is stored on the job because profiles are edited in place. Resolving
    them at query time makes a finished job silently claim whatever settings the file
    holds today, which is how a historical row ends up describing a print that never
    happened.

    Args:
        profile_path: Absolute path to the profile JSON.

    Returns:
        A (profile dict, nozzle diameter) pair; both None when the file is unreadable.
    """
    try:
        with open(profile_path, "r") as handle:
            data = json.load(handle)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not snapshot printer profile %s: %s", profile_path, exc)
        return None, None
    try:
        nozzle = float(data.get("machine_nozzle_size") or 0.4)
    except (TypeError, ValueError):
        nozzle = 0.4
    return data, nozzle


#: Verdict of the most recent database health check, so `/health` can answer without
#: a round trip to Supabase on every poll. Refreshed at startup and then every
#: `$DS_DB_HEALTH_INTERVAL_S` seconds while the server runs.
database_problems: list[str] = []

#: When `database_problems` was last refreshed, so a stale verdict is visible as one.
database_checked_at: Optional[datetime] = None

#: Default seconds between health checks. The database is a network service, and a
#: verdict taken once at startup would go on saying "healthy" through an outage.
DB_HEALTH_INTERVAL_S = 60.0


def health_interval_s(env: dict | None = None) -> Optional[float]:
    """Seconds between periodic database health checks, or None to disable.

    Args:
        env: Environment mapping; defaults to os.environ.

    Returns:
        The interval in seconds; 0 or negative disables the loop; an unparseable
        value falls back to the default rather than silently disabling the check.
    """
    raw = (env if env is not None else os.environ).get("DS_DB_HEALTH_INTERVAL_S")
    try:
        seconds = float(raw) if raw is not None else DB_HEALTH_INTERVAL_S
    except (TypeError, ValueError):
        seconds = DB_HEALTH_INTERVAL_S
    if seconds <= 0:
        return None
    return seconds


def subprocess_env(base: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """The environment for a process this server launches.

    Two sources, and only two: this server's own environment — which came from `.env`
    and from the image — plus `SUBPROCESS_ENV_KEYS`, the enumerated config-store keys
    a child actually reads. The store used to reach a subprocess by a third route:
    `POST /config` wrote `os.environ` and the startup hook copied the whole store into
    it, so every stored key was inherited by every launch. `PYTHONPATH` was a stored
    key, which made an unauthenticated request enough to prepend an import path to the
    pipeline container and to `run_operator.py`. Nothing here is copied wholesale, and
    the store cannot introduce a variable that is not on the allowlist.

    The store is read **here**, at launch, not cached at import: a printer key saved in
    Settings must reach the next job without a restart, which is the property the
    `os.environ` write was there to provide.

    A stored value wins over one of the same name in this process's environment —
    Settings is the live authority — and a key absent from the store leaves whatever
    `.env` set, rather than unsetting it.

    `OCTOPRINT_API_KEY` is on the allowlist and is also a bound credential, so it is
    read through `bound_printer_credential` rather than straight off the store: the
    child pairs it with `OCTOPRINT_URL`, which is the pairing the host binding exists
    to police. Forwarding it here and withholding it in `resolve_printer_target`
    would have left the key reaching the printer by the other route.

    `DS_API_TOKEN` is set here from this process's own `API_TOKEN` rather than being
    left to inheritance. Every child talks back to this server — the pipeline's
    collectors and the operator's both relay through `POST /jobs/{id}/internal-telemetry`
    — and that route is authenticated now, so a child without the token relays nothing.
    Inheritance covers only the case where the token came from `.env`; when the server
    generated one, it is in no environment but this function's answer.

    Args:
        base: The environment to start from. Defaults to this process's.

    Returns:
        A fresh mapping, safe for the caller to add its own `DS_*` variables to.
    """
    env = dict(os.environ if base is None else base)
    if API_TOKEN:
        env["DS_API_TOKEN"] = API_TOKEN
    for key in SUBPROCESS_ENV_KEYS:
        if key in PRINTER_CREDENTIAL_HOSTS:
            bound = bound_printer_credential(key, config_store.get)
            if bound.withheld:
                logger.warning("%s is not being forwarded: %s", key, bound.reason)
            # Removed before it is conditionally set, which the other keys do not need.
            # This mapping starts from `os.environ`, and `OCTOPRINT_API_KEY` is
            # documented in `.env.template` and loaded into every compose service by
            # `env_file` — so with no key *stored*, the binding had nothing to withhold,
            # the inherited one was never overwritten, and the address it was paired
            # with was still the store's. A printer credential in a child's environment
            # comes from the bound store or it does not come at all.
            env.pop(key, None)
            value = bound.value
        else:
            value = config_store.get(key)
        if value is not None:
            env[key] = value
    return env


def check_database_health(db: TelemetryDB) -> list[str]:
    """Verify the telemetry database is reachable and carries the schema.

    The SQLite file this replaced corrupted once and nothing noticed until a query
    answered `database disk image is malformed`; the lesson kept from that is that a
    server on a broken database must say so in its logs and on `/health`, not fail one
    endpoint at a time. What is checked changed with the storage: PostgreSQL's pages
    are its own business, so the questions are "does it answer" and "are the tables
    there".

    A missing table is the one problem this process can fix itself — the schema is
    idempotent DDL — so it is retried here before being reported. Anything else (the
    project paused, the network gone, a wrong URL) is reported as found. The verdict
    is cached in `database_problems` for `/health`.

    Args:
        db: A telemetry database handle.

    Returns:
        The problems found; empty when the database is sound.
    """
    global database_problems, database_checked_at

    problems = db.health_check()
    if problems and all(p.startswith("missing table") for p in problems):
        try:
            db.init_schema()
            problems = db.health_check()
        except Exception as exc:  # noqa: BLE001 — reported, not raised
            problems = [f"schema initialisation failed: {exc}"]

    database_problems = problems
    database_checked_at = datetime.now(timezone.utc)
    if problems:
        logger.error(
            "Telemetry database is UNHEALTHY (%s). Nothing is being recorded until "
            "this clears: %s", db.describe, "; ".join(problems),
        )
    return problems


#: Handle for the periodic health loop, cancelled at shutdown.
_db_health_task: Optional[asyncio.Task] = None


async def _periodic_db_health(interval_s: float) -> None:
    """Re-check the database on a cadence.

    Also what heals a server that started while Supabase was unreachable: the first
    check that succeeds creates any missing table, and `/health` turns green.

    Args:
        interval_s: Seconds between checks.
    """
    while True:
        await asyncio.sleep(interval_s)
        try:
            db = TelemetryDB()
            await asyncio.to_thread(check_database_health, db)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Periodic database health check failed: %s", exc)


#: Handle for the push reconciler, cancelled at shutdown.
_push_task: Optional[asyncio.Task] = None


async def _periodic_push(interval_s: float) -> None:
    """Ask the database whether any finished print still owes someone a notification.

    A loop rather than a hook on the three writers that set `awaiting_verdict` — see
    `server/push.py` for why. It is deliberately forgiving: a tick that raises logs and
    the next one runs, because the failure this must not have is a push subsystem that
    dies quietly and leaves every later print unannounced.

    Args:
        interval_s: Seconds between ticks.
    """
    while True:
        await asyncio.sleep(interval_s)
        db = None
        try:
            db = TelemetryDB()
            result = await push.reconcile_once(db, config_store)
            if result["notified"]:
                logger.info("Push reconciler notified %s", ", ".join(result["notified"]))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Push reconciler tick failed: %s", exc)
        finally:
            if db is not None:
                db.close()


@app.on_event("startup")
def startup_event():
    """Handle application startup events."""
    # The database comes first: everything below it — the strategy override, the
    # printer target, the secrets forwarded to subprocesses — is read from the config
    # store, whose table this is what creates. A missing URL is a configuration error
    # and stops the server here (`TelemetryDB()` raises, naming the variable); an
    # *unreachable* database is not — the server comes up degraded, `/health` says
    # why, and the periodic check below creates the schema once the connection returns.
    db = TelemetryDB()
    try:
        config_store.init_schema()
        db.init_schema()
        # A key this store no longer accepts leaves a row nothing can read, edit or
        # delete. `PYTHONPATH` is the one that has been retired, and leaving its value
        # encrypted in the table is not the same as removing it.
        for retired in config_store.purge_retired_keys():
            logger.info("Removed retired config key %s from the store", retired)
    except Exception as exc:  # noqa: BLE001 — reported by the health check below
        logger.error("Could not initialise the database schema (%s): %s", db.describe, exc)
    check_database_health(db)
    db.close()

    # The *path*, never the value. A token in the log is a token in every log
    # shipper, screen share and pasted traceback — and this line exists precisely for
    # the person who does not yet know where to look, so it has to be the one thing
    # that is safe to print. `make api-token` prints the value, deliberately by hand.
    if os.environ.get("DS_API_TOKEN", "").strip():
        logger.info("API authentication: the token comes from $DS_API_TOKEN")
    else:
        logger.info(
            "API authentication: the token is in %s (`make api-token` prints it)",
            default_api_token_path(),
        )

    strategy = get_resolved_strategy()
    logger.info(f"Resolved execution strategy: {strategy}")

    docker_available = False
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, timeout=3.0)
        docker_available = res.returncode == 0
    except Exception:
        pass

    if not docker_available and strategy in ("nvidia_docker", "cpu_docker"):
        logger.warning(f"Strategy {strategy} requires Docker, but Docker is not available!")

    repo_root = Path(__file__).parent.parent
    (repo_root / "data" / "inputs").mkdir(parents=True, exist_ok=True)
    (repo_root / "data" / "outputs").mkdir(parents=True, exist_ok=True)
    (repo_root / "data" / "logs").mkdir(parents=True, exist_ok=True)

    # The store is deliberately *not* copied into `os.environ` here. It used to be,
    # and `POST /config` wrote each value there as well, which made every stored key
    # part of both subprocess launches — `PYTHONPATH` among them. Everything that
    # needs a stored value reads it from the store at the moment it is used:
    # `subprocess_env()` for a launch, `config_store.get()` for this process.

    # Re-checked on a cadence, not just at startup. $DS_DB_HEALTH_INTERVAL_S=0
    # disables the loop.
    global _db_health_task
    interval = health_interval_s()
    if interval:
        _db_health_task = asyncio.get_event_loop().create_task(
            _periodic_db_health(interval)
        )
        logger.info("Database health check every %.0f s", interval)

    # The VAPID keypair is *not* generated here: it is generated the first time a
    # browser asks for the public half, so a deployment that never uses notifications
    # never mints a key. Until then there can be no subscriptions, so the loop below
    # has nothing to send and says so in one query.
    global _push_task
    push_interval = push.push_interval_s()
    if push_interval:
        _push_task = asyncio.get_event_loop().create_task(_periodic_push(push_interval))
        logger.info("Push reconciler every %.0f s", push_interval)

@app.on_event("shutdown")
async def shutdown_event():
    """Handle application shutdown events.

    Gracefully stops all active telemetry collectors.
    """
    if _db_health_task:
        _db_health_task.cancel()
    if _push_task:
        _push_task.cancel()
    for detector_task in active_detectors.values():
        detector_task.cancel()
    active_detectors.clear()
    for collector in active_collectors.values():
        await collector.stop()
    active_collectors.clear()
    await simulator_manager.stop_moonraker()
    await simulator_manager.stop_octoprint()

# Live log fan-out. Every stdout line reaches the browser, but coalesced: a docker
# build emits thousands of lines in a burst, and one WebSocket frame per line floods
# the socket and the React tree for no visible gain. Batching on a short interval
# still reads as live — roughly eight updates a second — at a fraction of the frames.
LOG_FLUSH_INTERVAL_S = 0.12
LOG_BATCH_MAX = 40

# ── The phase-banner protocol ────────────────────────────────────────────────
#
# The pipeline is a subprocess, so its stdout is the only channel it has: the entire
# UI — the progress rail, the stage, the phase WebSocket messages — is driven by
# `pipeline._phase_start/_phase_pass/_phase_fail` printing these lines and this regex
# recognising them. The two halves live in different processes and nothing links them,
# so a reworded banner breaks every phase update in the product while the pipeline
# still exits 0 and the log still looks right.
#
# Hoisted to module scope (from inside `_stream_output`, where they were locals) so
# `tests/test_phase_banners.py` can bind to the real parser rather than retyping it —
# a test carrying its own copy of the regex would agree with itself forever.
PHASE_BANNER_RE = re.compile(r"\[DS\] ═══ PHASE (\d+) (START|PASS|FAIL)(.*)═══")

#: Phase number → display name. Must match `pipeline._PHASE_NAMES`; the pipeline names
#: the phase in its `.status` file and this names it in the WebSocket message, and the
#: UI shows whichever arrives first.
PHASE_NAMES = {1: "Visualizer", 2: "Sculptor", 3: "Engineer", 4: "Slicer", 5: "Operator"}

#: Banner verb → the status the UI is told. `.status` records use the same three words,
#: which is what lets `_read_current_phase` and a phase_update describe one thing.
PHASE_BANNER_STATUS = {"START": "running", "PASS": "complete", "FAIL": "error"}


async def _stream_output(process, log_file_obj, job_id: str, on_phase=None):
    phase_re = PHASE_BANNER_RE
    phase_names = PHASE_NAMES

    pending: list[str] = []
    # Monotonic across the whole job, so a client can tell a quiet pipeline from a
    # dropped batch — the two look identical without it.
    seq = 0

    async def flush():
        nonlocal pending, seq
        if not pending:
            return
        batch, pending = pending, []
        seq += 1
        await broadcaster.broadcast(job_id, {
            "type": "log",
            "data": {
                "seq": seq,
                "lines": batch,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        })

    async def flusher():
        # A data-driven flush alone would hold the last few lines forever whenever the
        # pipeline goes quiet — which is exactly when someone is staring at the log
        # wondering whether anything is still happening.
        while True:
            await asyncio.sleep(LOG_FLUSH_INTERVAL_S)
            await flush()

    flusher_task = asyncio.create_task(flusher())
    try:
        async for line_bytes in process.stdout:
            line = line_bytes.decode('utf-8', errors='replace')
            log_file_obj.write(line)
            log_file_obj.flush()

            stripped = line.rstrip("\n")
            if stripped:
                pending.append(stripped)
                if len(pending) >= LOG_BATCH_MAX:
                    await flush()

            m = phase_re.search(line)
            if m:
                phase_num = int(m.group(1))
                action = m.group(2)
                name = phase_names.get(phase_num, "Unknown")

                status = PHASE_BANNER_STATUS[action]
                error = "Phase failed" if status == "error" else None

                # A phase banner is the one line that must not wait for the batch
                # timer: the whole UI keys off it.
                await flush()
                # Heavy rule for a START, so a phase boundary is findable by eye in a
                # stream that is otherwise thousands of tool lines.
                if action == "START":
                    activity.boundary(f"phase {phase_num:02d} · {name}")
                else:
                    activity.event(
                        f"phase {phase_num:02d} {name} · {'complete' if action == 'PASS' else 'FAILED'}",
                        level="INFO" if action == "PASS" else "ERROR",
                        source="pipeline",
                    )
                await broadcaster.broadcast(job_id, {
                    "type": "phase_update",
                    "data": {
                        "phase": phase_num,
                        "name": name,
                        "status": status,
                        "error": error,
                        "ts": datetime.now(timezone.utc).isoformat()
                    }
                })
                if on_phase is not None:
                    try:
                        await on_phase(phase_num, status)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Phase hook failed for job %s: %s", job_id, exc)
    finally:
        flusher_task.cancel()
        # The tail matters most — it is whatever the pipeline said before it stopped.
        await flush()

def _attach_job_telemetry(job_id: str, firmware: str, base_url: str, api_key) -> None:
    """Start the server-side collector and detector for a job that is now printing.

    Called when Phase 5 actually begins, not at job creation. Started at creation,
    the collector wrote roughly one idle-printer sample per second under this job's
    id for the entire pipeline duration — hours of temperature readings from a
    machine printing nothing, indistinguishable from print telemetry.

    Args:
        job_id: The job now being printed.
        firmware: The printer firmware, deciding which collector fits.
        base_url: The printer's base URL, reachable from this host process.
        api_key: The printer's API key, when it has one.
    """
    if job_id in active_collectors:
        return

    # The collector opens a socket and the detector's operator opens HTTP requests,
    # both from this process. When the server is the containerised one, its own
    # localhost is not the host's.
    base_url = container_reachable_url(base_url) or base_url

    collector = None
    if firmware in ("klipper", "moonraker"):
        ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
        if not ws_url.endswith("/websocket"):
            ws_url = ws_url.rstrip("/") + "/websocket"
        collector = MoonrakerCollector(ws_url, job_id, TelemetryDB())
    elif firmware == "octoprint":
        parsed = urlparse(base_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 80
        collector = OctoPrintCollector(
            host, port, api_key or "", job_id, TelemetryDB(),
            # The pipeline always uploads under this name; events for any other
            # file are another print's and must not settle this job.
            gcode_filename="engineered_mesh.gcode",
        )
    elif firmware == "bambu":
        logger.warning("Telemetry not yet available for Bambu")

    if collector:
        active_collectors[job_id] = collector
        asyncio.create_task(collector.start())

        # Consume the collector's samples — without this, automated failure
        # detection never runs. Whichever collector process wins the telemetry
        # claim is the one whose queue receives samples.
        try:
            operator = PrinterFactory.create(firmware, base_url, api_key)
        except Exception as e:
            operator = None
            logger.warning(f"No operator for detector ({firmware}): {e}")
        active_detectors[job_id] = attach_detector(collector, TelemetryDB(), operator)

        # These two are the background machinery that was completely silent: a job
        # whose collector never claimed the row, or whose detector had no operator
        # and therefore could not evaluate half its rules, looked identical to a
        # healthy one from the log.
        activity.action(
            "telemetry attached",
            [
                ("job", job_id[:8]),
                ("collector", type(collector).__name__),
                ("firmware", firmware),
                ("detector", "armed" if operator else "no operator — progress rules off"),
            ],
            outcome="sampling; the single-writer claim is taken on the first sample",
            status="ok" if operator else "warn",
            level="INFO" if operator else "WARNING",
            source="telemetry",
        )
    else:
        activity.event(
            f"no telemetry collector for firmware {firmware!r} · job {job_id[:8]}",
            level="WARNING",
            source="telemetry",
        )


def _phase_skips(request: JobRequest) -> tuple[bool, bool]:
    """Whether Phases 1 and 2 are skipped for this request: `(skip_viz, skip_sculpt)`.

    A spec request skips both regardless of the request's own flags or the config
    store: the compiler *is* its Phase 2, there is no image for a Phase 1 to make, and
    — because the blueprint gate arms exactly when Phase 1 runs — a spec job is never
    parked for an approval of an image that does not exist.
    """
    if request.spec_path or request.spec is not None:
        return True, True
    skip_viz = request.skip_visualizer or config_store.get("SKIP_VISUALIZER") == "true"
    skip_sculpt = request.skip_sculptor or config_store.get("SKIP_SCULPTOR") == "true"
    return bool(skip_viz), bool(skip_sculpt)


def _prompt_jobs_are_benched(request: JobRequest) -> bool:
    """Whether this request is a generative job the product is not currently offering.

    The shipping path is the parametric organizer: a spec job compiles its geometry
    deterministically (`pythonsrc/organizer/`), reaches no model weights, and cannot
    construct a sculptor at all — `_apply_spec_mode` sets `skip_sculptor` for it. The
    prompt path is the other one: Phase 1 renders a blueprint with FLUX and Phase 2
    reconstructs a mesh with TRELLIS.2.

    **Why this is a refusal rather than a comment in a design document.** The prompt
    path was benched as a decision and left wired as code. `startJob` takes its spec
    as an optional argument and will happily post a job without one, `prompt` is not
    a required field, and `SKIP_SCULPTOR` defaults to false — so the composer's own
    text field still reached Phase 2. From there
    `sculptors.resolve_backend_name`'s `auto` resolves remote → CUDA → **pixazo**, and
    on a machine with no NVIDIA GPU and `PIXAZO_API_KEY` in the environment — which is
    every Apple Silicon development laptop — that is the backend that bills, at
    €0,32 a generation, under terms whose output-ownership clause is unresolved
    (`docs/audits/2026-09-19-external-licence.md` § 0, E5). A subsystem nobody is
    maintaining should not be able to spend money by default.

    **Only a job that would actually build a sculptor is refused.** A request that
    skips Phase 2 — the dev and demo configuration `SKIP_SCULPTOR` exists for, which
    substitutes a reference mesh — still runs, because nothing about it reaches a
    model or a paid endpoint. The bench is on the generative path, not on prompts.

    Un-benching is a product decision, so it is a config-store key rather than a
    constant: set `ALLOW_PROMPT_JOBS=true` and the path is back with no deploy.

    Args:
        request: The incoming job request, already validated.

    Returns:
        True when the request should be refused before a job row exists.
    """
    if request.spec is not None or request.spec_path:
        return False
    if config_store.get("ALLOW_PROMPT_JOBS") == "true":
        return False
    _, skip_sculpt = _phase_skips(request)
    return not skip_sculpt


def _pipeline_args(
    request: JobRequest,
    *,
    skip_viz: bool,
    skip_sculpt: bool,
    profile: Optional[str],
) -> List[str]:
    """Build the pipeline subprocess arguments for one job request.

    Lifted out of `_run_pipeline` to be testable at all: every job-submission test
    patches `_run_pipeline` wholesale — it shells out to docker and bills the hosted
    sculptor — so the argv it assembles was unreachable from the suite. A flag
    declared on `JobRequest` and never forwarded is silently inert, which is what
    happened to `--target-mm` and is still true of `blueprint_path`.

    Args:
        request: The submitted job request.
        skip_viz: Whether Phase 1 is being skipped (from the request or config).
        skip_sculpt: Whether Phase 2 is being skipped.
        profile: The resolved printer profile path, or None.

    Returns:
        The argument list to append after the pipeline's positional prompt.
    """
    args: List[str] = []

    if request.spec_path:
        # The parametric path. `--spec` implies the skip flags and `--no-scale` in the
        # pipeline itself, and it must *not* be handed `--blueprint`: a spec run has no
        # image, and the shared path holds whichever job's render was written last —
        # snapshotting it would record that job's hash as this one's Phase 1 provenance.
        args.extend(["--spec", request.spec_path])
    elif skip_viz:
        # `blueprint_path` was declared on `JobRequest` and forwarded nowhere, which is
        # what let the approval gate approve one image and reconstruct another: the
        # continuation was launched against the flat input path, which belongs to no
        # particular job. A resumed run names its own snapshot. The flat path is still
        # the right default here, because this branch runs only when Phase 1 is skipped
        # — the one configuration that deliberately reuses whatever sits there.
        args.extend([
            "--skip-visualizer",
            "--blueprint",
            request.blueprint_path or "/app/data/inputs/blueprint.png",
        ])
    if skip_sculpt and not request.spec_path:
        args.append("--skip-sculptor")

    if profile:
        args.extend(["--profile", profile])

    args.append("--slice")

    # Forwarded so the pipeline can record them: the seed is what makes a blueprint
    # reproducible, and the material selects the density behind the mass estimate.
    if request.seed is not None:
        args.extend(["--seed", str(request.seed)])
    if request.material_type:
        args.extend(["--material-type", request.material_type])
    # Reaches Phase 1, where it changes the blueprint. Sanitised in
    # `blueprint_spec.normalise_colour`, not here — one implementation, and the CLI
    # path has to be covered by it too.
    if request.material_colour:
        args.extend(["--colour", request.material_colour])
    # Reaches Phase 1, where it changes the blueprint. Sanitised in
    # `blueprint_spec.normalise_colour`, not here — one implementation, and the CLI
    # path has to be covered by it too.
    # Phase 2's own seed and resolution. `--mesh-seed` is deliberately not `--seed`:
    # one reproduces the blueprint, the other the reconstruction, and a single value
    # for both would make it impossible to re-sculpt one image two ways.
    if request.pipeline_type:
        args.extend(["--pipeline-type", request.pipeline_type])
    if request.mesh_seed is not None:
        args.extend(["--mesh-seed", str(request.mesh_seed)])
    # Omitted when unset, so the pipeline's own default remains the only default.
    if request.target_mm is not None:
        args.extend(["--target-mm", str(request.target_mm)])
    if request.scale_axis:
        args.extend(["--scale-axis", request.scale_axis])

    if request.print:
        args.append("--print")
    if request.start_print:
        args.append("--start-print")

    return args


def _strip_stop_after(args: List[str]) -> List[str]:
    """Drop `--stop-after-phase N` from an argument list.

    The mps_native strategy parks *itself*, after its own native Phase 1, and then
    hands Phases 2-5 to a container. A stop flag surviving into that invocation would
    stop the continuation after Phase 1 as well — which, since Phase 1 is skipped
    there, means stopping before anything ran.

    Args:
        args: A pipeline argument list.

    Returns:
        The list without the flag or its value.
    """
    kept: List[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg == "--stop-after-phase":
            skip_next = True
            continue
        kept.append(arg)
    return kept


def _strip_phase1_args(args: List[str]) -> List[str]:
    """Drop the Phase 1 arguments the mps_native strategy supplies for itself.

    That strategy has already run the visualizer as a native process, so it appends
    its own `--skip-visualizer --blueprint <path>` and must remove any copy coming
    from `_pipeline_args`. The filter is value-blind by design — it drops the token
    after `--blueprint` whatever it looks like — which also means every other
    flag/value pair has to survive it intact. A size that lost its number here would
    be consumed by the pipeline from the *next* argument.

    Args:
        args: The full pipeline argument list.

    Returns:
        The list with `--skip-visualizer` and `--blueprint <path>` removed.
    """
    kept: List[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg == "--skip-visualizer":
            continue
        if arg == "--blueprint":
            skip_next = True
            continue
        kept.append(arg)
    return kept


async def _run_pipeline(job_id: str, request: JobRequest):
    repo_root = Path(__file__).parent.parent
    log_dir = repo_root / "data" / "logs"
    log_file = log_dir / f"{job_id}.log"

    strategy = get_resolved_strategy()

    skip_viz, skip_sculpt = _phase_skips(request)
    # Phase 1 writes one blueprint per job, not one per machine.
    # `data/inputs/blueprint.png` is a single filename shared by every run, and Phase 1
    # overwrites it in place — whether it runs natively on this host or inside the
    # pipeline container. Two jobs started within a few minutes of each other race for
    # it, and the loser sculpts, slices and prints the winner's image while recording
    # its own prompt and seed against it. Nothing downstream can tell: the file exists,
    # it is a real render, and its hash is whatever landed last.
    #
    # `skip_viz` is the deliberate exception. That configuration exists to *reuse* an
    # image already sitting at the shared path, so nothing generates one there and
    # nothing races for it; pointing it at an empty per-job directory would make the
    # pipeline stand a fixture in instead of using the blueprint someone put there.
    blueprint_rel = (
        Path("data") / "inputs" / "blueprint.png"
        if skip_viz
        else Path("data") / "inputs" / job_id / "blueprint.png"
    )
    blueprint_container_path = "/app/" + blueprint_rel.as_posix()

    # A path, not the name this boundary speaks in — see `profile_pipeline_argument`.
    profile = profile_pipeline_argument(
        request.profile or config_store.get("DEFAULT_PROFILE")
    )

    pipeline_args = _pipeline_args(
        request, skip_viz=skip_viz, skip_sculpt=skip_sculpt, profile=profile,
    )

    # Whether this invocation stops after Phase 1 and waits for a person.
    #
    # Gated exactly when Phase 1 actually runs here. That is also what makes the
    # continuation terminate: `_continue_pipeline` re-enters with
    # `skip_visualizer=True`, so `skip_viz` is set, so it is not gated, so it runs
    # through. Without that coupling the gate would re-arm on every approval.
    #
    # `--print` opts out. The CLI and any automation pass it, and there is nobody to
    # ask there — the same reasoning that makes Phase 5 unattended on that path.
    gated = not skip_viz and not request.print
    if gated and strategy != "mps_native":
        # The docker strategies run all five phases in one `docker compose run`, so the
        # seam has to be asked for. mps_native already has one: it runs Phase 1 as its
        # own process.
        pipeline_args = ["--stop-after-phase", "1"] + pipeline_args

    try:
        # Mark job as started
        db_start = TelemetryDB()
        db_start.update_job_start_time(job_id, datetime.now(timezone.utc))
        db_start.close()

        # This server's environment plus the allowlisted config-store keys, and
        # nothing else from the store — see `subprocess_env`.
        pipeline_env = subprocess_env()
        pipeline_env["DS_LOGS_DIR"] = str(log_dir)
        # The Hub reads its own variable name for the same secret. It is an alias for
        # HF_TOKEN rather than a key of its own, so it is derived here instead of
        # being a second thing anyone can store.
        if pipeline_env.get("HF_TOKEN"):
            pipeline_env["HUGGINGFACE_HUB_TOKEN"] = pipeline_env["HF_TOKEN"]


        # Export printer config to pipeline — resolved in one place so the pipeline
        # and the telemetry collector can never target different printers.
        profile_path = str(profile_path_or_default(request.profile))
        firmware, url, key = resolve_printer_target(profile_path)
        pipeline_env["DS_FIRMWARE"] = firmware

        # Kept before the Docker rewrite below, which is the *pipeline container's*
        # translation. The server-side collector makes its own — it may or may not be
        # containerised itself — inside `_attach_job_telemetry`.
        collector_url = url or "http://localhost:5001"
        collector_key = key

        async def on_phase(phase_num: int, phase_status: str) -> None:
            # Attach telemetry when the print actually starts. Attached at job
            # creation, the collector spent the whole pipeline writing idle-printer
            # samples under this job's id.
            if phase_num == 5 and phase_status == "running" and request.print:
                _attach_job_telemetry(job_id, firmware, collector_url, collector_key)

        # Stamp the code version into the container, which carries no .git.
        git_sha = resolve_git_sha()
        if git_sha:
            pipeline_env["DS_GIT_SHA"] = git_sha

        if url:
            # If pipeline is running in docker and the URL is localhost, rewrite it
            if "localhost" in url or "127.0.0.1" in url:
                url = url.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")
            pipeline_env["DS_PRINTER_URL"] = url

        if key:
            pipeline_env["DS_PRINTER_KEY"] = key

        # `pipeline_env` is the environment of the process this server launches
        # *itself*: on the mps_native path that is the native Phase 1 subprocess,
        # which reaches this server on the host's loopback. The pipeline is a
        # container on every strategy, so its copy of this variable is translated
        # where it crosses that boundary — see `_container_api_url`, which is also
        # why this value is no longer chosen by strategy.
        pipeline_env["DS_API_URL"] = NATIVE_API_URL

        # Appended, not truncated. The blueprint gate resumes a job as a *second*
        # invocation against the same log file, and "w" threw away the Phase 1 record —
        # the seed line, any screen verdict — the moment someone approved. The file is
        # job-scoped, so appending cannot mix two jobs together.
        log_mode = "a" if request.blueprint_path else "w"
        with open(log_file, log_mode) as f:
            if log_mode == "a":
                f.write("\n[DS] ─── resumed after blueprint approval ───\n")
                f.flush()
            docker_env_args = ["-e", "DS_LOGS_DIR=/app/data/logs"]
            if pipeline_env.get("DS_DATABASE_URL"):
                # The pipeline writes its own telemetry, so it needs the database.
                # `compose run` passes nothing from the host environment unless named
                # here — and a URL naming this host's loopback (a local PostgreSQL in
                # development) has to be translated for the container.
                docker_env_args.extend([
                    "-e", f"DS_DATABASE_URL={_container_database_url(pipeline_env['DS_DATABASE_URL'])}",
                ])
            if "DS_PRINTER_URL" in pipeline_env:
                docker_env_args.extend(["-e", f"DS_PRINTER_URL={pipeline_env['DS_PRINTER_URL']}"])
            if "DS_PRINTER_KEY" in pipeline_env:
                docker_env_args.extend(["-e", f"DS_PRINTER_KEY={pipeline_env['DS_PRINTER_KEY']}"])
            if "DS_FIRMWARE" in pipeline_env:
                docker_env_args.extend(["-e", f"DS_FIRMWARE={pipeline_env['DS_FIRMWARE']}"])
            if "DS_API_URL" in pipeline_env:
                # The collectors relay their samples here for WebSocket fan-out, and
                # inside the container the host's loopback is the container itself.
                docker_env_args.extend([
                    "-e", f"DS_API_URL={_container_api_url(pipeline_env['DS_API_URL'])}",
                ])
            if "DS_API_TOKEN" in pipeline_env:
                # By *name*, not `NAME=value`: `docker compose run -e DS_API_TOKEN`
                # reads the value out of this process's environment — which is
                # `pipeline_env` — instead of writing the shared secret into an argv
                # that every `ps` on the host can read. The container needs it because
                # the route its collectors relay to is authenticated, and a generated
                # token is in no `env_file` for compose to find.
                docker_env_args.extend(["-e", "DS_API_TOKEN"])
            # Forward the paid-backend kill switch across the container boundary.
            # Phase 2's hosted backend bills per call and runs *inside* the container,
            # so a guard that only exists in this process cannot stop it. `compose run`
            # passes nothing from the host environment unless it is named here.
            if "DS_DISABLE_PAID_BACKENDS" in pipeline_env:
                docker_env_args.extend([
                    "-e",
                    f"DS_DISABLE_PAID_BACKENDS={pipeline_env['DS_DISABLE_PAID_BACKENDS']}",
                ])
            if "DS_GIT_SHA" in pipeline_env:
                docker_env_args.extend(["-e", f"DS_GIT_SHA={pipeline_env['DS_GIT_SHA']}"])

            if strategy == "mps_native":
                if not skip_viz:
                    await broadcaster.broadcast(job_id, {"type": "phase_update", "data": {"phase": 1, "name": "Visualizer", "status": "running", "error": None, "ts": datetime.now(timezone.utc).isoformat()}})

                    phase1_cmd = ["bash", "infra/scripts/run_phase1_native.sh", request.prompt]
                    # Forwarded so a user-chosen seed reaches the native process —
                    # it used to be silently dropped on this path, recorded nowhere
                    # and used never.
                    if request.seed is not None:
                        phase1_cmd.extend(["--seed", str(request.seed)])
                    # Same reason as the seed: dropped on this path it would be
                    # recorded nowhere and used never.
                    if request.material_colour:
                        phase1_cmd.extend(["--colour", request.material_colour])
                    process1 = await asyncio.create_subprocess_exec(
                        *phase1_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        cwd=repo_root,
                        # The native script defaults to the shared path. This is what
                        # sends this job's render — and its provenance sidecar — to a
                        # directory no other job writes.
                        env={**pipeline_env, "DS_BLUEPRINT_OUTPUT": blueprint_rel.as_posix()},
                    )
                    active_pipelines[job_id] = process1
                    await _stream_output(process1, f, job_id)
                    await process1.wait()

                    if process1.returncode != 0:
                        await broadcaster.broadcast(job_id, {"type": "phase_update", "data": {"phase": 1, "name": "Visualizer", "status": "error", "error": f"Failed with code {process1.returncode}", "ts": datetime.now(timezone.utc).isoformat()}})
                        raise Exception(f"Phase 1 failed with code {process1.returncode}")

                    if not (repo_root / blueprint_rel).exists():
                        raise Exception(
                            f"Phase 1 completed but {blueprint_rel.as_posix()} not found"
                        )

                    await broadcaster.broadcast(job_id, {"type": "phase_update", "data": {"phase": 1, "name": "Visualizer", "status": "complete", "error": None, "ts": datetime.now(timezone.utc).isoformat()}})

                    # Park here, before the container that would run Phase 2 is
                    # started. Returning rather than awaiting is what makes the wait
                    # durable: the job's state is a row plus a snapshotted image, so
                    # it survives a server restart and has no time limit.
                    if gated:
                        if await _park_at_blueprint_gate(job_id):
                            return
                        raise Exception(
                            "Phase 1 completed but the job could not be parked for "
                            "approval, so Phase 2 was not started."
                        )

                clean_args = _strip_phase1_args(pipeline_args)

                # A spec run has no image: `--spec` implies the skip, and handing it the
                # blueprint path would snapshot another job's render as its provenance.
                phase1_flags = [] if request.spec_path else [
                    "--skip-visualizer",
                    # The approved snapshot when this is a gate continuation, else this
                    # job's own per-job render — never the shared path, which belongs to
                    # whichever run wrote it last.
                    "--blueprint", request.blueprint_path or blueprint_container_path,
                ]
                cmd = [
                    "docker", "compose", "-f", "infra/docker-compose.yml",
                    "run", "--rm"
                ] + docker_env_args + [
                    "pipeline-runner",
                    "python", "pythonsrc/pipeline.py", request.prompt,
                    *phase1_flags,
                    "--job-id", job_id
                ] + _strip_stop_after(clean_args)
            elif strategy == "nvidia_docker":
                cmd = [
                    "docker", "compose",
                    "-f", "infra/docker-compose.yml",
                    "-f", "infra/docker-compose.gpu.yml",
                    "run", "--rm"
                ] + docker_env_args + [
                    "pipeline-runner",
                    "python", "pythonsrc/pipeline.py", request.prompt,
                    "--job-id", job_id
                ] + pipeline_args
            else:
                cmd = [
                    "docker", "compose",
                    "-f", "infra/docker-compose.yml",
                    "run", "--rm"
                ] + docker_env_args + [
                    "pipeline-runner",
                    "python", "pythonsrc/pipeline.py", request.prompt,
                    "--job-id", job_id
                ] + pipeline_args

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=repo_root,
                env=pipeline_env
            )
            active_pipelines[job_id] = process
            await _stream_output(process, f, job_id, on_phase=on_phase)
            await process.wait()
            returncode = process.returncode

            # A gated run that exited cleanly stopped *on purpose*, after Phase 1. It
            # must not be recorded as a finished job: writing "success" here would make
            # `dispatch_state` report a job with no mesh and no G-code as ready to
            # print. The outcome column is deliberately left as it is — see
            # `_park_at_blueprint_gate`.
            if gated and returncode == 0 and job_id not in cancelled_jobs:
                if await _park_at_blueprint_gate(job_id):
                    return
                # The run stopped after Phase 1 as instructed but could not be parked —
                # no blueprint to show, or the decision could not be recorded. Falling
                # through would let Phase 2 spend money on an image nobody approved,
                # which is the one outcome this gate exists to prevent, so it fails
                # instead. A failed gate is a failed job, loudly.
                logger.error(
                    "Job %s stopped for approval but could not be parked — failing it "
                    "rather than continuing past the gate.", job_id,
                )
                _append_phase_status(job_id, 1, "error", "could not park for approval")
                returncode = 1

            db = TelemetryDB()
            if job_id in cancelled_jobs:
                # A stopped pipeline exits non-zero, exactly like a crash. Only the
                # cancel endpoint knows the difference, and recording "failure" here
                # would both mislead the user and put a crash in the dataset that
                # never happened.
                outcome = "cancelled"
            elif returncode != 0:
                outcome = "failure"
            elif request.print and request.start_print:
                # The pipeline exits as soon as the printer accepts the job, so a zero
                # exit code means "dispatched", not "printed". Recording that as a
                # success is how the outcome column ends up describing the software
                # rather than the part. Only a human can close this out.
                outcome = "awaiting_verdict"
            else:
                outcome = "success"
            db.update_job_outcome_verdict(
                job_id,
                outcome,
                source="machine",
                completed_at=datetime.now(timezone.utc),
            )
            db.close()
            activity.action(
                "pipeline finished",
                [("job", job_id[:8]), ("exit code", returncode), ("outcome", outcome)],
                outcome={
                    "cancelled": "stopped on request — not a failure",
                    "failure": "the pipeline exited non-zero",
                    "awaiting_verdict": "dispatched to the printer; only a person can close this out",
                }.get(outcome, "finished"),
                status="ok" if outcome in ("success", "awaiting_verdict") else "fail",
                level="INFO" if outcome in ("success", "awaiting_verdict") else "WARNING",
                source="pipeline",
            )
            await broadcaster.broadcast(job_id, {"type": "job_complete", "data": {"outcome": outcome}})
    except Exception as e:
        # Same reasoning as above: a phase raising because its process was killed is
        # a cancellation, not a failure.
        outcome = "cancelled" if job_id in cancelled_jobs else "failure"
        db = TelemetryDB()
        db.update_job_outcome_verdict(
            job_id, outcome, source="machine", completed_at=datetime.now(timezone.utc)
        )
        db.close()
        with open(log_file, "a") as f:
            f.write(f"\nPipeline failed to start: {e}\n")
        activity.action(
            "pipeline aborted",
            [("job", job_id[:8]), ("error", str(e))],
            outcome="stopped on request" if outcome == "cancelled" else "recorded as a failure",
            status="warn" if outcome == "cancelled" else "fail",
            level="WARNING" if outcome == "cancelled" else "ERROR",
            source="pipeline",
        )
        await broadcaster.broadcast(job_id, {"type": "job_complete", "data": {"outcome": outcome}})
    finally:
        active_pipelines.pop(job_id, None)
        cancelled_jobs.discard(job_id)
        detector_task = active_detectors.pop(job_id, None)
        if detector_task:
            detector_task.cancel()
        collector = active_collectors.pop(job_id, None)
        if collector:
            await collector.stop()

@app.post("/jobs", status_code=status.HTTP_202_ACCEPTED, response_model=JobResponse)
async def create_job(request: JobRequest):
    """Create a new print job.

    Validates the job request, generates a unique job ID, inserts a new 'queued'
    PrintJob record into the TelemetryDB, and launches the pipeline subprocess
    in the background.

    Args:
        request: The job configuration parameters.

    Returns:
        A JobResponse containing the job ID and 'queued' status immediately.
    """
    status_res = await printer_status()
    if not status_res.get("configured"):
        raise HTTPException(
            status_code=400,
            detail="Cannot start job: no printer or simulator is configured. "
                   "Choose one in Settings.",
        )
    # `configured` only means a target is set. Starting a five-phase run against a
    # printer that will refuse the file at the end wastes the whole pipeline — and on
    # the hosted sculptor backend it wastes real money.
    if not status_res.get("running"):
        raise HTTPException(
            status_code=400,
            detail="Cannot start job: the configured printer did not answer. "
                   + (status_res.get("detail") or "Test the connection in Settings."),
        )

    # Screened here, and here specifically: after the printer checks (a job that
    # cannot print should fail for that reason first) but before `job_id` is minted and
    # before the artifact-cleanup loop below, which unconditionally deletes the flat
    # mesh and G-code. A refusal after that point destroys the previous job's output in
    # order to reject a job that never existed.
    #
    # Every field that reaches the model is passed, not just the prompt:
    # `material_colour` is interpolated into the string sent to FLUX, so a screen
    # reading `prompt` alone leaves the colour box unwatched. `embossing_text` is the
    # third channel and the one that ends up *on* the part; each is screened on its
    # own tokens, so the spec's own purpose text ("deck box for Pokémon cards") is
    # not read as the emboss field's context.
    # Refused here for the same reason the IP screen is: before `job_id` is minted and
    # before the artifact-cleanup loop below, which unconditionally deletes the flat mesh
    # and G-code. A refusal after that point destroys the previous job's output in order
    # to reject a job that never existed.
    #
    # `profile` is free text, and the two joins further down read the named file:
    # `resolve_printer_target` pulls `firmware`/`base_url`/`api_key` out of it, and
    # `_profile_snapshot` `json.load`s it and stores the whole parsed dict as
    # `process_params`, which `GET /jobs/{id}/provenance` serves back verbatim. An
    # absolute path needs no traversal to escape, so this was an unauthenticated read of
    # any JSON file the server can open, written into the dataset and handed back.
    #
    # Only an *escaping* path is refused. A profile that merely does not exist stays a
    # 202 and disables printing, which is what `"default"` and `"test"` do today.
    try:
        resolve_profile_path(request.profile)
    except ProfileOutsideProfilesDir as exc:
        activity.action(
            "job refused",
            [("reason", "profile outside pythonsrc/profiles"),
             ("profile", request.profile)],
            outcome="refused before the job row was created",
            status="warn",
        )
        raise HTTPException(
            status_code=422,
            detail=(
                "A printer profile must be a file in pythonsrc/profiles; "
                f"{request.profile!r} resolves outside it."
            ),
        ) from exc

    # Refused before the IP screen, deliberately: the screen's job is to decide
    # whether a *subject* may be built, and telling someone their prompt names a
    # franchise is a worse answer than telling them the generative path is closed.
    if _prompt_jobs_are_benched(request):
        activity.action(
            "job refused",
            [("reason", "prompt jobs are benched"), ("prompt", request.prompt)],
            outcome="refused before the job row was created",
            status="warn",
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "Free-text jobs are not available. This build compiles an organizer "
                "spec into geometry; describe the part with the configurator instead. "
                "(An operator can re-enable the generative path by setting "
                "ALLOW_PROMPT_JOBS=true through POST /config; it is deliberately "
                "not one of the toggles the settings screen lists.)"
            ),
        )

    screen = screen_prompt(
        request.prompt, request.material_colour, embossing=request.embossing_text,
    )
    if screen.action == "block":
        activity.action(
            "job refused",
            [
                ("reason", "ip screen"),
                ("term", screen.term),
                # Which field carried the name. A refusal that does not say leaves
                # an operator reading the prompt for a term that was in the emboss
                # box, and the two have different answers for the person.
                ("channel", screen.channel),
                ("score", screen.score),
                ("prompt", request.prompt),
            ],
            outcome="refused before the job row was created",
            status="warn",
        )
        # The 4xx is already pushed into the activity feed by the request middleware,
        # so this block records the *decision* rather than the response.
        raise HTTPException(status_code=400, detail=screen.detail)

    job_id = str(uuid.uuid4())

    repo_root = Path(__file__).parent.parent

    # Clean up artifacts from previous jobs to prevent the UI from loading old images.
    #
    # `data/inputs/blueprint.png` is deliberately *not* in this list. Deleting it was
    # the other half of the shared-path race: creating one job removed the blueprint a
    # concurrent job was still reading, and in the skip-Phase-1 configuration — whose
    # whole purpose is to reuse the image sitting at that path — it deleted the input
    # the run was about to use, so the pipeline stood a fixture in instead. Jobs now
    # render into `data/inputs/{job_id}/`, which nothing else writes, so there is
    # nothing stale here to clear.
    #
    # The list is `stale_flat_artifacts` rather than spelled out here, because it is
    # half of `/download`'s safety and the two halves drifted apart the moment a third
    # format was added — see that function.
    for artifact in stale_flat_artifacts(repo_root):
        if artifact.exists():
            try:
                artifact.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete old artifact {artifact}: {e}")

    profile_path = str(profile_path_or_default(request.profile))
    firmware = "octoprint"
    if not os.path.exists(profile_path):
        logger.error(f"Printer profile not found: {profile_path} — disabling print")
        request.print = False
        request.start_print = False

    firmware, base_url, api_key = resolve_printer_target(profile_path)
    base_url = base_url or "http://localhost:5001"

    process_params, nozzle_diameter_mm = _profile_snapshot(profile_path)

    if request.spec is not None:
        # The spec is the job's input the way a blueprint is: written into the job's own
        # directory, which nothing else writes, in canonical form so the file on disk
        # hashes to the `spec_sha256` Phase 2 records. `spec_path` is the container's
        # view of it and rides in `request_params` with everything else.
        spec_rel = Path("data") / "inputs" / job_id / "spec.json"
        dump_spec(OrganizerSpec.from_dict(request.spec), repo_root / spec_rel)
        request.spec_path = "/app/" + spec_rel.as_posix()

    db = TelemetryDB()
    job = PrintJob(
        job_id=job_id,
        prompt=request.prompt,
        printer_id=request.printer_id,
        printer_firmware=firmware,
        slicer="cura",
        profile_name=request.profile or "default",
        started_at=None,
        completed_at=None,
        outcome="unknown",
        material_type=request.material_type,
        material_brand=request.material_brand,
        material_colour=request.material_colour,
        nozzle_diameter_mm=nozzle_diameter_mm,
        process_params=process_params,
        # "the default applied" is a different fact from "they chose 50 mm", so the
        # source is always written even when the size is not.
        # The request as submitted, so the approval gate's continuation — a different
        # process, after a human decision that has no time limit — reruns the same job
        # rather than a reconstruction of it.
        request_params=request.model_dump(mode="json"),
        requested_size_mm=request.target_mm,
        # "spec" when a spec decided every dimension — no single size, no axis — and
        # the model has already refused a spec arriving with a size beside it.
        size_source=(
            "spec" if request.spec is not None
            else (request.size_source or "user") if request.target_mm is not None
            else "default"
        ),
        requested_scale_axis=request.scale_axis,
        parent_job_id=request.parent_job_id,
        regeneration_reason=request.regeneration_reason,
    )
    db.insert_job(job)

    activity.action(
        "job created",
        [
            ("job", job_id[:8]),
            ("prompt", request.prompt),
            ("profile", request.profile or "default"),
            ("firmware", firmware),
            ("material", request.material_type or "unset"),
            ("seed", request.seed if request.seed is not None else "drawn at run time"),
            ("size", "from spec" if request.spec is not None
                     else f"{request.target_mm} mm" if request.target_mm is not None
                     else "50 mm (default)"),
            ("regen of", request.parent_job_id[:8] if request.parent_job_id else None),
        ],
        outcome="queued; pipeline subprocess starting",
        status="ok",
    )

    # A weak match proceeds and is recorded, so the person approving the blueprint
    # sees it and "how often does this fire" stays a query rather than a log grep.
    if screen.action == "flag":
        try:
            db.record_job_event(job_id, "ip_screen_flagged", {
                "term": screen.term,
                "score": screen.score,
                "detail": screen.detail,
                # How the term was used, so "how often does the functional-article
                # rule fire" is a query rather than a log grep. No schema change:
                # `job_event.detail` is JSONB.
                "usage": screen.usage,
                # And which field it was used in, so the same query can separate the
                # prompt from the colour box from the embossing text — three channels
                # whose flags mean three different things.
                "channel": screen.channel,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record ip_screen_flagged event: %s", exc)

    # A regeneration is an implicit judgement on the parent — the user looked at that
    # result and asked for another. Recorded against the parent, which is the job the
    # signal is actually about.
    if request.parent_job_id:
        try:
            db.record_job_event(request.parent_job_id, "regenerate", {
                "child_job_id": job_id,
                "reason": request.regeneration_reason,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record regenerate event: %s", exc)

    # The telemetry collector is deliberately *not* started here. Job creation is
    # hours before anything prints; `_run_pipeline` attaches it when the Phase 5
    # banner arrives, so a job's samples begin when its print does.

    db.close()

    asyncio.create_task(_run_pipeline(job_id, request))

    return JobResponse(job_id=job_id, status="queued")

@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str):
    """Retrieve the status and details of a specific print job.

    Args:
        job_id: The unique identifier of the print job.

    Returns:
        JobStatusResponse containing metadata, timestamps, status,
        and a tail of the execution log.

    Raises:
        HTTPException: If the job is not found in the database.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    # Both gates are derived here, on the same handle, so the list and the page cannot
    # disagree about who is waiting. Guarded on `job` because the 404 below is
    # deliberately raised *after* `db.close()`, so a missing row reaches this point.
    job_blueprint_gate_state = blueprint_gate_state(job, db) if job else "not_ready"
    blueprint_gate_subject = None
    if job and job_blueprint_gate_state == "awaiting_approval":
        artifact = resolve_job_artifact(job.job_id, "blueprint.png", per_job_only=True)
        if artifact is not None:
            blueprint_gate_subject = {
                "sha256": _file_sha256(artifact),
                "url": f"/jobs/{job.job_id}/blueprint",
            }

    # Phase 5 waits on a person too — see `dispatch_state`.
    job_dispatch_state = dispatch_state(job, db) if job else "not_ready"
    db.close()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    repo_root = Path(__file__).parent.parent
    log_dir = repo_root / "data" / "logs"
    log_file = log_dir / f"{job_id}.log"

    log_tail = []
    if log_file.exists():
        with open(log_file, "r") as f:
            lines = f.readlines()
            log_tail = [line.rstrip('\n') for line in lines[-20:]]

    current_phase = _read_current_phase(job_id)
    # A killed pipeline leaves its `.status` file frozen mid-phase, so a job that has
    # stopped keeps claiming that phase is running — and every client that polls this
    # endpoint re-lights the pulse the cancel just put out. The row's own outcome is
    # the authority on whether anything is still running.
    if (
        current_phase
        and current_phase.get("status") == "running"
        and job.outcome not in (None, "unknown")
    ):
        current_phase = {**current_phase, "status": "error", "error": "Stopped"}

    # Prefer the snapshot frozen when the job was created. Reading the profile file
    # instead means editing a profile retroactively rewrites what old jobs claim to
    # have printed with; the live read stays only as a fallback for rows predating
    # process_params.
    machine_name = None
    layer_height_mm = None
    build_volume_mm = None

    if job.process_params:
        machine_name = job.process_params.get("machine_name")
        layer_height_mm = job.process_params.get("layer_height")
        build_volume_mm = _profile_build_volume(job.process_params)
    else:
        profile_path_str = job.profile_name
        if profile_path_str and profile_path_str != "default":
            try:
                profile_full_path = profile_path_or_default(profile_path_str)
                if profile_full_path.exists():
                    with open(profile_full_path, "r") as pf:
                        profile_data = json.load(pf)
                        machine_name = profile_data.get("machine_name")
                        layer_height_mm = profile_data.get("layer_height")
                        build_volume_mm = _profile_build_volume(profile_data)
            except Exception:
                pass

    current_status = job_status_from_outcome(job.outcome, job.started_at)

    # The target is resolved on read too, so what a person confirms is the printer as it
    # stands rather than as it was when the job was created.
    job_dispatch_target = dispatch_target(job) if job_dispatch_state != "not_ready" else None

    return JobStatusResponse(
        job_id=job.job_id,
        status=current_status,
        prompt=job.prompt,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        outcome=job.outcome,
        log_tail=log_tail,
        current_phase=current_phase,
        printer_id=job.printer_id,
        printer_firmware=job.printer_firmware,
        profile_name=job.profile_name,
        machine_name=machine_name,
        layer_height_mm=layer_height_mm,
        build_volume_mm=build_volume_mm,
        nozzle_diameter_mm=job.nozzle_diameter_mm,
        printability_score=job.printability_score,
        printability_verdict=job.printability_verdict,
        material_type=job.material_type,
        material_brand=job.material_brand,
        material_colour=job.material_colour,
        blueprint_gate_state=job_blueprint_gate_state,
        blueprint_gate_subject=blueprint_gate_subject,
        requested_size_mm=job.requested_size_mm,
        size_source=job.size_source,
        requested_scale_axis=job.requested_scale_axis,
        blueprint_seed=job.blueprint_seed,
        parent_job_id=job.parent_job_id,
        download_count=job.download_count or 0,
        slice_status=job.slice_status,
        estimated_print_time_s=job.estimated_print_time_s,
        filament_used_mm3=job.filament_used_mm3,
        filament_used_g=job.filament_used_g,
        support_filament_mm3=job.support_filament_mm3,
        layer_count=job.layer_count,
        outcome_source=job.outcome_source,
        has_fit_photo=fit_photo_on_disk(job) is not None,
        awaiting_verdict=job.outcome == "awaiting_verdict",
        used_reference_assets=(
            None if job.used_reference_assets is None else bool(job.used_reference_assets)
        ),
        dispatch_state=job_dispatch_state,
        dispatch_target=job_dispatch_target,
        **job_spec_summary(job),
    )

@app.get("/jobs/{job_id}/printer-info")
async def get_printer_info(job_id: str):
    """Get normalized printer metadata for a job."""
    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    service_labels = {
        "octoprint": "OctoPrint",
        "klipper": "Klipper",
        "bambu": "Bambu Lab",
    }

    machine_name = None
    layer_height_mm = None
    machine_dimensions = None
    profile_path_str = job.profile_name

    if profile_path_str and profile_path_str != "default":
        try:
            profile_full_path = profile_path_or_default(profile_path_str)
            if profile_full_path.exists():
                with open(profile_full_path, "r") as pf:
                    profile_data = json.load(pf)
                    machine_name = profile_data.get("machine_name")
                    layer_height_mm = profile_data.get("layer_height")
                    w = profile_data.get("machine_width")
                    d = profile_data.get("machine_depth")
                    h = profile_data.get("machine_height")
                    if w and d and h:
                        machine_dimensions = {"width": w, "depth": d, "height": h}
        except Exception:
            pass

    firmware = job.printer_firmware or "octoprint"
    connection_status = "unknown"
    stored = config_store.get_all()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            if firmware == "octoprint":
                url = stored.get("OCTOPRINT_URL")
                if url:
                    # Same host binding as every other outbound printer request: this
                    # probe is as much a way to post the key somewhere as the
                    # connection test is.
                    headers = {}
                    api_key = printer_credential("octoprint", stored.get).value
                    if api_key:
                        headers["X-Api-Key"] = api_key
                    resp = await client.get(f"{url.rstrip('/')}/api/version", headers=headers)
                    connection_status = "online" if resp.status_code == 200 else "offline"
                else:
                    connection_status = "offline"
            elif firmware == "klipper":
                url = stored.get("MOONRAKER_URL")
                if url:
                    headers = {}
                    api_key = printer_credential("klipper", stored.get).value
                    if api_key:
                        headers["X-Api-Key"] = api_key
                    resp = await client.get(f"{url.rstrip('/')}/printer/info", headers=headers)
                    connection_status = "online" if resp.status_code == 200 else "offline"
                else:
                    connection_status = "offline"
            else:
                connection_status = "unknown"
    except Exception:
        connection_status = "offline"

    return {
        "service": firmware,
        "service_label": service_labels.get(firmware, firmware),
        "printer_name": machine_name or job.printer_id,
        "profile_name": profile_path_str,
        "connection_status": connection_status,
        "layer_height_mm": layer_height_mm,
        "machine_dimensions": machine_dimensions
    }

#: What `?format=` may name: the artifact it serves and the type it serves it as.
#:
#: Three files come out of one job and each has a different consumer, so they are one
#: endpoint with a parameter rather than three endpoints: the download *event* and
#: `download_count` mean "a person chose to keep this result", and that fact does not
#: subdivide by file extension — it is recorded once, in one place, with the format in
#: the detail. `gcode` is first and is the default, so every caller written before the
#: parameter existed keeps getting exactly what it got.
#:
#: The mesh types are IANA-registered (`model/stl`, `model/3mf`). G-code has no
#: registered type and stays `text/plain`, which is what the toolpath viewer's
#: `?preview=1` fetch has always been handed.
DOWNLOAD_FORMATS: dict[str, tuple[str, str]] = {
    "gcode": ("engineered_mesh.gcode", "text/plain"),
    "stl": ("engineered_mesh.stl", "model/stl"),
    "3mf": ("engineered_mesh.3mf", "model/3mf"),
}

DEFAULT_DOWNLOAD_FORMAT = "gcode"


def stale_flat_artifacts(repo_root: Path) -> list[Path]:
    """The flat-layout files `POST /jobs` clears before minting a job id.

    A run without `--job-id` — the manual CLI path — writes to flat `data/outputs/`,
    and `resolve_job_artifact` falls back there for a *finished* job that has no file
    of its own. So this sweep is the other half of `/download`'s guard: the
    `is_per_job` check refuses the fallback only for a job that never completed, and
    what keeps a completed job with no file of its own from being handed an earlier
    run's output is that the earlier run's output is no longer there.

    Which is why the download formats are read out of `DOWNLOAD_FORMATS` rather than
    listed again: a format that is servable and not swept mis-attributes a file, and
    that is exactly what happened when the 3MF was added to one list and not the
    other. `tests/test_job_artifacts.py` binds the two.

    Args:
        repo_root: The checkout root; `data/outputs/` hangs off it.

    Returns:
        Absolute paths, existing or not — the caller unlinks what it finds.
    """
    outputs = repo_root / "data" / "outputs"
    # raw_mesh.obj and engineered_mesh.obj are not download formats: the first is
    # Phase 2's output and the second is what the mesh viewer renders inline.
    served = [filename for filename, _ in DOWNLOAD_FORMATS.values()]
    return [outputs / name for name in ["raw_mesh.obj", "engineered_mesh.obj", *served]]


@app.get("/jobs/{job_id}/download")
async def download_job_output(
    job_id: str, preview: bool = False, format: str = DEFAULT_DOWNLOAD_FORMAT,
):
    """Download one of a completed job's output files.

    Args:
        job_id: The unique identifier of the print job.
        preview: True when the caller is a UI component fetching the bytes to
            *render* them (the toolpath viewer polls this endpoint automatically).
            A preview serves the same file but records nothing — the download
            event exists to mean "a person chose to keep this", and a component
            mount is not a person.
        format: Which artifact — `gcode` (default, and what every caller written
            before this parameter existed receives), `stl` or `3mf`. The two mesh
            formats are what a person needs when the printer is one this project
            cannot dispatch to: `GET /jobs/{id}/mesh` exists for the viewer and
            serves the `.obj` inline, which is not a handoff.

    Returns:
        A StreamingResponse carrying the file, typed and named for the format.

    Raises:
        HTTPException: 400 for an unrecognised format, 404 if the job or the file
            for that format is missing.
    """
    # Decided before the job is looked up: an unrecognised format is a malformed
    # request whatever the job id says, and answering 404 would send someone looking
    # for a missing file when the spelling is what is wrong. Named, because "invalid
    # format" does not say which ones are valid.
    if format not in DOWNLOAD_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown download format {format!r}. "
                f"Expected one of: {', '.join(DOWNLOAD_FORMATS)}."
            ),
        )
    filename, media_type = DOWNLOAD_FORMATS[format]

    db = TelemetryDB()
    job = db.get_job(job_id)

    if not job:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")

    artifact_path = resolve_job_artifact(job_id, filename)

    if artifact_path is None:
        db.close()
        raise HTTPException(status_code=404, detail="File not found")

    # A job that never finished has no output of its own. Serving the flat legacy file
    # here would hand the caller some other job's print — and every format has one, so
    # the guard covers all three rather than the G-code alone.
    is_per_job = artifact_path.parent.name == job_id
    if not is_per_job and job.outcome not in ("success", "cancelled", "awaiting_verdict"):
        db.close()
        raise HTTPException(
            status_code=404,
            detail=(
                f"No {format} for this job yet (job has not completed slicing)."
                if format == "gcode"
                else f"No {format} for this job yet."
            ),
        )

    # A download is the clearest signal that a result was worth keeping, and it is
    # unrecoverable after the fact — recorded before the bytes stream, since the
    # response is lazy and may be abandoned mid-flight. Preview fetches are served
    # and not counted: the toolpath viewer retries this endpoint every few seconds
    # until it answers, which made download_count a render counter.
    #
    # The format rides in the detail. Without it the event says a result was kept and
    # not which file was worth keeping — and "did anyone actually use the 3MF" is the
    # question that decides whether the handoff route is worth keeping.
    if not preview:
        try:
            db.record_job_event(
                job_id, "download", {"artifact": filename, "format": format},
            )
            db.increment_download_count(job_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record download event for %s: %s", job_id, exc)
    db.close()

    def iterfile():
        with open(artifact_path, mode="rb") as f:
            while chunk := f.read(8192):
                yield chunk

    headers = {
        "Content-Disposition": f'attachment; filename="{job_id}.{format}"'
    }
    from fastapi.responses import StreamingResponse
    return StreamingResponse(iterfile(), media_type=media_type, headers=headers)

class DispatchRequest(BaseModel):
    """A person's confirmation that this job may go to a machine.

    `confirmed` is required to be true. It is not a formality: nothing else in the
    system stops a print, so the flag is the gate, and a caller that cannot say a human
    approved the dispatch is a caller that must not dispatch. The optional `profile` and
    `base_url` are the target *as it was displayed* — when they are supplied and no
    longer match what the server resolves, the answer is 409 rather than a print to a
    machine nobody chose.
    """
    confirmed: bool = False
    profile: Optional[str] = None
    base_url: Optional[str] = None


class BlueprintApprovalRequest(BaseModel):
    """A person's decision about a rendered blueprint."""

    confirmed: bool = False
    """Must be true. The flag *is* the gate — there is deliberately no unconfirmed
    code path, so an empty body cannot start a reconstruction."""

    approve: bool = True
    """True to continue into Phase 2, false to record a rejection and stop."""

    sha256: Optional[str] = None
    """The blueprint's hash **as displayed**. When it no longer matches what the
    server resolves, the answer is 409: approving an image you are no longer looking
    at is not approving. Same rule as the dispatch gate's target check."""


def _snapshot_blueprint(job_id: str) -> Path | None:
    """Copy this job's rendered blueprint into its own output directory.

    Load-bearing for the approval gate: it binds the decision to an image that cannot
    be replaced underneath it, and gives the continuation a path to name explicitly
    rather than re-reading whatever sits on the input path by the time someone clicks.

    **This job's own input directory is searched first.** Phase 1 renders to
    `data/inputs/{job_id}/blueprint.png` (see `pipeline._blueprint_path`) precisely so
    that two concurrent jobs cannot overwrite each other's image. Reading only the flat
    `data/inputs/blueprint.png` — which is what this did before per-job inputs existed —
    finds nothing for a gated run, so `_park_at_blueprint_gate` reports "no blueprint to
    approve" and `_run_pipeline` fails a job whose Phase 1 had just succeeded. Worse
    when a stale shared PNG happens to be present: the gate then snapshots *another
    job's* render and binds this approval to it. The flat path stays as the fallback
    because the skip-Phase-1 configuration deliberately reuses it.

    The provenance sidecar is copied too: it is matched to the PNG by hash, and a
    blueprint that moves without it records NULL for seed, prompt and model on the
    continuation's skip-visualizer path.

    Args:
        job_id: The job to snapshot for.

    Returns:
        The snapshot path, or None if there was nothing to copy.
    """
    import shutil

    repo_root = Path(__file__).parent.parent
    inputs = repo_root / "data" / "inputs"
    for source in (inputs / job_id / "blueprint.png", inputs / "blueprint.png"):
        if source.exists():
            break
    else:
        return None

    target_dir = repo_root / "data" / "outputs" / job_id
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "blueprint.png"
        shutil.copy2(source, target)

        sidecar = source.with_name(source.stem + ".provenance.json")
        if sidecar.exists():
            shutil.copy2(sidecar, target_dir / sidecar.name)
        return target
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not snapshot the blueprint for %s: %s", job_id, exc)
        return None


async def _park_at_blueprint_gate(job_id: str) -> bool:
    """Leave a job waiting for a person to approve its blueprint.

    Records nothing in the outcome column on purpose. The outcome says what the
    *software* did, and "a person has not decided yet" is a decision record — which is
    `job_event`'s job, and is why `blueprint_gate_state` derives from events. Writing
    "success" here would also make `dispatch_state` report the job as ready to print.

    Args:
        job_id: The job to park.

    Returns:
        True when there is a blueprint to approve, False when there is nothing to show
        and the caller should carry on rather than park on an empty gate.
    """
    snapshot = _snapshot_blueprint(job_id)
    if snapshot is None:
        logger.warning(
            "Job %s produced no blueprint to approve — not parking at the gate.", job_id,
        )
        return False

    # The record that this run stopped and is waiting. Written before anything else,
    # because `blueprint_gate_state` derives from it: a park that is not recorded is a
    # job that silently continues past the gate.
    try:
        db = TelemetryDB()
        db.record_job_event(job_id, "blueprint_gate_parked", {
            "sha256": _file_sha256(snapshot),
        })
        db.close()
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not record the blueprint park for %s: %s", job_id, exc)
        return False

    _append_phase_status(job_id, 1, "complete")
    await broadcaster.broadcast(job_id, {
        "type": "blueprint_gate",
        "data": {
            "job_id": job_id,
            "state": "awaiting_approval",
            "sha256": _file_sha256(snapshot),
            "url": f"/jobs/{job_id}/blueprint",
        },
    })
    activity.action(
        "blueprint awaiting approval",
        [("job", job_id[:8])],
        outcome="Phase 2 held until a person approves the blueprint",
        status="ok",
    )
    logger.info("Job %s parked at the blueprint approval gate.", job_id)
    return True


async def _continue_pipeline(job_id: str, request: JobRequest):
    """Run Phases 2-5 for a job whose blueprint has been approved.

    A second subprocess invocation rather than a resumed one, which is what makes the
    gate durable: the decision is a row in the database, so the wait has no time limit
    and survives a server restart. `--skip-visualizer` loses nothing, because Phase 1
    left a provenance sidecar beside the PNG.

    Args:
        job_id: The approved job.
        request: The original request, rebuilt from `print_job.request_params`.
    """
    resumed = request.model_copy(update={"skip_visualizer": True})
    await _run_pipeline(job_id, resumed)


@app.post("/jobs/{job_id}/blueprint-approval")
async def blueprint_approval(job_id: str, request: BlueprintApprovalRequest | None = None):
    """Approve or reject a rendered blueprint, and continue the job if approved.

    This is the gate that stops Phase 2 running on an image nobody has seen. It is the
    only recovery path for a false positive from the image screen, and the only point
    at which a person can decline a result cheaply — before a paid reconstruction and
    before hours of printing.

    Checks, in the order they must happen:

    1. `confirmed: true`, refused **before any database read**, so an empty body cannot
       reach anything.
    2. The job exists.
    3. It is actually waiting — an already-decided job is a 409, because two clicks
       must not buy two reconstructions.
    4. The blueprint still hashes to what the caller was shown, or 409.

    Args:
        job_id: The job whose blueprint is being decided.
        request: The decision.

    Returns:
        The recorded decision and the resulting gate state.

    Raises:
        HTTPException: 400 unconfirmed, 404 unknown job, 409 already decided or the
            blueprint changed underneath the caller.
    """
    if request is None or not request.confirmed:
        raise HTTPException(
            status_code=400,
            detail="A blueprint approval must be explicitly confirmed.",
        )

    db = TelemetryDB()
    try:
        job = db.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

        state = blueprint_gate_state(job, db)
        if state in {"approved", "rejected"}:
            raise HTTPException(
                status_code=409,
                detail=f"This blueprint has already been {state}.",
            )
        if state != "awaiting_approval":
            raise HTTPException(
                status_code=409,
                detail="This job has no blueprint awaiting approval yet.",
            )

        artifact = resolve_job_artifact(job_id, "blueprint.png", per_job_only=True)
        current = _file_sha256(artifact) if artifact else None
        if request.sha256 and current and request.sha256 != current:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The blueprint has changed since it was shown to you. Reload and "
                    "look at the current one before approving it."
                ),
            )

        kind = "blueprint_approved" if request.approve else "blueprint_rejected"
        try:
            db.record_job_event(job_id, kind, {
                "sha256": current,
                "displayed_sha256": request.sha256,
            })
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not record %s for %s: %s", kind, job_id, exc)
            raise HTTPException(
                status_code=500,
                detail="The decision could not be recorded, so nothing was started.",
            ) from exc

        activity.action(
            "blueprint " + ("approved" if request.approve else "rejected"),
            [("job", job_id[:8]), ("sha256", (current or "")[:12])],
            outcome="continuing into Phase 2" if request.approve else "stopped by the requester",
            status="ok",
        )

        if not request.approve:
            # Settled, or the row reads as *running* forever: `job_status_from_outcome`
            # maps "unknown" to running, so a declined job would stay in the running
            # list and `NewJob` would re-attach to it on every page load — making the
            # landing composer unreachable. "cancelled" is the existing value for
            # stopped-on-request, and is already excluded from the success rate.
            db.update_job_outcome_verdict(
                job_id, "cancelled", source="user",
                completed_at=datetime.now(timezone.utc),
            )
            _append_phase_status(job_id, 1, "complete")
            return {"job_id": job_id, "decision": "rejected", "blueprint_gate_state": "rejected"}

        stored = job.request_params or {}
        try:
            resumed = JobRequest(**{
                **stored,
                "prompt": stored.get("prompt") or job.prompt,
                "printer_id": stored.get("printer_id") or job.printer_id or "default_printer",
                # The image that was approved, by its container path. Not the flat
                # input path: nothing binds that to this job, and a skip-Phase-1 run
                # started while this one was parked would leave a different render
                # there entirely — which is what the hash check would then have been
                # guarding for nothing.
                "blueprint_path": f"/app/data/outputs/{job_id}/blueprint.png",
                "skip_visualizer": True,
            })
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not rebuild the request for %s: %s", job_id, exc)
            raise HTTPException(
                status_code=500,
                detail="The original request could not be read, so the job cannot continue.",
            ) from exc
    finally:
        db.close()

    _append_phase_status(job_id, 2, "running")
    asyncio.create_task(_continue_pipeline(job_id, resumed))

    return {"job_id": job_id, "decision": "approved", "blueprint_gate_state": "approved"}


@app.post("/jobs/{job_id}/print-dispatch")
async def print_dispatch(job_id: str, request: DispatchRequest | None = None):
    """Run Phase 5 for an already-sliced job, once a person has confirmed the target.

    The pipeline is launched without `--print`, so it stops after the slicer and the job
    waits here. This is the human in the loop: the four checks below are the difference
    between a confirmation step and a button.

    Args:
        job_id: The job to dispatch.
        request: The confirmation, carrying the target the user was shown.

    Returns:
        A dict with the dispatch status and the target it went to.

    Raises:
        HTTPException: 404 unknown job; 400 unconfirmed or nothing to send; 409 when the
            target moved under the user or the printer will not answer.
    """
    confirmation = request or DispatchRequest()
    if not confirmation.confirmed:
        raise HTTPException(
            status_code=400,
            detail="A print is only dispatched on an explicit confirmation. "
                   "Review the printer and send it from the job view.",
        )

    db = TelemetryDB()
    job = db.get_job(job_id)
    if not job:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")

    state = dispatch_state(job, db)
    if state == "dispatched":
        db.close()
        raise HTTPException(status_code=409, detail="This job has already been sent to a printer.")

    gcode_path = resolve_job_artifact(job_id, "engineered_mesh.gcode")
    if gcode_path is None:
        db.close()
        raise HTTPException(status_code=400, detail="No G-code for this job. Complete phases 1–4 first.")

    target = dispatch_target(job)
    profile_path = resolve_job_profile(job)[1]
    if not profile_path:
        db.close()
        raise HTTPException(status_code=400, detail="Configured printer profile not found.")

    # Before anything with a side effect, because the alternative is what this replaced:
    # the operator was spawned for a Bambu target, connected, uploaded the CuraEngine
    # `.gcode` to the printer's SD card over FTPS, and only then had `start_print` refuse
    # — leaving a start-sequence-less file on the machine, the job marked failure with
    # "The operator exited with 1", and the reason visible only in a subprocess log.
    # Asked here, the refusal costs nothing and the person reads the actual sentence.
    #
    # The class, not an instance: this is a fact about the firmware, so it needs no
    # address and no credential to answer. See `PrinterFactory.operator_class`.
    try:
        operator_class = PrinterFactory.operator_class(target["firmware"])
    except ValueError as exc:
        db.close()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not operator_class.starts_prints:
        db.close()
        raise HTTPException(status_code=409, detail=operator_class.dispatch_refusal)

    # The target as shown, against the target as it stands. A profile swapped in Settings
    # between the two is exactly the case this step exists to catch.
    drifted = [
        (name, shown, current)
        for name, shown, current in (
            ("profile", confirmation.profile, target["profile"]),
            ("base_url", confirmation.base_url, target["base_url"]),
        )
        if shown and current and shown != current
    ]
    if drifted:
        db.close()
        changes = "; ".join(f"{name}: {shown} → {current}" for name, shown, current in drifted)
        raise HTTPException(
            status_code=409,
            detail=f"The printer changed since you looked ({changes}). Check it and confirm again.",
        )

    # A stored key belongs to the host it was saved beside, and this is the request
    # that would carry it to whatever host is configured now. Refused rather than sent
    # keyless: the operator would reach the machine, be rejected, and leave a job
    # reading as dispatched — and "re-enter the key" is an answer a person can act on,
    # where a 401 in a subprocess log is not.
    credential = printer_credential(target["firmware"])
    if credential.withheld:
        db.close()
        raise HTTPException(status_code=409, detail=credential.reason)

    # Asked, not assumed. A dead printer discovered here costs a click; discovered by the
    # operator subprocess it costs a job that reads as dispatched and never printed.
    probe = await printer_status()
    if not probe.get("running"):
        db.close()
        raise HTTPException(
            status_code=409,
            detail="The printer did not answer. " + (probe.get("detail") or "Test the connection in Settings."),
        )

    repo_root = Path(__file__).parent.parent
    try:
        db.record_job_event(job_id, "dispatch_confirmed", {
            "profile": target["profile"],
            "firmware": target["firmware"],
            "base_url": target["base_url"],
            "machine_name": target["machine_name"],
            "gcode": gcode_path.name,
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record the dispatch confirmation for %s: %s", job_id, exc)

    # Onto the row as well as into the event: the URL confirmed here is the only
    # thing that later distinguishes simulator telemetry from real hardware, and a
    # query cannot be expected to dig it out of an event's JSON detail.
    db.update_job_dispatch(job_id, printer_url=target["base_url"])

    # Dispatched is not printed. The file leaving for a machine settles nothing about the
    # part, so the row goes to awaiting_verdict and a person closes it out later.
    db.update_job_outcome_verdict(
        job_id, "awaiting_verdict", source="machine", completed_at=datetime.now(timezone.utc)
    )
    db.close()

    activity.action(
        "print dispatch confirmed",
        [
            ("job", job_id[:8]),
            ("profile", target["profile"]),
            ("firmware", target["firmware"]),
            ("printer", target["base_url"]),
        ],
        outcome="operator starting; the row is awaiting a human verdict",
        status="ok",
        source="operator",
    )

    log_dir = repo_root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _append_phase_status(job_id, 5, "running")
    await broadcaster.broadcast(job_id, {"type": "phase_update", "data": {
        "phase": 5, "name": "Operator", "status": "running", "error": None,
        "ts": datetime.now(timezone.utc).isoformat(),
    }})

    try:
        cmd = [
            sys.executable,
            str(repo_root / "pythonsrc" / "run_operator.py"),
            "--job-id", job_id,
            "--gcode-path", str(gcode_path),
            "--profile", profile_path,
        ]

        # This server's environment plus the allowlisted config-store keys, and
        # nothing else from the store — see `subprocess_env`.
        env = subprocess_env()

        # The operator is told which printer, at which address, with which key, in the
        # same three variables `create_job` hands the pipeline — and that is the whole
        # of it. It used to be handed `OCTOPRINT_API_KEY` beside an `OCTOPRINT_URL`
        # this block overwrote with `target["base_url"]`, which for a klipper or bambu
        # profile is `MOONRAKER_URL` or `BAMBU_IP`. The binding could not see that: it
        # had checked the key against `OCTOPRINT_URL` in `subprocess_env`, one
        # assignment earlier, and the gate above had checked the *target* firmware's
        # credential, which in that shape is unset and therefore not withheld. So an
        # OctoPrint key bound to the person's own printer left for whatever address an
        # unauthenticated `POST /config MOONRAKER_URL` had just named.
        #
        # `credential` is the gate's own answer, resolved for `target["firmware"]`, so
        # the key and the address here can only have come from the same firmware.
        env.pop("OCTOPRINT_API_KEY", None)
        env["DS_FIRMWARE"] = target["firmware"]
        if credential.value:
            env["DS_PRINTER_KEY"] = credential.value

        # The address the person just confirmed, not the dev default baked into the
        # profile file. `resolve_printer_target` makes the config store authoritative
        # for base_url, and the operator falls back to the profile's own — with the
        # profile's own key — when this is absent, so a real printer configured in
        # Settings is no longer dispatched to localhost:5001 while the gate displays
        # the right machine.
        #
        # The operator runs in this container, so it is given the route this process
        # already resolved rather than being left to derive one from a loopback
        # address it cannot reach. The configured address rides alongside it, because
        # that — not the container route standing in for it — is what
        # `dispatched_printer_url` must record.
        if target.get("base_url"):
            env["DS_PRINTER_URL"] = container_reachable_url(target["base_url"])
            env["DS_DISPATCH_URL"] = target["base_url"]
        # Bambu keys every MQTT topic on the serial, so without it the operator can
        # reach the printer and not address it. Not a credential — it is printed on the
        # machine and sits in the printer's own TLS certificate — but it is per-printer,
        # so it comes from the store rather than from the profile, which is committed.
        if canonical_firmware(target["firmware"]) == "bambu":
            serial = config_store.get("BAMBU_SERIAL")
            if serial:
                env["DS_PRINTER_SERIAL"] = serial
        # Without this the operator's telemetry collector has nowhere to relay samples,
        # so the print runs with a live socket open and nothing on it.
        # The operator runs beside this process — in this container, or on this host
        # — so the loopback address is the right one and needs no translation.
        env.setdefault("DS_API_URL", NATIVE_API_URL)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=repo_root,
            env=env,
        )

        async def _run():
            """Follow the operator to its end, rather than firing and forgetting.

            The old version launched it and returned. A dispatch that failed left the
            job claiming to be printing, with the reason only in a subprocess nobody
            was reading.
            """
            log_file = log_dir / f"{job_id}.log"
            with open(log_file, "a") as handle:
                handle.write(f"\n[dispatch] operator starting for {gcode_path.name}\n")
                await _stream_output(process, handle, job_id)
                await process.wait()
                handle.write(f"[dispatch] operator exited with {process.returncode}\n")

            failed = process.returncode != 0
            _append_phase_status(job_id, 5, "error" if failed else "complete",
                                 error=f"operator exited with {process.returncode}" if failed else None)
            await broadcaster.broadcast(job_id, {"type": "phase_update", "data": {
                "phase": 5, "name": "Operator", "status": "error" if failed else "complete",
                "error": f"The operator exited with {process.returncode}" if failed else None,
                "ts": datetime.now(timezone.utc).isoformat(),
            }})
            if failed:
                # The print never started, so the row must not sit in awaiting_verdict
                # asking a person about a part that does not exist.
                inner = TelemetryDB()
                inner.update_job_outcome_verdict(
                    job_id, "failure", source="machine",
                    completed_at=datetime.now(timezone.utc),
                )
                inner.close()
                await broadcaster.broadcast(job_id, {"type": "job_complete", "data": {"outcome": "failure"}})

        asyncio.create_task(_run())

        return {"status": "dispatching", "target": target}
    except Exception as e:
        logger.error(f"Error in print-dispatch: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    """Cancel the running job and the printer."""
    db = TelemetryDB()
    job = db.get_job(job_id)

    if not job:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")

    # Mark the job cancelled *before* killing anything. The pipeline's exit is
    # observed by `_run_pipeline`, which would otherwise read the non-zero code as a
    # crash and overwrite this verdict with "failure".
    cancelled_jobs.add(job_id)

    # Kill the pipeline, then make sure it is actually gone. `terminate()` only asks:
    # a pipeline blocked on a hosted generation or a docker build can sit in SIGTERM
    # handling for a long time, and the endpoint used to return "cancelled" while the
    # work carried on spending money in the background.
    process = active_pipelines.get(job_id)
    if process:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=PIPELINE_TERM_GRACE_S)
        except asyncio.TimeoutError:
            logger.warning(
                "Pipeline for job %s ignored SIGTERM after %ss; killing",
                job_id, PIPELINE_TERM_GRACE_S,
            )
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass
        except ProcessLookupError:
            pass

    # The phase the pipeline died inside is still recorded as "running", both in the
    # `.status` file it will never write again and in every client's phase row. Say so
    # explicitly, or the UI keeps a phase pulsing forever on a job that has stopped —
    # which reads as the Stop button having done nothing at all.
    stopped_phase = _read_current_phase(job_id)
    if stopped_phase and stopped_phase.get("status") == "running":
        await broadcaster.broadcast(job_id, {
            "type": "phase_update",
            "data": {
                "phase": stopped_phase.get("phase"),
                "name": stopped_phase.get("name"),
                "status": "error",
                "error": "Stopped",
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        })

    # Attempt to cancel printer
    profile_path = str(profile_path_or_default(config_store.get("DEFAULT_PROFILE")))
    try:
        if os.path.exists(profile_path):
            firmware, base_url, api_key = resolve_printer_target(profile_path)
            from pythonsrc.operators import PrinterFactory
            op = PrinterFactory.create(
                firmware=firmware,
                base_url=container_reachable_url(base_url or "http://localhost:5001"),
                api_key=api_key,
            )
            # Try to cancel
            try:
                op.cancel_print()
            except Exception as e:
                logger.warning(f"Could not cancel print on printer: {e}")
    except Exception as e:
        logger.warning(f"Error instantiating printer factory during cancel: {e}")

    # A machine-sourced write: it must never clobber a verdict a human already gave.
    db.update_job_outcome_verdict(
        job_id, "cancelled", source="machine",
        completed_at=datetime.now(timezone.utc),
    )
    db.close()

    activity.action(
        "job stopped by user",
        [
            ("job", job_id[:8]),
            ("phase", (stopped_phase or {}).get("phase")),
            ("printer", "cancel sent" if os.path.exists(profile_path) else "no profile"),
        ],
        outcome="pipeline killed, outcome recorded as cancelled",
        status="warn",
        level="WARNING",
    )
    await broadcaster.broadcast(job_id, {"type": "job_complete", "data": {"outcome": "cancelled"}})
    return {"status": "cancelled"}

class PrinterActionRequest(BaseModel):
    action: str

@app.post("/jobs/{job_id}/action")
async def printer_action(job_id: str, request: PrinterActionRequest):
    """Execute a printer action (pause, resume, cancel)."""
    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    profile_path = str(profile_path_or_default(config_store.get("DEFAULT_PROFILE")))

    if not os.path.exists(profile_path):
        raise HTTPException(status_code=400, detail="Printer profile not found")

    try:
        firmware, base_url, api_key = resolve_printer_target(profile_path)
        from pythonsrc.operators import PrinterFactory
        op = PrinterFactory.create(
            firmware=firmware,
            base_url=container_reachable_url(base_url or "http://localhost:5001"),
            api_key=api_key,
        )

        if request.action == "pause":
            op.pause_print()
        elif request.action == "resume":
            op.resume_print()
        elif request.action == "cancel":
            op.cancel_print()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")

        activity.action(
            f"printer {request.action}",
            [("job", job_id[:8]), ("firmware", firmware), ("target", base_url)],
            outcome="the machine accepted it",
            status="ok",
        )
        return {"status": "success", "action": request.action}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to execute printer action {request.action}: {e}")
        activity.action(
            f"printer {request.action}",
            [("job", job_id[:8]), ("error", str(e))],
            outcome="the machine refused it — nothing changed",
            status="fail",
            level="ERROR",
        )
        raise HTTPException(status_code=500, detail=str(e)) from e

class InternalTelemetryRequest(BaseModel):
    type: str
    data: dict

@app.post("/jobs/{job_id}/internal-telemetry")
async def internal_telemetry(job_id: str, request: InternalTelemetryRequest):
    """Internal endpoint for pipeline-runner to push telemetry/state updates."""
    await broadcaster.broadcast(job_id, {"type": request.type, "data": request.data})
    return {"status": "success"}

#: The filters ``GET /jobs`` knows about.
#:
#: An unrecognised value used to fall through the ``elif`` chain to no WHERE clause at
#: all, so the endpoint answered with every job, newest first. To a client that only
#: checks whether a row came back — which is what ``NewJob``'s re-attach did — that is
#: indistinguishable from "here is the job you asked about", and a browser one deploy
#: ahead of the server was handed a finished job and dropped into the running view.
#: Refusing beats guessing: the caller then knows the filter did not run.
JOB_LIST_STATUSES = (
    "all",
    "running",
    "completed",
    "failed",
    "awaiting_verdict",
    "awaiting_dispatch",
    "awaiting_blueprint_approval",
)


@app.get("/jobs")
async def list_jobs(limit: int = 20, offset: int = 0, status: str = 'all'):
    """List print jobs with pagination and status filtering.

    Raises:
        HTTPException: 400 when `status` is not one of `JOB_LIST_STATUSES`.
    """
    arbitrate_blueprint_gate = False
    if status not in JOB_LIST_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown status filter {status!r}. "
                f"Expected one of: {', '.join(JOB_LIST_STATUSES)}."
            ),
        )

    db = TelemetryDB()

    where_clause = ""
    params: list = []

    if status == 'running':
        # Parked at the blueprint gate is waiting, not running, and it has its own
        # filter. Left in here it would own the landing page: `NewJob` attaches to the
        # newest running job on mount, so one job nobody ever decides would drop every
        # new tab into its running view and make the composer unreachable — exactly the
        # failure `awaiting_dispatch` was introduced to fix, one gate earlier.
        where_clause = (
            "WHERE outcome = 'unknown' "
            "AND job_id NOT IN ("
            "  SELECT job_id FROM job_event WHERE kind = 'blueprint_gate_parked' "
            "  AND job_id NOT IN (SELECT job_id FROM job_event "
            "    WHERE kind IN ('blueprint_approved', 'blueprint_rejected'))"
            ")"
        )
    elif status == 'completed':
        where_clause = "WHERE outcome = 'success'"
    elif status == 'failed':
        where_clause = "WHERE outcome IN ('failure', 'cancelled')"
    elif status == 'awaiting_verdict':
        where_clause = "WHERE outcome = 'awaiting_verdict'"
    elif status == 'awaiting_blueprint_approval':
        # Parked after Phase 1, waiting on a person. Its own filter because such a job
        # is not "running" by any other definition, so without this the pending
        # decision vanishes on a page reload — which for a human-in-the-loop gate
        # means it does not survive at all.
        #
        # The SQL is only the candidate set: "outcome is unknown" is every running job.
        # Whether a job is *actually* waiting depends on a park event and an artifact
        # on disk, so the rows are arbitrated by `blueprint_gate_state` below — the
        # same function the job endpoint answers with, so the list and the page cannot
        # disagree about who is waiting.
        arbitrate_blueprint_gate = True
        where_clause = (
            "WHERE outcome = 'unknown' "
            "AND job_id IN (SELECT job_id FROM job_event "
            "WHERE kind = 'blueprint_gate_parked') "
            "AND job_id NOT IN (SELECT job_id FROM job_event "
            "WHERE kind IN ('blueprint_approved', 'blueprint_rejected'))"
        )
    elif status == 'awaiting_dispatch':
        # Sliced, finished, and never sent: the jobs whose Phase 5 is waiting on a
        # person. Without this the confirmation step would not survive a page reload,
        # which for a human-in-the-loop gate means it would not survive at all.
        where_clause = (
            "WHERE outcome = 'success' AND slice_status = 'success' "
            "AND job_id NOT IN (SELECT job_id FROM job_event WHERE kind = 'dispatch_confirmed')"
        )

    count_row = db.query_one(f"SELECT COUNT(*) AS n FROM print_job {where_clause}", params)
    total = int(count_row["n"]) if count_row else 0

    global_counts = db.query(
        "SELECT outcome, COUNT(*) AS count FROM print_job GROUP BY outcome"
    )

    stats = {
        "total": 0, "running": 0, "completed": 0, "failed": 0,
        "awaiting_verdict": 0, "dev": 0, "declined": 0,
    }
    for row in global_counts:
        outcome = row['outcome']
        c = row['count']
        stats["total"] += c
        if outcome == "unknown":
            stats["running"] += c
        elif outcome == "success":
            stats["completed"] += c
        elif outcome == "awaiting_verdict":
            # Its own bucket: counting an unconfirmed print as a failure would be as
            # wrong as counting it as a success.
            stats["awaiting_verdict"] += c
        elif outcome in ("dev", "declined"):
            # Not failures. A developer honestly marking a test run as `dev`, or a
            # user asking not to be asked again, used to increment the failed
            # counter the pilot is judged by.
            stats[outcome] += c
        else:
            stats["failed"] += c

    # NULLS LAST keeps the order the SQLite version had: PostgreSQL sorts NULL as the
    # largest value, which would put every never-started job at the top of the list.
    rows = db.query(
        f"SELECT * FROM print_job {where_clause} "
        "ORDER BY started_at DESC NULLS LAST LIMIT %s OFFSET %s",
        [*params, limit, offset],
    )

    # Which of these have actually been sent. One query rather than one per row, and the
    # only way a list row can tell "finished" from "finished and waiting on a person".
    dispatched = {
        r['job_id']
        for r in db.query("SELECT DISTINCT job_id FROM job_event WHERE kind = 'dispatch_confirmed'")
    }

    jobs = []
    for row in rows:
        job_outcome = row['outcome']
        status_val = job_status_from_outcome(job_outcome, row['started_at'])
        keys = row.keys()
        jobs.append({
            "job_id": row['job_id'],
            "prompt": row['prompt'],
            "printer_id": row['printer_id'],
            "printer_firmware": row['printer_firmware'],
            "started_at": _iso(row['started_at']),
            "completed_at": _iso(row['completed_at']),
            "outcome": job_outcome,
            "status": status_val,
            # Read via `keys` because a database migrated mid-session may not carry
            # these columns yet.
            "material_type": row['material_type'] if 'material_type' in keys else None,
            "awaiting_verdict": job_outcome == "awaiting_verdict",
            "outcome_source": row['outcome_source'] if 'outcome_source' in keys else None,
            # Sliced, finished, never sent: Phase 5 is waiting for someone to confirm the
            # printer. Reported here so the dashboard can say so instead of calling it
            # "Success" — nothing has been printed.
            "awaiting_dispatch": (
                job_outcome == "success"
                and ('slice_status' in keys and row['slice_status'] == "success")
                and row['job_id'] not in dispatched
            ),
        })
    db.close()

    # The park event is checked in SQL; whether the image is actually on disk is not
    # something SQL can answer, so the candidate rows are arbitrated here. Without it
    # the dashboard would offer to approve blueprints that do not exist — and the list
    # and `GET /jobs/{id}` would disagree about who is waiting, which is the shape of
    # bug that puts a "ready" badge beside a dead machine.
    if arbitrate_blueprint_gate:
        jobs = [
            job for job in jobs
            if resolve_job_artifact(job["job_id"], "blueprint.png", per_job_only=True)
            is not None
        ]
        total = len(jobs)

    return {"jobs": jobs, "total": total, "limit": limit, "offset": offset, "stats": stats}

class SizeHintRequest(BaseModel):
    """A prompt to look for a physical size in."""
    prompt: str = ""


@app.post("/prompt/size-hint")
async def prompt_size_hint(request: SizeHintRequest):
    """Offer the size written in a prompt, so the composer can prefill the control.

    A suggestion and nothing more. It does not touch a job, it does not persist, and
    nothing here can set `target_mm` — the person accepts it and the client sends it
    back with `size_source="prompt_hint"`. Parsing a size and applying it silently
    would put a number on the row that nobody chose.

    Its own endpoint rather than a field on the POST /jobs response because the
    composer calls it while the prompt is being typed; a hint delivered after
    submission could only explain what already happened.

    Args:
        request: The prompt to inspect.

    Returns:
        `{"hint": {...}}` with the size in millimetres, the matched text and its
        span, and the axis the phrasing implies — or `{"hint": None}`.
    """
    hint = parse_size_hint(request.prompt)
    if hint is None:
        return {"hint": None}
    return {"hint": {
        "mm": hint.mm,
        "text": hint.text,
        "span": list(hint.span),
        "axis": hint.axis,
    }}


@app.get("/organizer/boxes")
async def list_game_boxes():
    """The curated box interiors, so the composer can offer them instead of a blank field.

    The launch set of the game-box dimension KB (issue #154). **Curation, not a scrape**:
    it reads one committed JSON file, `pythonsrc/data/game_boxes.v1.json`, and reaches no
    network at all. BoardGameGeek carries external dimensions only, user-entered, in
    inches, behind a registration-gated commercial licence — there is no BGG client in
    this repository and there must not be one.

    Fetched rather than compiled into the client, which is the opposite of what
    `web/src/organizer/spec.ts` does for the archetype strip and the five closed
    vocabularies, and the difference is what each list *is*. Those are the schema's own
    literals, where an option the engine refuses is a fabrication; this is data that grows
    one curated measurement at a time, and a copy of it in TypeScript would be a second
    set of millimetres drifting from the ones a spec is resolved against. A fetch that
    fails degrades to exactly the mode this feature is designed around — a box nobody has
    measured, typed by hand, with `constraints.fit_margin_mm` taken off it.

    Returns:
        `{"version", "boxes": [...]}`. `version` is the KB's content version, the one a
        spec records in `box.kb_version`; each box carries its id, name, kind, publisher,
        the interior in mm and the per-axis provenance sentence behind each number.
    """
    current = game_box_kb()
    return {
        "version": current.version,
        "boxes": [
            {
                "id": entry.id,
                "name": entry.name,
                "kind": entry.kind,
                "publisher": entry.publisher,
                "note": entry.note,
                "interior_mm": list(entry.interior_mm),
                "provenance": entry.provenance(),
            }
            for entry in current.entries
        ],
    }


class SpecResolveRequest(BaseModel):
    """A spec, as the composer has it so far. Deliberately unvalidated by pydantic —
    the schema is the validator, and its refusal is this endpoint's answer.

    The one thing pydantic does still refuse is a `spec` that is not an object at all:
    an omitted key is an empty spec, but an explicit `null` is a 422 rather than a 200
    carrying `schema_valid: false`. Left that way because the composer never sends one
    — `specFromForm` always builds an object — and because "not a spec" and "a spec
    with problems" are different answers, not because the endpoint's own promise of an
    answer for a spec *complete or not* has an exception worth explaining to a caller.
    """
    spec: Dict[str, Any] = Field(default_factory=dict)


@app.post("/organizer/resolve")
async def resolve_organizer_spec(request: SpecResolveRequest):
    """Resolve a spec the way the compiler will, and say what is wrong with it.

    The composer's arithmetic, and the reason it is here rather than in TypeScript:
    **no number may appear on screen that a browser computed.** A stack height is a
    function of the dimension KB (`pythonsrc/organizer/dimensions.py`), and a second
    copy of that table in the client would drift from the one the geometry is built
    from — the same failure as a fits badge with nothing behind it, which is what the
    whole parametric pitch exists to refuse. So the form posts what the person typed
    and renders what comes back, and every millimetre it shows carries the `basis`
    sentence that says where it came from.

    Three things come back, and nothing else is computed here:

    - **the canonical spec and its hash** — what `POST /jobs` would store, so the
      table under the form shows the defaults the schema resolved (an archetype's
      wall, a fit intent's clearance) rather than blanks or client-side guesses;
    - **the resolved stack per card compartment** — `resolve_stack`'s footprint, pitch,
      height and its `basis`. A pocket compartment (`token_tray`) contributes none:
      its millimetres were typed, so there is nothing to resolve and no source to
      name, and the list is empty for a tray rather than carrying a fabricated row;
    - **every problem, with the dotted path it names** — `problems_with_paths`, the
      same shape `POST /jobs`'s 422 carries, so one mapping in the client routes both;
    - **the lettering the spec asks for, measured in millimetres** — the ink the
      vendored font actually sets for `emboss.text` at `emboss.height_mm`, plus a problem
      for any character the font has no glyph for. `pythonsrc/organizer/lettering.py` is
      fontTools and the standard library and nothing else, precisely so this process can
      answer it: a person typing a name into the composer should be told the font cannot
      set it while they are still typing, not after Phase 2 refused the job.

    **What this cannot answer about lettering is whether it fits the face**, and the
    boundary is the same one the fit verdict already sits on: the usable rectangle of a
    lid top or a divider tab is `emboss_frame` on the archetype module, and every
    archetype module imports `manifold3d`. So the width is here and the comparison is
    Phase 2's, with `compile_spec`'s refusal naming the measurement and the cap height
    that would fit. Lifting the face rectangles into a kernel-free table beside the
    metrics is the named follow-up; inventing them here in a second place is not.

    **There is no fit verdict**, and that is not an omission. `deck_box.fits_check`
    imports `manifold3d`, which the api-server image does not install, so this
    process cannot honestly answer "does it fit" — and the only verdict this product
    shows is Phase 3's measurement of the exported mesh anyway.

    The answer is `schema_valid` rather than `valid` for the same reason. Only
    `OrganizerSpec.from_dict` ran: the archetype's own rules — a deck box needs a lid
    section, a divider needs a divider section and no lid, a lip may not be thinner
    than `process.min_feature_mm` — live in modules that import the kernel and are
    enforced in Phase 2. A field called `valid` would claim a check nobody made.

    **A spec the schema refuses is still a 200.** The refusal *is* the answer a
    composer asked for: this endpoint reads nothing, writes nothing and starts
    nothing, and it is called while somebody is still typing, so answering a
    half-built spec with a 4xx would make every keystroke an error in the log and in
    the activity feed. `POST /jobs` is where a bad spec is refused, and it still is.

    Args:
        request: `{"spec": {...}}` — a spec as JSON, complete or not.

    Returns:
        `{"schema_valid", "problems", "spec", "spec_hash", "label", "stacks",
        "game_box", "lettering"}`. When `schema_valid` is false every field but
        `problems` is None or empty. `game_box` is the curated interior the spec named
        and its per-axis provenance, or **None for a box nobody has measured** — the
        degraded mode, where the millimetres are the ones somebody typed and
        `constraints.fit_margin_mm` comes off them just the same. The composer says
        which of the two it used, and this field is how it knows.
    """
    try:
        spec = OrganizerSpec.from_dict(request.spec)
    except SpecError as exc:
        return {
            "schema_valid": False,
            "problems": problems_with_paths(exc.problems),
            "spec": None,
            "spec_hash": None,
            "label": None,
            "stacks": [],
            "game_box": None,
            "lettering": None,
        }

    canonical = spec.to_dict()
    stacks = []
    for compartment in spec.compartments:
        contents = compartment.contents
        # A `Pocket` contributes no stack, and deliberately none: its millimetres were
        # typed, so there is nothing for `resolve_stack` to resolve and no `basis`
        # sentence to print under it. `stacks` is "the card compartments, resolved",
        # not "one entry per compartment" — inventing a row for a pocket would put a
        # figure with no source behind it on the exact readout that exists to carry one.
        if not isinstance(contents, CardStack):
            continue
        stack = resolve_stack(contents.count, contents.card, contents.sleeving)
        stacks.append({
            "count": stack.count,
            "card": stack.card,
            "sleeving": stack.sleeving,
            "footprint_w_mm": stack.footprint_w_mm,
            "footprint_h_mm": stack.footprint_h_mm,
            "pitch_mm": stack.pitch_mm,
            "stack_height_mm": stack.stack_height_mm,
            "basis": stack.basis,
        })

    lettering_problems = []
    lettering_info = None
    if spec.emboss is not None:
        lettering_problems = organizer_lettering.text_problems(
            spec.emboss.text, "spec.emboss.text"
        )
        if not lettering_problems:
            ink_w, ink_h = organizer_lettering.ink_extent_mm(
                spec.emboss.text, spec.emboss.height_mm
            )
            lettering_info = {
                "text": spec.emboss.text,
                "face": spec.emboss.face,
                "mode": spec.emboss.mode,
                "height_mm": spec.emboss.height_mm,
                "ink_width_mm": round(ink_w, 3),
                "ink_height_mm": round(ink_h, 3),
                "font": f"{organizer_lettering.FONT_FAMILY} {organizer_lettering.FONT_SUBFAMILY}",
            }

    return {
        # Still true: the schema accepted the spec. A missing glyph is a *lettering*
        # problem, reported beside the schema's own in the one list the client routes,
        # and it is not the schema's finding to claim.
        "schema_valid": True,
        "problems": problems_with_paths(lettering_problems),
        "spec": canonical,
        "spec_hash": spec_hash(spec),
        # What the job would be called if nobody types a line. See `spec_label`.
        "label": spec_label(canonical),
        "stacks": stacks,
        # None when no box was named, which is the honest answer and not an omission:
        # the interior is then three millimetres somebody typed, and there is no source
        # to print under them. `game_box_record` is the same function that writes the
        # row on `generation_params`, so the screen and the database cannot describe one
        # box two different ways.
        "game_box": game_box_record(spec),
        "lettering": lettering_info,
    }


@app.get("/health")
@public
async def health_check():
    """Health check endpoint.

    One of the two routes reachable without the shared secret: it is polled by things
    that hold no credential — a container healthcheck, a load balancer — and it reads
    no database, spends nothing and touches no printer. See `server/auth.py`.

    `database` reports the verdict of the most recent health check rather than
    making a round trip to Supabase: this endpoint is polled, and a database that
    has gone away would otherwise hold every poll for the pool timeout. The check
    runs at startup and every `$DS_DB_HEALTH_INTERVAL_S` seconds; `checked_at` says
    how old the verdict is. A degraded database is still reported by a server that
    answers — the server does work, it is the data underneath that is not being
    kept — so the caller gets the problems and decides.
    """
    strategy = get_resolved_strategy()
    detected = get_execution_strategy()
    return {
        "status": "ok" if not database_problems else "degraded",
        "version": app.version,
        "execution_strategy": strategy,
        "detected_strategy": detected,
        "database": {
            "healthy": not database_problems,
            "problems": database_problems,
            "checked_at": database_checked_at.isoformat() if database_checked_at else None,
        },
    }

@app.get("/jobs/{job_id}/telemetry")
async def get_job_telemetry(job_id: str) -> List[Dict[str, Any]]:
    """Retrieve telemetry samples for a specific print job.

    Args:
        job_id: The unique identifier of the job.

    Returns:
        A list of up to 100 recent telemetry samples as dictionaries.

    Raises:
        HTTPException: If the job is not found.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    if not job:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")

    samples = db.get_samples(job_id, limit=100)
    db.close()
    return [s.to_dict() for s in samples]

class FailureRequest(BaseModel):
    """Pydantic model representing a manual failure event report."""
    failure_type: str
    notes: Optional[str] = None

@app.get("/jobs/{job_id}/printability")
async def get_job_printability(job_id: str):
    """Return the pre-print printability report for a job.

    Args:
        job_id: The job whose report is wanted.

    Returns:
        The report as produced by `PrintabilityReport.to_dict()`.

    Raises:
        HTTPException: 404 if the job is unknown, or if it has no report — a job that
            never reached the Engineer has nothing to score.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.printability_report:
        return job.printability_report

    # Jobs run before the report was persisted still have the artifact on disk.
    report_path = resolve_job_artifact(job_id, "printability.json")
    if report_path is not None:
        try:
            with open(report_path, "r") as f:
                return json.load(f)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not read printability report for {job_id}: {exc}")

    raise HTTPException(status_code=404, detail="No printability report for this job yet")

@app.post("/jobs/{job_id}/failure")
async def create_failure_event(job_id: str, request: FailureRequest) -> Dict[str, Any]:
    """Manually flag a print job as failed.

    Args:
        job_id: The unique identifier of the job.
        request: The failure details and notes.

    Returns:
        A dictionary representation of the recorded FailureEvent.
    """
    db = TelemetryDB()
    try:
        if not db.get_job(job_id):
            raise HTTPException(status_code=404, detail="Job not found")
        samples = db.get_samples(job_id, limit=50)

        event_id = str(uuid.uuid4())
        event = FailureEvent(
            event_id=event_id,
            job_id=job_id,
            detected_at=datetime.now(timezone.utc),
            # get_samples returns oldest-first; the failure happened at the newest.
            # samples[0] here recorded a Z from the very start of the print.
            gcode_line=samples[-1].gcode_line if samples else None,
            z_height_mm=samples[-1].z_height_mm if samples else None,
            failure_type=request.failure_type,
            source="manual",
            notes=request.notes,
            snapshot=[s.to_dict() for s in samples]
        )
        db.insert_failure_event(event)
    finally:
        db.close()
    return event.to_dict()

@app.get("/jobs/{job_id}/failure")
async def get_failure_events(job_id: str) -> List[Dict[str, Any]]:
    """Retrieve failure events for a job.

    Args:
        job_id: The unique identifier of the job.

    Returns:
        A list of FailureEvent dictionaries.
    """
    db = TelemetryDB()
    events = db.get_failure_events(job_id)
    db.close()
    return [e.to_dict() for e in events]

@app.get("/jobs/{job_id}/provenance")
async def get_job_provenance(job_id: str) -> Dict[str, Any]:
    """Return everything captured about how a job's result was produced.

    Kept off `GET /jobs/{id}`, which is polled by the UI on a timer and would otherwise
    carry a large payload on every tick. This is the endpoint to read when analysing
    the pilot dataset.

    Args:
        job_id: The unique identifier of the job.

    Returns:
        A dictionary of blueprint, mesh, slice, target and engagement facts.

    Raises:
        HTTPException: If the job is not found.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    if not job:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")
    events = db.get_job_events(job_id)
    db.close()

    return {
        "job_id": job.job_id,
        "prompt": job.prompt,
        "blueprint": {
            "model": job.blueprint_model,
            "model_version": job.blueprint_model_version,
            "seed": job.blueprint_seed,
            "prompt_engineered": job.blueprint_prompt_engineered,
            "params": job.blueprint_params,
            "sha256": job.blueprint_sha256,
            "duration_s": job.blueprint_duration_s,
        },
        "generation": {
            "model": job.generation_model,
            "model_version": job.generation_model_version,
            "backend": job.generation_backend,
            "params": job.generation_params,
            "cost_eur": job.generation_cost_eur,
            "duration_s": job.generation_duration_s,
        },
        "mesh": {
            "raw_sha256": job.raw_mesh_sha256,
            "raw_features": job.raw_mesh_features,
            "repaired_sha256": job.repaired_mesh_sha256,
            "repaired_features": job.repaired_mesh_features,
            "printed_features": job.mesh_features,
        },
        "printability": {
            "score": job.printability_score,
            "verdict": job.printability_verdict,
        },
        "slice": {
            "status": job.slice_status,
            "error": job.slice_error,
            "duration_s": job.slice_duration_s,
            "estimated_print_time_s": job.estimated_print_time_s,
            "filament_used_mm": job.filament_used_mm,
            "filament_used_mm3": job.filament_used_mm3,
            "filament_used_g": job.filament_used_g,
            "support_filament_mm3": job.support_filament_mm3,
            "layer_count": job.layer_count,
            "stats": job.slice_stats,
        },
        "target": {
            "printer_id": job.printer_id,
            "printer_firmware": job.printer_firmware,
            "profile_name": job.profile_name,
            "process_params": job.process_params,
            "nozzle_diameter_mm": job.nozzle_diameter_mm,
            "material_type": job.material_type,
            "material_brand": job.material_brand,
            "material_colour": job.material_colour,
        },
        "engagement": {
            "download_count": job.download_count or 0,
            "parent_job_id": job.parent_job_id,
            "regeneration_reason": job.regeneration_reason,
            "events": [e.to_dict() for e in events],
        },
        "outcome": {
            "outcome": job.outcome,
            "source": job.outcome_source,
            "reported_at": job.outcome_reported_at.isoformat() if job.outcome_reported_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            # Evidence rather than verdict, and reported as such: a row can carry a
            # photo and no outcome, which is a person who looked and did not answer.
            "fit_photo_path": job.fit_photo_path,
        },
    }


#: The artifacts a spec run writes into its job directory, and the key each is served
#: under by `GET /jobs/{id}/spec`. `spec.json` is deliberately absent: the canonical
#: spec comes off the row (see `job_spec_summary`), and reading the file as well would
#: give one response two answers to the same question.
#:
#: `view.json` — the annotated preview's frame and dimension lines, from
#: `archetypes.view_for` — is written by Phase 2 and served here (issue #88). It is not
#: derived on demand and cannot be: this image carries no geometry kernel.
SPEC_ARTIFACTS = {
    "compile_features": "compile_features.json",
    "dimension_report": "dimension_report.json",
    "view": "view.json",
}


@app.get("/jobs/{job_id}/spec")
async def get_job_spec(job_id: str) -> Dict[str, Any]:
    """Everything the parametric path recorded about one job.

    The un-polled sibling of `GET /jobs/{id}`, on the `/provenance` precedent. The
    detail endpoint carries the four values the spec panel and the Fits Check render
    on every tick; this one adds the three documents that are read once and are far
    larger — `compile_features.json` (every designed dimension the compiler produced),
    `dimension_report.json` (every one of them measured back off the exported mesh,
    with its error) and `view.json` (the labelled table the composer renders, plus the
    frame and dimension lines the annotated preview draws). Putting those on the polled
    endpoint would send a few kilobytes of unchanging JSON every second for the whole
    of a job's life.

    Args:
        job_id: The unique identifier of the job.

    Returns:
        The summary from `job_spec_summary` plus a `compile_features`, a
        `dimension_report` and a `view` key, each None until the phase that writes it
        has run.

    Raises:
        HTTPException: 404 if the job does not exist, or if it has no spec — a
            prompt job has nothing to serve here, and an empty 200 would read as
            "compiled, and every number is missing".
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    summary = job_spec_summary(job)
    if summary["spec"] is None:
        raise HTTPException(status_code=404, detail="Job has no spec")

    documents: Dict[str, Any] = {}
    for key, filename in SPEC_ARTIFACTS.items():
        documents[key] = None
        artifact = resolve_job_artifact(job.job_id, filename)
        if artifact is None:
            continue
        try:
            documents[key] = json.loads(artifact.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — an unreadable artifact is not a 500
            logger.warning("Could not read %s for %s: %s", filename, job.job_id, exc)

    return {"job_id": job.job_id, **summary, **documents}


# ── Print outcome feedback ────────────────────────────────────────────────────
# The signal nothing else can supply. A printer reporting "job finished" says only
# that the file ran to the end; whether the part survived, adhered and came off the
# bed intact is knowable only by the person standing next to it. Everything below
# exists to make saying so take one tap, and to measure how often people bother.

@app.get("/feedback/pending")
async def list_pending_feedback(limit: int = 50) -> Dict[str, Any]:
    """List prints whose outcome no human has confirmed yet.

    Args:
        limit: Maximum number of jobs to return.

    Returns:
        A dictionary with the pending jobs and a count.
    """
    db = TelemetryDB()
    jobs = db.get_jobs_awaiting_verdict(limit=limit)
    db.close()

    return {
        "count": len(jobs),
        "jobs": [
            {
                "job_id": job.job_id,
                "prompt": job.prompt,
                "printer_id": job.printer_id,
                "material_type": job.material_type,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "estimated_print_time_s": job.estimated_print_time_s,
                "printability_score": job.printability_score,
            }
            for job in jobs
        ],
    }


@app.post("/jobs/{job_id}/outcome/prompt-shown")
async def record_outcome_prompt_shown(job_id: str) -> Dict[str, Any]:
    """Record that the outcome prompt was actually put in front of someone.

    Called by the UI when a pending card first renders. Logged once per job — the
    denominator of the pilot's response rate has to be prompts a person saw, not jobs
    that entered the queue, and a re-render or a page refresh must not inflate it.

    Args:
        job_id: The unique identifier of the job.

    Returns:
        A dictionary reporting whether a new event was recorded.

    Raises:
        HTTPException: If the job is not found.
    """
    db = TelemetryDB()
    if not db.get_job(job_id):
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")

    already = db.get_job_events(job_id, kind="outcome_prompt_shown")
    if already:
        db.close()
        return {"recorded": False, "reason": "already shown"}

    db.record_job_event(job_id, "outcome_prompt_shown")
    db.close()
    return {"recorded": True}


# ── Activation capture ───────────────────────────────────────────────────────
# The other half of the pilot's headline pair. "≥ 60 % of prompt submitters reach a
# preview" (PRD §7) had a denominator — every job carries a prompt — and no numerator
# at all: nothing in the system recorded that a person ever saw the geometry they
# asked for. Same shape as `prompt-shown` deliberately, dedup included.

@app.post("/jobs/{job_id}/events/preview-reached")
async def record_preview_reached(job_id: str) -> Dict[str, Any]:
    """Record that the mesh or the toolpath was actually put on screen for this job.

    Called by the running view when it first shows either artifact. Logged once per
    job: the activation rate counts people who got a preview, so a reload, a tab
    switch between the mesh and the toolpath, or a second visit two days later must
    not each count again. Deduplicated here rather than only in the client, because a
    fresh page has a fresh memory of what it has already sent.

    Args:
        job_id: The unique identifier of the job.

    Returns:
        A dictionary reporting whether a new event was recorded.

    Raises:
        HTTPException: If the job is not found.
    """
    db = TelemetryDB()
    if not db.get_job(job_id):
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")

    if db.get_job_events(job_id, kind="preview_reached"):
        db.close()
        return {"recorded": False, "reason": "already reached"}

    db.record_job_event(job_id, "preview_reached")
    db.close()
    return {"recorded": True}


@app.post("/jobs/{job_id}/outcome/dismiss")
async def dismiss_outcome_prompt(job_id: str) -> Dict[str, Any]:
    """Record that someone was asked for a verdict and chose not to give one.

    A skip is data. Whether pilot users will report outcomes at all is the thing being
    tested, so a declined prompt has to be distinguishable from one never shown. The
    job stays in `awaiting_verdict` and can still be answered later.

    Args:
        job_id: The unique identifier of the job.

    Returns:
        A dictionary confirming the dismissal was recorded.

    Raises:
        HTTPException: If the job is not found.
    """
    db = TelemetryDB()
    if not db.get_job(job_id):
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")
    db.record_job_event(job_id, "outcome_prompt_dismissed")
    db.close()
    return {"recorded": True}


@app.post("/jobs/{job_id}/outcome")
async def report_outcome(job_id: str, request: OutcomeRequest) -> Dict[str, Any]:
    """Record a human's verdict on whether a print succeeded.

    Writes `outcome_source="user"`, which is what separates ground truth from the
    printer's own report. A failure verdict also writes a manual `FailureEvent`, so the
    existing detector-versus-human comparison keeps working without a second code path.

    Args:
        job_id: The unique identifier of the job.
        request: The verdict, plus optional failure details.

    Returns:
        A dictionary with the recorded outcome.

    Raises:
        HTTPException: If the job is not found.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    if not job:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")

    db.update_job_outcome_verdict(job_id, request.verdict, source="user")

    failure_event = None
    if request.verdict == "failure":
        samples = db.get_samples(job_id, limit=50)
        failure_event = FailureEvent(
            event_id=str(uuid.uuid4()),
            job_id=job_id,
            detected_at=datetime.now(timezone.utc),
            # get_samples returns oldest-first; the failure happened at the newest.
            gcode_line=samples[-1].gcode_line if samples else None,
            z_height_mm=samples[-1].z_height_mm if samples else None,
            failure_type=request.failure_type or "unknown",
            source="manual",
            notes=request.notes,
            snapshot=[s.to_dict() for s in samples],
        )
        db.insert_failure_event(failure_event)

    db.record_job_event(job_id, "outcome_reported", {
        "verdict": request.verdict,
        "failure_type": request.failure_type,
        "layer_pct": request.layer_pct,
    })
    db.close()

    activity.action(
        "outcome reported by user",
        [
            ("job", job_id[:8]),
            ("verdict", request.verdict),
            ("failure", request.failure_type),
            ("at layer", f"{request.layer_pct}%" if request.layer_pct is not None else None),
        ],
        # Worth saying out loud: this is the one write a later machine event cannot
        # overturn, which is exactly why it is the label worth having.
        outcome="recorded as ground truth — machine events cannot overwrite it",
        status="ok" if request.verdict == "success" else "warn",
    )

    await broadcaster.broadcast(job_id, {
        "type": "job_complete",
        "data": {"outcome": request.verdict, "outcome_source": "user"},
    })

    return {
        "job_id": job_id,
        "outcome": request.verdict,
        "outcome_source": "user",
        "failure_event_id": failure_event.event_id if failure_event else None,
    }


# ── The fit photo ────────────────────────────────────────────────────────────
# "Does it fit?" is the question the whole parametric pivot turns on, and until now
# the only answer the system could hold was one word. A photograph of the tray with
# the cards in it is the evidence behind that word — and on a phone it costs one tap,
# because `capture="environment"` opens the rear camera directly.
#
# The body is the image itself, not a multipart form. `python-multipart` is not in the
# api-server image's package list (`infra/docker/server.Dockerfile`), and FastAPI
# raises at import when a route declares an `UploadFile` without it — so a multipart
# route would pass CI, where the requirements file installs it, and take the server
# down on the box that matters. A raw body needs no dependency, no SBOM entry and no
# Dockerfile change.

@app.post("/jobs/{job_id}/photo")
async def upload_fit_photo(job_id: str, request: Request) -> Dict[str, Any]:
    """Store a photo of the printed part.

    Authenticated by writing nothing: the shared-secret middleware refuses everything
    that is not marked `@public`, and this is not.

    The order of the checks is the design. The job is looked up before a single byte is
    read, so an unknown — or traversing — `job_id` is a 404 that never reaches a path
    join; the declared length is refused before the body arrives; and the stream is
    counted as it is consumed, because `Content-Length` is a claim and a chunked body
    makes none at all. A re-upload replaces the previous photo, including one stored
    under a different suffix: one part, one picture.

    Args:
        job_id: The job the photo is of.
        request: The raw request; its body is the image bytes.

    Returns:
        The stored repo-relative path, the byte count and the content type.

    Raises:
        HTTPException: 404 if the job does not exist, 415 if the type is not one of
            the three accepted or the bytes are not what the header claims, 413 if
            the body exceeds `FIT_PHOTO_MAX_BYTES`, 400 if the body is empty or the
            path join escapes `data/outputs`.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    if not job:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")

    accepted = ", ".join(sorted(FIT_PHOTO_TYPES))
    declared = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if declared not in FIT_PHOTO_TYPES:
        db.close()
        raise HTTPException(
            status_code=415,
            detail=f"Send the image as {accepted}, not {declared or 'an unlabelled body'}.",
        )

    # A declared length over the cap is refused here, before the body is transferred.
    length = request.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > FIT_PHOTO_MAX_BYTES:
        db.close()
        raise HTTPException(
            status_code=413,
            detail=f"The photo is larger than {FIT_PHOTO_MAX_BYTES // (1024 * 1024)} MB.",
        )

    # And counted again while it arrives, because a chunked body declares nothing and
    # uvicorn caps nothing. This is the check that actually bounds the disk.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > FIT_PHOTO_MAX_BYTES:
            db.close()
            raise HTTPException(
                status_code=413,
                detail=f"The photo is larger than {FIT_PHOTO_MAX_BYTES // (1024 * 1024)} MB.",
            )

    if not body:
        db.close()
        raise HTTPException(status_code=400, detail="The request body was empty.")

    if sniff_image_type(bytes(body[:12])) != declared:
        db.close()
        raise HTTPException(
            status_code=415,
            detail=f"Those bytes are not {declared}. Accepted: {accepted}.",
        )

    suffix = FIT_PHOTO_TYPES[declared]
    target = fit_photo_target(job_id, suffix)
    if target is None:
        db.close()
        raise HTTPException(status_code=400, detail="Invalid job id")

    target.parent.mkdir(parents=True, exist_ok=True)
    # Written beside the target and moved into place, so a connection that dies
    # halfway leaves no half-photo for the row to point at.
    staging = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
    try:
        staging.write_bytes(body)
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)

    # One photo per job: a JPEG replacing a PNG must not leave the PNG behind, because
    # the row can only point at one of them and the other would be an orphan nobody
    # ever looks at again.
    for other in FIT_PHOTO_TYPES.values():
        if other == suffix:
            continue
        stale = fit_photo_target(job_id, other)
        if stale is not None:
            stale.unlink(missing_ok=True)

    relative = target.relative_to(DATA_DIR.resolve().parent).as_posix()
    # `update_job_fit_photo`, never `update_job_outcome_verdict`: a photo is evidence,
    # not a verdict. The job stays `awaiting_verdict` until a person says a word.
    db.update_job_fit_photo(job_id, relative)
    db.close()

    activity.action(
        "fit photo stored",
        [
            ("job", job_id[:8]),
            ("type", declared),
            ("size", f"{len(body) / 1024:.0f} kB"),
        ],
        outcome=f"written to {relative}",
        status="ok",
    )

    return {
        "job_id": job_id,
        "fit_photo_path": relative,
        "bytes": len(body),
        "content_type": declared,
    }


@app.get("/jobs/{job_id}/photo")
async def get_fit_photo(job_id: str) -> FileResponse:
    """Serve the stored fit photo.

    Args:
        job_id: The job whose photo is wanted.

    Returns:
        The image, inline, with the media type its stored suffix implies.

    Raises:
        HTTPException: 404 if the job does not exist or has no photo.
    """
    db = TelemetryDB()
    job = db.get_job(job_id)
    db.close()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    path = fit_photo_on_disk(job)
    if path is None:
        raise HTTPException(status_code=404, detail="No photo for this job")

    media_type = next(
        (t for t, s in FIT_PHOTO_TYPES.items() if s == path.suffix), "application/octet-stream"
    )
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{path.name}"'},
    )


@app.get("/feedback/stats")
async def feedback_stats() -> Dict[str, Any]:
    """Report how often outcome prompts are actually answered, and the activation rate.

    The pilot's headline numbers. The response rate is counted over jobs that were
    prompted, so a job nobody has been shown yet neither helps nor hurts the rate, and
    a verdict volunteered without a prompt cannot push it above 1. The activation rate
    is counted the same way, over jobs rather than events: previews reached over
    prompts submitted (PRD §7).

    Returns:
        Funnel counts, raw event totals and the two derived rates.
    """
    db = TelemetryDB()
    funnel = db.feedback_funnel()
    activation = db.activation_funnel()
    reported_total = db.count_job_events("outcome_reported")
    pending = len(db.get_jobs_awaiting_verdict(limit=1000))
    db.close()

    submitted = activation["submitted"]
    prompted = funnel["prompted"]
    return {
        # Activation (PRD §7). Both halves over jobs: every job row is one prompt
        # submission, and `preview_reached` is deduplicated per job at the endpoint,
        # so the ratio cannot exceed 1 however many times a preview is looked at.
        # Named `jobs_submitted` rather than `prompts_submitted` because
        # `prompts_shown` two lines down counts *outcome* prompts, and a metric whose
        # denominator can be misread for another metric's is worse than a long name.
        "jobs_submitted": submitted,
        "previews_reached": activation["previewed"],
        "activation_rate": (
            round(activation["previewed"] / submitted, 4) if submitted else None
        ),
        "prompts_shown": prompted,
        "outcomes_reported": funnel["answered"],
        # An explicit "don't ask me again". A response, but not an answer about a
        # part — kept out of the response rate and reported on its own.
        "declined": funnel["declined"],
        "prompts_dismissed": funnel["dismissed"],
        "unanswered": funnel["unanswered"],
        # Includes verdicts given without a prompt, e.g. straight from a job page.
        "outcomes_reported_total": reported_total,
        "pending": pending,
        "response_rate": round(funnel["answered"] / prompted, 4) if prompted else None,
    }


# ── Web push ─────────────────────────────────────────────────────────────────
#
# See `server/push.py` for why this is a reconciler rather than three hooks, and why
# `push_sent` is the dedup key. These three routes are the whole HTTP surface: the key
# a browser needs to subscribe, and the two halves of a subscription's life.
#
# Authenticated by writing nothing — no `@public`, no third exemption in
# `tests/test_api_auth.py`. That matters more here than it looks: a subscription is an
# address this server will POST to, so an unauthenticated `POST /push/subscriptions`
# would let anyone who can reach the port aim it at a host of their choosing. It is the
# same shape as the `OCTOPRINT_URL` confused deputy, and it is closed the same way —
# except that there is no credential to bind, so the token is the whole answer.


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionRequest(BaseModel):
    """What `PushSubscription.toJSON()` hands back, field for field."""

    endpoint: str
    keys: PushSubscriptionKeys


class PushUnsubscribeRequest(BaseModel):
    endpoint: str


def _valid_push_endpoint(endpoint: str) -> bool:
    """Whether this is an address a push service could plausibly have issued.

    `https` and a host, nothing more. Every push service on the web is HTTPS, and the
    check is here because this endpoint is the one thing that tells the server where to
    send: a typo stored now is a delivery that fails silently in an hour, and a scheme
    like `file:` is not a typo at all.
    """
    parsed = urlparse(endpoint)
    return parsed.scheme == "https" and bool(parsed.netloc)


@app.get("/push/vapid-public-key")
async def push_vapid_public_key() -> Dict[str, Any]:
    """The application server key a browser needs before it can subscribe.

    Generated on first call and kept in the encrypted store — there is nothing for a
    person to type, and the private half it is generated with never leaves this
    process. A browser that holds a subscription made against an older key gets a
    different value here, which is exactly what tells the page to subscribe again.
    """
    public, _ = push.ensure_vapid_keys(config_store)
    return {"public_key": public}


@app.post("/push/subscriptions", status_code=status.HTTP_201_CREATED)
async def create_push_subscription(
    request: PushSubscriptionRequest, http_request: Request
) -> Dict[str, Any]:
    """Remember a device that has asked to be told when a print finishes.

    An upsert, because the browser hands the page the subscription it already has on
    every load: a plain insert would grow a row per visit for a device that subscribed
    once. The user agent rides along so a row in the table can be recognised as a
    phone rather than as an opaque URL.
    """
    if not _valid_push_endpoint(request.endpoint):
        raise HTTPException(
            status_code=422,
            detail="A push endpoint must be an https URL issued by a push service.",
        )

    db = TelemetryDB()
    try:
        db.upsert_push_subscription(
            endpoint=request.endpoint,
            p256dh=request.keys.p256dh,
            auth=request.keys.auth,
            user_agent=http_request.headers.get("user-agent"),
        )
        total = len(db.get_push_subscriptions())
    finally:
        db.close()

    activity.action(
        "push subscription saved",
        [("endpoint", request.endpoint[:60] + "…" if len(request.endpoint) > 60 else request.endpoint)],
        outcome=f"{total} device(s) will be told when a print finishes",
        status="ok",
    )
    return {"status": "subscribed", "subscriptions": total}


@app.delete("/push/subscriptions")
async def remove_push_subscription(request: PushUnsubscribeRequest) -> Dict[str, Any]:
    """Forget a device.

    Deleting something that is not there is a success, not a 404: the page calls this
    when a person turns notifications off, and a browser that had already dropped the
    subscription would otherwise leave the switch stuck on.
    """
    db = TelemetryDB()
    try:
        removed = db.delete_push_subscription(request.endpoint)
        total = len(db.get_push_subscriptions())
    finally:
        db.close()

    if removed:
        activity.action(
            "push subscription removed",
            [("remaining", str(total))],
            outcome="that device will not be told again",
            status="warn",
        )
    return {"status": "unsubscribed", "removed": removed, "subscriptions": total}


class ConfigUpdate(BaseModel):
    key: str
    value: str

class TestConnectionRequest(BaseModel):
    service: str

def host_binding(key: str, read) -> Optional[Dict[str, Any]]:
    """How a printer credential stands against the address configured for it.

    The extra step the binding introduces is only fair if the person can see it, so
    Settings is told which host the stored key belongs to, which host it would be
    sent to, and whether it will go. Without that, a key that was saved and is not
    being used looks exactly like a key that was never saved.

    Args:
        key: A config key; anything that is not a printer credential answers None.
        read: How to read a stored value — `stored.get` for an already-read store.

    Returns:
        `{"bound_to", "target", "sends", "message"}`, or None for every other key.
    """
    if key not in PRINTER_CREDENTIAL_HOSTS:
        return None
    credential = bound_printer_credential(key, read)
    return {
        "bound_to": credential.bound_host,
        "target": credential.target_host,
        "sends": credential.value is not None,
        "message": credential.reason,
    }


@app.get("/config")
async def get_config():
    """Get all configuration keys with their values and metadata.

    `INTERNAL_CONFIG_KEYS` are left out: they are the store's own bookkeeping, they
    are not editable here, and listing them would put three rows on the Settings page
    that a person can only be confused by.
    """
    stored = config_store.get_all()
    results = {}
    for key, meta in CONFIG_KEYS.items():
        if key in INTERNAL_CONFIG_KEYS:
            continue
        val = stored.get(key)
        is_set = val is not None

        display_val = None
        if is_set:
            display_val = "••••••••" if meta.get("secret") else val

        results[key] = {
            "value": display_val,
            "is_set": is_set,
            "label": meta.get("label"),
            "description": meta.get("description"),
            "required": meta.get("required"),
            "secret": meta.get("secret"),
            "host_binding": host_binding(key, stored.get),
        }
    return results

@app.post("/config")
async def update_config(update: ConfigUpdate):
    """Update a configuration value."""
    if update.key not in CONFIG_KEYS or update.key in INTERNAL_CONFIG_KEYS:
        # A writable `OCTOPRINT_API_KEY_HOST` would undo the whole binding in one
        # request, so the internal keys are as invalid here as an unknown one.
        raise HTTPException(status_code=400, detail="Invalid config key")

    meta = CONFIG_KEYS[update.key]
    secret = bool(meta.get("secret"))
    # Read the old value before overwriting it: "what changed" is the question anyone
    # debugging a configuration has, and it is unanswerable after the write.
    previous = config_store.get(update.key)

    # The store only. This handler used to write `os.environ[update.key]` as well, and
    # both subprocess launches copied that environment wholesale — so an
    # unauthenticated request set a variable in every pipeline container and every
    # operator this server spawns. Readers take the value from the store instead:
    # `config_store.get()` in this process, `subprocess_env()` at a launch.
    config_store.set(update.key, update.value)

    display_val = "••••••••" if secret else update.value
    # A secret's *value* never reaches the log; whether it went from unset to set does,
    # because that is the fact that explains a connection starting to work.
    activity.action(
        "config changed",
        [
            ("key", update.key),
            ("from", "••••••••" if (secret and previous) else (previous or "(unset)")),
            ("to", display_val),
        ],
        outcome="saved, encrypted at rest; live for the next request",
        status="ok",
    )

    return {
        "key": update.key,
        "value": display_val,
        "is_set": True,
        "label": meta.get("label"),
        "description": meta.get("description"),
        "required": meta.get("required"),
        "secret": meta.get("secret"),
        # Saving a key re-binds it, so the answer here is the one the page must show.
        "host_binding": host_binding(update.key, config_store.get),
    }

@app.delete("/config/{key}")
async def delete_config(key: str):
    """Delete a configuration value."""
    if key not in CONFIG_KEYS or key in INTERNAL_CONFIG_KEYS:
        raise HTTPException(status_code=400, detail="Invalid config key")

    # The store only, matching the write path above: nothing this endpoint set is in
    # `os.environ` any more, and deleting a key from there would clear a value that
    # came from `.env` and that the store never owned.
    config_store.delete(key)

    activity.action(
        "config cleared",
        [("key", key)],
        outcome="removed from the store",
        status="warn",
    )
    return {"status": "success", "key": key}

@app.get("/config/{key}/reveal")
async def reveal_config(key: str):
    """Reveal a secret configuration value."""
    if key not in CONFIG_KEYS or key in INTERNAL_CONFIG_KEYS:
        raise HTTPException(status_code=400, detail="Invalid config key")

    val = config_store.get(key)
    if val is None:
        raise HTTPException(status_code=404, detail="Config key not set")

    return {"key": key, "value": val}

@app.post("/config/test-connection")
async def test_connection(req: TestConnectionRequest):
    """Test connection to a specific service.

    The probe is the one request whose *whole job* is to be sent at whatever address
    is stored right now, which is what made it the lever: change `OCTOPRINT_URL`, ask
    for a test, and the server posted the real key to the new host. So the key goes
    out only when it is bound to that host, the probe still runs without it when it
    is not, and `withheld` is the sentence saying why — a keyless probe that silently
    401s would read as a wrong key and send someone to re-type a correct one.
    """
    service = req.service.lower()
    if service == "klipper":
        # The UI sends firmware names; Moonraker is the HTTP API fronting Klipper.
        # Same alias PrinterFactory accepts — without it every Klipper printer
        # reads "Offline" forever.
        service = "moonraker"
    stored = config_store.get_all()

    # Set when the stored key is bound to another host, and appended to whatever this
    # probe ends up saying.
    withheld: str | None = None

    import time
    start_time = time.time()

    def answer(success: bool, message: str, latency_ms: int | None = None) -> dict:
        """One exit, so the withholding is reported on every outcome and not just one."""
        if withheld:
            message = f"{message} · {withheld}"
        return {"success": success, "message": message, "latency_ms": latency_ms}

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            if service == "octoprint":
                url = stored.get("OCTOPRINT_URL")
                if not url:
                    return answer(False, "OCTOPRINT_URL not configured")
                credential = printer_credential("octoprint", stored.get)
                withheld = credential.reason
                # Opening a connection, so this is the one place the loopback address
                # has to be read from where this process actually stands.
                url = container_reachable_url(url)

                headers = {}
                if credential.value:
                    headers["X-Api-Key"] = credential.value

                resp = await client.get(f"{url.rstrip('/')}/api/version", headers=headers)
                resp.raise_for_status()

            elif service == "moonraker":
                url = stored.get("MOONRAKER_URL")
                if not url:
                    return answer(False, "MOONRAKER_URL not configured")
                credential = printer_credential("moonraker", stored.get)
                withheld = credential.reason
                url = container_reachable_url(url)

                # Moonraker takes the same header OctoPrint does when its
                # authorization component is configured. The probe used to send
                # nothing at all, so a secured Moonraker read Offline forever.
                headers = {}
                if credential.value:
                    headers["X-Api-Key"] = credential.value

                resp = await client.get(f"{url.rstrip('/')}/printer/info", headers=headers)
                resp.raise_for_status()

            elif service == "bambu":
                # Bambu speaks MQTT over TLS on 8883 in LAN mode, so there is no HTTP
                # endpoint to GET — which is why this branch does not look like the two
                # above it.
                host = stored.get("BAMBU_IP")
                if not host:
                    return answer(False, "BAMBU_IP not configured")
                credential = printer_credential("bambu", stored.get)
                if not credential.stored:
                    return answer(
                        False,
                        "No LAN access code yet — find it on the printer under "
                        "Settings → Network.",
                    )
                if credential.withheld:
                    # Nothing is sent on this probe either way, so there is no keyless
                    # connect worth making: the code cannot authenticate a print to
                    # this address, and that is the whole answer.
                    return answer(False, credential.reason)

                # A real authentication check, not a TCP connect. This used to open a
                # socket to 8883 and report reachability, which proved the printer was
                # on the network and said nothing about the access code — so a wrong
                # code passed the connection test and failed at dispatch, which is the
                # worst place to find out. `check_credentials` reads the MQTT CONNACK,
                # which is the only thing that carries the authentication result, and
                # needs no serial: a person setting a printer up has typed an address
                # and a code and wants to hear whether those two are right.
                operator = BambuOperator(host, credential.value)
                try:
                    await asyncio.to_thread(operator.check_credentials)
                except PrinterConnectionError as exc:
                    # `BambuOperator` phrases these for a person and distinguishes
                    # refused-code from unreachable; repeating that here in other words
                    # is how the two drift apart.
                    return answer(False, str(exc))

                return answer(
                    True,
                    f"{host} accepted the LAN access code on port 8883.",
                    int((time.time() - start_time) * 1000),
                )

            elif service == "huggingface":
                token = stored.get("HF_TOKEN")
                if not token:
                    return answer(False, "HF_TOKEN not configured")

                headers = {"Authorization": f"Bearer {token}"}
                resp = await client.get("https://huggingface.co/api/whoami-v2", headers=headers)
                resp.raise_for_status()

            else:
                raise HTTPException(status_code=400, detail="Invalid service")

            return answer(True, "Connection successful", int((time.time() - start_time) * 1000))

        except httpx.TimeoutException:
            return answer(False, "Connection timed out")
        except httpx.RequestError as e:
            return answer(False, f"Connection failed: {str(e)}")
        except httpx.HTTPStatusError as e:
            if service == "huggingface" and e.response.status_code == 401:
                return answer(False, "Invalid HuggingFace Token")
            # A 401/403 means we reached the printer and it refused us — the opposite
            # diagnosis from "unreachable", and the fix is a key rather than a cable.
            # Dumping the raw body here surfaced OctoPrint's stock Flask 403 page
            # ("You don't have the permission to access the requested resource"),
            # which names neither the printer nor the credential and sent people
            # looking at their network.
            if e.response.status_code in (401, 403):
                where = {
                    "octoprint": "OCTOPRINT_API_KEY",
                    "moonraker": "MOONRAKER_API_KEY",
                }.get(service, "the API key")
                hint = (
                    " For the bundled simulator it must match `accessControl` in "
                    "data/octoprint/octoprint/config.yaml."
                    if service == "octoprint"
                    else ""
                )
                return answer(
                    False,
                    f"Reached the printer, but it rejected the credential "
                    f"({e.response.status_code}). Check {where}.{hint}",
                    int((time.time() - start_time) * 1000),
                )
            return answer(
                False,
                f"HTTP {e.response.status_code} from {service}: {e.response.text[:200]}",
            )
        except Exception as e:
            return answer(False, str(e))

@app.websocket("/ws/jobs/{job_id}")
async def websocket_job_endpoint(websocket: WebSocket, job_id: str):
    db = TelemetryDB()
    job = db.get_job(job_id)
    if not job:
        db.close()
        await websocket.accept()
        await websocket.send_json({"type": "error", "data": {"code": 4004, "message": "Job not found"}})
        await websocket.close(code=4004)
        return

    samples = db.get_samples(job_id, limit=20)
    db.close()

    await websocket.accept()

    status_resp = await get_job(job_id)
    await websocket.send_json({"type": "job_status", "data": status_resp.dict()})

    await websocket.send_json({"type": "telemetry_batch", "data": [s.to_dict() for s in samples]})

    await broadcaster.connect(job_id, websocket)
    activity.event(f"watcher attached · job {job_id[:8]}", source="ws")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await broadcaster.disconnect(job_id, websocket)
        activity.event(f"watcher left · job {job_id[:8]}", source="ws")

class UiEvent(BaseModel):
    """One thing a person did in the browser that never reached another endpoint."""

    action: str = Field(..., min_length=1, max_length=80)
    detail: str | None = Field(default=None, max_length=200)


class UiEventBatch(BaseModel):
    events: list[UiEvent] = Field(default_factory=list, max_length=50)


@app.post("/activity/ui", status_code=status.HTTP_202_ACCEPTED)
async def record_ui_activity(batch: UiEventBatch):
    """Record interactions that change no server state.

    Switching a stage tab, expanding the process log, scrubbing a layer — none of these
    hit another endpoint, so from the server's side a user who spent five minutes
    looking for something was indistinguishable from an idle one. Batched by the client
    and capped here, because this is a debugging aid and must never become a write
    amplifier: nothing is persisted, it goes to the in-memory feed only.
    """
    for event in batch.events[:50]:
        activity.event(
            f"ui · {event.action}" + (f" · {event.detail}" if event.detail else ""),
            level="DEBUG",
            source="ui",
        )
    return {"accepted": len(batch.events[:50])}


@app.get("/activity")
async def get_activity(limit: int = 200):
    """The server's recent activity, newest last.

    Read once on page load; `/ws/activity` carries it from there. In memory only — a
    debugging aid must not add a second reader to the telemetry database.
    """
    return {"entries": activity.recent(limit=max(1, min(limit, 500)))}


@app.websocket("/ws/activity")
async def websocket_activity_endpoint(websocket: WebSocket):
    """Live server activity, in the symbol grammar defined in `server/activity.py`.

    Not scoped to a job, unlike `/ws/jobs/{job_id}`: config edits, simulator lifecycle
    and printer actions belong to no job, and those are exactly the ones that were
    invisible.
    """
    await websocket.accept()
    await websocket.send_json({"type": "activity_batch", "data": activity.recent(limit=200)})

    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

    def on_record(record) -> None:
        # `put_nowait` from a synchronous listener, so emitting activity never blocks
        # on a slow socket. A client that cannot keep up loses lines rather than
        # applying backpressure to a print job.
        try:
            queue.put_nowait(record.as_dict())
        except asyncio.QueueFull:
            pass

    unsubscribe = activity.subscribe(on_record)
    try:
        while True:
            entry = await queue.get()
            await websocket.send_json({"type": "activity", "data": entry})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("Activity socket closed", exc_info=True)
    finally:
        unsubscribe()


@app.get("/simulators/status")
async def get_simulators_status():
    return simulator_manager.get_status()

@app.post("/simulators/moonraker/start")
async def start_moonraker_simulator():
    status = await simulator_manager.start_moonraker()

    healthy = False
    async with httpx.AsyncClient(timeout=1.0) as client:
        for _ in range(30):
            try:
                resp = await client.get(f"{status['url']}/printer/info")
                if resp.status_code == 200:
                    healthy = True
                    break
            except Exception:
                pass
            await asyncio.sleep(0.1)

    status["healthy"] = healthy
    activity.action(
        "moonraker simulator start",
        [("url", status.get("url")), ("healthy", healthy)],
        outcome="answering /printer/info" if healthy else "started but not answering yet",
        status="ok" if healthy else "warn",
        level="INFO" if healthy else "WARNING",
        source="simulator",
    )
    await broadcaster.broadcast_all({"type": "simulator_update", "data": simulator_manager.get_status()})
    return status

@app.post("/simulators/moonraker/stop")
async def stop_moonraker_simulator():
    status = await simulator_manager.stop_moonraker()
    activity.event("moonraker simulator stopped", source="simulator", level="WARNING")
    await broadcaster.broadcast_all({"type": "simulator_update", "data": simulator_manager.get_status()})
    return status

@app.get("/simulators/moonraker/logs")
async def get_moonraker_simulator_logs():
    repo_root = Path(__file__).parent.parent
    log_file = repo_root / "data" / "logs" / "moonraker_mock.log"
    if not log_file.exists():
        return {"lines": []}

    with open(log_file, "r") as f:
        lines = f.readlines()

    return {"lines": [line.rstrip() for line in lines[-100:]]}

#: OctoPrint takes roughly half a minute to come up — intermediary server, plugin
#: load, then the real server. The old budget was 30 × 0.1s = 3 seconds, so a cold
#: start was always reported unhealthy.
_OCTOPRINT_BOOT_TIMEOUT_S = 90
_OCTOPRINT_POLL_INTERVAL_S = 1.0


@app.post("/simulators/octoprint/start")
async def start_octoprint_simulator():
    try:
        status = await simulator_manager.start_octoprint()
    except SimulatorAvailabilityError as exc:
        # Docker being down is an environment problem the user can fix, not a bug:
        # report it as such instead of a 500 with a stack trace.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # The probe must authenticate: OctoPrint answers an unauthenticated
    # /api/version with 403, so a keyless poll can never see it come up.
    #
    # No host binding here, and deliberately: `status['url']` is the simulator
    # container this process just started, not an address anyone typed, so there is
    # no address to have been repointed. The binding polices the store's own URL
    # keys — see `printer_credential`.
    api_key = status.get("api_key") or config_store.get("OCTOPRINT_API_KEY")
    headers = {"X-Api-Key": api_key} if api_key else {}

    healthy = False
    deadline = asyncio.get_event_loop().time() + _OCTOPRINT_BOOT_TIMEOUT_S
    async with httpx.AsyncClient(timeout=5.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await client.get(f"{status['url']}/api/version", headers=headers)
                if resp.status_code == 200:
                    healthy = True
                    break
                if resp.status_code in (401, 403):
                    logger.warning(
                        "OctoPrint simulator is up but rejected our API key (%s). "
                        "Is OCTOPRINT_API_KEY in sync with "
                        "data/octoprint/octoprint/config.yaml?",
                        resp.status_code,
                    )
                    break
            except Exception:
                pass  # still booting
            await asyncio.sleep(_OCTOPRINT_POLL_INTERVAL_S)

    status["healthy"] = healthy
    activity.action(
        "octoprint simulator start",
        [
            ("url", status.get("url")),
            ("api key", "present" if api_key else "MISSING"),
            ("healthy", healthy),
        ],
        outcome=(
            "answering /api/version"
            if healthy
            else "up but not authenticating — check OCTOPRINT_API_KEY against "
                 "data/octoprint/octoprint/config.yaml"
        ),
        status="ok" if healthy else "fail",
        level="INFO" if healthy else "WARNING",
        source="simulator",
    )
    await broadcaster.broadcast_all({"type": "simulator_update", "data": simulator_manager.get_status()})
    return status

@app.post("/simulators/octoprint/stop")
async def stop_octoprint_simulator():
    status = await simulator_manager.stop_octoprint()
    activity.event("octoprint simulator stopped", source="simulator", level="WARNING")
    await broadcaster.broadcast_all({"type": "simulator_update", "data": simulator_manager.get_status()})
    return status

@app.get("/simulators/octoprint/logs")
async def get_octoprint_simulator_logs():
    repo_root = Path(__file__).parent.parent
    log_file = repo_root / "data" / "logs" / "octoprint_mock.log"
    if not log_file.exists():
        return {"lines": []}

    with open(log_file, "r") as f:
        lines = f.readlines()

    return {"lines": [line.rstrip() for line in lines[-100:]]}

@app.get("/system/info")
async def system_info():
    detected = get_execution_strategy()
    resolved = get_resolved_strategy()

    docker_available = False
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, timeout=3.0)
        docker_available = res.returncode == 0
    except Exception:
        pass

    labels = {
        "mps_native": "macOS Apple Silicon (MPS native Phase 1, Docker Phases 2-5)",
        "nvidia_docker": "NVIDIA GPU (full pipeline via Docker with GPU)",
        "cpu_docker": "CPU only (full pipeline via Docker)"
    }

    return {
        "detected_strategy": detected,
        "resolved_strategy": resolved,
        "override_active": config_store.get("EXECUTION_STRATEGY_OVERRIDE") is not None and config_store.get("EXECUTION_STRATEGY_OVERRIDE") in ("mps_native", "nvidia_docker", "cpu_docker"),
        "strategy_label": labels.get(resolved, "Unknown"),
        "docker_available": docker_available,
        "platform": sys.platform,
        "python_version": platform.python_version()
    }

@app.get("/system/printer/status")
async def printer_status():
    """Whether there is a printer that will actually accept a job right now.

    This used to answer `running: True` for any profile file that existed, without
    opening a single connection — so a profile pointing at a switched-off printer
    reported ready, the pipeline view opened, and the failure surfaced four phases
    later at dispatch. `configured` means "a target is set"; `running` now means
    "we asked it and it answered", and only the second one should gate a job.

    The container reachability check is `test_connection`'s, reused rather than
    reimplemented: two probes that can disagree about the same printer is how a
    "ready" badge ends up next to a dead machine.
    """
    # The composer has to clamp a requested size before a job exists, and this is the
    # only endpoint it can ask. Reported on every branch — including the refusals —
    # because "no printer" and "a printer that declares no dimensions" are different
    # answers that happen to imply the same thing: do not clamp.
    def _ceiling(profile_ref: Optional[str]) -> Optional[List[float]]:
        # The `open(profile_ref)` fallback this used to carry was deliberate
        # absolute-path support, and also an unauthenticated arbitrary-JSON read:
        # `DEFAULT_PROFILE` is set through `PUT /config`, and `NewJob` forwards its value
        # as `request.profile`, so it is one value and takes one boundary.
        try:
            candidate = resolve_profile_path(profile_ref)
        except ProfileOutsideProfilesDir:
            logger.debug("Ignoring a build volume from outside %s: %s",
                         PROFILES_DIR, profile_ref)
            return None
        if candidate is None:
            return None
        try:
            with open(candidate, "r") as handle:
                return _profile_build_volume(json.load(handle))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not read a build volume from %s: %s", profile_ref, exc)
            return None

    sim_status = simulator_manager.get_status()
    if sim_status.get("octoprint", {}).get("running"):
        # The container being up is not the same as OctoPrint answering inside it, and
        # the boot takes tens of seconds.
        probe = await test_connection(TestConnectionRequest(service="octoprint"))
        return {
            "configured": True,
            "type": "simulator",
            "running": bool(probe.get("success")),
            "detail": probe.get("message"),
            # This branch resolves no profile of its own, so it answers with the
            # default one — the profile a job submitted right now would slice against.
            "build_volume_mm": _ceiling(config_store.get("DEFAULT_PROFILE")),
        }

    profile = config_store.get("DEFAULT_PROFILE")
    if not profile:
        return {"configured": False, "type": "none", "running": False,
                "detail": "No printer profile selected.", "build_volume_mm": None}

    try:
        profile_path = resolve_profile_path(profile)
    except ProfileOutsideProfilesDir:
        profile_path = None
    if profile_path is None or not profile_path.exists():
        return {"configured": False, "type": "none", "running": False,
                "detail": f"Profile file not found: {profile}", "build_volume_mm": None}

    try:
        firmware, _base_url, _api_key = resolve_printer_target(str(profile_path))
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "type": "real", "running": False,
                "detail": f"Could not read {profile}: {exc}", "build_volume_mm": None}

    service = {"klipper": "moonraker", "moonraker": "moonraker",
               "bambu": "bambu"}.get(firmware, "octoprint")
    probe = await test_connection(TestConnectionRequest(service=service))
    return {
        "configured": True,
        "type": "real",
        "running": bool(probe.get("success")),
        "detail": probe.get("message"),
        "build_volume_mm": _ceiling(profile),
    }

@app.get("/jobs/{job_id}/blueprint")
async def get_blueprint(job_id: str):
    """Serve the blueprint image this job used.

    Args:
        job_id: The job whose blueprint is wanted.

    Returns:
        The PNG image, from the job's own directory when the pipeline snapshotted it.
    """
    blueprint_path = resolve_job_artifact(job_id, "blueprint.png")
    if blueprint_path is None:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    return FileResponse(str(blueprint_path), media_type="image/png")



@app.get("/jobs/{job_id}/mesh")
async def get_mesh(job_id: str):
    """Serve the engineered mesh this job produced.

    Args:
        job_id: The job whose mesh is wanted.

    Returns:
        The .obj file, from the job's own directory when it exists.
    """
    mesh_path = resolve_job_artifact(job_id, "engineered_mesh.obj")
    if mesh_path is None:
        raise HTTPException(status_code=404, detail="Mesh not found")
    return FileResponse(str(mesh_path), media_type="application/octet-stream")

# --- Serve SPA ---
@app.get("/{full_path:path}")
@public
async def serve_spa(full_path: str):
    """Catch-all route to serve the React SPA and its static assets.

    The second of the two routes reachable without the shared secret, and it has to be:
    this is the bundle a person loads *in order to* type the token. It serves files
    under `web/dist` and nothing else — `contained_path` is what makes that true, and
    is why an exempt catch-all is not an exempt arbitrary read.

    `full_path` is the percent-decoded request target and is matched by the `:path`
    converter, so it arrives with its slashes and its dot segments intact — this is the
    one route in the app that can be handed `../../../etc/passwd`. It therefore joins
    through `contained_path` rather than `os.path.join`.

    A refused path is answered with the SPA shell, not a 403: client-side routing means
    an unmatched path is the normal case for a deep link, and there is nothing useful to
    tell a caller about a file it may not have. `StaticFiles` does its own containment
    and was considered for the asset half, but it would cover only this one join —
    `resolve_job_artifact` and `resolve_job_profile` need the same check — and would
    still leave this handler to serve the fallback. One shared helper is less machinery
    than a mount beside it.

    Args:
        full_path: The requested path, request-controlled and unnormalised.

    Returns:
        A FileResponse containing the requested asset or index.html.

    Raises:
        HTTPException: If the frontend is not built or found.
    """
    if full_path:
        asset = contained_path(DIST_DIR, full_path)
        if asset is not None and asset.is_file():
            return FileResponse(str(asset))

    # Fall back to index.html for client-side routing.
    index_path = DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))

    raise HTTPException(status_code=404, detail="Frontend not built or not found")

