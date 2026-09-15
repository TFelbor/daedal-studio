"""The telemetry relay authenticates, and says so when it cannot.

`POST /jobs/{id}/internal-telemetry` is the route a collector running in the pipeline
container or beside the dispatch operator posts every sample to, and it is the route
that puts live print telemetry on the job's WebSocket. It was open: anything that could
reach the port could inject invented samples into a running job and into the dataset
this project exists to gather.

Closing it means the relay has to hold the token — the server hands it over in
`subprocess_env` — and it means a collector *without* one has to fail in a way somebody
can see, because the fallback it takes is silent by design.
"""

import asyncio
import logging

import pytest
from aiohttp import web

from pythonsrc import api_token
from pythonsrc.telemetry import internal_telemetry
from pythonsrc.telemetry.internal_telemetry import (
    internal_telemetry_headers,
    send_internal_telemetry,
)


@pytest.fixture
def fake_api(unused_tcp_port, monkeypatch):
    """An aiohttp stand-in for the API server that records what it was sent."""
    received: list[dict] = []

    async def handler(request):
        received.append(
            {
                "authorization": request.headers.get("Authorization"),
                "path": request.path,
            }
        )
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_post("/jobs/{job_id}/internal-telemetry", handler)

    async def serve():
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", unused_tcp_port)
        await site.start()
        return runner

    loop = asyncio.new_event_loop()
    runner = loop.run_until_complete(serve())
    monkeypatch.setenv("DS_API_URL", f"http://127.0.0.1:{unused_tcp_port}")
    try:
        yield loop, received
    finally:
        loop.run_until_complete(runner.cleanup())
        loop.close()


@pytest.fixture(autouse=True)
def reset_the_one_shot_warning():
    internal_telemetry._warned_about_missing_token = False
    yield
    internal_telemetry._warned_about_missing_token = False


def test_the_relay_sends_the_bearer_header(fake_api, monkeypatch):
    """The token the server handed the child is what the child sends back."""
    monkeypatch.setenv("DS_API_TOKEN", "the-shared-secret")
    loop, received = fake_api

    assert loop.run_until_complete(send_internal_telemetry("job-1", {"type": "x"}))
    assert received[0]["authorization"] == "Bearer the-shared-secret"


def test_no_token_falls_back_and_says_so_once(monkeypatch, tmp_path, caplog):
    """A collector with no token is a run with no live feed — that has to be visible.

    The fallback is the local broadcaster, which is right for a collector inside the
    server process and useless for one in the pipeline container. Silence is what made
    the earlier relay bug survive; one warning is the difference.
    """
    monkeypatch.delenv("DS_API_TOKEN", raising=False)
    monkeypatch.setenv(api_token.API_TOKEN_PATH_ENV, str(tmp_path / "absent"))

    with caplog.at_level(logging.WARNING):
        assert internal_telemetry_headers() == {}
        assert internal_telemetry_headers() == {}

    warnings = [r for r in caplog.records if "DS_API_TOKEN" in r.getMessage()]
    assert len(warnings) == 1, "the missing-token warning is per process, not per sample"


def test_a_refused_post_falls_back_to_the_local_broadcaster(unused_tcp_port, monkeypatch):
    """A 401 is a failed post like any other, and the fallback still runs.

    This is what keeps an upgrade from losing the in-process collectors' feed while
    someone works out where the token went.
    """
    monkeypatch.setenv("DS_API_URL", f"http://127.0.0.1:{unused_tcp_port}")
    monkeypatch.delenv("DS_API_TOKEN", raising=False)

    broadcast: list = []

    class Recorder:
        async def broadcast(self, job_id, message):
            broadcast.append((job_id, message))

    monkeypatch.setattr(internal_telemetry, "local_broadcaster", Recorder())

    assert asyncio.run(send_internal_telemetry("job-2", {"type": "x"})) is True
    assert broadcast == [("job-2", {"type": "x"})]
