"""The PWA's two new files come off the same catch-all as the bundle, and no other way.

An installable app needs three things served: the manifest, the worker at the root, and
the icons. None of them got a route. That is the point of this file — the `@public`
catch-all already serves anything under `web/dist`, so adding a route for the manifest
would have been a *third* endpoint reachable without the shared secret, and
`tests/test_api_auth.py` asserts the exempt set is exactly two.

What did have to change is the media type. `FileResponse` guesses it from
`mimetypes.guess_type`, whose table comes from the interpreter and the host: CPython
learned `.webmanifest` in 3.11 and the server image is `python:3.10-slim`, where the
guess is `None` and Starlette falls back to `text/plain`. Chrome warns and installs
anyway; Safari does not — so the app would have been installable on the CI runner and
on a developer's machine, and silently not on iOS.
"""

import json
import mimetypes
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import server.app as app_module
from server.app import app
from tests.test_api_auth import EXPECTED_PUBLIC_PATHS


@pytest.fixture
def dist(tmp_path, monkeypatch):
    """A stand-in `web/dist`. The real one is built by a different CI job."""
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<!doctype html><title>shell</title>")
    (root / "manifest.webmanifest").write_text(json.dumps({"name": "Daedal Studio"}))
    (root / "sw.js").write_text("self.addEventListener('fetch', () => {})")
    (root / "icons").mkdir()
    (root / "icons" / "icon-192.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(app_module, "DIST_DIR", root)
    return root


@pytest.fixture
def anonymous():
    """No credential at all: this is how the app is loaded before a token exists."""
    return TestClient(app, headers={})


def test_the_manifest_is_served_as_a_manifest(anonymous, dist):
    """`text/plain` here is an app iOS declines to install, with no error anywhere."""
    response = anonymous.get("/manifest.webmanifest")
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] == "application/manifest+json"


def test_the_webmanifest_type_is_registered_rather_than_inherited():
    """The `add_type` in `server/app.py`, checked without a request.

    The suite runs on 3.11, where CPython's own table already has this — so a test that
    only made the request would pass here and tell us nothing about the 3.10 image the
    server actually ships in. This asserts the registration exists.
    """
    assert mimetypes.guess_type("x.webmanifest")[0] == "application/manifest+json"
    source = Path(app_module.__file__).read_text()
    assert 'mimetypes.add_type("application/manifest+json", ".webmanifest")' in source


def test_the_worker_is_served_from_the_root_as_javascript(anonymous, dist):
    """A worker's scope is the directory it is served from; `/sw.js` scopes it to `/`."""
    response = anonymous.get("/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] in {
        "text/javascript",
        "application/javascript",
    }


def test_the_icons_are_served_from_their_subdirectory(anonymous, dist):
    assert anonymous.get("/icons/icon-192.png").status_code == 200


def test_none_of_it_needs_the_token(anonymous, dist):
    """Everything the worker may cache is reachable with no credential.

    This is the other half of `web/src/sw.ts`'s allowlist: the worker has no way to read
    the shared secret, so a path on that list that *did* need one would be a resource the
    worker caches a 401 for and then serves from cache.
    """
    for path in ("/", "/manifest.webmanifest", "/sw.js", "/icons/icon-192.png"):
        assert anonymous.get(path).status_code == 200, path


def test_serving_the_pwa_added_no_public_endpoint():
    """Two exempt paths, the same two as before: the healthcheck and the bundle."""
    assert EXPECTED_PUBLIC_PATHS == {"/health", "/{full_path:path}"}


def test_an_unknown_path_still_falls_back_to_the_shell(anonymous, dist):
    """Client-side routing, unchanged — the worker's navigation fallback relies on it."""
    response = anonymous.get("/dashboard/ds-not-a-real-job")
    assert response.status_code == 200
    assert "shell" in response.text
