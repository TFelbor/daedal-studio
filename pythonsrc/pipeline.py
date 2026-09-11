"""
pipeline.py — Unified Daedal Studio entrypoint.

Chains Phases 1→2→3→4→5 in a single command:

    python pythonsrc/pipeline.py "a ceramic vase with geometric patterns"
    python pythonsrc/pipeline.py "a miniature chess knight" --target-mm 80 --hollow
    python pythonsrc/pipeline.py --skip-visualizer --blueprint /app/inputs/blueprint.png
    python pythonsrc/pipeline.py --skip-sculptor   --mesh /app/outputs/test_mesh.obj
    python pythonsrc/pipeline.py "a vase" --pipeline-type 1536_cascade --mesh-seed 7

Phase 5 (Operator) is triggered with --print / --octoprint-url.
Phase 4 (Slicer) converts the engineered .obj → .gcode before upload:

    python pythonsrc/pipeline.py "a chess knight" --print \\
        --octoprint-url http://localhost:5001 --octoprint-key MY_API_KEY --start-print \\
        --profile pythonsrc/profiles/ender3.json
"""

# ── MPS fallback — MUST be set before any torch import ────────────────────────
# Several MPS ops used by Phase 1's diffusion stack (e.g. upsample_bicubic2d) are
# not yet implemented on Apple Silicon. This flag makes PyTorch silently fall back
# to CPU for those ops. It must be in the environment *before* `import torch` is
# first executed in this process — hence it lives here at the very top, ahead of
# all other imports. Phase 2 does not need it: TRELLIS.2 is CUDA-only and never
# runs on MPS at all.
import os
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

# Phase 2's allocator setting, for the same reason and with a sharper deadline.
# TRELLIS.2 moves 4B parameters on and off the GPU per stage, and expandable
# segments are what keep that from fragmenting VRAM into an OOM. The CUDA caching
# allocator reads this once, when it initialises on the first CUDA allocation —
# which on a GPU host is Phase 1, long before the sculptor is constructed. Setting
# it inside the backend would therefore be too late to have any effect.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import sys
import time
import json
import traceback
import logging
import argparse
import asyncio
from pathlib import Path
from datetime import datetime, timezone

# Add the parent directory (project root or /app inside docker) to sys.path
# This ensures that "import pythonsrc.operators" works even when the script
# is invoked directly as "python pythonsrc/pipeline.py"
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from config import CURA_ENGINE_PATH, INPUTS_DIR, OUTPUTS_DIR
except ImportError:
    from pythonsrc.config import CURA_ENGINE_PATH, INPUTS_DIR, OUTPUTS_DIR

from pythonsrc.sculptors.base import DEFAULT_TARGET_FACES

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger("ds.pipeline")

# ── Phase banner helpers ──────────────────────────────────────────────────────
_PHASE_NAMES = {
    1: "Visualizer",
    2: "Sculptor",
    3: "Engineer",
    4: "Slicer",
    5: "Operator",
}

CURRENT_JOB_ID = None

#: Real Phase 1 and Phase 2 outputs, shipped with the source. A debugging run that
#: skips those phases installs these instead of fabricating something.
#:
#: The pipeline used to make its own stand-ins: a flat blue rectangle and a 50mm
#: `trimesh.creation.box`. A cube is watertight, convex, has no boundary edges, no
#: non-manifold edges, no thin walls and no overhangs — so Phase 3 had nothing to
#: repair, the printability gate scored geometry no reconstruction produces, the
#: adhesion rule never fired, and the slicer saw six faces instead of six figures.
#: Every defect the phases downstream exist to handle was absent from the only mesh
#: most dev runs ever saw. See `pythonsrc/assets/dev_reference/README.md`.
DEV_REFERENCE_DIR = Path(__file__).parent / "assets" / "dev_reference"
DEV_REFERENCE_BLUEPRINT = DEV_REFERENCE_DIR / "blueprint.png"
DEV_REFERENCE_MESH = DEV_REFERENCE_DIR / "raw_mesh.obj"

#: Prefix for the output directory of a run that installed one of those files.
#: `data/outputs/` holds real jobs and debugging runs side by side, and a mesh made
#: from a fixture must not be mistaken for one a model produced — by a person reading
#: the directory listing, or by anything that walks it later.
DEV_OUTPUT_PREFIX = "dev-"

#: The flat square earlier versions wrote in place of a blueprint, in both sizes they
#: used. No longer written, still recognised: those files persist on the *shared*
#: blueprint path, and the only thing stopping a per-generation backend from being
#: billed to reconstruct one is that this guard knows what they look like.
_LEGACY_PLACEHOLDER_SIZES = ((1024, 1024), (512, 512))
_PLACEHOLDER_COLOUR = (73, 109, 137)


def _install_dev_asset(source: Path, destination: Path, what: str) -> None:
    """Copy a bundled reference asset into place, or fail loudly.

    Args:
        source: The file under `assets/dev_reference/`.
        destination: Where the phase that was skipped would have written.
        what: Human name for the log line.

    Raises:
        FileNotFoundError: If the reference asset is missing. Silently continuing
            would leave the next phase reading whatever happened to be on disk.
    """
    if not source.exists():
        raise FileNotFoundError(
            f"The dev reference {what} is missing: {source}. It ships with the source; "
            "restore it, or supply a real file instead of skipping the phase."
        )
    import shutil

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    logger.warning(
        "Installed the dev reference %s at %s — this run's %s came from a fixture, "
        "not from a model.",
        what,
        destination,
        what,
    )


def _should_install_reference_blueprint(args, blueprint_path: Path) -> bool:
    """Whether this run needs the bundled blueprint stood in for Phase 1.

    True when Phase 1 was skipped with nothing at that path — including when Phase 2 is
    skipped as well. That last case used to be excluded (`and not args.skip_sculptor`),
    on the reasoning that a skipped Phase 2 has nothing to hand the image to. It is the
    commonest dev configuration there is: both `SKIP_VISUALIZER` and `SKIP_SCULPTOR` set
    in the config store is how the UI runs Phases 3-5 on a machine with no GPU. Those
    runs installed the reference mesh, no blueprint, and said nothing — exit 0, a `dev-`
    directory holding `raw_mesh.obj` alone, an empty blueprint stage in the running view
    and NULL for every Phase 1 provenance column. Phase 2 is not the blueprint's only
    consumer.

    False when `--mesh` supplied the geometry. That run is not a fixture run — nothing
    in it came from `assets/dev_reference/`, so `_will_use_reference_assets` is False and
    its outputs land in the real namespace. Standing a blueprint in there would put a
    fabricated input beside real artifacts and record its hash as this job's Phase 1
    provenance, which is the one thing the `dev-` prefix exists to prevent.

    Args:
        args: Parsed CLI arguments.
        blueprint_path: Where Phase 1's output is expected.

    Returns:
        True if the bundled reference blueprint should be copied to `blueprint_path`.
    """
    if getattr(args, "spec", None):
        # There was never an image. Inventing one would stamp a fixture's hash as this
        # job's Phase 1 provenance.
        return False
    if not args.skip_visualizer:
        return False
    if blueprint_path.exists():
        return False
    return not args.mesh


def _blueprint_is_stand_in(path: Path) -> bool:
    """True when this image is a stand-in rather than something Phase 1 rendered.

    Two kinds, and both matter. The bundled reference blueprint is matched by hash —
    it is a real image, so nothing about its pixels gives it away, and it is a file
    this repo controls byte for byte. The flat rectangles earlier versions wrote are
    matched by `_blueprint_is_placeholder` below.

    The check is by content, not by remembering that this run installed it: a stand-in
    goes to the *shared* blueprint path and then persists, so the next run finds a
    file that exists and cannot otherwise tell it from a fresh render. That is how a
    flat blue rectangle came to be sent repeatedly to a backend billed per generation.
    """
    if not path.exists():
        return False
    if DEV_REFERENCE_BLUEPRINT.exists():
        if _file_sha256(path) == _file_sha256(DEV_REFERENCE_BLUEPRINT):
            return True
    return _blueprint_is_placeholder(path)


def _blueprint_is_placeholder(path: Path) -> bool:
    """True when this image is one of the flat rectangles earlier versions wrote.

    Pixels rather than a hash so the check survives a Pillow upgrade re-encoding the
    same image differently — these files were written by code that is gone, and the
    ones on disk are the only copies there will ever be.
    """
    try:
        from PIL import Image

        with Image.open(path) as img:
            if img.size not in _LEGACY_PLACEHOLDER_SIZES:
                return False
            colours = img.convert("RGB").getcolors(maxcolors=2)
    except Exception:
        return False

    return bool(colours) and len(colours) == 1 and colours[0][1] == _PLACEHOLDER_COLOUR

def _write_status(phase_num: int, status: str, error: str = None) -> None:
    if not CURRENT_JOB_ID:
        return
    log_dir_env = os.environ.get("DS_LOGS_DIR")
    log_dir = Path(log_dir_env) if log_dir_env else (Path.home() / ".ds-mvp" / "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    status_file = log_dir / f"{CURRENT_JOB_ID}.status"
    
    name = _PHASE_NAMES.get(phase_num, "unknown").lower()
    record = {
        "phase": phase_num,
        "name": name,
        "status": status,
        "ts": datetime.now(timezone.utc).isoformat()
    }
    if error is not None:
        record["error"] = error
        
    with open(status_file, "a") as f:
        f.write(json.dumps(record) + "\n")
        f.flush()


#: Brim width when the measured first-layer footprint is too small. Cura's own
#: default, and about 20 extruded lines at a 0.4mm nozzle.
BRIM_WIDTH_MM = 8.0

#: Nozzle width assumed when the process profile does not state one. Only used to
#: turn BRIM_WIDTH_MM into a line count.
DEFAULT_NOZZLE_MM = 0.4


def _adhesion_args(report, profile=None) -> list[str]:
    """Slice with a brim when the part's own footprint will not hold it down.

    A part with a flat base is held by its own first layer, and the printer
    profiles ask for a *skirt* — which primes the nozzle and touches nothing.
    That is useless for anything standing on a small base: a real job reached the
    plate with a 6mm² footprint against the 25mm² the process profile wants, and
    `bed_contact` had been warning about exactly that while the slicer ignored it.

    A brim is the right mechanism rather than a modelled plinth: it is one flat
    ring of material around the first layer, it peels off, and it does not alter
    the object someone asked for. Generated base geometry would print a part that
    is not the part they requested, and would still have to be cut off.

    Switched on from the measurement rather than always, because a brim on a part
    that does not need one is wasted filament and a finishing job.

    **The knob is `brim_line_count`, not `brim_width`.** `brim_width` is a Cura
    *frontend* setting: the UI divides it by the line width and hands CuraEngine
    the count. CuraEngine itself never reads the width, so the override this
    function used to emit did nothing at all. Measured with CuraEngine 4.13 on the
    bundled definitions: `brim_line_count=5` produced 119 adhesion moves, `=20`
    produced 907, and `brim_width=2` on its own produced exactly the default.

    Args:
        report: The printability report, or None when scoring was skipped.
        profile: The `ProcessProfile` the mesh was scored against, used for its
            nozzle width. None falls back to `DEFAULT_NOZZLE_MM`.

    Returns:
        CuraEngine arguments, empty when the footprint is already sufficient.
    """
    if report is None:
        return []
    bed = next((c for c in report.checks if c.check == "bed_contact"), None)
    if bed is None or bed.status == "pass":
        return []
    nozzle = getattr(profile, "nozzle_diameter_mm", None) or DEFAULT_NOZZLE_MM
    line_count = max(1, round(BRIM_WIDTH_MM / nozzle))
    logger.info(
        "Adding a %.0fmm brim (%d lines at a %.2fmm nozzle) — %s",
        BRIM_WIDTH_MM,
        line_count,
        nozzle,
        bed.detail,
    )
    print(
        f"[DS] Adhesion: brim {BRIM_WIDTH_MM:.0f}mm / {line_count} lines "
        "(small first-layer footprint)",
        flush=True,
    )
    return ["-s", "adhesion_type=brim", "-s", f"brim_line_count={line_count}"]


def _record_generation(args, model, model_version, backend, params, cost_eur, duration_s) -> None:
    """Persist which model produced this job's mesh, and what it cost.

    A hosted, pay-per-generation backend (e.g. TRELLIS.2 on fal.ai) makes cost and
    latency per-generation facts that cannot be reconstructed later, and a model swap
    otherwise mixes two populations in one dataset with nothing to tell them apart.
    The same applies to *where* a self-hosted model ran: a `remote_worker` job's
    duration includes upload and queueing, so mixing it with `local` timings without
    a label makes both meaningless.

    Reads its values off the sculptor when present, so swapping in a new backend means
    setting MODEL_NAME / MODEL_VERSION / BACKEND / last_generation_cost_eur on it rather
    than touching the pipeline.

    Args:
        args: Parsed CLI arguments; nothing is recorded without --job-id.
        model: Model name, e.g. "TRELLIS.2".
        model_version: Version, revision or hosted endpoint id.
        backend: "local", "remote_worker" or "hosted_api".
        params: Generation settings used.
        cost_eur: Charge for this generation in euro, if the backend bills per call.
        duration_s: Wall-clock generation seconds.
    """
    if not args.job_id:
        return
    try:
        from pythonsrc.telemetry.db import TelemetryDB

        db = TelemetryDB()
        db.update_job_generation(
            args.job_id,
            model=model,
            model_version=model_version,
            backend=backend,
            params=params,
            cost_eur=cost_eur,
            duration_s=duration_s,
        )
        db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record generation provenance: %s", exc)


def _resolve_git_sha() -> str | None:
    """The commit of the code running this job, or None when unknowable.

    Delegates to the shared torch-free helper so the server (which stamps
    `$DS_GIT_SHA` into container subprocesses) and the pipeline resolve the
    value the same way.
    """
    from pythonsrc.telemetry.run_context import resolve_git_sha

    return resolve_git_sha()


def _record_run_context(args, used_reference_assets: bool) -> None:
    """Persist which code ran this job and whether its inputs were real.

    The fixture flag exists only in this process's head: the output directory's
    `dev-` prefix says it on disk, but nothing queryable said it in the database,
    so a training query could not exclude fixture runs without comparing hashes
    by hand. False is recorded too — "verified real" is not the same row state as
    "predates the column".

    Args:
        args: Parsed CLI arguments; nothing is recorded without --job-id.
        used_reference_assets: Whether a bundled dev-reference asset stands in
            for a phase's output on this run.
    """
    if not args.job_id:
        return
    try:
        from pythonsrc.telemetry.db import TelemetryDB

        db = TelemetryDB()
        db.update_job_run_context(
            args.job_id,
            git_sha=_resolve_git_sha(),
            used_reference_assets=used_reference_assets,
        )
        db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record run context: %s", exc)


def _file_sha256(path) -> str | None:
    """Hash a file's contents.

    Args:
        path: Path to the file.

    Returns:
        The lowercase hex digest, or None if the file cannot be read.
    """
    import hashlib

    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        logger.warning("Could not hash %s: %s", path, exc)
        return None


def _record_blueprint(args, blueprint_path, result=None) -> None:
    """Persist how this job's blueprint was produced.

    The seed is the reason this exists. It used to be derived from the wall clock
    inside the visualizer and discarded, so no result in the system could be
    reproduced or compared against another. `result` is None when Phase 1 was skipped
    and the image came from elsewhere; the hash is still recorded, because it is the
    only thing that identifies a user-supplied blueprint.

    Args:
        args: Parsed CLI arguments; nothing is recorded without --job-id.
        blueprint_path: Path to the blueprint PNG.
        result: The visualizer's BlueprintResult, when Phase 1 ran.
    """
    if not args.job_id:
        return
    try:
        from pythonsrc.telemetry.db import TelemetryDB

        db = TelemetryDB()
        db.update_job_blueprint(
            args.job_id,
            model=getattr(result, "model_id", None),
            model_version=getattr(result, "model_id", None),
            seed=getattr(result, "seed", None),
            prompt_engineered=getattr(result, "engineered_prompt", None),
            params=getattr(result, "params", None),
            sha256=_file_sha256(blueprint_path),
            duration_s=getattr(result, "duration_s", None),
        )
        db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record blueprint provenance: %s", exc)


def _profile_nozzle_mm(args) -> float:
    """The nozzle the spec's wall floor is derived from, in mm.

    Read off the same printer profile Phase 3.5 and the slicer read, through
    `ProcessProfile.from_printer_profile` so `machine_nozzle_size` has one reader on
    the pipeline side. (`server/app.py`'s `_profile_snapshot` reads the key a second
    time, for the job record, with its own silent 0,4 fallback; routing it through
    `ProcessProfile` too is follow-up work, not this phase's.) Phase 2 is the first
    place in the run that needs it: the wall floor is a property of the machine, and a
    wall the nozzle cannot lay down should be refused before a mesh is built for it,
    not after (`archetypes.compile_spec`).

    An unreadable profile falls back to the `ProcessProfile` default rather than
    failing the phase: no profile has ever meant "no printer" here, and the floor at
    0,4 mm is the one every bundled profile declares anyway.
    """
    try:
        from printability import ProcessProfile
    except ImportError:
        from pythonsrc.printability import ProcessProfile

    profile_path = args.profile or "pythonsrc/profiles/ender3.json"
    try:
        with open(profile_path, "r") as handle:
            return ProcessProfile.from_printer_profile(json.load(handle)).nozzle_diameter_mm
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Could not read %s for the nozzle diameter (%s) — using the FDM default.",
            profile_path, exc,
        )
        return ProcessProfile().nozzle_diameter_mm


def _compile_spec_phase(args, outputs_dir: Path):
    """Phase 2 for a spec run: compile the spec into the job directory.

    Writes three files beside each other so the job directory explains itself:
    `compiled_mesh.stl` (what Phase 3 receives), `spec.json` (the spec in canonical,
    sorted form — the saved object, F11) and `compile_features.json` (every designed
    dimension, the part list, the archetype and version, the spec hash). Nothing here
    is a fixture, so the caller's `outputs_dir` is the real namespace.

    The printer profile's nozzle is handed to the compiler, which is the whole of
    issue #72's plumbing: `process.wall_mm` is held to three extrusion widths of *this*
    machine's nozzle, and the archetype's own default applies when the spec states no
    wall at all. `spec.json` is written after the compile, so a refused spec leaves no
    canonical file claiming to describe a part that was never built.

    Args:
        args: Parsed CLI arguments; `args.spec` names the spec file and
            `args.profile` the printer.
        outputs_dir: The job's output directory.

    Returns:
        The compiled mesh path and the `CompileResult`.

    Raises:
        SpecError: If the file is not a spec, the archetype refuses it, or the wall is
            below the nozzle-derived floor.
    """
    try:
        from organizer.spec import load_spec, dump_spec
        from organizer.archetypes import compile_spec
        from organizer.compiler import export_stl
    except ImportError:
        from pythonsrc.organizer.spec import load_spec, dump_spec
        from pythonsrc.organizer.archetypes import compile_spec
        from pythonsrc.organizer.compiler import export_stl

    spec = load_spec(args.spec)
    result = compile_spec(spec, nozzle_diameter_mm=_profile_nozzle_mm(args))
    _ensure_outputs_dir(outputs_dir)
    mesh_path = export_stl(result.mesh, outputs_dir / "compiled_mesh.stl")
    dump_spec(spec, outputs_dir / "spec.json")
    (outputs_dir / "compile_features.json").write_text(
        json.dumps(result.features_document(), indent=2, sort_keys=True) + "\n"
    )
    print(
        f"[DS] Compiled {result.archetype} v{result.archetype_version} "
        f"(spec {result.spec_hash[:12]}, {len(result.parts)} parts, "
        f"{len(result.mesh.faces)} faces) → {mesh_path}",
        flush=True,
    )
    return mesh_path, result


def _record_spec_generation(args, result, duration_s: float) -> None:
    """Record the compiler as this job's generation model.

    `generation_model` records what actually made the mesh, and for a spec run that is
    the archetype — no weights, no cost, `local` backend. The spec hash rides in
    `generation_params` so the row can be joined back to the exact spec without a new
    column; `blueprint_*` stay NULL, which is correct, because no image ever existed.
    """
    _record_generation(
        args,
        model=f"organizer/{result.archetype}",
        model_version=result.archetype_version,
        backend="local",
        params={"schema_version": 1, **result.features_document()},
        cost_eur=None,
        duration_s=round(duration_s, 3),
    )


def _record_mesh_lineage(args, raw_mesh_path, repaired_mesh_path, repair_report=None) -> None:
    """Persist a before/after description of the mesh around repair.

    Repair is the pipeline's least observable step: it can rescue a broken mesh or
    mangle a sound one, and afterwards only the result survives. Hashes plus feature
    snapshots make the difference measurable without keeping the geometry.

    Wall thickness is skipped on the raw mesh: it is the expensive measurement, and
    the raw mesh has not been scaled to millimetres yet, so the number would be
    meaningless as well as slow.

    Args:
        args: Parsed CLI arguments; nothing is recorded without --job-id.
        raw_mesh_path: The sculptor's output, before repair.
        repaired_mesh_path: The engineer's output, after repair.
        repair_report: `Engineer.last_report` — which repair path ran and the
            scale factor applied, previously visible only in the log.
    """
    if not args.job_id:
        return
    try:
        import trimesh

        try:
            from printability import extract_features
        except ImportError:
            from pythonsrc.printability import extract_features
        from pythonsrc.telemetry.db import TelemetryDB

        def describe(path, *, thickness):
            if not Path(path).exists():
                return None, None
            try:
                mesh = trimesh.load(str(path), force="mesh")
                return _file_sha256(path), extract_features(mesh, thickness=thickness)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not describe mesh %s: %s", path, exc)
                return _file_sha256(path), None

        raw_hash, raw_features = describe(raw_mesh_path, thickness=False)
        repaired_hash, repaired_features = describe(repaired_mesh_path, thickness=True)

        db = TelemetryDB()
        db.update_job_mesh_lineage(
            args.job_id,
            raw_sha256=raw_hash,
            raw_features=raw_features,
            repaired_sha256=repaired_hash,
            repaired_features=repaired_features,
            repair_report=repair_report,
        )
        db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record mesh lineage: %s", exc)


def _record_printability_failure(args, outputs_dir, exc) -> None:
    """Persist the fact that scoring itself broke.

    Printability is advisory, so a crash in the scorer must never fail the job — which
    used to mean it left no trace at all: no artifact, no telemetry row, nothing. The UI
    then could not tell "nothing measured this mesh" from "the measurement broke", and
    rendered both as the same empty panel. An empty quality panel reads as a clean one,
    which is the one thing a gate must not look like.

    The envelope is deliberately *not* a PrintabilityReport. There is no score, and
    inventing one — 0 for safety, 100 for convenience — would be a fabricated
    measurement in the column the pilot is measured from. It carries the reason instead,
    which is the only part anyone can act on.

    Args:
        args: Parsed CLI arguments; telemetry is only written with --job-id.
        outputs_dir: The job's output directory, where the artifact is written.
        exc: The exception the scorer raised.
    """
    envelope = {
        "job_id": args.job_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "status": "error",
        "error": str(exc) or exc.__class__.__name__,
        "error_type": exc.__class__.__name__,
    }

    try:
        with open(_ensure_outputs_dir(Path(outputs_dir)) / "printability.json", "w") as f:
            json.dump(envelope, f, indent=2)
    except Exception as write_exc:  # noqa: BLE001
        logger.warning("Could not write the printability failure artifact: %s", write_exc)

    if not args.job_id:
        return
    try:
        from pythonsrc.telemetry.db import TelemetryDB

        db = TelemetryDB()
        db.update_job_printability(args.job_id, report=envelope)
        db.close()
    except Exception as db_exc:  # noqa: BLE001
        logger.warning("Could not persist the printability failure: %s", db_exc)


def _record_slice(args, gcode_path, duration_s, status="success", error=None, extra_args=None) -> None:
    """Persist the slicer's verdict and its material estimates.

    Called on failure as well as success: "this mesh could not be sliced" is a result,
    and a dataset that only contains successful slices cannot be used to predict which
    meshes will fail.

    Statistics come from `gcode_stats`, which derives them from the E axis rather than
    the G-code header — CuraEngine's CLI leaves the header's filament figure at zero.

    Args:
        args: Parsed CLI arguments; nothing is recorded without --job-id.
        gcode_path: The produced G-code, when the slice succeeded.
        duration_s: Wall-clock slicing seconds.
        status: "success", "failed" or "skipped".
        error: Slicer error text, when it failed.
        extra_args: CuraEngine overrides this run added (e.g. the brim decision).
            Recorded because the profile alone no longer describes the slice, and
            "did the adhesion brim help" is a question the dataset must answer.
    """
    if not args.job_id:
        return
    try:
        from pythonsrc.telemetry.db import TelemetryDB

        stats = None
        if status == "success" and gcode_path and Path(gcode_path).exists():
            try:
                try:
                    from gcode_stats import parse_gcode_file
                except ImportError:
                    from pythonsrc.gcode_stats import parse_gcode_file

                stats = parse_gcode_file(
                    gcode_path,
                    filament_diameter_mm=_filament_diameter(args),
                    material_type=getattr(args, "material_type", None),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not parse G-code statistics: %s", exc)

        stats_payload = stats.to_dict() if stats else {}
        if extra_args:
            stats_payload["slicer_overrides"] = list(extra_args)

        db = TelemetryDB()
        db.update_job_slice(
            args.job_id,
            status=status,
            error=error,
            duration_s=round(duration_s, 2),
            estimated_print_time_s=getattr(stats, "estimated_print_time_s", None),
            filament_used_mm=getattr(stats, "filament_used_mm", None),
            filament_used_mm3=getattr(stats, "filament_used_mm3", None),
            filament_used_g=getattr(stats, "filament_used_g", None),
            support_filament_mm3=getattr(stats, "support_filament_mm3", None),
            layer_count=getattr(stats, "layer_count", None),
            stats=stats_payload or None,
        )
        db.close()

        if stats:
            print(
                f"[DS] Slice stats: {stats.filament_used_mm / 1000:.2f}m filament, "
                f"{stats.layer_count} layers, ~{(stats.estimated_print_time_s or 0) / 60:.0f}min",
                flush=True,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record slice statistics: %s", exc)


def _filament_diameter(args) -> float:
    """Resolve the filament diameter to convert extruded length into volume.

    Args:
        args: Parsed CLI arguments, whose --profile may name a printer profile.

    Returns:
        The diameter in millimetres, defaulting to 1.75 when the profile is silent.
    """
    try:
        from gcode_stats import DEFAULT_FILAMENT_DIAMETER_MM
    except ImportError:
        from pythonsrc.gcode_stats import DEFAULT_FILAMENT_DIAMETER_MM

    profile_path = getattr(args, "profile", None)
    if not profile_path:
        return DEFAULT_FILAMENT_DIAMETER_MM
    try:
        with open(profile_path, "r") as handle:
            return float(json.load(handle).get("material_diameter", DEFAULT_FILAMENT_DIAMETER_MM))
    except Exception:  # noqa: BLE001
        return DEFAULT_FILAMENT_DIAMETER_MM


def _should_stop_after(stop_after_phase: int | None, phase_num: int) -> bool:
    """Whether the run must end now that *phase_num* has completed.

    Inclusive of the named phase: `--stop-after-phase 1` means Phase 1 ran and nothing
    after it may. The comparison is `>=` rather than `==` so a stop point that is never
    reached exactly — because an earlier phase was skipped — still stops the run rather
    than silently running to the end.

    Args:
        stop_after_phase: The requested stop point, or None to run everything.
        phase_num: The phase that has just completed.

    Returns:
        True when the run should exit cleanly here.
    """
    if stop_after_phase is None:
        return False
    return phase_num >= stop_after_phase


def _stop_here(phase_num: int, reason: str) -> None:
    """End the run cleanly after a completed phase, saying why.

    Exits 0: this is a run that did what it was asked, not a failure. The banner is
    deliberately in the printability form (`─── NAME ───`) and **not** the phase form
    (`═══ PHASE n ═══`), which the server parses into progress updates — a gate is a
    note about a phase, not a phase.
    """
    print(f"[DS] ─── STOPPED AFTER PHASE {phase_num} ─── {reason}", flush=True)
    sys.exit(0)


def _phase_start(phase_num: int) -> float:
    """Print a phase start banner and return the start timestamp."""
    name = _PHASE_NAMES.get(phase_num, "Unknown")
    print(f"\n[DS] ═══ PHASE {phase_num} START: {name} ═══", flush=True)
    return time.time()


def _phase_pass(phase_num: int, start_time: float, output_path: str = "") -> None:
    """Print a phase pass banner with timing and output path."""
    elapsed = time.time() - start_time
    name = _PHASE_NAMES.get(phase_num, "Unknown")
    out_info = f" (output: {output_path})" if output_path else ""
    print(f"[DS] ═══ PHASE {phase_num} PASS  ✓{out_info} ═══", flush=True)
    print(f"[DS] Phase {phase_num} duration: {elapsed:.1f}s", flush=True)
    _write_status(phase_num, "complete")


def _phase_fail(phase_num: int, start_time: float, exc: Exception) -> None:
    """Print a phase fail banner with traceback, then exit."""
    elapsed = time.time() - start_time
    name = _PHASE_NAMES.get(phase_num, "Unknown")
    print(f"[DS] ═══ PHASE {phase_num} FAIL  ✗ ═══", flush=True)
    print(f"[DS] Phase {phase_num} duration: {elapsed:.1f}s", flush=True)
    print(f"[DS] ERROR: {exc}", flush=True)
    print(f"[DS] TRACEBACK:", flush=True)
    traceback.print_exc()
    _write_status(phase_num, "error", str(exc))
    sys.exit(1)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="[%(levelname)s] %(name)s — %(message)s",
        level=level,
    )


def _will_use_reference_assets(args, blueprint_path: Path, mesh_candidates: list[Path]) -> bool:
    """Whether this run will stand a bundled fixture in for a model's output.

    True exactly when a skipped phase has nothing real to work from. That is a
    narrower thing than "a phase was skipped": the primary Mac workflow always passes
    `--skip-visualizer` because Phase 1 ran natively a moment earlier, and its
    blueprint is as real as they get. Likewise `--skip-sculptor --mesh real.obj`.

    Args:
        args: Parsed CLI arguments.
        blueprint_path: Where Phase 1's output is expected.
        mesh_candidates: Every path Phase 2's output could already be at.

    Returns:
        True if the blueprint or the mesh will come from `assets/dev_reference/`.
    """
    if getattr(args, "spec", None):
        # A spec run compiles its own geometry and substitutes nothing. Its outputs
        # belong in the real namespace: nothing in them came from a fixture.
        return False
    if args.skip_visualizer and not blueprint_path.exists():
        return True
    if args.skip_sculptor and not any(path.exists() for path in mesh_candidates):
        return True
    return False


def _apply_spec_mode(args: argparse.Namespace) -> argparse.Namespace:
    """Make `--spec` mean what it says, and refuse what it cannot mean.

    A spec run *is* the documented `--skip-visualizer --skip-sculptor --mesh --no-scale`
    seam with the compile step in front of it, so the three flags are implied rather than
    required — asking a person to type them is asking for the run that forgets
    `--no-scale` and prints a 50 mm deck box. Two combinations are refused rather than
    resolved: `--mesh` is a second source of geometry, and `--hollow` voxelises at a
    pitch and re-scales, which cannot honour authored dimensions (`Engineer.process`
    refuses it too; refusing here names the reason before anything runs).

    Raises:
        ValueError: Naming the offending flag.
    """
    if not getattr(args, "spec", None):
        return args
    if args.mesh:
        raise ValueError("--spec and --mesh both supply the geometry; pass one of them")
    if args.hollow:
        raise ValueError(
            "--spec refuses --hollow: a compiled spec's dimensions are final, and "
            "hollowing voxelises then re-scales. Model the cavity in the spec instead."
        )
    if args.blueprint:
        # Dropped, not refused: the server's mps_native strategy hardcodes this flag for
        # every containerised run. A spec run has no image, and reading the shared path
        # would snapshot whichever job's render sits there and record its hash as this
        # job's Phase 1 provenance.
        logger.warning(
            "--spec ignores --blueprint %s: a compiled spec has no image, so nothing is "
            "read, snapshotted or hashed from it.", args.blueprint,
        )
        args.blueprint = None
    args.skip_visualizer = True
    args.skip_sculptor = True
    args.no_scale = True
    return args


def _repair_mode_for(args) -> str:
    """Which of `Engineer.REPAIR_MODES` Phase 3 runs: "assert" for a spec, else "repair".

    A reconstruction arrives torn and repair is the service. A compiled mesh is
    watertight by construction, so a defect is a compiler bug and repairing it hides
    the bug — the voxel escalation rebuilds the surface at a pitch that discards the
    dimensions the spec fixed. `--mesh` stays on the repair path: a mesh of one's own
    made no promise about its topology.
    """
    return "assert" if getattr(args, "spec", None) else "repair"


def _assert_spec_dimensions(compile_result, engineered_path: Path, outputs_dir: Path) -> dict:
    """Measure Phase 3's output against the spec and refuse it if it drifted.

    The dimensional half of the assertion. `compile_features.json` says what was
    designed; this reads what the slicer will receive — the engineered mesh, after
    orientation, as exported — with the archetype's own `measure()` and compares every
    feature it promises to read back, at `DEFAULT_TOLERANCE_MM` (PRD N1).

    Three things about the order. The spec is reloaded from `spec.json` in the job
    directory — what Phase 2 recorded — not from the argument, so a file edited between
    phases cannot move the goalposts. `dimension_report.json` is written **before** the
    verdict, so a failure leaves the numbers behind to read. And the verdict is a raised
    `MeasureError`, which the caller's `_phase_fail(3)` turns into a failed Phase 3: a
    spec run that ships a wrong dimension has failed, however watertight it is.

    Args:
        compile_result: Phase 2's `CompileResult` (the designed features).
        engineered_path: Phase 3's exported mesh.
        outputs_dir: The job directory holding `spec.json`; the report is written here.

    Returns:
        The report as written, for `last_report["dimension_check"]`.

    Raises:
        MeasureError: If any required feature is missing or out of tolerance, or the
            mesh does not have the planes the design says it has.
        FileNotFoundError: If Phase 2's `spec.json` is not in the job directory.
    """
    try:
        from organizer.spec import load_spec
        from organizer.archetypes import verify_spec_mesh
        from organizer.compiler import MeasureError
    except ImportError:
        from pythonsrc.organizer.spec import load_spec
        from pythonsrc.organizer.archetypes import verify_spec_mesh
        from pythonsrc.organizer.compiler import MeasureError
    import trimesh

    spec = load_spec(outputs_dir / "spec.json")
    mesh = trimesh.load(str(engineered_path), force="mesh")
    report = verify_spec_mesh(spec, compile_result.features, mesh)
    document = report.to_dict()
    (outputs_dir / "dimension_report.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    max_err = document["max_abs_error_mm"]
    print(
        f"[DS] Dimensions: {document['features_within']}/{document['features_checked']} designed "
        f"features within ±{report.tolerance_mm:g} mm of the spec"
        + (f" (max error {max_err:.6f} mm)" if max_err is not None else ""),
        flush=True,
    )
    for problem in report.problems():
        print(f"[DS]   ✗ {problem}", flush=True)
    if not report.within_tolerance:
        raise MeasureError(
            "Phase 3's output does not match the spec: " + "; ".join(report.problems())
            + f". See {outputs_dir / 'dimension_report.json'}."
        )
    return document


def _blueprint_path(args, inputs_root: Path) -> Path:
    """Where this run's blueprint is written and read.

    **A job gets its own directory.** `data/inputs/blueprint.png` is one path shared
    by every run on the machine, and Phase 1 writes it in place. Two jobs started
    close together therefore race for it, and the loser sculpts, slices and prints
    the winner's image while recording its own prompt and seed against it — a
    mislabelled row in the one dataset this project exists to collect, and on a
    per-generation sculptor backend, money spent reconstructing the wrong picture.
    Nothing downstream can notice: the file exists, it is a real render, and its
    hash is whatever was written last.

    The per-job snapshot `run()` takes afterwards does not fix this. It copies
    whichever image won the race into the job's output directory, which preserves
    the mistake rather than preventing it.

    The provenance sidecar shares the directory for the same reason. `read_sidecar`
    refuses a sidecar whose recorded hash does not match the image beside it, so a
    race cost the *winner* its seed and engineered prompt as well — the loser's
    sidecar was the one left on disk.

    Two paths deliberately stay flat. A run without a `--job-id` is manual CLI use
    and keeps the old layout, and an explicit `--blueprint` always wins: that is how
    a caller supplies its own image, and how the skip-Phase-1 configuration reuses
    the one already sitting at the shared path.

    Args:
        args: Parsed CLI arguments.
        inputs_root: `data/inputs`.

    Returns:
        The blueprint path. Its parent is not created here.
    """
    if args.blueprint:
        return Path(args.blueprint)
    if args.job_id:
        return inputs_root / args.job_id / "blueprint.png"
    return inputs_root / "blueprint.png"


def _job_outputs_dir(args, outputs_root: Path, blueprint_path: Path) -> Path:
    """Choose this job's output directory, and say in its name where the assets came from.

    A run that installs a reference asset writes to `dev-{job_id}`. Without that,
    `data/outputs/` mixes real jobs with debugging runs and nothing distinguishes them:
    the artifacts have the same filenames, the same shapes and the same job-id-looking
    parent, so a mesh that came from a fixture reads exactly like one a model made.

    An existing directory always wins, so re-running the same job id cannot split one
    job's artifacts across two locations. The one exception is a directory holding
    *only* a blueprint snapshot and its sidecar: that is the approval gate's work,
    created before Phase 2 has run, and treating it as a claim on the plain namespace
    would let a run that then substitutes a fixture mesh write into
    `data/outputs/{job_id}` — the one thing the `dev-` prefix exists to prevent.

    Args:
        args: Parsed CLI arguments; `job_id` must be set.
        outputs_root: `data/outputs`.
        blueprint_path: Where Phase 1's output is expected.

    Returns:
        The directory to write into. Not created here.
    """
    plain = outputs_root / args.job_id
    dev = outputs_root / f"{DEV_OUTPUT_PREFIX}{args.job_id}"
    if dev.exists():
        return dev
    if plain.exists():
        contents = list(plain.iterdir())
        # A directory holding *only* a blueprint snapshot is the approval gate's work,
        # not a previous run's output. An empty one still counts as claimed — that is
        # the pre-existing contract and nothing is being split by honouring it.
        snapshot_only = bool(contents) and all(
            child.name == "blueprint.png" or child.name.endswith(".provenance.json")
            for child in contents
        )
        if not snapshot_only:
            return plain
    mesh_candidates = [Path(args.mesh)] if args.mesh else [plain / "raw_mesh.obj", dev / "raw_mesh.obj"]
    return dev if _will_use_reference_assets(args, blueprint_path, mesh_candidates) else plain


def _ensure_outputs_dir(outputs_dir: Path) -> Path:
    """Create the job's output directory, at the moment something is about to write.

    Called from the write, never from the setup. Creating it up front left one behind
    for every run that died before Phase 2 produced anything — a compose mount error, a
    spec the archetype refuses, a killed container — and nothing ever revisits or prunes
    those, so `data/outputs` filled with UUID-named directories that hold nothing and
    say nothing about which of their neighbours do. Removing the directory on the way
    out cannot cover it: `_phase_fail` exits, but a SIGKILLed container runs no handler
    at all, and that is one of the three cases.

    Most of the writers do this for themselves already — `Engineer.export_mesh`,
    `SculptorBackend.postprocess`, `CuraSlicer.slice` and `_install_dev_asset` each
    create their output's parent — so this is for the four writes `pipeline.py` performs
    directly: the blueprint snapshot, the compiled spec's artifacts, the printability
    report and the envelope written when scoring it crashes.

    Args:
        outputs_dir: The directory chosen by `_job_outputs_dir`, or flat `data/outputs`.

    Returns:
        `outputs_dir`, so a write can be expressed as one statement.
    """
    outputs_dir.mkdir(parents=True, exist_ok=True)
    return outputs_dir


# ── Pipeline ──────────────────────────────────────────────────────────────────
def run(args: argparse.Namespace) -> None:
    pipeline_start = time.time()

    os.makedirs(INPUTS_DIR, exist_ok=True)
    os.makedirs(OUTPUTS_DIR, exist_ok=True)

    # Resolved before the output directory, because whether this run is a debugging one
    # depends on whether a real blueprint is already sitting there.
    blueprint_path = _blueprint_path(args, Path(INPUTS_DIR))
    blueprint_path.parent.mkdir(parents=True, exist_ok=True)

    # Per-job output directory. Without this every job overwrites the same
    # engineered_mesh.* files, so downloading job A's G-code can hand you job B's.
    # Runs without a --job-id (manual CLI use) keep the flat layout.
    # Chosen here, created at the first write (`_ensure_outputs_dir`). Creating it here
    # left an empty directory behind for every run that died before anything was
    # produced, and nothing prunes those.
    if args.job_id:
        outputs_dir = _job_outputs_dir(args, Path(OUTPUTS_DIR), blueprint_path)
    else:
        outputs_dir = Path(OUTPUTS_DIR)

    if args.spec:

        raw_mesh_path = outputs_dir / "compiled_mesh.stl"

    else:

        raw_mesh_path = Path(args.mesh) if args.mesh else outputs_dir / "raw_mesh.obj"
    final_mesh_path = outputs_dir / "engineered_mesh.obj"
    gcode_path = outputs_dir / "engineered_mesh.gcode"

    # Written before any phase runs: the fixture decision and the code version are
    # facts about this run, not about any phase's outcome, and a run that dies in
    # Phase 1 should still be excludable from (or attributable in) the dataset.
    if args.job_id:
        _record_run_context(
            args,
            used_reference_assets=(
                outputs_dir.name.startswith(DEV_OUTPUT_PREFIX)
                or _will_use_reference_assets(args, blueprint_path, [raw_mesh_path])
            ),
        )

    # ── Phase 1: Visualizer ───────────────────────────────────────────────────
    # True when the blueprint is a stand-in rather than a render. Phase 2 consults it
    # before handing the image to a backend that charges per generation.
    blueprint_is_stand_in = False

    if not args.skip_visualizer:
        if not args.prompt:
            logger.error("A --prompt is required unless --skip-visualizer is set.")
            sys.exit(1)

        def _is_running_in_docker():
            return os.path.exists("/.dockerenv")

        if _is_running_in_docker():
            print(
                "\n[DS] ⚠️  WARNING: Phase 1 is running inside Docker on Mac.\n"
                "[DS]     MPS (Apple Silicon GPU) is NOT accessible from inside\n"
                "[DS]     a Docker container. This will run on CPU and take ~84min.\n"
                "[DS]     RECOMMENDED: Run Phase 1 natively on Mac instead:\n"
                "[DS]       bash infra/scripts/run_phase1_native.sh \"your prompt\"\n"
                "[DS]     Then use --skip-visualizer for the Docker run.\n"
            )

        t0 = _phase_start(1)
        try:
            from visualizer import Visualizer

            viz = Visualizer()
            blueprint_result = viz.generate_blueprint(
                prompt=args.prompt,
                output_path=blueprint_path,
                num_inference_steps=args.steps,
                seed=args.seed,
                colour=args.colour,
            )
            print(f"[DS] Blueprint seed: {blueprint_result.seed}", flush=True)
            _record_blueprint(args, blueprint_path, blueprint_result)
            _phase_pass(1, t0, str(blueprint_path))
        except Exception as exc:
            _phase_fail(1, t0, exc)
    else:
        logger.info("Skipping Phase 1 — using existing blueprint: %s", blueprint_path)
        if _should_install_reference_blueprint(args, blueprint_path):
            try:
                _install_dev_asset(DEV_REFERENCE_BLUEPRINT, blueprint_path, "blueprint")
            except Exception as e:
                logger.error("Failed to install the reference blueprint: %s", e)
                sys.exit(1)
        elif not blueprint_path.exists():
            # `--skip-sculptor --mesh real.obj` with no blueprint: legitimately nothing
            # to show. Said out loud, because the running view's first stage will be
            # empty and an unexplained empty stage reads as a broken pipeline.
            if args.spec:
                # Not a gap: a compiled spec has no image stage. Said at INFO so the
                # running view's empty first stage has an explanation in the log.
                logger.info(
                    "Phase 1 does not apply — the geometry is compiled from %s, so there "
                    "is no blueprint to show or hash.", args.spec,
                )
            else:
                logger.warning(
                    "No blueprint at %s and none will be installed — the mesh came from "
                    "--mesh, so there is no Phase 1 output to show or hash.",
                    blueprint_path,
                )

        # Checked by content every time, not just when this run installed it: a stand-in
        # left behind by an earlier run is still a stand-in, and Phase 2 must refuse to
        # pay for it below.
        if blueprint_path.exists():
            blueprint_is_stand_in = _blueprint_is_stand_in(blueprint_path)
            if blueprint_is_stand_in:
                logger.warning(
                    "%s is a stand-in blueprint, not a fresh render. Phases 3-5 can run "
                    "on it; reconstruction of it is refused for any backend that charges "
                    "per generation.",
                    blueprint_path,
                )

    # Snapshot the blueprint this job actually used, so the job's outputs are
    # self-contained: Phase 1 may have run natively, in another process, writing under
    # data/inputs/ — and a run given --blueprint reads a file this job does not own at
    # all. Provenance that lives only in an input directory is provenance the outputs
    # cannot vouch for. It is a copy, not the source of truth: `_blueprint_path` is
    # what stops two jobs sharing one image in the first place.
    # The reference blueprint *is* copied in — it is a real image, the UI's blueprint
    # stage has something to show, and the `dev-` directory name is what says it did not
    # come from a model. A flat legacy rectangle is not: snapshotting those only filled
    # data/outputs with identical blue squares, which is what it used to do.
    if args.job_id and blueprint_path.exists() and not _blueprint_is_placeholder(blueprint_path):
        try:
            import shutil
            shutil.copy2(blueprint_path, _ensure_outputs_dir(outputs_dir) / "blueprint.png")
        except Exception as exc:
            logger.warning("Could not snapshot blueprint for job %s: %s", args.job_id, exc)

    # A skipped Phase 1 usually still has full provenance to record: the primary Mac
    # workflow runs the visualizer natively and it leaves a sidecar beside the PNG.
    # Reading it back is what stops every job on that path from recording NULL for
    # seed, prompt and model. When there is no (valid) sidecar the hash alone is
    # recorded — it is the only thing that identifies a user-supplied blueprint.
    if args.skip_visualizer and blueprint_path.exists():
        try:
            from blueprint_spec import read_sidecar
        except ImportError:
            from pythonsrc.blueprint_spec import read_sidecar

        sidecar_result = read_sidecar(blueprint_path)
        if sidecar_result is not None:
            print(
                f"[DS] Blueprint provenance restored from sidecar (seed {sidecar_result.seed})",
                flush=True,
            )
        _record_blueprint(args, blueprint_path, sidecar_result)

    if _should_stop_after(args.stop_after_phase, 1):
        _stop_here(1, f"blueprint at {blueprint_path}")

    # The image screen has to run on this path too. On the primary Mac workflow the
    # blueprint was rendered by a *different process* (run_phase1_native.sh) and
    # `visualizer.save_screened` already covered it there — but a blueprint supplied
    # with `--blueprint` was not screened by anyone, and it is about to be handed to a
    # backend that may charge for it.
    #
    # A stand-in is deliberately exempt: it is a bundled fixture, screening it wastes
    # a model load on a known image, and the same guard already stops Phase 2 from
    # paying to reconstruct it.
    blueprint_screen = None
    if args.skip_visualizer and blueprint_path.exists() and not blueprint_is_stand_in:
        try:
            from PIL import Image

            try:
                from ip_screen_image import screen_image
            except ImportError:
                from pythonsrc.ip_screen_image import screen_image

            with Image.open(blueprint_path) as handle:
                blueprint_screen = screen_image(handle.convert("RGB"))

            if blueprint_screen.action == "block":
                print(
                    f"[DS] ─── BLUEPRINT REFUSED ─── {blueprint_screen.reason}",
                    flush=True,
                )
                _write_status(1, "error", blueprint_screen.reason or "blueprint refused")
                sys.exit(1)
            if blueprint_screen.action == "flag":
                # Not a phase banner: the server's regex turns `═══ PHASE n ═══` into a
                # progress update, and this is a note about one, not a phase of its own.
                print(
                    f"[DS] ─── BLUEPRINT FLAGGED ─── {blueprint_screen.reason}",
                    flush=True,
                )
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Blueprint image screen did not run: %s", exc)

    # ── Phase 2: Sculptor, or the Compiler for a spec run ─────────────────────

    compile_result = None

    if args.spec:

        # The parametric path. Same phase number and the same banner emitters as the

        # sculptor — the UI names this phase "Compiler" and keys off the number — so a

        # spec run's rail moves truthfully and the banner contract is untouched.

        t0 = _phase_start(2)

        try:

            raw_mesh_path, compile_result = _compile_spec_phase(args, outputs_dir)

            _record_spec_generation(args, compile_result, time.time() - t0)

            _phase_pass(2, t0, str(raw_mesh_path))

        except Exception as exc:  # noqa: BLE001 — a SpecError is a Phase 2 failure

            _phase_fail(2, t0, exc)

    elif not args.skip_sculptor:
        t0 = _phase_start(2)
        sculptor = None
        try:
            from sculptor import create_sculptor

            sculptor = create_sculptor(
                args.sculptor_backend,
                pipeline_type=args.pipeline_type,
                seed=args.mesh_seed,
            )
            print(f"[DS] Sculptor backend: {sculptor.describe()}", flush=True)

            # Never pay to reconstruct a stand-in. A backend that bills per call turns
            # a missing blueprint from a harmless dev convenience into a charge for a
            # fixture — which is exactly what happened, repeatedly, when an unmocked
            # test triggered the pipeline. Free backends may proceed: the reference
            # blueprint is a real image and reconstructing it is a real exercise.
            if blueprint_is_stand_in and getattr(sculptor, "BACKEND", "") == "hosted_api":
                raise RuntimeError(
                    f"Refusing to spend money reconstructing a stand-in blueprint. "
                    f"The '{sculptor.name}' backend bills per generation and "
                    f"{blueprint_path} was auto-generated because no real blueprint "
                    "existed. Provide a blueprint, drop --skip-visualizer so Phase 1 "
                    "makes one, or pass --skip-sculptor to skip reconstruction."
                )
            sculptor.generate_mesh(
                image_path=blueprint_path,
                output_path=raw_mesh_path,
                target_faces=args.faces,
                smooth_iterations=args.smooth,
            )
            _record_generation(
                args,
                model=getattr(sculptor, "MODEL_NAME", "TRELLIS.2"),
                model_version=getattr(sculptor, "MODEL_VERSION", None),
                backend=getattr(sculptor, "BACKEND", "local"),
                # The backend reports its own sampler settings; the pipeline adds
                # only what it owns. Both matter: sampler settings change the
                # geometry, and nothing after the fact says which resolution or
                # seed produced a given mesh.
                params={
                    **sculptor.generation_params(),
                    "smooth_iterations": args.smooth,
                    "target_faces": args.faces,
                    "target_mm": args.target_mm,
                    "scale_axis": args.scale_axis,
                    "hollow": args.hollow,
                },
                cost_eur=getattr(sculptor, "last_generation_cost_eur", None),
                duration_s=round(time.time() - t0, 2),
            )
            _phase_pass(2, t0, str(raw_mesh_path))
        except Exception as exc:
            # Persist whatever provenance the backend accumulated before it failed.
            # A hosted generation is billed the moment the gateway accepts it, so a
            # Phase 2 that dies in polling, download or post-processing has still
            # spent money — and without this the charge and the request_id die with
            # the process, leaving no record of the spend and no handle to re-fetch
            # the artifact that was paid for. Best-effort: a telemetry failure must
            # not replace the real error with its own.
            if sculptor is not None:
                try:
                    _record_generation(
                        args,
                        model=getattr(sculptor, "MODEL_NAME", None),
                        model_version=getattr(sculptor, "MODEL_VERSION", None),
                        backend=getattr(sculptor, "BACKEND", None),
                        params={
                            **sculptor.generation_params(),
                            "phase2_failed": True,
                            "phase2_error": str(exc)[:500],
                        },
                        cost_eur=getattr(sculptor, "last_generation_cost_eur", None),
                        duration_s=round(time.time() - t0, 2),
                    )
                except Exception as record_exc:
                    logger.warning(
                        "Could not record provenance for the failed Phase 2: %s",
                        record_exc,
                    )
            _phase_fail(2, t0, exc)
    else:
        logger.info("Skipping Phase 2 — using existing mesh: %s", raw_mesh_path)
        if not raw_mesh_path.exists():
            # Stand the bundled reference mesh in rather than fabricating geometry.
            # A 50mm `trimesh.creation.box` used to be exported here, which is the
            # worst available outcome: a cube is watertight, convex, has no boundary
            # or non-manifold edges, no thin walls and no overhangs, so repair has
            # nothing to repair, printability scores geometry no reconstruction
            # produces, the adhesion rule never fires and the slicer sees six faces
            # instead of six figures. `assets/dev_reference/raw_mesh.obj` is a real
            # O-Voxel reconstruction carrying the defects Phases 3-5 exist to handle,
            # and a run that installs it is marked as a fixture run twice over: the
            # output directory is named `dev-{job_id}` and `used_reference_assets` is
            # set on the telemetry row.
            try:
                _install_dev_asset(DEV_REFERENCE_MESH, raw_mesh_path, "mesh")
            except Exception as e:
                logger.error("Failed to install the reference mesh: %s", e)
                sys.exit(1)

    if _should_stop_after(args.stop_after_phase, 2):
        _stop_here(2, f"raw mesh at {raw_mesh_path}")

    # The machine's limits, read once. Needed before Phase 3 so the oversize check can
    # run against the size that was just applied, rather than being discovered in the
    # printability report after the fact.
    process_profile_limits = None
    try:
        with open(args.profile or "pythonsrc/profiles/ender3.json", "r") as handle:
            profile_data = json.load(handle)
        keys = ("machine_width", "machine_depth", "machine_height")
        if all(profile_data.get(k) is not None for k in keys):
            process_profile_limits = [float(profile_data[k]) for k in keys]
    except Exception as exc:  # noqa: BLE001
        logger.debug("No build volume available for the oversize check: %s", exc)

    # ── Phase 3: Engineer ─────────────────────────────────────────────────────
    t0 = _phase_start(3)
    try:
        from engineer import Engineer

        eng = Engineer()
        eng.process(
            input_path=raw_mesh_path,
            output_path=final_mesh_path,
            target_mm=None if args.no_scale else args.target_mm,
            hollow=args.hollow,
            wall_thickness=args.wall,
            scale_axis=args.scale_axis,
            # A compiled mesh is asserted, never repaired: a defect is a compiler bug,
            # and repairing it would ship dimensions the spec did not ask for.
            repair_mode=_repair_mode_for(args),
        )
        if compile_result is not None:
            # The dimensional half. Measured on the exported mesh, recorded on the row
            # via `repair_report` (the `achieved_extent_mm` precedent), and a failure
            # here is a failed Phase 3 — see `_assert_spec_dimensions`.
            eng.last_report["dimension_check"] = _assert_spec_dimensions(
                compile_result, final_mesh_path, outputs_dir
            )
        # Height mode bounds one axis by construction and the other two not at all, so
        # a wide model asked for a tall height can come out past the bed. The size is
        # *not* silently reduced — a part quietly scaled to something other than what
        # was asked for is the bug this whole change set exists to remove — but it is
        # said plainly here, and `build_volume_fit` (critical, weight 2.0) fails it in
        # the printability report a few lines below.
        achieved = (eng.last_report or {}).get("achieved_extent_mm")
        if achieved and process_profile_limits:
            over = [
                f"{axis} {extent:.0f}mm > {limit:.0f}mm"
                for axis, extent, limit in zip("XYZ", achieved, process_profile_limits)
                if extent > limit
            ]
            if over:
                # Says "the part", not "the scaled part": with --no-scale nothing was
                # scaled, and the remedy is to change the spec rather than the size.
                print(
                    "[DS] ─── OVERSIZE ─── the part exceeds the build volume: "
                    + ", ".join(over)
                    + ". It was not shrunk; choose a smaller size or a bigger printer.",
                    flush=True,
                )

        _record_mesh_lineage(args, raw_mesh_path, final_mesh_path, eng.last_report)
        _phase_pass(3, t0, str(final_mesh_path))
    except Exception as exc:
        _phase_fail(3, t0, exc)

    if _should_stop_after(args.stop_after_phase, 3):
        _stop_here(3, f"engineered mesh at {final_mesh_path}")

    # ── Phase 3.5: Printability gate ──────────────────────────────────────────
    # Deliberately not a numbered phase: the .status protocol, the WebSocket phase
    # updates and the UI progress bar all key off phases 1-5, and renumbering would
    # silently change what every historical .status file means.
    printability_report = None
    # Held outside the try so Phase 4 can read the nozzle width off it: the brim
    # override is a line *count*, which only means something against a line width.
    process_profile = None
    print("\n[DS] ─── PRINTABILITY START ───", flush=True)
    t0 = time.time()
    try:
        try:
            from printability import ProcessProfile, evaluate_mesh_file
        except ImportError:
            from pythonsrc.printability import ProcessProfile, evaluate_mesh_file

        process_profile = ProcessProfile()
        profile_path = args.profile or "pythonsrc/profiles/ender3.json"
        try:
            with open(profile_path, "r") as f:
                process_profile = ProcessProfile.from_printer_profile(json.load(f))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read %s for printability limits (%s) — using FDM defaults.", profile_path, exc)

        report = evaluate_mesh_file(
            str(final_mesh_path),
            profile=process_profile,
            job_id=args.job_id,
            was_hollowed=args.hollow,
            expected_components=len(compile_result.parts) if compile_result else None,
        )
        printability_report = report

        report_path = _ensure_outputs_dir(outputs_dir) / "printability.json"
        with open(report_path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)

        print(f"[DS] Printability score: {report.score:.1f}/100 → {report.verdict}", flush=True)
        for check in report.failed():
            print(f"[DS]   ✗ {check.check}: {check.detail}", flush=True)
        for check in report.warnings():
            print(f"[DS]   ! {check.check}: {check.detail}", flush=True)
        # A thin-walled part is reported as unprintable at a size that is already
        # fixed, and the one remedy — print it bigger — was never named. Derived only
        # when the wall check actually complained, because the measurement costs a
        # voxelisation and a distance transform. Hollowing voxelises at an absolute
        # pitch, so the prediction does not hold for it and is not offered.
        wall_check = next(
            (c for c in report.checks if c.check == "min_wall_thickness"), None,
        )
        if wall_check is not None and wall_check.status in {"fail", "warn"} and not args.hollow:
            try:
                try:
                    from printability import size_feasibility
                except ImportError:
                    from pythonsrc.printability import size_feasibility

                import trimesh as _trimesh

                feasibility = size_feasibility(
                    _trimesh.load(str(final_mesh_path), force="mesh"),
                    process_profile,
                    scale_axis=args.scale_axis,
                )
                if feasibility["smallest_viable_mm"] is not None and feasibility["fits"]:
                    print(
                        f"[DS]   → at about {feasibility['smallest_viable_mm']:.0f}mm "
                        f"({args.scale_axis}) this mesh's walls would clear the "
                        f"{process_profile.min_wall_mm:.2f}mm minimum; it was scaled to "
                        f"{args.target_mm:.0f}mm.",
                        flush=True,
                    )
                elif feasibility["reason"]:
                    print(f"[DS]   → {feasibility['reason']}", flush=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not derive a size suggestion: %s", exc)

        print(f"[DS] ─── PRINTABILITY DONE ({time.time() - t0:.1f}s) → {report_path} ───\n", flush=True)

        if args.job_id:
            try:
                from pythonsrc.telemetry.db import TelemetryDB

                db = TelemetryDB()
                db.update_job_printability(
                    args.job_id,
                    score=report.score,
                    verdict=report.verdict,
                    features=report.features,
                    report=report.to_dict(),
                )
                db.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not persist printability report: %s", exc)

        # Advisory by default — a low score never blocks a print unless the caller
        # explicitly asks for a floor.
        if args.min_printability is not None and report.score < args.min_printability:
            logger.error(
                "Printability score %.1f is below the requested minimum %.1f — stopping before the slicer.",
                report.score,
                args.min_printability,
            )
            _write_status(3, "error", f"printability {report.score:.1f} < {args.min_printability:.1f}")
            sys.exit(1)

    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        # Scoring is diagnostic; never fail a print because the scorer itself broke.
        logger.warning("Printability evaluation failed (%s) — continuing without a score.", exc)
        print("[DS] ─── PRINTABILITY SKIPPED (evaluation error) ───\n", flush=True)
        # Only when there is no report to protect: a failure *after* a successful score
        # (a failed write, a dead database) must not overwrite the score with its own
        # excuse.
        if printability_report is None:
            _record_printability_failure(args, outputs_dir, exc)

    # ── Phase 4: Slicer ───────────────────────────────────────────────────────
    if getattr(args, "slice", False) or args.print:
        t0 = _phase_start(4)
        try:
            from slicer import CuraSlicer, SlicerError

            slicer = CuraSlicer(
                cura_engine=args.cura_engine,
                profile=args.profile,
            )
            # Slicer (CuraEngine) needs .stl, Engineer outputs both .obj and .stl
            stl_mesh_path = final_mesh_path.with_suffix(".stl")
            slicer_overrides = _adhesion_args(printability_report, process_profile)
            gcode_path = slicer.slice(
                input_path=stl_mesh_path,
                output_path=gcode_path,
                extra_args=slicer_overrides,
            )
            _record_slice(
                args, gcode_path, time.time() - t0,
                status="success", extra_args=slicer_overrides,
            )
            _phase_pass(4, t0, str(gcode_path))
        except Exception as exc:
            # Recorded before _phase_fail, which exits the process. A mesh that could
            # not be sliced is a data point, and a dataset holding only successful
            # slices cannot predict which meshes will fail.
            _record_slice(args, None, time.time() - t0, status="failed", error=str(exc))
            _phase_fail(4, t0, exc)
    elif args.job_id:
        _record_slice(args, None, 0.0, status="skipped")

    # ── Phase 5: Operator ─────────────────────────────────────────────────────
    if args.print:
        t0 = _phase_start(5)
        try:
            from pythonsrc.operators import PrinterFactory

            # Load profile for printer settings
            profile_path = args.profile or "pythonsrc/profiles/ender3.json"
            with open(profile_path, "r") as f:
                profile_data = json.load(f)
            
            firmware = os.environ.get("DS_FIRMWARE", profile_data.get("firmware", "octoprint"))
            base_url = os.environ.get("DS_PRINTER_URL", profile_data.get("base_url", "http://localhost:5001"))

            # Recorded before the Docker rewrite below: host.docker.internal is a
            # container artifact, not the address anyone configured.
            dispatch_url = base_url

            # Rewrite localhost if running inside docker so it can reach the host
            if "localhost" in base_url or "127.0.0.1" in base_url:
                if os.path.exists("/.dockerenv"):
                    base_url = base_url.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")

            api_key = os.environ.get("DS_PRINTER_KEY", profile_data.get("api_key"))

            op = PrinterFactory.create(
                firmware=firmware,
                base_url=base_url,
                api_key=api_key
            )

            # Ensure printer is connected and operational before upload
            logger.info(f"Connecting to {firmware} printer…")
            op.connect()

            logger.info("Uploading G-code…")
            # Only the two-argument form is part of the BasePrinterOperator contract —
            # OctoPrint's upload-and-print shortcut is not, so it must not be used here
            # or every other firmware raises TypeError.
            op.upload_file(str(gcode_path), gcode_path.name)
            logger.info(f"Upload complete — file available on {firmware}.")

            # The dispatch moment is the only moment the target URL is true: profiles
            # are resolved on read and edited in place, and this URL is what later
            # distinguishes simulator telemetry from real-hardware telemetry.
            if args.job_id:
                try:
                    from pythonsrc.telemetry.db import TelemetryDB as _DispatchDB

                    _ddb = _DispatchDB()
                    _ddb.update_job_dispatch(args.job_id, printer_url=dispatch_url)
                    _ddb.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not record the dispatch target: %s", exc)

            if args.start_print:
                logger.info("Starting print…")
                op.start_print(gcode_path.name)

                from pythonsrc.telemetry.db import TelemetryDB
                from pythonsrc.telemetry.detector import attach_detector
                from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector
                from urllib.parse import urlparse

                async def monitor_print():
                    logger.info("Starting telemetry collector and polling print status…")
                    db = TelemetryDB()
                    parsed = urlparse(base_url)
                    port = parsed.port or (443 if parsed.scheme == "https" else 80)
                    
                    # A CLI-launched job may have a row with no start time. Stamp
                    # started_at — not completed_at, which this used to write:
                    # `update_job_outcome`'s second timestamp is the *completion*
                    # column, so every print marked its finish at the moment it began.
                    job = db.get_job(args.job_id)
                    if job and job.outcome == 'unknown' and not job.started_at:
                        db.update_job_start_time(args.job_id, datetime.now(timezone.utc))

                    collector = OctoPrintCollector(
                        parsed.hostname or "localhost", port, api_key or "",
                        args.job_id, db, gcode_filename=gcode_path.name,
                    )
                    await collector.start()

                    # Consume the collector's samples so automated failure detection
                    # actually runs; `op` gives the detector real state/progress.
                    detector_task = attach_detector(collector, db, op)

                    try:
                        # Give the printer a moment to transition to printing state
                        await asyncio.sleep(5)
                        while True:
                            try:
                                state = op.get_printer_state()
                                flags = state.get("state", {}).get("flags", {})
                                state_text = state.get("state", {}).get("text", "").lower()
                                
                                # If it's ready, operational, or printed and NOT printing, we are done
                                if (flags.get("ready") or flags.get("operational") or state_text == "operational" or state_text == "printed") and not flags.get("printing"):
                                    logger.info(f"Print job completed! Final state: {state_text}")
                                    break
                                
                                if flags.get("error") or flags.get("closedOrError") or state_text == "error":
                                    logger.error("Printer reported an error state!")
                                    raise Exception("Printer error state detected during printing.")
                                    
                            except Exception as e:
                                logger.error(f"Error polling printer state: {e}")
                                raise e
                                
                            await asyncio.sleep(5)
                    finally:
                        detector_task.cancel()
                        try:
                            await detector_task
                        except asyncio.CancelledError:
                            pass
                        await collector.stop()
                        db.close()

                asyncio.run(monitor_print())

            _phase_pass(5, t0, str(gcode_path))
        except Exception as exc:
            _phase_fail(5, t0, exc)

    # ── Pipeline summary ──────────────────────────────────────────────────────
    total_elapsed = time.time() - pipeline_start
    total_min = int(total_elapsed // 60)
    total_sec = int(total_elapsed % 60)
    print("\n[DS] ══════════════════════════════", flush=True)
    print("[DS] PIPELINE COMPLETE ✓", flush=True)
    print(f"[DS] Total duration: {total_min}m {total_sec}s", flush=True)
    print("[DS] ══════════════════════════════\n", flush=True)

    logger.info("Mesh: %s", final_mesh_path)
    if args.print:
        logger.info("G-code: %s", gcode_path)


# ── CLI ───────────────────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Daedal Studio — unified mesh pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Prompt
    parser.add_argument("prompt", nargs="?", help="Text prompt for the object to generate")

    # Skip flags for fast iteration
    skip = parser.add_argument_group("skip flags (for iterating on a specific phase)")
    skip.add_argument("--skip-visualizer", action="store_true", help="Skip Phase 1 (reuse existing blueprint)")
    skip.add_argument("--skip-sculptor", action="store_true", help="Skip Phase 2 (reuse existing raw mesh)")

    # Paths
    paths = parser.add_argument_group("paths")
    paths.add_argument(
        "--blueprint",
        metavar="PATH",
        help="Override the blueprint image path (default: data/inputs/{job-id}/blueprint.png "
             "with --job-id, data/inputs/blueprint.png without)",
    )
    paths.add_argument("--mesh", metavar="PATH", help="Override raw mesh path")
    paths.add_argument(
        "--spec",
        metavar="PATH",
        help="Compile an organizer spec (pythonsrc/organizer) into the mesh instead of "
             "running Phases 1-2. Implies --skip-visualizer --skip-sculptor --no-scale; "
             "refuses --mesh and --hollow",
    )
    
    # Telemetry
    telemetry = parser.add_argument_group("telemetry")
    telemetry.add_argument("--job-id", metavar="ID", help="Telemetry Job ID for status reporting")
    telemetry.add_argument(
        "--min-printability",
        type=float,
        default=None,
        metavar="SCORE",
        help="Stop before slicing if the printability score is below SCORE (0-100). "
             "Off by default — printability is advisory and only recorded.",
    )
    # Material is a pipeline input, not just a label: it sets the density used to turn
    # extruded volume into grams, and it is the field most likely to explain a bed
    # adhesion failure after the fact.
    telemetry.add_argument(
        "--material-type",
        default=None,
        metavar="TYPE",
        help="Filament type (PLA, PETG, ABS, TPU, ASA); also selects the density used "
             "for the filament mass estimate",
    )

    # Phase 1 options
    p1 = parser.add_argument_group("Phase 1 — Visualizer")
    p1.add_argument("--steps", type=int, default=4, metavar="N", help="Diffusion inference steps")
    # The blueprint is rendered in the requester's filament colour when they named
    # one, so the preview matches the part. Blueprint only: Phase 2 strips appearance
    # and CuraEngine has no use for a material.
    p1.add_argument("--colour", "--color", dest="colour", default=None, metavar="NAME", help="Filament colour to render the blueprint in")
    p1.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="RNG seed for the blueprint; a random one is drawn, reported and recorded if omitted",
    )

    # Phase 2 options
    p2 = parser.add_argument_group("Phase 2 — Sculptor (TRELLIS.2)")
    p2.add_argument("--faces", type=int, default=DEFAULT_TARGET_FACES, metavar="N", help="Target face count after decimation; 0 disables it")
    p2.add_argument(
        "--sculptor-backend",
        default=None,
        choices=["auto", "trellis2", "remote", "pixazo"],
        help="Where reconstruction runs: trellis2 in-process (needs a CUDA GPU), "
             "remote via a self-hosted GPU worker, pixazo via the hosted endpoint "
             "(bills EUR 0,32 per generation), or auto "
             "(default: $DS_SCULPTOR_BACKEND, else auto)",
    )
    p2.add_argument(
        "--pipeline-type",
        default=None,
        choices=["512", "1024", "1024_cascade", "1536_cascade"],
        help="TRELLIS.2 voxel resolution — higher captures finer detail at more "
             "GPU time (default: 1024_cascade)",
    )
    p2.add_argument(
        "--mesh-seed",
        type=int,
        default=None,
        metavar="N",
        help="Sampling seed for reconstruction; the same seed and blueprint "
             "reproduce the same mesh. Distinct from --seed, which is Phase 1's.",
    )
    p2.add_argument(
        "--smooth",
        type=int,
        default=None,
        metavar="N",
        help="Taubin smoothing passes. Defaults to 0 for TRELLIS.2 — smoothing "
             "rounds off exactly the sharp features the model recovers.",
    )

    # Where to stop. The blueprint approval gate needs a seam after Phase 1: the
    # docker strategies run all five phases in one `docker compose run`, so without
    # this there is nowhere for a job to park and be picked up again. The continuation
    # is a second invocation with --skip-visualizer, whose provenance is complete
    # because Phase 1 left a sidecar beside the PNG.
    parser.add_argument(
        "--stop-after-phase",
        type=int,
        default=None,
        metavar="N",
        choices=(1, 2, 3, 4),
        help="Exit cleanly once phase N has completed (used by the approval gate)",
    )

    # Phase 3 options
    p3 = parser.add_argument_group("Phase 3 — Engineer")
    p3.add_argument("--target-mm", type=float, default=50.0, metavar="MM", help="Target size in mm, measured along --scale-axis")
    # Which extent the size describes. Height by default because that is what a
    # person means by "how big"; "longest" is the old behaviour, kept reachable for
    # anything that depended on it.
    p3.add_argument("--scale-axis", choices=("height", "longest"), default="height", help="Which extent --target-mm describes (default: height)")
    # A mesh built from a parametric spec already carries its final dimensions, and
    # Phase 3 used to resize it to --target-mm's 50.0 default regardless — silently,
    # since the result is still watertight, still slices and still prints.
    p3.add_argument(
        "--no-scale",
        action="store_true",
        help="Preserve the mesh's own dimensions (ignores --target-mm; refuses --hollow)",
    )
    p3.add_argument("--hollow", action="store_true", help="Apply voxel-based hollowing")
    p3.add_argument("--wall", type=float, default=1.2, metavar="MM", help="Wall thickness for hollowing in mm")

    # Phase 4 options (Slicer)
    p4 = parser.add_argument_group("Phase 4 — Slicer (CuraEngine)")
    p4.add_argument("--slice", action="store_true", help="Slice the generated mesh into G-code")
    p4.add_argument(
        "--profile",
        metavar="PATH",
        default=None,
        help="Printer profile JSON for CuraEngine (default: built-in Ender-3 settings)",
    )
    p4.add_argument(
        "--cura-engine",
        metavar="BIN",
        default=CURA_ENGINE_PATH,
        help="CuraEngine binary name or full path",
    )

    # Phase 5 options (Operator)
    p5 = parser.add_argument_group("Phase 5 — Operator (OctoPrint)")
    p5.add_argument("--print", dest="print", action="store_true", help="Slice and upload final mesh to OctoPrint")
    p5.add_argument("--octoprint-url", default=os.environ.get("OCTOPRINT_URL", "http://localhost:5001"), metavar="URL", help="OctoPrint base URL")
    p5.add_argument("--octoprint-key", default=os.environ.get("OCTOPRINT_API_KEY", ""), metavar="KEY", help="OctoPrint API key")
    p5.add_argument("--start-print", action="store_true", help="Automatically start the print job after upload")

    # General
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    try:
        _apply_spec_mode(args)
    except ValueError as exc:
        parser.error(str(exc))

    if args.job_id:
        CURRENT_JOB_ID = args.job_id
    _setup_logging(args.verbose)
    run(args)
