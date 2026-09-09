"""The static-file routes must not hand out files from outside their own directory.

`server/app.py` has no end-user authentication, and the api-server process is the one
with `~/.ds-mvp/.config_key` bind-mounted — the Fernet key for the encrypted config
store that holds printer API keys. So an unauthenticated read of an arbitrary path is a
credential disclosure, not merely an information leak.

Nothing in the stack collapses dot segments before a handler sees the path: uvicorn
percent-decodes into `scope["path"]`, Starlette's `{...:path}` converter matches slashes
and `..` alike, and `os.path.join` happily walks out of the directory it was given.
Every test here therefore sends the traversal **percent-encoded** — `httpx` normalises a
literal `../` away client-side, which a real client (`curl --path-as-is`, or any socket)
does not.
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import app, resolve_job_artifact, resolve_job_profile
from pythonsrc.telemetry.db import TelemetryDB
from pythonsrc.telemetry.schema import PrintJob

client = TestClient(app)

REPO_ROOT = Path(__file__).parent.parent
DIST = REPO_ROOT / "web" / "dist"
SENTINEL_NAME = "traversal-sentinel.txt"
SENTINEL_BODY = "the config key would be here\n"


@pytest.fixture
def dist_with_sentinel():
    """A built-looking `web/dist`, plus a sentinel file one level above it.

    The sentinel stands in for `.env`, `pythonsrc/config.py` or the mounted Fernet key:
    a real, readable file that a correct handler must never serve. Putting it in `web/`
    rather than the repo root keeps the traversal one segment deep, so the test does not
    depend on how far below the root `web/dist` happens to sit.
    """
    created_dirs = []
    d = DIST
    if not d.exists():
        for parent in (d.parent, d):
            if not parent.exists():
                parent.mkdir()
                created_dirs.append(parent)

    # A real subdirectory, so the traversal cases that go *through* one have a
    # directory the kernel can actually resolve `..` against. Without it the stat fails
    # for the wrong reason and the test passes without exercising anything.
    assets = d / "assets"
    assets_pre_existing = assets.exists()
    if not assets_pre_existing:
        assets.mkdir()

    index = d / "index.html"
    index_pre_existing = index.exists()
    if not index_pre_existing:
        index.write_text("<!doctype html><title>SPA</title>\n")

    asset = d / "app.js"
    asset_pre_existing = asset.exists()
    if not asset_pre_existing:
        asset.write_text("console.log('spa')\n")

    sentinel = d.parent / SENTINEL_NAME
    sentinel.write_text(SENTINEL_BODY)

    yield {"dist": d, "index": index, "asset": asset, "sentinel": sentinel}

    sentinel.unlink()
    if not asset_pre_existing:
        asset.unlink()
    if not index_pre_existing:
        index.unlink()
    if not assets_pre_existing:
        assets.rmdir()
    for parent in reversed(created_dirs):
        parent.rmdir()


@pytest.mark.parametrize(
    "path",
    [
        # Percent-encoded dot segments: uvicorn decodes these into `scope["path"]`
        # before routing, so the handler receives literal `..` components.
        f"/%2e%2e/{SENTINEL_NAME}",
        f"/%2E%2E/{SENTINEL_NAME}",
        # Encoded separator: `..%2f` decodes to `../`, which the `:path` converter
        # matches as one segment.
        f"/..%2f{SENTINEL_NAME}",
        # Traversal through a directory that really exists, which is what makes the
        # kernel resolve the `..` rather than failing the stat.
        f"/assets/%2e%2e/%2e%2e/{SENTINEL_NAME}",
    ],
)
def test_spa_refuses_encoded_traversal(dist_with_sentinel, path):
    resp = client.get(path)
    assert SENTINEL_BODY not in resp.text, f"{path} served a file outside web/dist"
    # Client-side routing depends on the fallback, so an unmatched path is the SPA
    # shell, not a 403 — a 403 here would break deep links.
    assert resp.status_code == 200
    assert resp.text == dist_with_sentinel["index"].read_text()


def test_spa_refuses_absolute_full_path(dist_with_sentinel):
    """An absolute `full_path` discards the base, and needs no `..` at all.

    `os.path.join("web/dist", "/etc/passwd")` is `/etc/passwd`; so is
    `Path("web/dist") / "/etc/passwd"`. Encoding only the *leading* slash as `%2F` is
    what gets it past the client: `//Users/...` is collapsed to `/Users/...` by httpx,
    but `/%2FUsers/...` decodes to a path whose `full_path` group keeps its leading
    slash.
    """
    absolute = dist_with_sentinel["sentinel"].resolve()
    resp = client.get(f"/%2F{str(absolute).lstrip('/')}")
    assert SENTINEL_BODY not in resp.text
    assert resp.status_code == 200
    assert resp.text == dist_with_sentinel["index"].read_text()


def test_spa_still_serves_a_real_asset(dist_with_sentinel):
    resp = client.get("/app.js")
    assert resp.status_code == 200
    assert resp.text == dist_with_sentinel["asset"].read_text()


def test_spa_falls_back_to_index_for_an_unknown_route(dist_with_sentinel):
    resp = client.get("/dashboard/some/deep/link")
    assert resp.status_code == 200
    assert resp.text == dist_with_sentinel["index"].read_text()


# --- resolve_job_artifact ---

@pytest.fixture
def stray_data_file():
    """A file in `data/` — one level above both `data/outputs` and `data/inputs`."""
    data = REPO_ROOT / "data"
    outputs = data / "outputs"
    inputs = data / "inputs"
    for d in (outputs, inputs):
        d.mkdir(parents=True, exist_ok=True)
    stray = data / "blueprint.png"
    pre_existing = stray.exists()
    if not pre_existing:
        stray.write_bytes(b"not this job's blueprint")
    yield stray
    if not pre_existing:
        stray.unlink()


def test_resolve_job_artifact_refuses_a_traversing_job_id(stray_data_file):
    """`job_id` is one URL segment, so `..` is the whole of the traversal it can carry.

    `/jobs/%2e%2e/blueprint` decodes to `/jobs/../blueprint`, which the route's
    `[^/]+` group matches with `job_id == ".."` — and `data/outputs/../blueprint.png`
    is `data/blueprint.png`.
    """
    assert resolve_job_artifact("..", "blueprint.png") is None


def test_resolve_job_artifact_refuses_a_traversing_filename(stray_data_file):
    """Every call site passes a literal today; the parameter is still a parameter."""
    assert resolve_job_artifact("outputs", "../blueprint.png") is None


def test_resolve_job_artifact_refuses_an_absolute_filename(stray_data_file):
    assert resolve_job_artifact("outputs", str(stray_data_file.resolve())) is None


# --- resolve_job_profile ---

def _job_with_profile(profile: str) -> PrintJob:
    return PrintJob(
        job_id=str(uuid.uuid4()),
        prompt="a vase",
        printer_id="default",
        printer_firmware="octoprint",
        slicer="cura",
        profile_name=profile,
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        outcome="unknown",
    )


def test_resolve_job_profile_refuses_a_path_outside_the_repo(tmp_path):
    """`profile` is free text on `POST /jobs`, and it is joined onto the repo root.

    `Path(repo_root) / "/etc/passwd"` is `/etc/passwd`. The value is then `json.load`ed
    by `dispatch_target` and handed to `run_operator.py` as the profile to print with.
    """
    outside = tmp_path / "outside.json"
    outside.write_text('{"machine_name": "leaked"}')

    profile, path = resolve_job_profile(_job_with_profile(str(outside)))
    assert path != str(outside)
    assert profile != str(outside)


def test_resolve_job_profile_refuses_a_traversing_relative_path(tmp_path):
    """The relative form of the same escape, aimed at a file that really is there.

    `os.path.relpath` is what makes this honest: a hand-written `../../../../etc/passwd`
    lands wherever this checkout happens to sit and usually misses, so the test would
    pass without the join ever being contained.
    """
    outside = tmp_path / "outside.json"
    outside.write_text('{"machine_name": "leaked"}')
    relative = os.path.relpath(outside, REPO_ROOT)
    assert relative.startswith(".."), "expected a traversing relative path"

    profile, path = resolve_job_profile(_job_with_profile(relative))
    assert profile != relative
    assert path is None or Path(path).resolve() != outside.resolve()


def test_resolve_job_profile_still_accepts_a_bundled_profile():
    profile, path = resolve_job_profile(_job_with_profile("pythonsrc/profiles/ender3.json"))
    assert profile == "pythonsrc/profiles/ender3.json"
    assert path == str(REPO_ROOT / "pythonsrc" / "profiles" / "ender3.json")
