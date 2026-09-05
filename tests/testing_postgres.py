"""A PostgreSQL for the test suite.

The telemetry database is PostgreSQL (Supabase) in every deployed mode, so the tests
run against PostgreSQL too — a SQLite stand-in would pass while the production driver,
types and SQL went untested. Two ways to get one:

* **`DS_TEST_DATABASE_URL`** — a URL the suite may use as an administrator (it creates
  and drops schemas). CI sets this to a `postgres` service container.
* **Nothing** — `conftest.py` starts a throwaway `postgres:17-alpine` container on a
  random loopback port with the Docker CLI and removes it when the session ends.
  `DS_TEST_POSTGRES_IMAGE` overrides the image.

Isolation is a schema per test, not a database per test: `CREATE SCHEMA` is
milliseconds, and the schema name travels in the URL as
`options=-csearch_path=<schema>`, so `TelemetryDB` needs no test-only knob to land in
the right place.

If a run is killed hard, the container survives it. It is named
`ds-mvp-test-pg-<hex>`; `docker rm -f $(docker ps -aq -f name=ds-mvp-test-pg-)` cleans up.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid

import psycopg

URL_ENV = "DS_TEST_DATABASE_URL"
IMAGE_ENV = "DS_TEST_POSTGRES_IMAGE"
DEFAULT_IMAGE = "postgres:17-alpine"
CONTAINER_PREFIX = "ds-mvp-test-pg-"

_HELP = (
    "The test suite needs a PostgreSQL to run against. Either set "
    f"{URL_ENV} to a database the suite may administer, or have Docker running so a "
    f"throwaway `{DEFAULT_IMAGE}` container can be started (override the image with "
    f"{IMAGE_ENV})."
)


def schema_url(admin_url: str, schema: str) -> str:
    """`admin_url` with `search_path` pinned to `schema` for every connection."""
    separator = "&" if "?" in admin_url else "?"
    return f"{admin_url}{separator}options=-csearch_path%3D{schema}"


def wait_ready(url: str, timeout_s: float) -> None:
    """Block until `url` accepts a connection, or raise after `timeout_s`."""
    deadline = time.monotonic() + timeout_s
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(url, connect_timeout=2) as conn:
                conn.execute("SELECT 1")
            return
        except psycopg.OperationalError as exc:
            last = exc
            time.sleep(0.25)
    raise RuntimeError(f"PostgreSQL at {url} did not become ready in {timeout_s:.0f}s: {last}")


class TestPostgres:
    """Lifecycle of the suite's PostgreSQL and the schemas carved out of it."""

    __test__ = False  # not a test class, despite the name

    def __init__(self) -> None:
        self.admin_url: str | None = None
        self._container: str | None = None

    def start(self) -> str:
        """Provision (or adopt) a database and return its administrator URL."""
        provided = os.environ.get(URL_ENV, "").strip()
        if provided:
            wait_ready(provided, 30)
            self.admin_url = provided
            return provided

        image = os.environ.get(IMAGE_ENV, DEFAULT_IMAGE)
        name = CONTAINER_PREFIX + uuid.uuid4().hex[:8]
        try:
            subprocess.run(
                [
                    "docker", "run", "-d", "--rm", "--name", name,
                    "-e", "POSTGRES_PASSWORD=ds",
                    "-e", "POSTGRES_DB=ds_test",
                    "-p", "127.0.0.1::5432",
                    image,
                ],
                check=True, capture_output=True, text=True, timeout=180,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"{_HELP} (docker: not found)") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"{_HELP} (docker run failed: {exc.stderr.strip()})") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{_HELP} (docker run timed out pulling {image})") from exc
        self._container = name

        published = subprocess.run(
            ["docker", "port", name, "5432/tcp"],
            check=True, capture_output=True, text=True, timeout=30,
        ).stdout.strip().splitlines()
        port = published[0].rsplit(":", 1)[-1]
        self.admin_url = f"postgresql://postgres:ds@127.0.0.1:{port}/ds_test"
        try:
            wait_ready(self.admin_url, 90)
        except RuntimeError:
            self.stop()
            raise
        return self.admin_url

    def stop(self) -> None:
        """Remove the container this object started, if any."""
        if self._container:
            subprocess.run(
                ["docker", "rm", "-f", self._container],
                capture_output=True, text=True, timeout=60,
            )
            self._container = None

    def create_schema(self) -> tuple[str, str]:
        """A fresh, empty schema and the URL that lands every connection in it."""
        assert self.admin_url, "start() first"
        name = "t_" + uuid.uuid4().hex[:12]
        with psycopg.connect(self.admin_url, autocommit=True) as conn:
            conn.execute(f'CREATE SCHEMA "{name}"')
        return name, schema_url(self.admin_url, name)

    def drop_schema(self, name: str) -> None:
        assert self.admin_url, "start() first"
        with psycopg.connect(self.admin_url, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
