"""Every route but two refuses a caller that does not hold the shared secret.

`server/app.py` had no authentication of any kind. `POST /jobs` spends EUR 0,32 per
hosted generation, `POST /jobs/{id}/print-dispatch` heats a nozzle for hours,
`POST /jobs/{id}/blueprint-approval` stands in for the person who is supposed to look
at a Tier 3 IP screen, and `PUT /config` rewrites the printer credentials the server
then ships. Every one of those answered anything that could reach the port.

The matrix below is built **from the app's own router**, not from a list written here.
That is the whole point: a route added next month is covered by this file on the day it
is added, and it is covered *closed* — the only way to be exempt is to wear `@public`,
and the set of endpoints wearing it is itself asserted.
"""

import logging

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import Route
from starlette.testclient import TestClient, WebSocketDenialResponse

from server.app import app
from server.auth import PUBLIC_MARKER, SharedSecretAuth
from tests.conftest import TEST_API_TOKEN

#: The endpoints that may be reached with no credential at all. Two, both GET, both
#: reading nothing: the healthcheck a load balancer polls, and the bundle a person has
#: to load *in order to* type the token. Adding a third is a security decision and
#: belongs in a review, which is what this assertion forces.
EXPECTED_PUBLIC_PATHS = {"/health", "/{full_path:path}"}

#: Path parameters are filled with something syntactically valid but real enough to be
#: rejected only by the handler — which must never run. A 404 here would mean the
#: request reached the router.
DUMMY_PARAM = "ds-auth-probe"


@pytest.fixture
def anonymous():
    """A client with no credentials. `headers={}` is conftest's documented opt-out."""
    return TestClient(app, headers={})


@pytest.fixture
def authenticated():
    """A client carrying the session token, the way every other test module's does."""
    return TestClient(app)


def _fill(path: str) -> str:
    """`/jobs/{job_id}/download` → `/jobs/ds-auth-probe/download`."""
    out = []
    for segment in path.split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            out.append(DUMMY_PARAM)
        else:
            out.append(segment)
    return "/".join(out)


def _public_endpoints():
    return {
        route.path
        for route in app.router.routes
        if getattr(getattr(route, "endpoint", None), PUBLIC_MARKER, False)
    }


def _protected_http_routes():
    """Every HTTP route the app serves, minus the ones marked `@public`."""
    for route in app.router.routes:
        if not isinstance(route, (APIRoute, Route)):
            continue
        if getattr(getattr(route, "endpoint", None), PUBLIC_MARKER, False):
            continue
        for method in sorted(route.methods or set()):
            if method in ("HEAD", "OPTIONS"):
                continue
            yield route.path, method


# --- the marker ------------------------------------------------------------------


def test_exactly_two_endpoints_are_public():
    """Asserted from the routes, so a new `@public` has to be argued for here."""
    assert _public_endpoints() == EXPECTED_PUBLIC_PATHS


def test_the_public_endpoints_are_read_only():
    """Nothing that writes is ever exempt — `_is_public` refuses to walk a non-GET."""
    for route in app.router.routes:
        if getattr(getattr(route, "endpoint", None), PUBLIC_MARKER, False):
            assert route.methods <= {"GET", "HEAD"}, (
                f"{route.path} is marked @public and accepts {route.methods}"
            )


def test_a_new_route_is_protected_by_writing_nothing():
    """The default is closed: an endpoint with no marker is refused."""
    middleware = SharedSecretAuth(app=None, fastapi_app=app, token="secret")
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/jobs",
        "root_path": "",
        "headers": [],
        "query_string": b"",
    }
    assert middleware._is_public(scope) is False
    assert middleware._is_public({**scope, "path": "/health"}) is True
    # A write to a public path is still not public.
    assert middleware._is_public({**scope, "path": "/health", "method": "POST"}) is False


# --- the 401 matrix --------------------------------------------------------------


def test_every_protected_route_refuses_an_anonymous_caller(anonymous):
    """The matrix, over every method of every route the router knows about."""
    routes = list(_protected_http_routes())
    assert len(routes) > 40, "the router walk found suspiciously few routes"

    open_routes = []
    for path, method in routes:
        response = anonymous.request(method, _fill(path))
        if response.status_code != 401:
            open_routes.append(f"{method} {path} → {response.status_code}")

    assert not open_routes, "routes answered an unauthenticated caller: " + "; ".join(
        open_routes
    )


def test_the_download_route_refuses_without_a_token(anonymous):
    """Named explicitly by the issue: the artifacts are not public either."""
    assert anonymous.get(f"/jobs/{DUMMY_PARAM}/download").status_code == 401


def test_the_schema_routes_are_not_public(anonymous):
    """`/openapi.json` lists `/config/{key}/reveal`; it is a map, and it is closed."""
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert anonymous.get(path).status_code == 401, f"{path} answered anonymously"


def test_an_unknown_path_is_a_401_for_anything_that_writes(anonymous):
    """A write to a path that does not exist is refused before it is looked up.

    The middleware never walks the router for a non-GET, so no unauthenticated caller
    can learn which write routes exist by watching 404s turn into 405s.
    """
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        response = anonymous.request(method, "/there-is-no-such-thing")
        assert response.status_code == 401, f"{method} on an unknown path"


def test_an_unknown_get_falls_to_the_spa_and_reads_nothing(anonymous):
    """An unknown GET is a deep link, and the SPA catch-all is public on purpose.

    The catch-all matches every path, so "unmatched" is not a state a GET can be in.
    What keeps that from being an anonymous arbitrary read is `contained_path`: the
    handler serves files under `web/dist` or the shell, and nothing else. Asserted
    here so the pairing — public route, contained join — is written down in the auth
    tests rather than only in the traversal ones.
    """
    response = anonymous.get("/../../.env")
    assert response.status_code != 200 or b"DS_API_TOKEN=" not in response.content


def test_a_wrong_token_is_refused():
    """Including one that differs by a single character, which `compare_digest` sees."""
    for wrong in ("", "wrong", TEST_API_TOKEN + "x", TEST_API_TOKEN[:-1]):
        client = TestClient(app, headers={"Authorization": f"Bearer {wrong}"})
        assert client.get("/jobs").status_code == 401, f"{wrong!r} was accepted"


def test_a_token_in_the_wrong_place_is_refused():
    """Not Basic, not a bare value, not a query parameter on an HTTP route.

    `?token=` exists for the WebSocket upgrade alone, where a browser cannot set a
    header. Honouring it on HTTP routes would put the secret in every referer,
    bookmark and proxy log for no gain.
    """
    assert TestClient(app, headers={"Authorization": TEST_API_TOKEN}).get(
        "/jobs"
    ).status_code == 401
    assert TestClient(app, headers={"Authorization": f"Basic {TEST_API_TOKEN}"}).get(
        "/jobs"
    ).status_code == 401
    assert TestClient(app, headers={}).get(
        f"/jobs?token={TEST_API_TOKEN}"
    ).status_code == 401


def test_the_refusal_names_the_scheme(anonymous):
    """`WWW-Authenticate: Bearer` — what a 401 owes the caller."""
    response = anonymous.get("/jobs")
    assert response.headers.get("www-authenticate") == "Bearer"
    assert "DS_API_TOKEN" in response.json()["detail"]


# --- the exempt routes actually answer -------------------------------------------


def test_health_answers_without_a_token(anonymous):
    """Something with no credential has to be able to ask whether the server is up."""
    response = anonymous.get("/health")
    assert response.status_code == 200
    assert "status" in response.json()


def test_the_spa_answers_without_a_token(anonymous):
    """The bundle is how a person gets to the box they type the token into.

    404 when `web/dist` has not been built, which is the state in CI; either way it is
    not a 401, which is the only thing this asserts.
    """
    assert anonymous.get("/").status_code != 401


# --- the token works --------------------------------------------------------------


def test_a_token_round_trip(authenticated):
    """The header opens the routes the anonymous client was refused."""
    assert authenticated.get("/jobs").status_code == 200
    assert authenticated.get("/health").status_code == 200
    assert authenticated.get("/openapi.json").status_code == 200
    # A job that does not exist is a 404 from the handler — which means the request
    # got past the middleware and into the router.
    assert authenticated.get(f"/jobs/{DUMMY_PARAM}/download").status_code == 404


# --- the WebSocket upgrade ---------------------------------------------------------


def _ws_paths():
    return [route.path for route in app.router.routes if isinstance(route, APIWebSocketRoute)]


def test_every_websocket_refuses_the_upgrade_itself(anonymous):
    """401 on the upgrade, not a socket that is accepted and then closed.

    Accepting first would leave unauthenticated sockets open until something timed
    them out, and would put the check in every handler instead of in one place.
    """
    assert _ws_paths(), "the app registered no WebSocket routes"
    for path in _ws_paths():
        with pytest.raises(WebSocketDenialResponse) as denial:
            with anonymous.websocket_connect(_fill(path)):
                pass
        assert denial.value.status_code == 401, path


def test_a_websocket_opens_with_the_token_in_the_query(anonymous):
    """A browser cannot set a header on `new WebSocket(...)`; this is the way in."""
    with anonymous.websocket_connect(f"/ws/activity?token={TEST_API_TOKEN}") as ws:
        assert ws.receive_json()["type"] == "activity_batch"


def test_a_wrong_token_in_the_query_is_refused(anonymous):
    with pytest.raises(WebSocketDenialResponse) as denial:
        with anonymous.websocket_connect("/ws/activity?token=nope"):
            pass
    assert denial.value.status_code == 401


def test_a_websocket_opens_with_the_bearer_header(authenticated):
    """Non-browser callers keep the header they already speak."""
    with authenticated.websocket_connect("/ws/activity") as ws:
        assert ws.receive_json()["type"] == "activity_batch"


def test_the_middleware_never_logs_the_query_string(anonymous, caplog):
    """The token rides in a URL exactly once, and no log line may carry it.

    uvicorn's access log is off (`server/logging_config.py`) and `log_requests`
    records `url.path` — this pins that both stay true, because a secret in a log file
    outlives every other precaution taken here.
    """
    with caplog.at_level(logging.DEBUG):
        with anonymous.websocket_connect(f"/ws/activity?token={TEST_API_TOKEN}"):
            pass
        anonymous.get(f"/health?token={TEST_API_TOKEN}")

    for record in caplog.records:
        assert TEST_API_TOKEN not in record.getMessage(), (
            f"the token reached the log: {record.getMessage()!r}"
        )


# --- the token is not a config key -------------------------------------------------


def test_the_shared_secret_cannot_be_rotated_through_the_config_api(authenticated):
    """`PUT /config` must not be able to change the credential protecting `PUT /config`.

    One bad write would otherwise lock every client out of the server, with no way
    back in through the API — so the token is deliberately not a `CONFIG_KEYS` entry
    and the endpoint refuses it as an unknown key.
    """
    from server.config_store import CONFIG_KEYS

    assert "DS_API_TOKEN" not in CONFIG_KEYS
    response = authenticated.put("/config", json={"DS_API_TOKEN": "hijacked"})
    assert response.status_code >= 400
