"""Command line for the organizer engine — the developer loop before `pipeline.py --spec`.

    python -m pythonsrc.organizer example deck_box > deck.json
    python -m pythonsrc.organizer compile deck.json --out deck.stl --features features.json
    python -m pythonsrc.organizer measure deck.json deck.stl

In the pipeline image (`PYTHONPATH=/app/pythonsrc`) the module is `organizer`. Exit codes:
0 ok, 1 measurement out of tolerance, 2 a spec or usage problem.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import trimesh

from .archetypes import compile_spec, example_spec, measure_spec_mesh
from .compiler import DEFAULT_TOLERANCE_MM, MeasureError, compare_features, export_stl
from .spec import SpecError, dump_spec, load_spec


def _cmd_example(args: argparse.Namespace) -> int:
    print(example_spec(args.archetype).to_json())
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    result = compile_spec(spec)
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
        measured = measure_spec_mesh(spec, mesh)
    except MeasureError as exc:
        print(f"cannot measure {args.mesh}: {exc}", file=sys.stderr)
        return 1
    rows = compare_features(result.features, measured, args.tol)
    width = max(len(name) for name in rows)
    failed = 0
    for name, (designed, got, err) in rows.items():
        ok = abs(err) <= args.tol
        failed += not ok
        print(f"{name:<{width}}  designed {designed:9.3f}  measured {got:9.3f}  error {err:+.3f}  {'OK' if ok else 'OUT'}")
    print(f"{len(rows) - failed}/{len(rows)} features within ±{args.tol:g} mm")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pythonsrc.organizer",
        description="Compile and measure organizer specs (the developer loop before pipeline.py --spec).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_example = sub.add_parser("example", help="print an example spec for an archetype")
    p_example.add_argument("archetype")
    p_example.set_defaults(func=_cmd_example)

    p_compile = sub.add_parser("compile", help="compile a spec file to an STL")
    p_compile.add_argument("spec", help="spec JSON file")
    p_compile.add_argument("--out", required=True, help="mesh path to write (.stl)")
    p_compile.add_argument("--features", help="also write the designed features as JSON")
    p_compile.add_argument("--spec-out", dest="spec_out", help="also write the spec in canonical, sorted form")
    p_compile.set_defaults(func=_cmd_compile)

    p_measure = sub.add_parser("measure", help="measure a mesh against the spec it claims to implement")
    p_measure.add_argument("spec")
    p_measure.add_argument("mesh")
    p_measure.add_argument("--tol", type=float, default=DEFAULT_TOLERANCE_MM, help="allowed error per feature, mm")
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
