"""Command line for the organizer engine — the developer loop before `pipeline.py --spec`.

    python -m pythonsrc.organizer example deck_box > deck.json
    python -m pythonsrc.organizer example card_divider > divider.json
    python -m pythonsrc.organizer example --archetype token_tray > tray.json
    python -m pythonsrc.organizer compile deck.json --out deck.stl --features features.json
    python -m pythonsrc.organizer measure deck.json deck.stl [--report dimension_report.json]

`example` takes the archetype positionally or as `--archetype`; the two spellings are
the same argument, because the acceptance criteria and the existing tests reach for
different ones and a developer loop is not worth a rename.

In the pipeline image (`PYTHONPATH=/app/pythonsrc`) the module is `organizer`. Exit codes:
0 ok, 1 measurement out of tolerance, 2 a spec or usage problem.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import trimesh

from .archetypes import compile_spec, example_spec, verify_spec_mesh
from .compiler import DEFAULT_TOLERANCE_MM, MeasureError, export_stl
from .spec import ARCHETYPES, DEFAULT_NOZZLE_DIAMETER_MM, SpecError, dump_spec, load_spec


def _cmd_example(args: argparse.Namespace) -> int:
    name = args.archetype_flag or args.archetype
    if not name:
        raise SpecError([f"name an archetype: one of {list(ARCHETYPES)}"])
    print(example_spec(name).to_json())
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    result = compile_spec(spec, nozzle_diameter_mm=args.nozzle_mm)
    out = export_stl(result.mesh, args.out)
    if args.features:
        Path(args.features).write_text(json.dumps(result.features_document(), indent=2, sort_keys=True) + "\n")
    if args.spec_out:
        dump_spec(spec, args.spec_out)
    print(f"compiled {result.archetype} v{result.archetype_version} (spec {result.spec_hash[:12]}) → {out}")
    return 0


def _cmd_measure(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    result = compile_spec(spec)
    mesh = trimesh.load(str(args.mesh), force="mesh")
    try:
        report = verify_spec_mesh(spec, result.features, mesh, args.tol)
    except MeasureError as exc:
        print(f"cannot measure {args.mesh}: {exc}", file=sys.stderr)
        return 1
    if args.report:
        # The same document `pipeline.py --spec` writes as `dimension_report.json`.
        Path(args.report).write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
    rows = report.features
    width = max(len(name) for name in rows)
    for name, (designed, got, err) in rows.items():
        ok = name not in report.out_of_tolerance
        print(f"{name:<{width}}  designed {designed:9.3f}  measured {got:9.3f}  error {err:+.3f}  {'OK' if ok else 'OUT'}")
    for name in report.missing:
        print(f"{name:<{width}}  not measured")
    print(f"{len(rows) - len(report.out_of_tolerance)}/{len(rows)} features within ±{args.tol:g} mm")
    return 0 if report.within_tolerance else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pythonsrc.organizer",
        description="Compile and measure organizer specs (the developer loop before pipeline.py --spec).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_example = sub.add_parser("example", help="print an example spec for an archetype")
    # Deliberately not `choices=ARCHETYPES`: an unknown name must come back as the
    # registry's own `SpecError` (exit 2, every known archetype listed) rather than as
    # argparse's usage banner, which is how every other spec problem here is reported.
    p_example.add_argument("archetype", nargs="?", help="which archetype")
    p_example.add_argument("--archetype", dest="archetype_flag",
                           help="the same argument, spelled as a flag")
    p_example.set_defaults(func=_cmd_example)

    p_compile = sub.add_parser("compile", help="compile a spec file to an STL")
    p_compile.add_argument("spec", help="spec JSON file")
    p_compile.add_argument("--out", required=True, help="mesh path to write (.stl)")
    p_compile.add_argument("--features", help="also write the designed features as JSON")
    p_compile.add_argument("--spec-out", dest="spec_out", help="also write the spec in canonical, sorted form")
    # The wall floor is three of these (`spec.wall_floor_mm`). A flag rather than a
    # profile path because this is the developer loop and the loop has no printer;
    # `pipeline.py --spec` reads the real machine's `machine_nozzle_size` instead.
    p_compile.add_argument("--nozzle-mm", dest="nozzle_mm", type=float,
                           default=DEFAULT_NOZZLE_DIAMETER_MM,
                           help="nozzle diameter the wall floor is derived from, mm "
                                f"(default: {DEFAULT_NOZZLE_DIAMETER_MM:g})")
    p_compile.set_defaults(func=_cmd_compile)

    p_measure = sub.add_parser("measure", help="measure a mesh against the spec it claims to implement")
    p_measure.add_argument("spec")
    p_measure.add_argument("mesh")
    p_measure.add_argument("--tol", type=float, default=DEFAULT_TOLERANCE_MM, help="allowed error per feature, mm")
    p_measure.add_argument("--report", help="also write the per-feature report as JSON (the pipeline's dimension_report.json)")
    p_measure.set_defaults(func=_cmd_measure)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SpecError as exc:
        print("\n".join(f"spec: {p}" for p in exc.problems), file=sys.stderr)
        return 2
    except (OSError, MeasureError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
