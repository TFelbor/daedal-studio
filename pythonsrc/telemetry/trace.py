#!/usr/bin/env python3
"""Show what one job actually wrote to the telemetry database, in write order.

The capture story is spread across three processes — `POST /jobs` opens the row,
`pipeline.py` fills it in phase by phase, and a collector appends samples after
dispatch — so no single file shows what a finished job looks like. Reading the
schema tells you which columns *exist*; it does not tell you which ones a real run
populates, and a column that is always NULL is indistinguishable from one that is
never written until someone looks.

This is that look. `STAGES` below is the map: every write to `print_job`, in the
order it happens, annotated with the call site that performs it. Rendering a real
row against that map turns "50 optional columns" into "these 7 were written at
Phase 1, these 6 at Phase 2, this one is still empty".

**Read-only by construction.** The connection is opened with `mode=ro`, so this
tool can never become the second writer the single-writer rule exists to prevent
(see `db._configure_connection`). That also makes `--db` safe to point at one of
the rotating `telemetry.db.backup-*` snapshots.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sqlite3
import sys
from pathlib import Path

from pythonsrc.telemetry.db import (
    _row_to_job,
    _str_to_dt,
    get_default_db_path,
)


# ── The map ───────────────────────────────────────────────────────────────────
# Every write to print_job, in the order a job encounters them. Kept as data
# rather than prose so the renderer, the coverage summary and the --json output
# all read the same list, and so adding a capture point is one entry here.

@dataclasses.dataclass(frozen=True)
class Stage:
    """One moment at which some process writes to a job's `print_job` row.

    Attributes:
        key: Short identifier, used in `--json` output.
        title: Human label for the stage.
        trigger: What causes the write to happen.
        writer: The `TelemetryDB` method that performs it.
        call_site: `file:line` of the caller, so the reader can go look.
        columns: The columns this stage is responsible for.
        duration_column: The column holding this stage's own wall-clock time, if
            it records one.
    """

    key: str
    title: str
    trigger: str
    writer: str
    call_site: str
    columns: tuple[str, ...]
    duration_column: str | None = None


STAGES: tuple[Stage, ...] = (
    Stage(
        key="created",
        title="Job created",
        trigger="POST /jobs",
        writer="db.insert_job()",
        call_site="server/app.py:728",
        # insert_job writes every dataclass field, but only these carry a value at
        # creation time: the target is resolved and the profile snapshotted before
        # the row exists, precisely so editing a profile later cannot rewrite what
        # a finished job claims to have used.
        columns=(
            "prompt",
            "printer_id",
            "printer_firmware",
            "slicer",
            "profile_name",
            "material_type",
            "material_brand",
            "material_colour",
            "nozzle_diameter_mm",
            "process_params",
            "parent_job_id",
            "regeneration_reason",
        ),
    ),
    Stage(
        key="started",
        title="Pipeline launched",
        trigger="subprocess spawn",
        writer="db.update_job_start_time()",
        call_site="server/app.py:490",
        columns=("started_at",),
    ),
    Stage(
        key="phase1",
        title="Phase 1 · Visualizer",
        trigger="prompt → blueprint.png (FLUX)",
        writer="db.update_job_blueprint()",
        call_site="pythonsrc/pipeline.py:267",
        columns=(
            "blueprint_model",
            "blueprint_model_version",
            "blueprint_seed",
            "blueprint_prompt_engineered",
            "blueprint_params",
            "blueprint_sha256",
            "blueprint_duration_s",
        ),
        duration_column="blueprint_duration_s",
    ),
    Stage(
        key="phase2",
        title="Phase 2 · Sculptor",
        trigger="blueprint → raw_mesh (TRELLIS.2)",
        writer="db.update_job_generation()",
        call_site="pythonsrc/pipeline.py:211",
        columns=(
            "generation_model",
            "generation_model_version",
            "generation_backend",
            "generation_params",
            "generation_cost_eur",
            "generation_duration_s",
        ),
        duration_column="generation_duration_s",
    ),
    Stage(
        key="phase3",
        title="Phase 3 · Engineer",
        trigger="repair + scale, before/after pair",
        writer="db.update_job_mesh_lineage()",
        call_site="pythonsrc/pipeline.py:323",
        columns=(
            "raw_mesh_sha256",
            "raw_mesh_features",
            "repaired_mesh_sha256",
            "repaired_mesh_features",
        ),
    ),
    Stage(
        key="printability",
        title="Printability gate",
        trigger="advisory scoring, not a numbered phase",
        writer="db.update_job_printability()",
        call_site="pythonsrc/pipeline.py:718",
        columns=(
            "printability_score",
            "printability_verdict",
            "mesh_features",
            "printability_report",
        ),
    ),
    Stage(
        key="phase4",
        title="Phase 4 · Slicer",
        trigger="mesh → G-code (CuraEngine)",
        writer="db.update_job_slice()",
        call_site="pythonsrc/pipeline.py:374",
        # Written on failure too: a dataset of only successful slices cannot
        # predict which meshes fail.
        columns=(
            "slice_status",
            "slice_error",
            "slice_duration_s",
            "estimated_print_time_s",
            "filament_used_mm",
            "filament_used_mm3",
            "filament_used_g",
            "support_filament_mm3",
            "layer_count",
            "slice_stats",
        ),
        duration_column="slice_duration_s",
    ),
    Stage(
        key="outcome",
        title="Outcome",
        trigger="printer event, or a human tapping a verdict",
        writer="db.update_job_outcome_verdict()",
        call_site="server/app.py:1580 · octoprint_collector.py:324",
        # outcome_source is the whole point: only "user" is ground truth, and a
        # machine write never overwrites a human one.
        columns=(
            "outcome",
            "outcome_source",
            "completed_at",
            "outcome_reported_at",
        ),
    ),
    Stage(
        key="engagement",
        title="Engagement",
        trigger="GET /jobs/{id}/download",
        writer="db.increment_download_count()",
        call_site="server/app.py:993",
        columns=("download_count",),
    ),
)

# Columns held as JSON text; summarised rather than dumped unless -v is given.
_JSON_COLUMNS = frozenset({
    "process_params",
    "blueprint_params",
    "generation_params",
    "raw_mesh_features",
    "repaired_mesh_features",
    "mesh_features",
    "printability_report",
    "slice_stats",
})

# Values written at row creation as placeholders, not as captured data. `outcome`
# is NOT NULL and starts as "unknown", so counting it as populated would report
# every queued job as having a recorded result. `download_count` defaults to 0,
# which is an absence of downloads. Both are gaps wearing a value.
_PLACEHOLDER_VALUES = {
    "outcome": ("unknown", 'inserted as "unknown" until the printer or a human decides'),
    "download_count": (0, "nobody has downloaded the G-code"),
}

# Values that are legitimately absent rather than missing, so an empty one is not
# a gap worth flagging. `generation_cost_eur` is None for every self-hosted run;
# `slice_error` is None on success; the lineage columns are only set when the job
# is a regeneration.
_EXPECTED_NULL = {
    "generation_cost_eur": "not billed unless backend is hosted_api",
    "slice_error": "only set when the slice failed",
    "parent_job_id": "only set on a regeneration",
    "regeneration_reason": "only set on a regeneration",
    "material_brand": "optional at job creation",
    "material_colour": "optional at job creation",
    "blueprint_seed": "absent under --skip-visualizer",
    "blueprint_prompt_engineered": "absent under --skip-visualizer",
    "outcome_reported_at": "only set once a human answers",
    "support_filament_mm3": "only set when supports were generated",
}


# ── Rendering ─────────────────────────────────────────────────────────────────

class Palette:
    """ANSI codes, or empty strings when the output is not a terminal.

    Follows the same convention as `server/logging_config.py`: `$NO_COLOR`
    disables, `$P2P_LOG_COLOR` forces on, otherwise colour when stdout is a tty.
    """

    def __init__(self, enabled: bool):
        def code(value: str) -> str:
            return value if enabled else ""

        self.reset = code("\033[0m")
        self.dim = code("\033[2m")
        self.bold = code("\033[1m")
        self.green = code("\033[32m")
        self.red = code("\033[31m")
        self.yellow = code("\033[33m")
        self.blue = code("\033[36m")
        self.magenta = code("\033[35m")


def colour_enabled(stream) -> bool:
    """Decide whether to emit ANSI codes.

    Args:
        stream: The output stream that will be written to.

    Returns:
        True if colour should be used.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("P2P_LOG_COLOR") == "1":
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


def format_value(name: str, value, *, verbose: bool, width: int = 58) -> str:
    """Render one column value for a single terminal line.

    Args:
        name: Column name, used to recognise hashes and JSON payloads.
        value: The raw value read from SQLite.
        verbose: When True, JSON payloads are expanded instead of summarised.
        width: Maximum characters before truncation.

    Returns:
        A display string.
    """
    if value is None:
        return "—"

    if name in _JSON_COLUMNS:
        try:
            decoded = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError):
            decoded = None
        if verbose:
            return json.dumps(decoded, indent=2, default=str)
        if isinstance(decoded, dict):
            keys = ", ".join(list(decoded)[:4])
            more = "…" if len(decoded) > 4 else ""
            return f"{{{len(decoded)} keys}} {keys}{more}"
        if isinstance(decoded, list):
            return f"[{len(decoded)} items]"
        return str(decoded)

    if name.endswith("sha256") and isinstance(value, str) and len(value) == 64:
        return value[:12] + "…" if not verbose else value

    if isinstance(value, float):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
    else:
        text = str(value)

    text = text.replace("\n", " ")
    if not verbose and len(text) > width:
        text = text[: width - 1] + "…"
    return text


def _is_populated(name: str, value) -> bool:
    """Decide whether a column holds captured data or merely holds a value.

    One implementation, used by both the per-job report and the listing's coverage
    count, so the two can never disagree about what "captured" means.

    Args:
        name: Column name.
        value: The raw value read from SQLite.

    Returns:
        True if something actually wrote this column.
    """
    if value is None:
        return False
    placeholder = _PLACEHOLDER_VALUES.get(name)
    return not (placeholder and value == placeholder[0])


def stage_report(job, stage: Stage, row: dict) -> dict:
    """Summarise one stage's columns for a job.

    Args:
        job: The reconstructed `PrintJob`.
        stage: The stage to report on.
        row: The raw `print_job` row as a dict, used for columns whose stored form
            differs from the dataclass field (JSON text, ISO timestamps).

    Returns:
        A dict with the per-column values and a populated/total count.
    """
    columns = {}
    populated = 0
    for name in stage.columns:
        raw = row.get(name)
        is_set = _is_populated(name, raw)
        if is_set:
            populated += 1
        columns[name] = {"value": raw, "populated": is_set}
    return {
        "key": stage.key,
        "title": stage.title,
        "populated": populated,
        "total": len(stage.columns),
        "columns": columns,
    }


def render(job, row: dict, extras: dict, *, palette: Palette, verbose: bool) -> str:
    """Build the full trace for one job.

    Args:
        job: The reconstructed `PrintJob`.
        row: The raw `print_job` row as a dict.
        extras: Counts and rows from the satellite tables.
        palette: Colour codes.
        verbose: Expand JSON payloads and full hashes.

    Returns:
        The rendered report.
    """
    c = palette
    out: list[str] = []
    add = out.append

    prompt = (job.prompt or "").replace("\n", " ")
    if len(prompt) > 64:
        prompt = prompt[:63] + "…"
    add("")
    add(f'{c.bold}{job.job_id}{c.reset}  {c.dim}"{prompt}"{c.reset}')
    add(
        f"{c.dim}{job.printer_firmware} · {job.profile_name} · "
        f"{job.material_type or 'no material'}{c.reset}"
    )
    add("")

    total_populated = 0
    total_columns = 0

    for stage in STAGES:
        report = stage_report(job, stage, row)
        total_populated += report["populated"]
        total_columns += report["total"]

        filled = report["populated"]
        of = report["total"]
        if filled == 0:
            marker, colour = "○", c.dim
        elif filled == of:
            marker, colour = "●", c.green
        else:
            marker, colour = "◐", c.yellow

        duration = ""
        if stage.duration_column:
            seconds = row.get(stage.duration_column)
            if seconds is not None:
                duration = f"  {c.blue}{float(seconds):.1f}s{c.reset}"

        rule = "─" * max(2, 34 - len(stage.title))
        add(
            f"{colour}{marker}{c.reset} {c.bold}{stage.title}{c.reset} "
            f"{c.dim}{rule}{c.reset} {colour}{filled}/{of}{c.reset}{duration}"
        )
        add(f"    {c.dim}{stage.trigger}{c.reset}")
        add(f"    {c.dim}{stage.writer}  ·  {stage.call_site}{c.reset}")

        for name, info in report["columns"].items():
            if info["populated"]:
                tick = f"{c.green}✓{c.reset}"
                value = format_value(name, info["value"], verbose=verbose)
                if verbose and "\n" in value:
                    indented = value.replace("\n", "\n" + " " * 8)
                    add(f"    {tick} {name}")
                    add(f"        {c.dim}{indented}{c.reset}")
                    continue
            else:
                note = _EXPECTED_NULL.get(name)
                shown = "—"
                if name in _PLACEHOLDER_VALUES and info["value"] is not None:
                    # Show the placeholder rather than an em dash: the column does
                    # hold something, and pretending otherwise sends the reader
                    # looking for a NULL that is not there.
                    note = _PLACEHOLDER_VALUES[name][1]
                    shown = str(info["value"])
                tick = f"{c.dim}·{c.reset}" if note else f"{c.red}✗{c.reset}"
                value = (
                    f"{c.dim}{shown} ({note}){c.reset}" if note
                    else f"{c.dim}{shown}{c.reset}"
                )
            add(f"    {tick} {name:<30} {value}")
        add("")

    # ── Satellite tables ──────────────────────────────────────────────────────
    # Rows rather than columns, so they cannot be shown as a fill-in count.
    add(f"{c.bold}Satellite tables{c.reset}  {c.dim}{'─' * 20}{c.reset}")

    samples = extras["samples"]
    if samples["count"]:
        span = ""
        if samples["first"] and samples["last"]:
            seconds = (samples["last"] - samples["first"]).total_seconds()
            span = f" over {seconds / 60:.1f} min"
        add(
            f"    {c.green}✓{c.reset} telemetry_sample            "
            f"{samples['count']} rows{span}"
        )
        add(
            f"      {c.dim}written by MoonrakerCollector / OctoPrintCollector, "
            f"one writer per job{c.reset}"
        )
    else:
        add(f"    {c.dim}·{c.reset} telemetry_sample            {c.dim}0 rows{c.reset}")

    claim = extras["claim"]
    if claim:
        add(
            f"    {c.green}✓{c.reset} telemetry_collector_claim   "
            f"owner={claim['owner']}  {c.dim}heartbeat {claim['heartbeat_at']}{c.reset}"
        )
    else:
        add(
            f"    {c.dim}·{c.reset} telemetry_collector_claim   "
            f"{c.dim}unclaimed{c.reset}"
        )

    failures = extras["failures"]
    if failures:
        add(f"    {c.red}✓{c.reset} failure_event               {len(failures)} rows")
        for event in failures:
            add(
                f"      {c.red}{event['failure_type']}{c.reset} "
                f"{c.dim}source={event['source']} at {event['detected_at']}{c.reset}"
            )
    else:
        add(f"    {c.dim}·{c.reset} failure_event               {c.dim}0 rows{c.reset}")

    events = extras["events"]
    if events:
        add(f"    {c.green}✓{c.reset} job_event                   {len(events)} rows")
        for event in events:
            add(
                f"      {c.magenta}{event['kind']:<24}{c.reset} "
                f"{c.dim}{event['occurred_at']}{c.reset}"
            )
    else:
        add(f"    {c.dim}·{c.reset} job_event                   {c.dim}0 rows{c.reset}")

    add("")
    pct = (total_populated / total_columns * 100) if total_columns else 0.0
    add(
        f"{c.bold}Captured{c.reset} {total_populated}/{total_columns} "
        f"print_job columns ({pct:.0f}%)"
    )
    add("")
    return "\n".join(out)


# ── Reading ───────────────────────────────────────────────────────────────────

def open_readonly(db_path: str) -> sqlite3.Connection:
    """Open the telemetry database read-only.

    Read-only is deliberate rather than defensive: the database has exactly one
    writer by design, and an inspection tool that opens a writable handle is one
    `commit` away from being the second.

    Args:
        db_path: Path to the SQLite file.

    Returns:
        A connection with `sqlite3.Row` rows.

    Raises:
        FileNotFoundError: If the database file does not exist.
    """
    if not Path(db_path).exists():
        raise FileNotFoundError(db_path)
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def read_extras(conn: sqlite3.Connection, job_id: str) -> dict:
    """Collect the satellite-table rows for a job.

    Each table is queried defensively: an older database may predate `job_event`
    or the claim table, and a missing table is "nothing recorded", not an error.

    Args:
        conn: A read-only connection.
        job_id: The job to read.

    Returns:
        A dict of sample counts, claim, failure events and job events.
    """
    def query(sql: str, params: tuple = ()) -> list:
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []

    sample_row = query(
        "SELECT COUNT(*) AS n, MIN(sampled_at) AS first, MAX(sampled_at) AS last "
        "FROM telemetry_sample WHERE job_id = ?",
        (job_id,),
    )
    samples = {"count": 0, "first": None, "last": None}
    if sample_row:
        samples = {
            "count": sample_row[0]["n"] or 0,
            "first": _str_to_dt(sample_row[0]["first"]),
            "last": _str_to_dt(sample_row[0]["last"]),
        }

    claim_rows = query(
        "SELECT owner, claimed_at, heartbeat_at FROM telemetry_collector_claim "
        "WHERE job_id = ?",
        (job_id,),
    )
    failures = query(
        "SELECT failure_type, source, detected_at, notes FROM failure_event "
        "WHERE job_id = ? ORDER BY detected_at",
        (job_id,),
    )
    events = query(
        "SELECT kind, occurred_at, detail FROM job_event "
        "WHERE job_id = ? ORDER BY occurred_at",
        (job_id,),
    )

    return {
        "samples": samples,
        "claim": dict(claim_rows[0]) if claim_rows else None,
        "failures": [dict(r) for r in failures],
        "events": [dict(r) for r in events],
    }


def list_jobs(conn: sqlite3.Connection, limit: int, palette: Palette) -> str:
    """Render a compact index of recent jobs and how complete each row is.

    Args:
        conn: A read-only connection.
        limit: Maximum jobs to list.
        palette: Colour codes.

    Returns:
        The rendered listing.
    """
    c = palette
    rows = conn.execute(
        "SELECT * FROM print_job "
        "ORDER BY COALESCE(started_at, '') DESC, job_id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        return (
            f"\n{c.yellow}No jobs in this database yet.{c.reset}\n\n"
            f"  {c.dim}Submit one through the UI, or run the pipeline with "
            f"--job-id to populate a row.{c.reset}\n"
        )

    total_columns = sum(len(s.columns) for s in STAGES)
    out = ["", f"{c.bold}{'job_id':<38}{'started':<21}{'outcome':<18}captured{c.reset}"]
    for row in rows:
        data = dict(row)
        populated = sum(
            1
            for stage in STAGES
            for name in stage.columns
            if _is_populated(name, data.get(name))
        )
        started = (data.get("started_at") or "—")[:19]
        out.append(
            f"{data['job_id']:<38}{started:<21}"
            f"{str(data.get('outcome')):<18}{populated}/{total_columns}"
        )
    out.append("")
    out.append(f"{c.dim}Trace one with: python -m pythonsrc.telemetry.trace <job_id>{c.reset}")
    out.append("")
    return "\n".join(out)


def build_json(job, row: dict, extras: dict) -> dict:
    """Assemble the machine-readable form of the trace.

    Args:
        job: The reconstructed `PrintJob`.
        row: The raw `print_job` row as a dict.
        extras: Satellite-table rows.

    Returns:
        A JSON-serialisable dict.
    """
    stages = []
    for stage in STAGES:
        report = stage_report(job, stage, row)
        stages.append({
            "key": stage.key,
            "title": stage.title,
            "writer": stage.writer,
            "call_site": stage.call_site,
            "populated": report["populated"],
            "total": report["total"],
            "columns": {
                name: info["populated"] for name, info in report["columns"].items()
            },
        })
    return {
        "job_id": job.job_id,
        "prompt": job.prompt,
        "stages": stages,
        "satellite": {
            "telemetry_sample_rows": extras["samples"]["count"],
            "collector_claim": extras["claim"],
            "failure_events": extras["failures"],
            "job_events": extras["events"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Argument list, defaulting to `sys.argv[1:]`.

    Returns:
        A process exit code.
    """
    parser = argparse.ArgumentParser(
        prog="python -m pythonsrc.telemetry.trace",
        description="Show what a job wrote to the telemetry database, in write order.",
    )
    parser.add_argument("job_id", nargs="?", help="Job to trace. Accepts a unique prefix.")
    parser.add_argument("--latest", action="store_true", help="Trace the most recent job.")
    parser.add_argument("--list", action="store_true", help="List recent jobs and exit.")
    parser.add_argument("--limit", type=int, default=20, help="Rows for --list.")
    parser.add_argument(
        "--db",
        default=None,
        help="Database file. Defaults to the standard path; a backup snapshot works too.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Expand JSON payloads and full hashes."
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a report.")
    args = parser.parse_args(argv)

    palette = Palette(colour_enabled(sys.stdout) and not args.json)
    db_path = args.db or get_default_db_path()

    try:
        conn = open_readonly(db_path)
    except FileNotFoundError:
        print(f"No telemetry database at {db_path}", file=sys.stderr)
        return 1

    try:
        if args.list or not (args.job_id or args.latest):
            print(list_jobs(conn, args.limit, palette))
            return 0

        if args.latest:
            row = conn.execute(
                "SELECT * FROM print_job "
                "ORDER BY COALESCE(started_at, '') DESC, job_id DESC LIMIT 1"
            ).fetchone()
        else:
            # A prefix is enough: job ids are UUIDs and nobody types them in full.
            matches = conn.execute(
                "SELECT * FROM print_job WHERE job_id LIKE ?", (args.job_id + "%",)
            ).fetchall()
            if len(matches) > 1:
                print(
                    f"'{args.job_id}' matches {len(matches)} jobs; be more specific.",
                    file=sys.stderr,
                )
                return 1
            row = matches[0] if matches else None

        if row is None:
            print(f"Job not found in {db_path}. Try --list.", file=sys.stderr)
            return 1

        job = _row_to_job(row)
        raw = dict(row)
        extras = read_extras(conn, job.job_id)

        if args.json:
            print(json.dumps(build_json(job, raw, extras), indent=2, default=str))
        else:
            print(render(job, raw, extras, palette=palette, verbose=args.verbose))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
