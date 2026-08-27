#!/usr/bin/env python3
"""normalise_licence_data.py — make raw licence-tool output fit to commit.

Both tools emit things that must not go into git as they stand.

**`pip-licenses --with-license-file` embeds every licence text in full.** That data is
what catches the failure mode this repo has hit twice — a package tagged one thing whose
licence text says another (`openai/clip-vit-*`, `briaai/RMBG-2.0`) — so it is worth
capturing. Kept for every package it is also several megabytes of MIT boilerplate per
merge, which makes the file useless to diff. So the text survives only where reading it
could change an answer: anything the policy does not classify as permissive. A permissive
row keeps its `LicenseFile` path, which is enough to fetch the text from the image later.

**`license-checker` emits absolute paths.** Committed verbatim they record whichever
machine ran the tool — `/Users/<someone>/…` locally, `/home/runner/work/…` in CI — so the
file churns on every run for reasons that have nothing to do with licences, and a
developer's directory layout ends up in git.

Idempotent: running it twice changes nothing the second time. The ecosystem is detected
from the payload shape, so the same command works on either file.

    python infra/scripts/normalise_licence_data.py licenses/python.json
    python infra/scripts/normalise_licence_data.py licenses/node.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from pythonsrc.licence_policy import PERMISSIVE, classify  # noqa: E402

#: Enough of a licence to identify it and to spot an out-of-scope or non-commercial
#: clause, which in practice sit in the opening paragraphs.
MAX_TEXT_CHARS = 6000

_TRUNCATION_MARKER = "\n… truncated; read the file named in LicenseFile."

_PLACEHOLDERS = frozenset({"", "UNKNOWN", "NOASSERTION"})

#: Path fields license-checker fills with absolute locations.
_PATH_FIELDS = ("path", "licenseFile")

#: The only artifact fields a licence audit reads. syft's own output for the pipeline
#: image is **16 MB**: `metadata` alone is 9 MB of per-package file manifests, `files` a
#: further 6 MB, and `cpes` most of the rest. None of it says anything about a licence,
#: and committing it on every merge would put 20 MB of churn in git for a file nothing
#: can diff. `purl` is kept because it is the one field that identifies a package
#: unambiguously across ecosystems.
KEEP_ARTIFACT_FIELDS = ("name", "version", "type", "language", "licenses", "purl")

#: Top-level syft keys worth keeping: what was scanned, which distro it was, and which
#: syft produced it. Without `descriptor` a stale SBOM cannot be told from a fresh one.
KEEP_SBOM_FIELDS = ("source", "distro", "descriptor", "schema")


def trim_pip_licenses(rows: list[dict], max_chars: int = MAX_TEXT_CHARS) -> tuple[int, int]:
    """Drop permissive licence texts, truncate the rest. Returns (kept, dropped)."""
    kept = dropped = 0
    for row in rows:
        text = row.get("LicenseText")
        if not isinstance(text, str) or text in _PLACEHOLDERS:
            row.pop("LicenseText", None)
            continue
        if classify(row.get("License")) == PERMISSIVE:
            row.pop("LicenseText", None)
            dropped += 1
            continue
        if len(text) > max_chars and not text.endswith(_TRUNCATION_MARKER):
            row["LicenseText"] = text[:max_chars] + _TRUNCATION_MARKER
        kept += 1
    return kept, dropped


def _relative(value: str) -> str:
    """Turn an absolute path into one relative to the repo, wherever it was produced.

    The tool runs in `web/`, inside a checkout whose location differs per machine, so the
    repo root cannot be matched by prefix. `node_modules` is the anchor that is always
    present and always in the same place relative to the app.
    """
    if not isinstance(value, str) or not value:
        return value
    # Already relative — a second pass over a normalised file must be a no-op, or the
    # committed data churns every run and `git diff` stops meaning "a licence changed".
    if not Path(value).is_absolute():
        return value
    marker = "node_modules/"
    index = value.find(marker)
    if index != -1:
        return "web/" + value[index:]
    try:
        return str(Path(value).relative_to(REPO_ROOT))
    except ValueError:
        return Path(value).name


def relativise_node_paths(payload: dict) -> int:
    """Rewrite absolute paths in license-checker output. Returns fields changed."""
    changed = 0
    for row in payload.values():
        if not isinstance(row, dict):
            continue
        for field in _PATH_FIELDS:
            value = row.get(field)
            new = _relative(value)
            if new != value:
                row[field] = new
                changed += 1
    return changed


def slim_sbom(payload: dict) -> tuple[int, int]:
    """Reduce a syft-json SBOM to the licence-relevant fields.

    Returns `(artifacts, fields_dropped)`. Idempotent: an already-slimmed SBOM has
    nothing left to drop.
    """
    dropped = 0
    artifacts = []
    for artifact in payload.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        dropped += sum(1 for key in artifact if key not in KEEP_ARTIFACT_FIELDS)
        artifacts.append(
            {key: artifact[key] for key in KEEP_ARTIFACT_FIELDS if key in artifact}
        )
    artifacts.sort(key=lambda a: (str(a.get("name", "")).lower(), str(a.get("version", ""))))

    for key in list(payload):
        if key not in KEEP_SBOM_FIELDS and key != "artifacts":
            del payload[key]
            dropped += 1
    payload["artifacts"] = artifacts
    return len(artifacts), dropped


def _is_sbom(payload: object) -> bool:
    return isinstance(payload, dict) and "artifacts" in payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path, help="licence data file to rewrite in place")
    parser.add_argument("--out", type=Path, default=None, help="write here instead of in place")
    parser.add_argument("--max-chars", type=int, default=MAX_TEXT_CHARS)
    args = parser.parse_args(argv)

    payload = json.loads(args.path.read_text(encoding="utf-8"))
    target = args.out or args.path

    if _is_sbom(payload):
        count, dropped = slim_sbom(payload)
        summary = f"{count} artifacts, {dropped} licence-irrelevant fields dropped"
    elif isinstance(payload, list):
        kept, dropped = trim_pip_licenses(payload, args.max_chars)
        payload.sort(key=lambda row: str(row.get("Name", "")).lower())
        summary = (
            f"{len(payload)} packages, {kept} licence texts kept for review, "
            f"{dropped} permissive texts dropped"
        )
    elif isinstance(payload, dict):
        changed = relativise_node_paths(payload)
        payload = {key: payload[key] for key in sorted(payload)}
        summary = f"{len(payload)} packages, {changed} absolute paths made relative"
    else:
        print(f"[normalise-licence-data] {args.path}: unrecognised shape", file=sys.stderr)
        return 2

    target.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[normalise-licence-data] {target}: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
