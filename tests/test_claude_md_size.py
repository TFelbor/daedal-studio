"""`CLAUDE.md` is the contract, `docs/SYSTEM-AS-BUILT.md` is the reasoning.

The action loads `CLAUDE.md` into **every turn of every pipeline run** — implement,
fix, review, plan — so a 200-turn implement job carried it two hundred times. At
167 KB it was the largest single item in each request and all but a tenth of it was
reference material an agent needs by section, on demand. Issue #91 moved everything
from `## Project Overview` down into `docs/SYSTEM-AS-BUILT.md` verbatim; see
`docs/PIPELINE.md` § `--max-turns` for the arithmetic.

Two failure modes, both invisible in a diff and both closed here:

* **The contract grows back.** Nothing about a documentation file resists 40 KB of
  new prose being appended to it, and the cost lands on every turn of every run
  rather than on the person who wrote the paragraph. `MAX_CONTRACT_BYTES` is the
  ceiling, and a section that does not fit belongs in `SYSTEM-AS-BUILT.md`.
* **A section is dropped in a later edit.** The moved prose is load-bearing — it was
  reviewed sentence by sentence, and several paragraphs are the only record of why a
  line of code is what it is. `PRE_MOVE_HEADINGS` is the full `## `/`### ` list of
  `CLAUDE.md` as it stood immediately before the move, so every heading has to be
  accounted for in one file or the other.

A third: **a `CLAUDE.md §` reference that names a section CLAUDE.md no longer has.**
Such a pointer does not fail, it just sends whoever follows it to the wrong file, and
there is no build step that resolves it.

`PRE_MOVE_HEADINGS` was computed from git history rather than copied by eye, at the
commit that split the file — its first parent is the last revision of the combined
`CLAUDE.md`, so piping `git show <split-commit>~1:CLAUDE.md` through `headings()`
below reproduces the list exactly. The fence skip `headings()` performs is what makes
that honest: `## Build & Run Commands` holds a fenced shell block whose comment lines
begin with `#`, and reading those as headings invents a dozen sections that never
existed.

Everything here is static: no file is written and no model is called.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "CLAUDE.md"
SYSTEM_AS_BUILT = REPO_ROOT / "docs" / "SYSTEM-AS-BUILT.md"

# 30 KB, against ~11 KB today: room for the contract to grow by half again before
# anyone has to argue about it, and a hard stop long before it is a per-turn cost.
MAX_CONTRACT_BYTES = 30 * 1024

# `CLAUDE.md`'s headings immediately before the split, in file order. The first five
# are the contract and stay; every one after `## Project Overview` moved.
PRE_MOVE_HEADINGS = [
    "## ds-mvp — Claude Code guide",
    "### Build and test",
    "### Layout",
    "### Conventions",
    "### Definition of done",
    "## Project Overview",
    "## Build & Run Commands",
    "## Architecture",
    "### Pipeline (pythonsrc/pipeline.py)",
    "### Sculptor — Phase 2 (pythonsrc/sculptors/)",
    "### Hosted sculptor (pythonsrc/sculptors/pixazo.py)",
    "### Sculptor worker (services/trellis2_worker/)",
    "### Organizer — the parametric path (pythonsrc/organizer/)",
    "### Server (server/app.py)",
    "### Data Flow",
    "### Telemetry (pythonsrc/telemetry/)",
    "### Slice statistics (pythonsrc/gcode_stats.py)",
    "### Mesh repair — Phase 3 (pythonsrc/engineer.py)",
    "### Printability (pythonsrc/printability.py)",
    "### Orientation and adhesion (Phase 3 → Phase 4)",
    "### Slicer — Phase 4 (pythonsrc/slicer.py)",
    "### Printer readiness (`printer_status`)",
    "### Dispatch gate — Phase 5 waits on a person",
    "### IP screening and the blueprint gate",
    "### Printer Operators (pythonsrc/operators/)",
    "### Docker Infrastructure",
    "### Frontend (web/)",
    "## Configuration",
    "## Licensing Constraints",
    "## Important Constraints",
]

_SPLIT_AT = PRE_MOVE_HEADINGS.index("## Project Overview")
KEPT_HEADINGS = PRE_MOVE_HEADINGS[:_SPLIT_AT]
MOVED_HEADINGS = PRE_MOVE_HEADINGS[_SPLIT_AT:]

# The index in `CLAUDE.md` that stands in for the moved sections.
INDEX_HEADING = "## The system as built"


def headings(text: str) -> list[str]:
    """Every `## `/`### ` heading, skipping fenced code blocks."""
    found: list[str] = []
    fence = False
    for line in text.split("\n"):
        if line.startswith("```"):
            fence = not fence
            continue
        if not fence and line.startswith(("## ", "### ")):
            found.append(line.rstrip())
    return found


def _normalise(text: str) -> str:
    """Drop the markdown emphasis that separates an index entry from a heading."""
    return re.sub(r"[`*#]", "", text).strip()


def test_contract_stays_small() -> None:
    """`CLAUDE.md` rides in every turn, so its size is a per-turn cost."""
    size = CONTRACT.stat().st_size
    assert size < MAX_CONTRACT_BYTES, (
        f"CLAUDE.md is {size} bytes, over the {MAX_CONTRACT_BYTES}-byte ceiling. "
        "It is loaded into every turn of every pipeline run; reference prose belongs "
        "in docs/SYSTEM-AS-BUILT.md, with a one-line entry in the index."
    )


def test_system_as_built_exists() -> None:
    assert SYSTEM_AS_BUILT.is_file(), f"{SYSTEM_AS_BUILT} is missing"


@pytest.mark.parametrize("heading", MOVED_HEADINGS)
def test_every_moved_section_survives(heading: str) -> None:
    """Nothing was dropped on the way across."""
    assert heading in headings(SYSTEM_AS_BUILT.read_text(encoding="utf-8")), (
        f"{heading!r} was in CLAUDE.md before the split and is in neither file now. "
        "The moved prose is the only record of why several decisions are what they "
        "are; restore it rather than rewriting it."
    )


@pytest.mark.parametrize("heading", KEPT_HEADINGS)
def test_the_contract_sections_stay_in_claude_md(heading: str) -> None:
    """Build and test, layout, conventions and done are what an agent must obey."""
    assert heading in headings(CONTRACT.read_text(encoding="utf-8")), (
        f"{heading!r} is part of the contract and must stay in CLAUDE.md"
    )


def test_the_index_lists_every_moved_section() -> None:
    """An unlisted section is one nobody knows to go and read."""
    text = CONTRACT.read_text(encoding="utf-8")
    assert INDEX_HEADING in text, f"CLAUDE.md has no {INDEX_HEADING!r} section"
    index = _normalise(text.split(INDEX_HEADING, 1)[1])

    missing = [h for h in MOVED_HEADINGS if _normalise(h) not in index]
    assert not missing, (
        "CLAUDE.md's index does not name these moved sections: "
        + ", ".join(repr(h) for h in missing)
    )


def test_the_index_points_at_the_file_it_indexes() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    assert "docs/SYSTEM-AS-BUILT.md" in text.split(INDEX_HEADING, 1)[1]


# Where a `CLAUDE.md §` pointer may appear. `docs/superpowers/` is deliberately out:
# those are dated plans and specs, a record of what was true when they were written.
SEARCH_ROOTS = (".github", "docs", "infra", "pythonsrc", "server", "tests", "web/src")
SEARCH_SUFFIXES = {".md", ".py", ".ts", ".tsx", ".sh", ".yml", ".yaml", ".json"}
SECTION_REF = re.compile(r"CLAUDE\.md\s*§\s*(.+)")


def _searchable_files() -> list[Path]:
    files = [p for p in REPO_ROOT.glob("*.md") if p.is_file()]
    for root in SEARCH_ROOTS:
        for path in (REPO_ROOT / root).rglob("*"):
            if not path.is_file() or path.suffix not in SEARCH_SUFFIXES:
                continue
            if "superpowers" in path.parts or "node_modules" in path.parts:
                continue
            files.append(path)
    return files


def test_section_references_name_a_section_claude_md_still_has() -> None:
    """`CLAUDE.md § Organizer` now means `docs/SYSTEM-AS-BUILT.md § Organizer`."""
    kept = tuple(_normalise(h) for h in KEPT_HEADINGS)
    offenders: list[str] = []
    for path in _searchable_files():
        if path == Path(__file__).resolve():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = SECTION_REF.search(line)
            if not match:
                continue
            named = _normalise(match.group(1))
            if not any(named.startswith(section) for section in kept):
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{number}: {line.strip()}")

    assert not offenders, (
        "These reference a CLAUDE.md section that moved to docs/SYSTEM-AS-BUILT.md:\n"
        + "\n".join(offenders)
    )
