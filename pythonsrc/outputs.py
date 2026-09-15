"""`data/outputs` seen from the disk: what each job directory holds, and what is safe to delete.

`data/outputs/{job_id}/` is named after a UUID, and until something has been written
into it there is nothing on screen to tell it from its ninety neighbours. The routes
that existed were `GET /jobs/{id}/mesh` — which needs the running app and the id you do
not have — and `ls -t data/outputs`, which shows the same ninety names with no hint of
which hold a mesh.

This module reads **only the filesystem**. That is the point rather than an economy:
the directories a developer cannot account for are the ones left by runs that died
before writing a telemetry row, or on a machine where `DS_DATABASE_URL` is not set at
all, so `python -m pythonsrc.telemetry.trace --list` — which opens a read-only session
against PostgreSQL — cannot answer for exactly the population in question. It is
stdlib-only for the same reason: it must run in a checkout with no virtualenv.

    python -m pythonsrc.outputs                    # newest first, what each one holds
    python -m pythonsrc.outputs --json             # the same, for a script
    python -m pythonsrc.outputs --prune            # remove the empty ones
    python -m pythonsrc.outputs --prune --days 30  # ...and job directories older than 30 days
    python -m pythonsrc.outputs --prune --days 30 --dry-run

`make outputs` and `make clean-outputs` are the same two commands.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Debugging runs that stood a bundled fixture in for Phase 1 or Phase 2 write here, so
# that a mesh built from a fixture never sits in the real namespace looking like one a
# model made. Mirrors `pipeline.DEV_OUTPUT_PREFIX`, which cannot be imported: that module
# pulls in the whole pipeline stack, and this one must run with nothing installed.
DEV_OUTPUT_PREFIX = "dev-"

# One column per thing a person looks for, in pipeline order, each satisfied by any of
# its filenames. `mesh` covers both sources of geometry — a reconstruction and a
# compiled spec — because the question the column answers is "did Phase 2 produce
# anything", not which path it took.
ARTIFACT_COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bp", ("blueprint.png",)),
    ("spec", ("spec.json",)),
    ("mesh", ("raw_mesh.obj", "compiled_mesh.stl")),
    ("eng", ("engineered_mesh.obj", "engineered_mesh.stl", "engineered_mesh.3mf")),
    ("gcode", ("engineered_mesh.gcode",)),
    ("score", ("printability.json",)),
)

# What the blueprint gate leaves behind before Phase 2 has run. Such a directory is not
# an abandoned run — a person is being asked to approve the image in it — so it is
# called out by name rather than being reported as "nearly empty".
_GATE_SNAPSHOT = ("blueprint.png",)


def outputs_root() -> Path:
    """Locate `data/outputs`, honouring the same override the pipeline reads.

    Returns:
        The configured output root. It need not exist.
    """
    configured = os.environ.get("DS_OUTPUTS_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent.parent / "data" / "outputs"


@dataclass(frozen=True)
class JobOutputs:
    """One directory under `data/outputs`, described from what is in it."""

    path: Path
    job_id: str
    is_fixture: bool
    is_empty: bool
    files: tuple[str, ...]
    total_bytes: int
    mtime: float

    @property
    def is_gate_snapshot(self) -> bool:
        """True when this holds the approval gate's blueprint and nothing else.

        Such a directory predates Phase 2 deliberately, and pruning by age would throw
        away the image a parked job is asking someone to approve.
        """
        if not self.files:
            return False
        return all(
            name in _GATE_SNAPSHOT or name.endswith(".provenance.json")
            for name in self.files
        )

    def has(self, column: str) -> bool:
        """Whether this directory holds the artifact a display column stands for.

        Args:
            column: A key from `ARTIFACT_COLUMNS`.

        Returns:
            True when at least one of that column's filenames is present.
        """
        for name, filenames in ARTIFACT_COLUMNS:
            if name == column:
                return any(f in self.files for f in filenames)
        raise KeyError(column)

    def to_dict(self) -> dict:
        """Render for `--json`, with the columns resolved so a script need not repeat them."""
        return {
            "job_id": self.job_id,
            "path": str(self.path),
            "fixture": self.is_fixture,
            "empty": self.is_empty,
            "gate_snapshot": self.is_gate_snapshot,
            "files": list(self.files),
            "bytes": self.total_bytes,
            "modified": self.mtime,
            "artifacts": {name: self.has(name) for name, _ in ARTIFACT_COLUMNS},
        }


def describe(path: Path) -> JobOutputs:
    """Describe one job directory from its contents.

    Args:
        path: A directory under `data/outputs`.

    Returns:
        Its `JobOutputs`. `is_empty` follows `find -type d -empty` — no entries at all,
        not "no files I recognise" — because that is the predicate the prune acts on and
        the two must not drift apart.
    """
    files: list[str] = []
    total = 0
    newest = 0.0
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        files.append(child.name)
        total += stat.st_size
        newest = max(newest, stat.st_mtime)

    try:
        empty = not any(path.iterdir())
    except OSError:
        empty = False

    if not newest:
        try:
            newest = path.stat().st_mtime
        except OSError:
            newest = 0.0

    name = path.name
    is_fixture = name.startswith(DEV_OUTPUT_PREFIX)
    return JobOutputs(
        path=path,
        job_id=name[len(DEV_OUTPUT_PREFIX):] if is_fixture else name,
        is_fixture=is_fixture,
        is_empty=empty,
        files=tuple(sorted(files)),
        total_bytes=total,
        mtime=newest,
    )


def scan(root: Path | None = None) -> list[JobOutputs]:
    """Describe every job directory under the output root, newest first.

    Symlinks are skipped rather than followed: the prune reuses this list, and a
    directory reached through a link is not one this tool may delete.

    Args:
        root: The output root. Defaults to `outputs_root()`.

    Returns:
        One `JobOutputs` per direct child directory, most recently written first.
    """
    root = outputs_root() if root is None else root
    if not root.is_dir():
        return []
    found = [
        describe(child)
        for child in root.iterdir()
        if child.is_dir() and not child.is_symlink()
    ]
    return sorted(found, key=lambda job: job.mtime, reverse=True)


def flat_artifacts(root: Path | None = None) -> tuple[str, ...]:
    """List artifacts sitting directly in the output root.

    A run without `--job-id` — the manual CLI path — writes there, and `POST /jobs`
    sweeps those files precisely because a finished job with no export of its own would
    otherwise be answered with one of them. Worth showing, because they belong to no
    job and nothing in a directory listing says so.

    Args:
        root: The output root. Defaults to `outputs_root()`.

    Returns:
        The filenames, sorted.
    """
    root = outputs_root() if root is None else root
    if not root.is_dir():
        return ()
    return tuple(sorted(child.name for child in root.iterdir() if child.is_file()))


def prunable(
    jobs: list[JobOutputs], *, days: float | None = None, now: float | None = None
) -> list[JobOutputs]:
    """Choose what a prune should remove.

    Empty directories always: removing one cannot lose anything, and they are the whole
    of the reported problem. Age is opt-in and separate, because "older than N days" is
    a retention policy over real artifacts and must never be what a bare
    `make clean-outputs` does.

    The approval gate's blueprint snapshot is exempt from the age rule: a job can sit
    parked indefinitely, and the image it is asking a person to approve is the one thing
    that must survive. An *empty* directory is still removed — the gate always writes
    the blueprint, so an empty one is not a parked job.

    Args:
        jobs: Directories from `scan()`.
        days: Also remove directories not written to in this many days. None means empty only.
        now: Epoch seconds to measure age from. For tests.

    Returns:
        The subset to remove, in the order given.
    """
    now = time.time() if now is None else now
    cutoff = None if days is None else now - days * 86400
    chosen = []
    for job in jobs:
        if job.is_empty:
            chosen.append(job)
        elif cutoff is not None and job.mtime < cutoff and not job.is_gate_snapshot:
            chosen.append(job)
    return chosen


def remove(job: JobOutputs, root: Path) -> None:
    """Delete one job directory, refusing anything that is not one.

    Args:
        job: The directory to remove.
        root: The output root it must be a direct child of.

    Raises:
        ValueError: If the path is not a direct, non-symlink child directory of `root`.
            The age mode deletes real artifacts, so the containment check is not
            decoration — a `DS_OUTPUTS_DIR` pointing somewhere unexpected, or a symlink
            planted in the tree, must fail rather than be followed.
    """
    path = job.path
    if path.parent.resolve() != root.resolve() or path.is_symlink() or not path.is_dir():
        raise ValueError(f"Refusing to remove {path}: not a job directory under {root}")
    if job.is_empty:
        path.rmdir()
    else:
        shutil.rmtree(path)


# ── Rendering ─────────────────────────────────────────────────────────────────
def _age(seconds: float) -> str:
    """Render an age as the largest unit that still reads as a number."""
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 5400:
        return f"{int(seconds / 60)}m"
    if seconds < 172800:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"


def _size(nbytes: int) -> str:
    """Render a byte count in the largest unit under 1024."""
    value = float(nbytes)
    for unit in ("B", "K", "M", "G"):
        if value < 1024 or unit == "G":
            return f"{value:.0f}{unit}" if unit == "B" or value >= 10 else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.0f}G"


def render(jobs: list[JobOutputs], flat: tuple[str, ...], now: float) -> str:
    """Render the listing a person reads.

    Args:
        jobs: Directories from `scan()`, newest first.
        flat: Filenames from `flat_artifacts()`.
        now: Epoch seconds to measure ages from.

    Returns:
        The whole report, without a trailing newline.
    """
    if not jobs and not flat:
        return "No job output directories."

    headers = [name for name, _ in ARTIFACT_COLUMNS]
    widths = [max(len(h), 3) for h in headers]
    lines = [
        "  ".join(
            ["AGE".rjust(5), "SIZE".rjust(6)]
            + [h.upper().center(w) for h, w in zip(headers, widths, strict=True)]
            + ["JOB"]
        )
    ]
    for job in jobs:
        cells = [
            ("✓" if job.has(name) else "·").center(w)
            for (name, _), w in zip(ARTIFACT_COLUMNS, widths, strict=True)
        ]
        notes = []
        if job.is_empty:
            notes.append("empty")
        if job.is_fixture:
            notes.append("fixture")
        if job.is_gate_snapshot:
            notes.append("awaiting approval")
        suffix = f"  ({', '.join(notes)})" if notes else ""
        lines.append(
            "  ".join(
                [_age(now - job.mtime).rjust(5), _size(job.total_bytes).rjust(6)]
                + cells
                + [job.path.name + suffix]
            )
        )

    empty = sum(1 for job in jobs if job.is_empty)
    total = sum(job.total_bytes for job in jobs)
    lines.append("")
    lines.append(
        f"{len(jobs)} job directories, {empty} empty, {_size(total)} total."
        + ("" if not empty else "  Remove the empty ones with: make clean-outputs")
    )
    if flat:
        lines.append(
            "Flat layout (a run with no --job-id, owned by no job): " + ", ".join(flat)
        )
    return "\n".join(lines)


def _plural(count: int) -> str:
    """Render a directory count with an ending that matches it."""
    return f"{count} director" + ("y" if count == 1 else "ies")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pythonsrc.outputs",
        description="What each data/outputs job directory holds, and what is safe to delete.",
    )
    parser.add_argument("--limit", type=int, default=0, metavar="N", help="Show only the N newest.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Remove empty job directories (nothing else, unless --days is given).",
    )
    parser.add_argument(
        "--days",
        type=float,
        default=None,
        metavar="N",
        help="With --prune, also remove job directories not written to in N days. "
             "This deletes real artifacts.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="With --prune, list what would go and remove nothing."
    )
    parser.add_argument(
        "--root", default=None, metavar="DIR", help="Output root (default: $DS_OUTPUTS_DIR or data/outputs)."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    args = _build_parser().parse_args(argv)
    if args.days is not None and not args.prune:
        print("--days only means something with --prune.", file=sys.stderr)
        return 2

    root = Path(args.root) if args.root else outputs_root()
    jobs = scan(root)
    now = time.time()

    if args.prune:
        doomed = prunable(jobs, days=args.days, now=now)
        if not doomed:
            print(f"Nothing to prune in {root}.")
            return 0
        # Printed before anything is removed, and printed in full: with --days this
        # deletes meshes and G-code, and a count alone is not something a person can
        # check against what they meant to type.
        verb = "Would remove" if args.dry_run else "Removing"
        for job in doomed:
            why = "empty" if job.is_empty else f"{_age(now - job.mtime)} old, {_size(job.total_bytes)}"
            print(f"{verb} {job.path.name}  ({why})")
        if args.dry_run:
            print(f"\n{_plural(len(doomed))} would be removed. Nothing was.")
            return 0
        removed = 0
        for job in doomed:
            try:
                remove(job, root)
                removed += 1
            except (OSError, ValueError) as exc:
                print(f"Could not remove {job.path}: {exc}", file=sys.stderr)
        print(f"\nRemoved {removed} of {_plural(len(doomed))}.")
        return 0 if removed == len(doomed) else 1

    shown = jobs[: args.limit] if args.limit else jobs
    flat = flat_artifacts(root)
    if args.json:
        print(json.dumps(
            {"root": str(root), "jobs": [job.to_dict() for job in shown], "flat": list(flat)},
            indent=2,
        ))
        return 0
    print(render(shown, flat, now))
    return 0


if __name__ == "__main__":
    sys.exit(main())
