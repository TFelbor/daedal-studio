"""Guards on stand-in assets: what a debugging run substitutes, and what says so.

When Phase 1 or Phase 2 is skipped with nothing real to work from, the pipeline installs
a bundled reference asset — a real blueprint and a real 195k-face reconstruction from job
`ec076d7e`. It used to fabricate them instead: a flat blue rectangle and a 50mm cube,
neither of which exercises anything downstream.

Two properties are load-bearing and both have bitten before. A stand-in goes to the
*shared* blueprint path and persists, so it must remain recognisable on the next run —
that is the only thing stopping a per-generation backend from being billed to reconstruct
a fixture. And a job whose inputs came from a fixture must not sit in `data/outputs/`
looking exactly like one a model produced.
"""

import argparse
from pathlib import Path

from PIL import Image

from pythonsrc.blueprint_spec import BlueprintResult, read_sidecar, write_sidecar
from pythonsrc.pipeline import (
    DEV_OUTPUT_PREFIX,
    DEV_REFERENCE_BLUEPRINT,
    DEV_REFERENCE_MESH,
    _blueprint_is_placeholder,
    _blueprint_is_stand_in,
    _blueprint_path,
    _install_dev_asset,
    _job_outputs_dir,
    _should_install_reference_blueprint,
    _will_use_reference_assets,
)

_LEGACY_COLOUR = (73, 109, 137)


def _args(**overrides) -> argparse.Namespace:
    base = dict(
        job_id="job-1", skip_visualizer=False, skip_sculptor=False, mesh=None, blueprint=None
    )
    base.update(overrides)
    return argparse.Namespace(**base)


# ── The bundled assets ───────────────────────────────────────────────────────


def test_the_reference_assets_ship_with_the_source():
    """They are inputs to every debugging run; a missing one fails the run loudly."""
    assert DEV_REFERENCE_BLUEPRINT.exists(), DEV_REFERENCE_BLUEPRINT
    assert DEV_REFERENCE_MESH.exists(), DEV_REFERENCE_MESH


def test_the_reference_blueprint_matches_the_shape_phase_1_produces():
    """1024x1024, so the artifact does not change size when a real render replaces it."""
    with Image.open(DEV_REFERENCE_BLUEPRINT) as img:
        assert img.size == (1024, 1024)


def test_the_reference_mesh_carries_the_defects_phase_3_exists_for():
    """The reason this is a real reconstruction and not `trimesh.creation.box`.

    A cube is watertight, convex and single-component, so `Engineer.repair_mesh` has
    nothing to remove, `_largest_component` nothing to choose between, and the
    printability gate scores geometry no reconstruction ever produces. This mesh arrives
    with non-manifold edges and loose fragments, which is what those code paths were
    written for and what a dev run needs to exercise them.
    """
    import numpy as np
    import trimesh
    from trimesh import grouping

    mesh = trimesh.load(str(DEV_REFERENCE_MESH), force="mesh")
    counts = np.array([len(g) for g in grouping.group_rows(mesh.edges_sorted, require_count=None)])

    assert len(mesh.faces) > 1000, "a handful of faces is a primitive, not a reconstruction"
    assert int((counts > 2).sum()) > 0, "no non-manifold edges: repair would have nothing to do"
    assert len(mesh.split(only_watertight=False)) > 1, "one component: pruning is never exercised"


def test_installing_an_asset_copies_it_byte_for_byte(tmp_path: Path):
    destination = tmp_path / "nested" / "raw_mesh.obj"
    _install_dev_asset(DEV_REFERENCE_MESH, destination, "mesh")
    assert destination.read_bytes() == DEV_REFERENCE_MESH.read_bytes()


def test_a_missing_reference_asset_raises(tmp_path: Path):
    """Continuing would leave the next phase reading whatever is on disk."""
    try:
        _install_dev_asset(tmp_path / "gone.obj", tmp_path / "out.obj", "mesh")
    except FileNotFoundError as exc:
        assert "dev reference" in str(exc)
    else:
        raise AssertionError("a missing reference asset must not pass silently")


# ── Recognising a stand-in ───────────────────────────────────────────────────


def test_the_installed_reference_blueprint_is_recognised(tmp_path: Path):
    """The whole point: existence on disk is not evidence of a real render."""
    path = tmp_path / "blueprint.png"
    _install_dev_asset(DEV_REFERENCE_BLUEPRINT, path, "blueprint")
    assert _blueprint_is_stand_in(path) is True


def test_a_real_blueprint_is_not_mistaken_for_a_stand_in(tmp_path: Path):
    path = tmp_path / "blueprint.png"
    image = Image.new("RGB", (1024, 1024), color=_LEGACY_COLOUR)
    # One differing pixel is enough to make it not-flat, and it is not the reference
    # file, so neither leg of the check should fire.
    image.putpixel((0, 0), (255, 255, 255))
    image.save(path)
    assert _blueprint_is_stand_in(path) is False


def test_a_flat_rectangle_from_an_earlier_version_is_still_recognised(tmp_path: Path):
    """Those files persist on the shared path, and the guard is the only thing on watch.

    Both sizes the old code wrote, because the placeholder grew from 512 to 1024 once
    already and the smaller ones are still out there.
    """
    for size in ((1024, 1024), (512, 512)):
        path = tmp_path / f"blueprint-{size[0]}.png"
        Image.new("RGB", size, color=_LEGACY_COLOUR).save(path)
        assert _blueprint_is_stand_in(path) is True
        assert _blueprint_is_placeholder(path) is True


def test_a_flat_image_of_another_size_or_colour_is_not_a_stand_in(tmp_path: Path):
    odd_size = tmp_path / "odd.png"
    Image.new("RGB", (256, 256), color=_LEGACY_COLOUR).save(odd_size)
    assert _blueprint_is_stand_in(odd_size) is False

    odd_colour = tmp_path / "colour.png"
    Image.new("RGB", (512, 512), color=(10, 10, 10)).save(odd_colour)
    assert _blueprint_is_stand_in(odd_colour) is False


def test_a_missing_or_unreadable_file_is_not_a_stand_in(tmp_path: Path):
    assert _blueprint_is_stand_in(tmp_path / "nope.png") is False
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    assert _blueprint_is_stand_in(broken) is False


# ── Naming what a debugging run produced ─────────────────────────────────────


def test_a_debugging_run_writes_to_a_dev_directory(tmp_path: Path):
    outputs = tmp_path / "outputs"
    directory = _job_outputs_dir(
        _args(skip_visualizer=True, skip_sculptor=True),
        outputs,
        tmp_path / "missing-blueprint.png",
    )
    assert directory.name == f"{DEV_OUTPUT_PREFIX}job-1"


def test_the_native_mac_path_is_not_a_debugging_run(tmp_path: Path):
    """`--skip-visualizer` is the primary Mac workflow: Phase 1 ran, natively, first.

    Marking those outputs `dev-` would label almost every real run on a Mac as fabricated.
    """
    outputs = tmp_path / "outputs"
    blueprint = tmp_path / "blueprint.png"
    Image.new("RGB", (1024, 1024), color=(1, 2, 3)).save(blueprint)

    directory = _job_outputs_dir(_args(skip_visualizer=True), outputs, blueprint)
    assert directory.name == "job-1"


def test_a_supplied_mesh_is_not_a_fixture(tmp_path: Path):
    """`--skip-sculptor --mesh real.obj` skips a phase without fabricating anything."""
    mesh = tmp_path / "real.obj"
    mesh.write_text("o real\n")
    blueprint = tmp_path / "blueprint.png"
    Image.new("RGB", (1024, 1024), color=(1, 2, 3)).save(blueprint)

    assert _will_use_reference_assets(
        _args(skip_visualizer=True, skip_sculptor=True, mesh=str(mesh)), blueprint, [mesh]
    ) is False


def test_an_existing_directory_wins_over_the_prediction(tmp_path: Path):
    """A re-run must not split one job's artifacts across two directories."""
    outputs = tmp_path / "outputs"
    (outputs / "job-1").mkdir(parents=True)

    directory = _job_outputs_dir(
        _args(skip_visualizer=True, skip_sculptor=True),
        outputs,
        tmp_path / "missing.png",
    )
    assert directory.name == "job-1"

    (outputs / f"{DEV_OUTPUT_PREFIX}job-1").mkdir()
    assert _job_outputs_dir(_args(), outputs, tmp_path / "missing.png").name == f"{DEV_OUTPUT_PREFIX}job-1"


def test_the_server_serves_artifacts_out_of_a_dev_directory():
    """The prefix keeps fixtures out of the real namespace; it must not hide them."""
    import uuid

    from server.app import resolve_job_artifact

    job_id = str(uuid.uuid4())
    outputs = Path(__file__).parent.parent / "data" / "outputs"
    directory = outputs / f"dev-{job_id}"
    directory.mkdir(parents=True)
    artifact = directory / "engineered_mesh.gcode"
    artifact.write_text(";TIME:1\n")
    try:
        assert resolve_job_artifact(job_id, "engineered_mesh.gcode") == artifact
    finally:
        artifact.unlink()
        directory.rmdir()


# ── Which runs get a stand-in blueprint ──────────────────────────────────────


def test_both_phases_skipped_still_gets_a_blueprint(tmp_path: Path):
    """The commonest dev configuration, and the one that silently got nothing.

    Setting both config-store flags — `SKIP_VISUALIZER` and `SKIP_SCULPTOR`, which is
    how the UI runs Phases 3-5 on a machine with no GPU — used to install the reference
    *mesh* and no blueprint at all: the condition withheld it whenever Phase 2 was also
    skipped, on the reasoning that a skipped Phase 2 has nothing to hand it to. But
    Phase 2 is not the blueprint's only consumer. It is the first thing the running view
    shows, and its hash is the job's only Phase 1 provenance. Every `dev-` job directory
    on this machine came out with `raw_mesh.obj` and no `blueprint.png`, exit code 0, and
    nothing in the log saying so.
    """
    assert _should_install_reference_blueprint(
        _args(skip_visualizer=True, skip_sculptor=True), tmp_path / "missing.png"
    ) is True


def test_a_skipped_phase_1_alone_gets_a_blueprint(tmp_path: Path):
    """Phase 2 is going to run and needs an image to reconstruct."""
    assert _should_install_reference_blueprint(
        _args(skip_visualizer=True), tmp_path / "missing.png"
    ) is True


def test_a_supplied_mesh_gets_no_invented_blueprint(tmp_path: Path):
    """`--skip-sculptor --mesh real.obj` is a real run, so it stays honestly empty.

    Nothing in it came from a fixture, so `_will_use_reference_assets` is False and the
    outputs land in the real namespace. Installing a blueprint there would put a
    fabricated input beside real artifacts and stamp its hash as this job's Phase 1
    provenance.
    """
    mesh = tmp_path / "real.obj"
    mesh.write_text("o real\n")
    assert _should_install_reference_blueprint(
        _args(skip_visualizer=True, skip_sculptor=True, mesh=str(mesh)),
        tmp_path / "missing.png",
    ) is False


def test_an_existing_blueprint_is_never_replaced(tmp_path: Path):
    """The native Mac path: Phase 1 just ran and wrote it."""
    blueprint = tmp_path / "blueprint.png"
    Image.new("RGB", (1024, 1024), color=(1, 2, 3)).save(blueprint)
    assert _should_install_reference_blueprint(
        _args(skip_visualizer=True, skip_sculptor=True), blueprint
    ) is False


def test_nothing_is_installed_when_phase_1_runs(tmp_path: Path):
    """Phase 1 is about to write a real blueprint at that path."""
    assert _should_install_reference_blueprint(
        _args(), tmp_path / "missing.png"
    ) is False


def test_the_fixture_flag_reaches_the_running_view():
    """A fixture blueprint must not be presented as something the model drew.

    The `dev-` prefix and `used_reference_assets` kept fixture runs out of the dataset,
    but nothing told the *person* looking at the page: the running view captioned the
    reference blueprint "drawn from the prompt" like any other. Now that a both-phases-
    skipped run actually installs one, that caption would be a straight lie, so the flag
    has to come out of `GET /jobs/{id}` where the UI can say so.
    """
    import uuid
    from datetime import datetime, timezone

    from fastapi.testclient import TestClient

    from pythonsrc.telemetry.db import TelemetryDB
    from pythonsrc.telemetry.schema import PrintJob
    from server.app import app

    job_id = str(uuid.uuid4())
    db = TelemetryDB()
    db.init_schema()
    db.insert_job(
        PrintJob(
            job_id=job_id,
            prompt="a low poly planter",
            printer_id="default",
            printer_firmware="octoprint",
            slicer="cura",
            profile_name="pythonsrc/profiles/ender3.json",
            started_at=datetime.now(timezone.utc),
            completed_at=None,
            outcome="unknown",
        )
    )
    db.update_job_run_context(job_id, git_sha="abc1234", used_reference_assets=True)
    db.close()

    body = TestClient(app).get(f"/jobs/{job_id}").json()
    assert body["used_reference_assets"] is True


# ── One blueprint per job, not one per machine ──────────────────────────────
#
# `data/inputs/blueprint.png` is a single filename that every run wrote in place.
# Phase 1 takes ~30s natively and minutes in Docker, so two jobs started in that window
# race for it — and the loser goes on to sculpt, slice and print the winner's image
# while recording its own prompt and seed against it. Nothing downstream can notice:
# the file exists, it is a real render, and its hash is whatever landed last. The row
# that results is a mislabelled example in the one dataset this project exists to
# collect, and on a per-generation sculptor backend it is money spent reconstructing
# the wrong picture.
#
# Snapshotting into `data/outputs/{job_id}/` afterwards does not fix it — that copies
# whichever image won.


def test_each_job_renders_into_its_own_directory(tmp_path: Path):
    inputs = tmp_path / "inputs"

    first = _blueprint_path(_args(job_id="job-a"), inputs)
    second = _blueprint_path(_args(job_id="job-b"), inputs)

    assert first != second, "two jobs would still overwrite one another's blueprint"
    assert first == inputs / "job-a" / "blueprint.png"
    assert second == inputs / "job-b" / "blueprint.png"


def test_a_run_without_a_job_id_keeps_the_flat_layout(tmp_path: Path):
    """Manual CLI use. There is no job to name a directory after, and nothing to race.

    The same reasoning as the flat `data/outputs/` fallback: a person running the
    pipeline by hand gets the documented paths, unchanged.
    """
    inputs = tmp_path / "inputs"
    assert _blueprint_path(_args(job_id=None), inputs) == inputs / "blueprint.png"


def test_an_explicit_blueprint_always_wins(tmp_path: Path):
    """`--blueprint` is how a caller supplies its own image.

    It is also how the skip-Phase-1 configuration reuses the one already sitting at the
    shared path — that run generates nothing, so there is nothing for it to race for,
    and redirecting it to an empty per-job directory would make the pipeline stand a
    fixture in instead of using the blueprint someone deliberately put there.
    """
    supplied = tmp_path / "somewhere" / "mine.png"
    resolved = _blueprint_path(_args(job_id="job-a", blueprint=str(supplied)), tmp_path)
    assert resolved == supplied


def test_a_concurrent_job_cannot_overwrite_another_jobs_blueprint(tmp_path: Path):
    """The race, played out: two jobs render one after the other and both survive.

    On the shared path the second `save` replaced the first, and the first job carried
    on with an image of the wrong prompt.
    """
    inputs = tmp_path / "inputs"

    first = _blueprint_path(_args(job_id="job-a"), inputs)
    first.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1024, 1024), color=(10, 20, 30)).save(first)

    second = _blueprint_path(_args(job_id="job-b"), inputs)
    second.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1024, 1024), color=(40, 50, 60)).save(second)

    with Image.open(first) as img:
        assert img.convert("RGB").getpixel((0, 0)) == (10, 20, 30)


def test_each_job_keeps_its_own_provenance_sidecar(tmp_path: Path):
    """The other half of the race, and the one that cost the *winner*.

    `write_sidecar` puts the seed and engineered prompt beside the PNG, and
    `read_sidecar` refuses a sidecar whose recorded hash does not match the image next
    to it. On one shared path the loser's sidecar was the file left on disk, so the
    winner's own provenance was discarded as stale and its job recorded NULL for seed,
    prompt and model — the columns the sidecar exists to fill.
    """
    inputs = tmp_path / "inputs"

    for job_id, colour, seed in (("job-a", (10, 20, 30), 111), ("job-b", (40, 50, 60), 222)):
        path = _blueprint_path(_args(job_id=job_id), inputs)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1024, 1024), color=colour).save(path)
        write_sidecar(
            BlueprintResult(
                path=path,
                seed=seed,
                prompt=f"prompt for {job_id}",
                engineered_prompt=f"prompt for {job_id}, clay render",
                params={},
                duration_s=1.0,
                model_id="flux",
            )
        )

    for job_id, seed in (("job-a", 111), ("job-b", 222)):
        restored = read_sidecar(_blueprint_path(_args(job_id=job_id), inputs))
        assert restored is not None, f"{job_id} lost its provenance"
        assert restored.seed == seed
        assert restored.prompt == f"prompt for {job_id}"


def test_the_server_serves_a_jobs_own_blueprint_not_the_shared_one():
    """`resolve_job_artifact` must not hand back another run's image.

    Its last resort is the shared input path, which is right for rows written before
    inputs were per-job and for the skip-Phase-1 configuration. It is wrong for a job
    that has an input directory of its own: that job rendered into it, so the shared
    file demonstrably belongs to some other run, and serving it would commit the same
    mis-attribution in the endpoint that the per-job path removed from the pipeline.
    """
    import uuid

    from server.app import resolve_job_artifact

    repo_root = Path(__file__).parent.parent
    job_id = str(uuid.uuid4())
    inputs = repo_root / "data" / "inputs"
    job_inputs = inputs / job_id
    job_inputs.mkdir(parents=True)
    mine = job_inputs / "blueprint.png"
    Image.new("RGB", (1024, 1024), color=(10, 20, 30)).save(mine)

    shared = inputs / "blueprint.png"
    shared_existed = shared.exists()
    if not shared_existed:
        Image.new("RGB", (1024, 1024), color=(40, 50, 60)).save(shared)

    try:
        assert resolve_job_artifact(job_id, "blueprint.png") == mine

        # With its own directory but nothing in it, the job still must not be handed
        # the shared image — an empty first stage is honest, a foreign one is not.
        mine.unlink()
        assert resolve_job_artifact(job_id, "blueprint.png") is None
    finally:
        job_inputs.rmdir()
        if not shared_existed:
            shared.unlink()
