#!/usr/bin/env python3
"""Every file under `licenses/` must parse as JSON.

Cheap, static, and it is the check that was missing: `licenses/sbom/ds-mvp-pipeline.json`
was committed unparseable six times in ten regenerations (#129) and nothing anywhere
said so. `licence_report.py` now records an unreadable source in `unreadable_sources`
and drops the verdict to `incomplete`, but that is the audit describing its own damage
after the fact. This refuses to let the damage be committed at all, and the same
function backs `tests/test_licence_data.py`, so a corrupt artifact fails an ordinary
`pytest tests/` on the pull request that carries it rather than on the next audit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LICENCES_DIR = REPO_ROOT / "licenses"


def unparseable(licences_dir: Path) -> list[tuple[Path, str]]:
    """Every `*.json` under `licences_dir` that does not parse, with its reason.

    Recursive: the SBOMs live in `licenses/sbom/`, and they are the ones this exists
    for. Returned rather than printed so a test can assert on the list.
    """
    bad: list[tuple[Path, str]] = []
    for path in sorted(licences_dir.rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            bad.append((path, str(exc)))
    return bad


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    licences_dir = Path(argv[0]) if argv else LICENCES_DIR
    if not licences_dir.is_dir():
        print(f"[check-licence-json] no such directory: {licences_dir}", file=sys.stderr)
        return 2

    bad = unparseable(licences_dir)
    for path, reason in bad:
        try:
            where = path.relative_to(REPO_ROOT)
        except ValueError:
            where = path
        print(f"::error file={where}::does not parse as JSON — {reason}")
        print(f"[check-licence-json] {where}: {reason}", file=sys.stderr)

    if bad:
        print(
            f"[check-licence-json] {len(bad)} unparseable file(s) under {licences_dir}. "
            "A licence artifact that does not parse is an audit that cannot be "
            "reproduced; it is not committed.",
            file=sys.stderr,
        )
        return 1

    count = len(list(licences_dir.rglob("*.json")))
    print(f"[check-licence-json] {count} file(s) under {licences_dir} parse.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
