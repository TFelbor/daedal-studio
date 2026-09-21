"""The generative path is closed in code, not only in intention.

The product ships the parametric organizer: a spec job compiles its geometry
deterministically in `pythonsrc/organizer/`, reaches no model weights, and cannot
construct a sculptor — `_apply_spec_mode` sets `skip_sculptor` for it. TRELLIS.2 and
the hosted Pixazo endpoint serve the *other* path, the one that turns a sentence into
a blueprint and a blueprint into a mesh.

That path was benched as a decision and left wired as code, which is a different
thing. `startJob` takes its spec as an optional argument, `prompt` is not a required
field, and `SKIP_SCULPTOR` defaults to false — so the composer's text box still
reached Phase 2, where `resolve_backend_name`'s `auto` resolves remote → CUDA →
**pixazo**. On a machine with no NVIDIA GPU and `PIXAZO_API_KEY` set — every Apple
Silicon development laptop — a prompt job therefore selected the backend that bills,
at €0,32 a generation, under terms whose output-ownership clause is unresolved
(`docs/audits/2026-09-19-external-licence.md` § 0 and E5).

These tests hold three things together, because each alone is undone by the other two
drifting:

- a spec-less job that would build a sculptor is refused before a row exists;
- a job that would *not* build one is untouched, so the dev and demo configuration
  `SKIP_SCULPTOR` exists for still runs;
- the switch that reverses all of it is a real config key, and it is not handed to a
  subprocess.
"""

import pytest
from fastapi.testclient import TestClient

from server import app as app_module
from server.app import JobRequest, _prompt_jobs_are_benched, app
from server.config_store import CONFIG_KEYS, SUBPROCESS_ENV_KEYS

client = TestClient(app)

#: Every test here is about the refusal, so none of them may take the suite-wide
#: `ALLOW_PROMPT_JOBS` default that `conftest._generative_path_open` applies to the
#: modules that predate the bench.
pytestmark = pytest.mark.prompt_jobs_benched

SPEC = {
    "archetype": "deck_box",
    "compartments": [{"contents": {"count": 100, "card": "standard", "sleeving": "double"}}],
    "lid": {"kind": "lift_off", "magnets": False, "height_mm": 15.0, "wall_mm": 1.2,
            "clearance_mm": 0.2, "top_mm": 2.0},
    "schema_version": 1,
}


@pytest.fixture
def store(monkeypatch):
    """The config store as a dict, so a test can say what an operator has set."""
    values: dict[str, str] = {}
    monkeypatch.setattr(
        app_module.config_store, "get", lambda key: values.get(key)
    )
    return values


def request_for(**kwargs) -> JobRequest:
    return JobRequest(printer_id="default_printer", **kwargs)


# ── What is refused ───────────────────────────────────────────────────────────

def test_a_spec_less_job_that_would_sculpt_is_benched(store):
    """The default. Nothing set, a sentence and no spec: this is the benched path."""
    assert _prompt_jobs_are_benched(request_for(prompt="a low-poly fox")) is True


def test_the_refusal_arrives_as_a_400_before_any_row_exists(store, printer_configured):
    """A 400, not a 422: the request is well-formed, the capability is closed.

    It is raised ahead of `job_id = uuid4()`, so a refused job leaves no row, no
    directory and no telemetry — which is what "before the job row was created"
    means everywhere else in this endpoint.
    """
    response = client.post("/jobs", json={
        "prompt": "a low-poly fox",
        "printer_id": "default_printer",
    })

    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    # The person is told where to go instead, and the operator is told which key
    # reverses it. A refusal that says only "no" sends both of them to the source.
    assert "configurator" in detail
    assert "ALLOW_PROMPT_JOBS" in detail


def test_the_bench_is_checked_before_the_ip_screen(store, printer_configured):
    """A franchise name in a benched prompt is answered by the bench, not the screen.

    Both refuse with a 400, so only the wording distinguishes them — and telling
    someone their prompt names a protected character, when no prompt of any kind
    would have been accepted, is a refusal about the wrong thing.
    """
    response = client.post("/jobs", json={
        "prompt": "a pikachu figurine",
        "printer_id": "default_printer",
    })

    assert response.status_code == 400, response.text
    assert "ALLOW_PROMPT_JOBS" in response.json()["detail"]


# ── What is not ───────────────────────────────────────────────────────────────

def test_a_spec_job_is_never_benched(store):
    """The shipping path. A spec compiles its own geometry and reaches no model."""
    assert _prompt_jobs_are_benched(request_for(spec=SPEC)) is False


def test_a_request_that_skips_the_sculptor_is_not_benched(store):
    """`skip_sculptor` substitutes a reference mesh and reaches no model or endpoint.

    The bench is on the generative path, not on prompts. Refusing this would break
    the dev and demo configuration while protecting nothing.
    """
    assert _prompt_jobs_are_benched(
        request_for(prompt="a low-poly fox", skip_sculptor=True)
    ) is False


def test_the_store_can_skip_the_sculptor_for_every_job(store):
    """The same, set by an operator rather than by the request."""
    store["SKIP_SCULPTOR"] = "true"

    assert _prompt_jobs_are_benched(request_for(prompt="a low-poly fox")) is False


# ── The switch ────────────────────────────────────────────────────────────────

def test_allow_prompt_jobs_reopens_the_path(store):
    """Un-benching is one key, so it needs no deploy and no code change."""
    store["ALLOW_PROMPT_JOBS"] = "true"

    assert _prompt_jobs_are_benched(request_for(prompt="a low-poly fox")) is False


@pytest.mark.parametrize("value", ["", "false", "True", "1", "yes", None])
def test_only_the_exact_string_true_reopens_it(store, value):
    """Anything else is benched, including the spellings that look affirmative.

    `SKIP_SCULPTOR` and `SKIP_VISUALIZER` are compared against `"true"` the same way,
    and a switch that spends money should not be the one place a truthy-looking value
    is guessed at.
    """
    if value is not None:
        store["ALLOW_PROMPT_JOBS"] = value

    assert _prompt_jobs_are_benched(request_for(prompt="a low-poly fox")) is True


def test_the_key_is_settable_and_is_not_a_secret():
    """It has to be reachable from the settings UI, and it is not a credential."""
    assert "ALLOW_PROMPT_JOBS" in CONFIG_KEYS
    assert CONFIG_KEYS["ALLOW_PROMPT_JOBS"]["secret"] is False
    assert CONFIG_KEYS["ALLOW_PROMPT_JOBS"]["required"] is False


def test_the_key_is_never_handed_to_a_subprocess():
    """It is read in this process to produce a refusal; nothing downstream reads it.

    `SUBPROCESS_ENV_KEYS` is the list of keys the server puts in a child's
    environment, and every entry there is a key somebody can name a reader for.
    """
    assert "ALLOW_PROMPT_JOBS" not in SUBPROCESS_ENV_KEYS
