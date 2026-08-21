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

from pythonsrc.pipeline import (
    DEV_OUTPUT_PREFIX,
    DEV_REFERENCE_BLUEPRINT,
    DEV_REFERENCE_MESH,
    _blueprint_is_placeholder,
    _blueprint_is_stand_in,
    _install_dev_asset,
    _job_outputs_dir,
    _will_use_reference_assets,
)

_LEGACY_COLOUR = (73, 109, 137)


def _args(**overrides) -> argparse.Namespace:
    base = dict(job_id="job-1", skip_visualizer=False, skip_sculptor=False, mesh=None)
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
