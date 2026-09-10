"""`data/outputs` stays legible: no directory without an artifact, and a way to look.

Two rules, and the failure mode of both is silence. A job directory created before
anything is written stays behind when the run dies, and nothing revisits it — 57 of 93
on one dev machine, none of them holding a byte. Nothing notices that for months, so
the tests are what notice.

The first half pins lazy creation: `_job_outputs_dir` chooses, `_ensure_outputs_dir`
creates, and the gate's deliberate pre-creation of a directory holding only a blueprint
snapshot keeps working — that one is load-bearing, and it is the reason the naive fix
("never create it early") cannot simply be applied everywhere.

The second half pins `pythonsrc/outputs.py`: what it reports, and — the part worth
being careful about — what its prune will and will not delete.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pythonsrc import outputs as outputs_mod
from pythonsrc.pipeline import (
    _build_parser,
    _ensure_outputs_dir,
    _job_outputs_dir,
    run,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_BLUEPRINT = REPO_ROOT / "pythonsrc" / "assets" / "dev_reference" / "blueprint.png"


# ── Lazy creation ─────────────────────────────────────────────────────────────
def _ns(**kw):
    base = dict(spec=None, mesh=None, skip_visualizer=False, skip_sculptor=False, job_id="j1")
    base.update(kw)
    return argparse.Namespace(**base)


def test_choosing_the_directory_does_not_create_it(tmp_path):
    chosen = _job_outputs_dir(_ns(), tmp_path, tmp_path / "missing.png")
    assert chosen == tmp_path / "j1"
    assert not chosen.exists()
    assert list(tmp_path.iterdir()) == []


def test_ensure_creates_and_is_idempotent(tmp_path):
    target = tmp_path / "j1"
    assert _ensure_outputs_dir(target) == target
    assert target.is_dir()
    assert _ensure_outputs_dir(target) == target


def test_pipeline_creates_the_directory_only_through_the_helper():
    """The guard that keeps the rule true.

    Lazy creation is one deleted line, and re-adding it is invisible in a diff: the
    pipeline still runs, still exits 0 and still writes every artifact, and the only
    symptom is a directory nobody looks at. So the source is asserted, not just the
    behaviour — a second `mkdir` anywhere in `pipeline.py` would restore the bug
    without failing any behavioural test that does not happen to take that path.
    """
    source = (REPO_ROOT / "pythonsrc" / "pipeline.py").read_text()
    helper = source.index("def _ensure_outputs_dir")
    body_end = source.index("\ndef ", helper + 1)
    outside = source[:helper] + source[body_end:]
    assert "outputs_dir.mkdir" not in outside


def test_a_directory_holding_only_the_gate_snapshot_does_not_claim_the_plain_namespace(tmp_path):
    """The approval gate creates `data/outputs/{job_id}` before Phase 2 on purpose.

    Lazy creation must not be read as "the directory is always absent until a phase
    writes": the gate puts a blueprint there so a parked job has an image to show, and
    a run that then substitutes a fixture mesh must still be routed to `dev-`.
    """
    parked = tmp_path / "j1"
    parked.mkdir()
    (parked / "blueprint.png").write_bytes(b"snapshot")
    (parked / "blueprint.provenance.json").write_text("{}")

    args = _ns(skip_sculptor=True)
    assert _job_outputs_dir(args, tmp_path, parked / "blueprint.png") == tmp_path / "dev-j1"


def test_a_directory_holding_real_output_still_wins(tmp_path):
    previous = tmp_path / "j1"
    previous.mkdir()
    (previous / "engineered_mesh.obj").write_text("v 0 0 0")
    assert _job_outputs_dir(_ns(), tmp_path, tmp_path / "missing.png") == tmp_path / "j1"


@pytest.fixture
def pipeline_dirs(tmp_path, monkeypatch):
    """Point the pipeline's I/O roots at a tmpdir and cut it off from the database."""
    from pythonsrc import pipeline

    inputs, outs = tmp_path / "inputs", tmp_path / "outputs"
    monkeypatch.setattr(pipeline, "INPUTS_DIR", str(inputs))
    monkeypatch.setattr(pipeline, "OUTPUTS_DIR", str(outs))
    monkeypatch.setenv("DS_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(pipeline, "_record_run_context", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_record_blueprint", lambda *a, **k: None)
    return inputs, outs


def test_a_run_that_dies_before_any_artifact_leaves_no_directory(pipeline_dirs):
    """The reported failure: a job that fails early used to leave an empty directory.

    A missing prompt stands in for the real causes — a compose mount error, a spec the
    archetype refuses, a killed container. All of them fail at or before Phase 1, which
    is after the output directory has been chosen and, until now, created.
    """
    inputs, outs = pipeline_dirs
    args = _build_parser().parse_args(["--job-id", "j-early-death"])

    with pytest.raises(SystemExit) as exit_info:
        run(args)

    assert exit_info.value.code == 1
    assert list(outs.iterdir()) == []


def test_the_first_write_creates_the_directory(pipeline_dirs):
    """And the other half: a run that produces something gets its directory."""
    inputs, outs = pipeline_dirs
    job = "j-snapshot"
    (inputs / job).mkdir(parents=True)
    (inputs / job / "blueprint.png").write_bytes(REFERENCE_BLUEPRINT.read_bytes())

    args = _build_parser().parse_args(
        ["--job-id", job, "--skip-visualizer", "--stop-after-phase", "1"]
    )
    with pytest.raises(SystemExit) as exit_info:
        run(args)

    assert exit_info.value.code == 0
    assert (outs / job / "blueprint.png").exists()


# ── The lister ────────────────────────────────────────────────────────────────
def _job(root: Path, name: str, files: dict[str, bytes] | None = None, age_days: float = 0.0):
    """Build one job directory, optionally backdated."""
    path = root / name
    path.mkdir(parents=True)
    for filename, payload in (files or {}).items():
        (path / filename).write_bytes(payload)
    if age_days:
        when = time.time() - age_days * 86400
        for child in list(path.iterdir()) + [path]:
            import os

            os.utime(child, (when, when))
    return path


def test_describe_reads_what_is_there(tmp_path):
    path = _job(tmp_path, "j1", {"engineered_mesh.gcode": b"G1", "blueprint.png": b"png"})
    job = outputs_mod.describe(path)
    assert job.job_id == "j1"
    assert not job.is_empty and not job.is_fixture
    assert job.has("gcode") and job.has("bp")
    assert not job.has("spec") and not job.has("mesh")
    assert job.total_bytes == 5


def test_a_compiled_spec_counts_as_a_mesh(tmp_path):
    """`mesh` answers "did Phase 2 produce anything", not which path it took."""
    job = outputs_mod.describe(_job(tmp_path, "j1", {"compiled_mesh.stl": b"solid"}))
    assert job.has("mesh")


def test_an_empty_directory_reads_as_empty(tmp_path):
    job = outputs_mod.describe(_job(tmp_path, "j1"))
    assert job.is_empty and job.files == () and job.total_bytes == 0


def test_the_fixture_prefix_is_recognised_and_stripped(tmp_path):
    job = outputs_mod.describe(_job(tmp_path, "dev-j1", {"raw_mesh.obj": b"v"}))
    assert job.is_fixture and job.job_id == "j1"


def test_a_parked_gate_snapshot_is_named_as_one(tmp_path):
    job = outputs_mod.describe(
        _job(tmp_path, "j1", {"blueprint.png": b"png", "blueprint.provenance.json": b"{}"})
    )
    assert job.is_gate_snapshot
    populated = outputs_mod.describe(_job(tmp_path, "j2", {"blueprint.png": b"p", "raw_mesh.obj": b"v"}))
    assert not populated.is_gate_snapshot


def test_scan_is_newest_first_and_skips_files(tmp_path):
    _job(tmp_path, "old", {"engineered_mesh.gcode": b"G"}, age_days=5)
    _job(tmp_path, "new", {"engineered_mesh.gcode": b"G"})
    (tmp_path / "engineered_mesh.gcode").write_bytes(b"flat")

    assert [job.job_id for job in outputs_mod.scan(tmp_path)] == ["new", "old"]
    assert outputs_mod.flat_artifacts(tmp_path) == ("engineered_mesh.gcode",)


def test_scan_of_a_missing_root_is_empty(tmp_path):
    assert outputs_mod.scan(tmp_path / "nope") == []
    assert outputs_mod.flat_artifacts(tmp_path / "nope") == ()


# ── The prune ─────────────────────────────────────────────────────────────────
def test_prune_takes_empty_directories_and_nothing_else(tmp_path):
    _job(tmp_path, "empty")
    _job(tmp_path, "ancient", {"engineered_mesh.gcode": b"G"}, age_days=400)

    doomed = outputs_mod.prunable(outputs_mod.scan(tmp_path))
    assert [job.job_id for job in doomed] == ["empty"]


def test_days_is_opt_in_and_reaches_real_artifacts(tmp_path):
    _job(tmp_path, "recent", {"engineered_mesh.gcode": b"G"}, age_days=2)
    _job(tmp_path, "ancient", {"engineered_mesh.gcode": b"G"}, age_days=40)

    doomed = outputs_mod.prunable(outputs_mod.scan(tmp_path), days=30)
    assert [job.job_id for job in doomed] == ["ancient"]


def test_a_parked_gate_snapshot_survives_the_age_rule(tmp_path):
    """A job can sit parked indefinitely; the image it asks about must outlive any retention."""
    _job(tmp_path, "parked", {"blueprint.png": b"png"}, age_days=400)
    assert outputs_mod.prunable(outputs_mod.scan(tmp_path), days=30) == []


def test_an_empty_gate_directory_is_still_pruned(tmp_path):
    """The gate always writes the blueprint, so an empty one is not a parked job."""
    _job(tmp_path, "parked-but-empty")
    doomed = outputs_mod.prunable(outputs_mod.scan(tmp_path), days=None)
    assert [job.job_id for job in doomed] == ["parked-but-empty"]


def test_remove_refuses_anything_that_is_not_a_job_directory(tmp_path):
    """The age mode deletes real artifacts, so containment is not decoration.

    `DS_OUTPUTS_DIR` is an environment variable and `--root` is an argument; either can
    name somewhere unexpected, and a symlink planted in the tree is a second route out.
    """
    root = tmp_path / "outputs"
    root.mkdir()
    elsewhere = _job(tmp_path, "elsewhere", {"precious.stl": b"solid"})
    stray = outputs_mod.describe(elsewhere)

    with pytest.raises(ValueError):
        outputs_mod.remove(stray, root)
    assert (elsewhere / "precious.stl").exists()

    link = root / "linked"
    link.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError):
        outputs_mod.remove(outputs_mod.describe(link), root)
    assert (elsewhere / "precious.stl").exists()


def test_remove_deletes_an_empty_directory_and_a_stale_one(tmp_path):
    empty = _job(tmp_path, "empty")
    stale = _job(tmp_path, "stale", {"engineered_mesh.gcode": b"G"})

    outputs_mod.remove(outputs_mod.describe(empty), tmp_path)
    outputs_mod.remove(outputs_mod.describe(stale), tmp_path)
    assert not empty.exists() and not stale.exists()


# ── The command line ──────────────────────────────────────────────────────────
def test_the_default_listing_names_the_empty_ones(tmp_path, capsys):
    _job(tmp_path, "empty")
    _job(tmp_path, "full", {"engineered_mesh.gcode": b"G"})

    assert outputs_mod.main(["--root", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert "empty" in printed and "full" in printed
    assert "1 empty" in printed
    assert (tmp_path / "empty").exists(), "listing must not delete anything"


def test_json_carries_the_resolved_columns(tmp_path, capsys):
    _job(tmp_path, "full", {"engineered_mesh.gcode": b"G", "spec.json": b"{}"})
    assert outputs_mod.main(["--root", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    (job,) = payload["jobs"]
    assert job["artifacts"] == {
        "bp": False, "spec": True, "mesh": False, "eng": False, "gcode": True, "score": False,
    }


def test_dry_run_removes_nothing(tmp_path, capsys):
    _job(tmp_path, "empty")
    assert outputs_mod.main(["--root", str(tmp_path), "--prune", "--dry-run"]) == 0
    assert "Would remove empty" in capsys.readouterr().out
    assert (tmp_path / "empty").exists()


def test_prune_removes_the_empty_ones_and_keeps_the_rest(tmp_path, capsys):
    _job(tmp_path, "empty")
    _job(tmp_path, "full", {"engineered_mesh.gcode": b"G"}, age_days=400)

    assert outputs_mod.main(["--root", str(tmp_path), "--prune"]) == 0
    assert not (tmp_path / "empty").exists()
    assert (tmp_path / "full" / "engineered_mesh.gcode").exists()


def test_prune_prints_every_path_before_deleting_by_age(tmp_path, capsys):
    """A count is not something a person can check against what they meant to type."""
    _job(tmp_path, "ancient", {"engineered_mesh.gcode": b"G"}, age_days=400)
    assert outputs_mod.main(["--root", str(tmp_path), "--prune", "--days", "30"]) == 0
    assert "Removing ancient" in capsys.readouterr().out
    assert not (tmp_path / "ancient").exists()


def test_days_without_prune_is_refused(tmp_path, capsys):
    _job(tmp_path, "ancient", {"engineered_mesh.gcode": b"G"}, age_days=400)
    assert outputs_mod.main(["--root", str(tmp_path), "--days", "30"]) == 2
    assert (tmp_path / "ancient").exists()


def test_the_root_honours_the_pipeline_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DS_OUTPUTS_DIR", str(tmp_path / "elsewhere"))
    assert outputs_mod.outputs_root() == tmp_path / "elsewhere"
    monkeypatch.delenv("DS_OUTPUTS_DIR")
    assert outputs_mod.outputs_root() == REPO_ROOT / "data" / "outputs"


def test_it_runs_with_nothing_installed(tmp_path):
    """Stdlib-only, and asserted by running it with the site directory cut off.

    A developer reaching for this is often the one whose environment is the problem;
    an import of trimesh or psycopg here would make the tool useless in exactly that
    case, and the import would be added by someone who never ran it that way.
    """
    _job(tmp_path, "full", {"engineered_mesh.gcode": b"G"})
    completed = subprocess.run(
        [sys.executable, "-S", "-m", "pythonsrc.outputs", "--root", str(tmp_path)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "full" in completed.stdout


# ── The documented commands ───────────────────────────────────────────────────
def test_the_make_targets_call_this_module():
    """`make outputs` / `make clean-outputs` are what the docs tell people to run."""
    makefile = (REPO_ROOT / "Makefile").read_text()
    for target in ("outputs:", "clean-outputs:"):
        body = makefile.split(f"\n{target}", 1)
        assert len(body) == 2, f"Makefile has no {target} target"
        assert "pythonsrc.outputs" in body[1].split("\n\n", 1)[0]
    assert "--prune" in makefile
