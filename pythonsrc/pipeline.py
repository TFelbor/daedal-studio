"""
pipeline.py — Unified Prompt2Print entrypoint.

Chains Phases 1→2→3→4→5 in a single command:

    python pythonsrc/pipeline.py "a ceramic vase with geometric patterns"
    python pythonsrc/pipeline.py "a miniature chess knight" --target-mm 80 --hollow
    python pythonsrc/pipeline.py --skip-visualizer --blueprint /app/inputs/blueprint.png
    python pythonsrc/pipeline.py --skip-sculptor   --mesh /app/outputs/test_mesh.obj

Phase 5 (Operator) is triggered with --print / --octoprint-url.
Phase 4 (Slicer) converts the engineered .obj → .gcode before upload:

    python pythonsrc/pipeline.py "a chess knight" --print \\
        --octoprint-url http://localhost:5001 --octoprint-key MY_API_KEY --start-print \\
        --profile pythonsrc/profiles/ender3.json
"""

# ── MPS fallback — MUST be set before any torch import ────────────────────────
# Several MPS ops (e.g. upsample_bicubic2d used by TripoSR's ViT image
# tokeniser) are not yet implemented on Apple Silicon. This flag makes PyTorch
# silently fall back to CPU for those ops. It must be in the environment
# *before* `import torch` is first executed in this process — hence it lives
# here at the very top, ahead of all other imports.
import os
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import os
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

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger("p2p.pipeline")

# ── Phase banner helpers ──────────────────────────────────────────────────────
_PHASE_NAMES = {
    1: "Visualizer",
    2: "Sculptor",
    3: "Engineer",
    4: "Slicer",
    5: "Operator",
}

CURRENT_JOB_ID = None

def _write_status(phase_num: int, status: str, error: str = None) -> None:
    if not CURRENT_JOB_ID:
        print(f"DEBUG: CURRENT_JOB_ID is None! sys.argv={sys.argv}")
        return
    log_dir_env = os.environ.get("P2P_LOGS_DIR")
    log_dir = Path(log_dir_env) if log_dir_env else (Path.home() / ".p2p-mesh" / "logs")
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


def _record_generation(args, model, model_version, backend, params, cost_usd, duration_s) -> None:
    """Persist which model produced this job's mesh, and what it cost.

    A hosted, pay-per-generation backend (fal.ai TRELLIS.2) makes cost and latency
    per-generation facts that cannot be reconstructed later, and a model swap otherwise
    mixes two populations in one dataset with nothing to tell them apart.

    Reads its values off the sculptor when present, so swapping in a new backend means
    setting MODEL_NAME / MODEL_VERSION / BACKEND / last_generation_cost_usd on it rather
    than touching the pipeline.

    Args:
        args: Parsed CLI arguments; nothing is recorded without --job-id.
        model: Model name, e.g. "TripoSR" or "TRELLIS.2".
        model_version: Version, revision or hosted endpoint id.
        backend: "local" or "hosted_api".
        params: Generation settings used.
        cost_usd: Charge for this generation, if the backend bills per call.
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
            cost_usd=cost_usd,
            duration_s=duration_s,
        )
        db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record generation provenance: %s", exc)


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


def _record_mesh_lineage(args, raw_mesh_path, repaired_mesh_path) -> None:
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
        )
        db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record mesh lineage: %s", exc)


def _record_slice(args, gcode_path, duration_s, status="success", error=None) -> None:
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
            stats=stats.to_dict() if stats else None,
        )
        db.close()

        if stats:
            print(
                f"[P2P] Slice stats: {stats.filament_used_mm / 1000:.2f}m filament, "
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


def _phase_start(phase_num: int) -> float:
    """Print a phase start banner and return the start timestamp."""
    name = _PHASE_NAMES.get(phase_num, "Unknown")
    print(f"\n[P2P] ═══ PHASE {phase_num} START: {name} ═══", flush=True)
    return time.time()


def _phase_pass(phase_num: int, start_time: float, output_path: str = "") -> None:
    """Print a phase pass banner with timing and output path."""
    elapsed = time.time() - start_time
    name = _PHASE_NAMES.get(phase_num, "Unknown")
    out_info = f" (output: {output_path})" if output_path else ""
    print(f"[P2P] ═══ PHASE {phase_num} PASS  ✓{out_info} ═══", flush=True)
    print(f"[P2P] Phase {phase_num} duration: {elapsed:.1f}s", flush=True)
    _write_status(phase_num, "complete")


def _phase_fail(phase_num: int, start_time: float, exc: Exception) -> None:
    """Print a phase fail banner with traceback, then exit."""
    elapsed = time.time() - start_time
    name = _PHASE_NAMES.get(phase_num, "Unknown")
    print(f"[P2P] ═══ PHASE {phase_num} FAIL  ✗ ═══", flush=True)
    print(f"[P2P] Phase {phase_num} duration: {elapsed:.1f}s", flush=True)
    print(f"[P2P] ERROR: {exc}", flush=True)
    print(f"[P2P] TRACEBACK:", flush=True)
    traceback.print_exc()
    _write_status(phase_num, "error", str(exc))
    sys.exit(1)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="[%(levelname)s] %(name)s — %(message)s",
        level=level,
    )


# ── Pipeline ──────────────────────────────────────────────────────────────────
def run(args: argparse.Namespace) -> None:
    pipeline_start = time.time()

    os.makedirs(INPUTS_DIR, exist_ok=True)
    os.makedirs(OUTPUTS_DIR, exist_ok=True)

    # Per-job output directory. Without this every job overwrites the same
    # engineered_mesh.* files, so downloading job A's G-code can hand you job B's.
    # Runs without a --job-id (manual CLI use) keep the flat layout.
    if args.job_id:
        outputs_dir = Path(OUTPUTS_DIR) / args.job_id
        outputs_dir.mkdir(parents=True, exist_ok=True)
    else:
        outputs_dir = Path(OUTPUTS_DIR)

    blueprint_path = Path(args.blueprint) if args.blueprint else Path(os.path.join(INPUTS_DIR, "blueprint.png"))
    raw_mesh_path = Path(args.mesh) if args.mesh else outputs_dir / "raw_mesh.obj"
    final_mesh_path = outputs_dir / "engineered_mesh.obj"
    gcode_path = outputs_dir / "engineered_mesh.gcode"

    # ── Phase 1: Visualizer ───────────────────────────────────────────────────
    if not args.skip_visualizer:
        if not args.prompt:
            logger.error("A --prompt is required unless --skip-visualizer is set.")
            sys.exit(1)

        def _is_running_in_docker():
            return os.path.exists("/.dockerenv")

        if _is_running_in_docker():
            print(
                "\n[P2P] ⚠️  WARNING: Phase 1 is running inside Docker on Mac.\n"
                "[P2P]     MPS (Apple Silicon GPU) is NOT accessible from inside\n"
                "[P2P]     a Docker container. This will run on CPU and take ~84min.\n"
                "[P2P]     RECOMMENDED: Run Phase 1 natively on Mac instead:\n"
                "[P2P]       bash infra/scripts/run_phase1_native.sh \"your prompt\"\n"
                "[P2P]     Then use --skip-visualizer for the Docker run.\n"
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
            )
            print(f"[P2P] Blueprint seed: {blueprint_result.seed}", flush=True)
            _record_blueprint(args, blueprint_path, blueprint_result)
            _phase_pass(1, t0, str(blueprint_path))
        except Exception as exc:
            _phase_fail(1, t0, exc)
    else:
        logger.info("Skipping Phase 1 — using existing blueprint: %s", blueprint_path)
        if not blueprint_path.exists() and not args.skip_sculptor:
            logger.warning("Blueprint not found, generating a dummy fallback image...")
            try:
                from PIL import Image
                img = Image.new('RGB', (512, 512), color=(73, 109, 137))
                img.save(blueprint_path)
            except Exception as e:
                logger.error("Failed to generate fallback blueprint: %s", e)
                sys.exit(1)

    # Snapshot the blueprint this job actually used. Phase 1 may run natively and
    # write the shared data/inputs/blueprint.png, so copy it in for provenance.
    if args.job_id and blueprint_path.exists():
        try:
            import shutil
            shutil.copy2(blueprint_path, outputs_dir / "blueprint.png")
        except Exception as exc:
            logger.warning("Could not snapshot blueprint for job %s: %s", args.job_id, exc)

    # A skipped Phase 1 has no seed or prompt to record, but the image still needs
    # identifying — without a hash there is nothing to distinguish two runs that were
    # handed different blueprints.
    if args.skip_visualizer and blueprint_path.exists():
        _record_blueprint(args, blueprint_path, None)

    # ── Phase 2: Sculptor ─────────────────────────────────────────────────────
    if not args.skip_sculptor:
        t0 = _phase_start(2)
        try:
            from sculptor import P2PSculptor

            sculptor = P2PSculptor()
            sculptor.generate_mesh(
                image_path=blueprint_path,
                output_path=raw_mesh_path,
                target_faces=args.faces,
            )
            _record_generation(
                args,
                model=getattr(sculptor, "MODEL_NAME", "TripoSR"),
                model_version=getattr(sculptor, "MODEL_VERSION", None),
                backend=getattr(sculptor, "BACKEND", "local"),
                params={"target_faces": args.faces, "target_mm": args.target_mm, "hollow": args.hollow},
                cost_usd=getattr(sculptor, "last_generation_cost_usd", None),
                duration_s=round(time.time() - t0, 2),
            )
            _phase_pass(2, t0, str(raw_mesh_path))
        except Exception as exc:
            _phase_fail(2, t0, exc)
    else:
        logger.info("Skipping Phase 2 — using existing mesh: %s", raw_mesh_path)
        if not raw_mesh_path.exists():
            logger.warning("Raw mesh not found, generating a dummy fallback cube...")
            try:
                import trimesh
                mesh = trimesh.creation.box(extents=(50, 50, 50))
                mesh.export(raw_mesh_path)
            except Exception as e:
                logger.error("Failed to generate fallback mesh: %s", e)
                sys.exit(1)

    # ── Phase 3: Engineer ─────────────────────────────────────────────────────
    t0 = _phase_start(3)
    try:
        from engineer import Engineer

        eng = Engineer()
        eng.process(
            input_path=raw_mesh_path,
            output_path=final_mesh_path,
            target_mm=args.target_mm,
            hollow=args.hollow,
            wall_thickness=args.wall,
        )
        _record_mesh_lineage(args, raw_mesh_path, final_mesh_path)
        _phase_pass(3, t0, str(final_mesh_path))
    except Exception as exc:
        _phase_fail(3, t0, exc)

    # ── Phase 3.5: Printability gate ──────────────────────────────────────────
    # Deliberately not a numbered phase: the .status protocol, the WebSocket phase
    # updates and the UI progress bar all key off phases 1-5, and renumbering would
    # silently change what every historical .status file means.
    printability_report = None
    print("\n[P2P] ─── PRINTABILITY START ───", flush=True)
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
        )
        printability_report = report

        report_path = outputs_dir / "printability.json"
        with open(report_path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)

        print(f"[P2P] Printability score: {report.score:.1f}/100 → {report.verdict}", flush=True)
        for check in report.failed():
            print(f"[P2P]   ✗ {check.check}: {check.detail}", flush=True)
        for check in report.warnings():
            print(f"[P2P]   ! {check.check}: {check.detail}", flush=True)
        print(f"[P2P] ─── PRINTABILITY DONE ({time.time() - t0:.1f}s) → {report_path} ───\n", flush=True)

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
        print("[P2P] ─── PRINTABILITY SKIPPED (evaluation error) ───\n", flush=True)

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
            gcode_path = slicer.slice(
                input_path=stl_mesh_path,
                output_path=gcode_path,
            )
            _record_slice(args, gcode_path, time.time() - t0, status="success")
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
            
            firmware = os.environ.get("P2P_FIRMWARE", profile_data.get("firmware", "octoprint"))
            base_url = os.environ.get("P2P_PRINTER_URL", profile_data.get("base_url", "http://localhost:5001"))
            
            # Rewrite localhost if running inside docker so it can reach the host
            if "localhost" in base_url or "127.0.0.1" in base_url:
                if os.path.exists("/.dockerenv"):
                    base_url = base_url.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")

            api_key = os.environ.get("P2P_PRINTER_KEY", profile_data.get("api_key"))

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

            if args.start_print:
                logger.info("Starting print…")
                op.start_print(gcode_path.name)

                import asyncio
                from pythonsrc.telemetry.db import TelemetryDB
                from pythonsrc.telemetry.detector import attach_detector
                from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector
                from urllib.parse import urlparse

                async def monitor_print():
                    logger.info("Starting telemetry collector and polling print status…")
                    db = TelemetryDB()
                    parsed = urlparse(base_url)
                    port = parsed.port or (443 if parsed.scheme == "https" else 80)
                    
                    # Ensure job exists in DB
                    job = db.get_job(args.job_id)
                    if job and job.outcome == 'unknown' and not job.started_at:
                        import datetime
                        db.update_job_outcome(args.job_id, 'unknown', datetime.datetime.now(datetime.timezone.utc))

                    collector = OctoPrintCollector(parsed.hostname or "localhost", port, api_key or "", args.job_id, db)
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
    print("\n[P2P] ══════════════════════════════", flush=True)
    print("[P2P] PIPELINE COMPLETE ✓", flush=True)
    print(f"[P2P] Total duration: {total_min}m {total_sec}s", flush=True)
    print("[P2P] ══════════════════════════════\n", flush=True)

    logger.info("Mesh: %s", final_mesh_path)
    if args.print:
        logger.info("G-code: %s", gcode_path)


# ── CLI ───────────────────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prompt2Print — unified mesh pipeline",
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
    paths.add_argument("--workspace", default=".", metavar="DIR", help="Project root (data/inputs/ and data/outputs/ live here)")
    paths.add_argument("--blueprint", metavar="PATH", help="Override blueprint image path")
    paths.add_argument("--mesh", metavar="PATH", help="Override raw mesh path")
    
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
    p1.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="RNG seed for the blueprint; a random one is drawn, reported and recorded if omitted",
    )

    # Phase 2 options
    p2 = parser.add_argument_group("Phase 2 — Sculptor")
    p2.add_argument("--faces", type=int, default=5_000, metavar="N", help="Target face count after decimation")

    # Phase 3 options
    p3 = parser.add_argument_group("Phase 3 — Engineer")
    p3.add_argument("--target-mm", type=float, default=50.0, metavar="MM", help="Target longest dimension in mm")
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
    
    if args.job_id:
        CURRENT_JOB_ID = args.job_id
    _setup_logging(args.verbose)
    run(args)
