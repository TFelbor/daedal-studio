"""`run_operator.py` must import when launched the way the dispatch gate launches it.

`POST /jobs/{id}/print-dispatch` runs the operator as a subprocess:
`[sys.executable, str(repo_root / "pythonsrc" / "run_operator.py"), ...]` with
`cwd=repo_root`. Python puts the **script's own directory** on `sys.path`, never the
working directory — so `/app/pythonsrc` was importable and `/app` was not, and
`from pythonsrc.operators import PrinterFactory` raised on every confirmed dispatch:

    [dispatch] operator starting for engineered_mesh.gcode
    ModuleNotFoundError: No module named 'pythonsrc'
    [dispatch] operator exited with 1

which the gate correctly records as a failed Phase 5 — a job that reached a printer
having sliced, scored and asserted everything, and never opened a connection.

Not a development-only accident: it reproduces in the api-server image, which is where
that subprocess really runs —

    docker run --rm -w /app ds-api-server:latest python pythonsrc/run_operator.py --help

— and the image's own `PYTHONPATH=/app/pythonsrc` cannot help, because that is the path
for `import operators`, not for `import pythonsrc.operators`. `pipeline.py` has inserted
the repository root itself since it was written (`sys.path.insert` near its top); its
sibling entry point had not, and nothing compared them. Found by the first real
end-to-end spec run (#110).

`--help` is enough: the import runs at module load, before `argparse` sees anything, so
an exit code of 0 means the module imported. The launch is repeated from three working
directories because the defect was invisible from exactly one of them — a shell sitting
in the repository root with `pythonsrc` importable for its own reasons.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Launched by absolute path from `server.app`, so the working directory is the gate's
#: to choose and must not decide whether the process starts.
OPERATOR = REPO_ROOT / "pythonsrc" / "run_operator.py"


def test_the_entry_point_is_where_the_gate_looks_for_it():
    assert OPERATOR.exists(), (
        f"{OPERATOR.relative_to(REPO_ROOT)} is gone, and server/app.py launches it by "
        "that path"
    )


@pytest.mark.parametrize(
    "where",
    [
        pytest.param(REPO_ROOT, id="repo-root"),
        # The gate passes `cwd=repo_root`, but nothing in the script may depend on it.
        pytest.param(REPO_ROOT / "pythonsrc", id="script-dir"),
        pytest.param(Path(__file__).resolve().parent, id="elsewhere"),
    ],
)
def test_it_imports_whatever_the_working_directory_is(where):
    finished = subprocess.run(
        [sys.executable, str(OPERATOR), "--help"],
        cwd=where,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert finished.returncode == 0, (
        "the operator could not start from "
        f"{where}:\n{finished.stdout}\n{finished.stderr}"
    )
    # The flags the gate actually passes, so a rename is caught here rather than as a
    # failed dispatch.
    for flag in ("--job-id", "--gcode-path", "--profile"):
        assert flag in finished.stdout, f"{flag} is gone from the operator's interface"


#: Every firmware name that may not appear in a module-level import. OctoPrint is the
#: one #74 names, because it is the one that was there; the rest are here because the
#: criterion's *point* is that this module stays firmware-agnostic until it has read
#: `DS_FIRMWARE`, and a guard that only forbids yesterday's mistake is not a guard.
FIRMWARE_NAMES = ("octoprint", "moonraker", "klipper", "bambu")


def _module_level_imports(path: Path) -> list[str]:
    """Every name imported at module level — not inside a function, not conditionally."""
    names: list[str] = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
            names += [alias.name for alias in node.names]
    return names


def test_no_firmware_specific_import_at_module_top_level():
    """#74's fourth criterion, asserted rather than inspected.

    `run_operator.py` is launched once per dispatch and learns which printer it is
    talking to from `DS_FIRMWARE` at runtime. A firmware-specific import at module level
    is the shape the defect had: `OctoPrintCollector` imported unconditionally, and
    therefore used unconditionally, whatever firmware the gate had resolved.

    Walked with `ast` rather than grepped, so a name inside a function body — which is
    where `collector_for` legitimately imports all three — does not trip it.
    """
    offenders = [
        name
        for name in _module_level_imports(OPERATOR)
        if any(firmware in name.lower() for firmware in FIRMWARE_NAMES)
    ]

    assert offenders == [], (
        f"{OPERATOR.name} imports {offenders} at module level. The firmware is not "
        "known until DS_FIRMWARE is read; import inside the branch that needs it."
    )


def test_the_guard_would_catch_the_import_it_exists_for(tmp_path: Path):
    """The guard's own regression test. An assertion over a list that is empty for the
    wrong reason — a walk that finds nothing — passes just as quietly."""
    offender = tmp_path / "run_operator.py"
    offender.write_text(
        "from pythonsrc.telemetry.octoprint_collector import OctoPrintCollector\n"
        "def f():\n"
        "    from pythonsrc.telemetry.moonraker_collector import MoonrakerCollector\n"
    )

    found = [
        name
        for name in _module_level_imports(offender)
        if any(firmware in name.lower() for firmware in FIRMWARE_NAMES)
    ]

    # The top-level one is caught; the one inside `f` is not, which is the distinction
    # `collector_for` depends on.
    assert any("octoprint" in name.lower() for name in found)
    assert not any("moonraker" in name.lower() for name in found)
