#!/usr/bin/env python3
"""licence_report.py — merge the committed licence data into one scored index.

`licenses/` holds raw tool output, regenerated in CI
(`.github/workflows/licence-data.yml`): `pip-licenses` run *inside* the built images,
`license-checker` over the web app's production tree, and `syft` SBOMs that catch the
OS packages a base image drags in. Each file is complete and none of them is readable
at a glance — pip-licenses alone runs to several hundred entries.

This script turns them into `licenses/report.json`: counts, a licence histogram, and
the rows that need a person. It is the file an audit should read *first*, because it
answers "what changed and what is not permissive" without loading the raw trees.

Every verdict comes from `pythonsrc/licence_policy.py`, which the test suite imports
too — a report with its own idea of which licences are acceptable is a report that
disagrees with the guards it is supposed to summarise.

Two design points worth keeping:

* **Ecosystem decides `in_process`.** A Python distribution and an npm package are
  linked into something this project runs; a `.deb` inside an image is not linked into
  anything by being installed. AGPL-3.0 is a hard stop in the first case and a recorded
  isolation in the second, so the same licence string earns different verdicts and the
  source file is what tells them apart.
* **A wheel in an image is in-process only when our code runs in that image.** The rule
  above is right for `ds-mvp-pipeline` and `ds-api-server`, and for the registry images
  they are built *on* — a wheel in `python:3.10-slim` is a wheel our server imports. It
  is wrong for a peer service: `octoprint/octoprint` is reached over HTTP and holds
  OctoPrint's own AGPL plugins, and scoring those as linked denied the build on every
  merge to `main` for a tree this project never imports. `licence_policy`
  `ARM_LENGTH_IMAGE_SBOMS` names the exceptions, and their flags aggregate rather than
  listing one row per plugin — the isolation is recorded once, not re-litigated on
  every run.
* **`allow` rows are counted, not listed.** `findings` carries flags, denials and the
  arm's-length components that are *expected* to appear. A report that lists all 1,400
  permissive packages is one nobody diffs, and the point of committing this is true
  deltas rather than the same forty lines on every run.

Usage:
    python infra/scripts/licence_report.py                      # write licenses/report.json
    python infra/scripts/licence_report.py --audit-out auto     # + docs/audits/<date>-licence.md
    python infra/scripts/licence_report.py --fail-on flag       # non-zero exit on any flag
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from pythonsrc.licence_policy import (  # noqa: E402  (path set above)
    ALLOW,
    DENY,
    FLAG,
    PROJECT_LICENCE,
    UNKNOWN,
    arm_length_image,
    verdict,
    worst_severity,
)

SCHEMA_VERSION = 3

#: The files CI produces, and what each one is. `in_process` is the licensing question,
#: not a description of the file: it decides whether strong copyleft in that tree is a
#: violation or an isolation to confirm. Anything found in `licenses/` that is not
#: described here is still read — as an unlabelled source with the safe (in-process)
#: assumption — because a new tool must not be silently dropped from the audit.
KNOWN_SOURCES: dict[str, dict[str, Any]] = {
    "python.json": {
        "label": "Python — pipeline-runner image (Phases 1, 3-5)",
        "ecosystem": "python",
        "tool": "pip-licenses",
        "in_process": True,
    },
    "python-api-server.json": {
        "label": "Python — api-server image",
        "ecosystem": "python",
        "tool": "pip-licenses",
        "in_process": True,
    },
    "python-mac.json": {
        # Not distributed, and therefore not refreshed on the schedule (2026-09-12):
        # this is the tree a developer installs on their own Apple Silicon machine to
        # run the models locally instead of paying for an API, and licence obligations
        # attach to distribution. The label says so, because a reader comparing dates
        # across sources will otherwise read a stale file as a broken pipeline.
        "label": (
            "Python — macOS native dev tree (requirements-mac.txt); "
            "not distributed, refreshed on request only"
        ),
        "ecosystem": "python",
        "tool": "pip-licenses",
        "in_process": True,
    },
    "python-worker.json": {
        "label": "Python — TRELLIS.2 GPU worker image (Phase 2)",
        "ecosystem": "python",
        "tool": "pip-licenses",
        "in_process": True,
    },
    "node.json": {
        "label": "npm — web app, production tree only",
        "ecosystem": "npm",
        "tool": "license-checker",
        "in_process": True,
    },
    "node-dev.json": {
        "label": "npm — web app build toolchain (dev dependencies)",
        "ecosystem": "npm",
        "tool": "license-checker",
        "in_process": False,
    },
}

#: Which files must exist for the report to be considered complete. A missing one is
#: recorded in `missing_sources` rather than quietly reducing the package count — an
#: audit that cannot tell "no findings" from "no data" is worse than no audit.
EXPECTED_SOURCES = ("python.json", "python-api-server.json", "node.json")

#: Package types an image SBOM reports that are *linked into* something this project
#: runs. A wheel inside the pipeline image is the same in-process risk as one named in
#: `requirements-base.txt`; the SBOM is just how it was discovered.
LINKED_PACKAGE_TYPES = frozenset({"python", "npm", "javascript", "gem", "rust-crate", "go-module"})

#: Package types that are the operating system underneath. Every Debian or Alpine base
#: image carries dozens of GPL packages — bash, coreutils, gcc's runtime — and none of
#: them is a violation while the images stay undistributed and the components stay at
#: arm's length. Listing them one per row buries the finding that matters, so copyleft
#: at this layer is rolled into one aggregate per image and licence class: the count
#: still moves when a base image changes, which is the signal worth diffing.
OS_PACKAGE_TYPES = frozenset({"deb", "apk", "rpm", "alpm", "binary", "os", "spdx", "portage", "nix"})


# ── Readers ──────────────────────────────────────────────────────────────────


def _read_pip_licenses(payload: Any) -> Iterator[dict[str, Any]]:
    """pip-licenses `--format=json`: a list of records with capitalised keys."""
    if not isinstance(payload, list):
        return
    for row in payload:
        if not isinstance(row, dict):
            continue
        yield {
            "package": row.get("Name") or "",
            "version": row.get("Version") or "",
            "licence": row.get("License") or "",
            "url": row.get("URL") or "",
            "author": row.get("Author") or "",
        }


_NPM_KEY_RE = re.compile(r"^(?P<name>.+)@(?P<version>[^@]+)$")


def _read_license_checker(payload: Any) -> Iterator[dict[str, Any]]:
    """license-checker `--json`: an object keyed `name@version`."""
    if not isinstance(payload, dict):
        return
    for key, row in payload.items():
        match = _NPM_KEY_RE.match(key)
        name = match.group("name") if match else key
        version = match.group("version") if match else ""
        row = row if isinstance(row, dict) else {}
        licences = row.get("licenses")
        if isinstance(licences, list):
            licences = " AND ".join(str(item) for item in licences)
        yield {
            "package": name,
            "version": version,
            "licence": licences or "",
            "url": row.get("repository") or "",
            "author": row.get("publisher") or "",
            "private": bool(row.get("private")),
        }


def _syft_licence(entry: Any) -> str:
    """syft reports a list of licence objects; prefer the SPDX expression."""
    if not isinstance(entry, list):
        return ""
    values: list[str] = []
    for item in entry:
        if isinstance(item, dict):
            value = item.get("spdxExpression") or item.get("value") or ""
        else:
            value = str(item)
        if value:
            values.append(value)
    # Several declared licences on one package means all of them apply.
    return " AND ".join(dict.fromkeys(values))


def _read_sbom(payload: Any) -> Iterator[dict[str, Any]]:
    """syft-json (`artifacts`) or SPDX-json (`packages`)."""
    if not isinstance(payload, dict):
        return
    for artifact in payload.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        yield {
            "package": artifact.get("name") or "",
            "version": artifact.get("version") or "",
            "licence": _syft_licence(artifact.get("licenses")),
            "type": artifact.get("type") or "",
            "url": "",
            "author": "",
        }
    for package in payload.get("packages") or []:
        if not isinstance(package, dict):
            continue
        declared = package.get("licenseDeclared") or ""
        concluded = package.get("licenseConcluded") or ""
        licence = concluded if concluded not in ("", "NOASSERTION") else declared
        yield {
            "package": package.get("name") or "",
            "version": package.get("versionInfo") or "",
            "licence": "" if licence == "NOASSERTION" else licence,
            "type": "spdx",
            "url": "",
            "author": "",
        }


def _load(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[licence-report] could not read {path}: {exc}", file=sys.stderr)
        return None


# ── Report ───────────────────────────────────────────────────────────────────


def _git_sha() -> str:
    for env_key in ("GITHUB_SHA", "DS_GIT_SHA"):
        import os

        value = os.environ.get(env_key)
        if value:
            return value
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _iter_source_files(licences_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Every data file in `licenses/`, each with its descriptor.

    Discovered rather than enumerated: a new image's SBOM must join the audit by being
    written to the directory, not by also being added to a list here.
    """
    found: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(licences_dir.glob("*.json")):
        if path.name == "report.json":
            continue
        descriptor = KNOWN_SOURCES.get(path.name)
        if descriptor is None:
            descriptor = {
                "label": f"Unlabelled source ({path.name})",
                "ecosystem": "unknown",
                "tool": "unknown",
                "in_process": True,
            }
        found.append((path, descriptor))
    for path in sorted((licences_dir / "sbom").glob("*.json")):
        isolation = arm_length_image(path.stem)
        found.append(
            (
                path,
                {
                    "label": (
                        f"SBOM — {path.stem} (arm's length)"
                        if isolation
                        else f"SBOM — {path.stem}"
                    ),
                    "ecosystem": "image",
                    "tool": "syft",
                    "in_process": False,
                    # `linked` is the question the per-row override below turns on: does
                    # anything this project runs live inside this image? Defaulted True
                    # so an unrecognised SBOM keeps the safe assumption.
                    "linked": isolation is None,
                    "isolation": isolation or "",
                },
            )
        )
    return found


def _rows_for(path: Path, descriptor: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _load(path)
    if payload is None:
        return []
    if descriptor["ecosystem"] == "image":
        return list(_read_sbom(payload))
    if descriptor["tool"] == "license-checker" or isinstance(payload, dict):
        return list(_read_license_checker(payload))
    return list(_read_pip_licenses(payload))


def build_report(licences_dir: Path) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    histogram: Counter[str] = Counter()
    by_classification: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    total_packages = 0

    for path, descriptor in _iter_source_files(licences_dir):
        rows = _rows_for(path, descriptor)
        source_name = str(path.relative_to(licences_dir))
        source_histogram: Counter[str] = Counter()

        aggregate: dict[tuple[str, str], dict[str, Any]] = {}
        self_declared = 0

        for row in rows:
            package = row["package"]
            if not package:
                continue
            # The workspace root is this project, declared `UNLICENSED` because it is
            # private. Scoring it would report Daedal Studio as an unlicensed dependency
            # of itself, once per run, forever.
            if row.get("private"):
                self_declared += 1
                continue
            row_type = (row.get("type") or "").lower()
            # An SBOM's own wheels are linked; its .debs are the platform underneath —
            # but only for an image our code runs in. In a peer service every layer is
            # arm's length, so `linked` gates the override rather than the type alone.
            row_in_process = bool(descriptor["in_process"]) or (
                descriptor.get("linked", True) and row_type in LINKED_PACKAGE_TYPES
            )
            severity, classification, note = verdict(
                package, row["licence"], in_process=row_in_process
            )
            licence_label = row["licence"] or "UNDECLARED"
            histogram[licence_label] += 1
            source_histogram[licence_label] += 1
            by_classification[classification] += 1
            by_severity[severity] += 1
            total_packages += 1

            # `allow` rows are counted above and listed only when they are a recorded
            # exception — an arm's-length or reviewed-copyleft component carries a note,
            # and those are exactly the rows an auditor must not re-litigate each run.
            # Two kinds of SBOM row are expected in bulk and say nothing individually:
            # the operating system underneath, and a wheel whose licence syft could not
            # read but the dedicated tool did. Both are aggregated. A denial never is.
            layer = ""
            if descriptor["ecosystem"] == "image":
                if row_type in OS_PACKAGE_TYPES and not row_in_process:
                    layer = "os"
                elif not descriptor.get("linked", True):
                    # A peer service's application packages. AGPL is what OctoPrint *is*;
                    # the count moving is the signal, a row per plugin is not.
                    layer = "service"
                elif row_type in LINKED_PACKAGE_TYPES and classification == UNKNOWN:
                    layer = "unreadable"

            if severity == FLAG and layer:
                bucket = aggregate.setdefault(
                    (layer, classification),
                    {"count": 0, "packages": [], "licences": Counter()},
                )
                bucket["count"] += 1
                bucket["packages"].append(f"{package}@{row['version']}" if row["version"] else package)
                bucket["licences"][licence_label] += 1
                continue

            if severity != ALLOW or note:
                findings.append(
                    {
                        "package": package,
                        "version": row["version"],
                        "licence": licence_label,
                        "classification": classification,
                        "severity": severity,
                        "source": source_name,
                        "ecosystem": descriptor["ecosystem"],
                        "note": note,
                    }
                )

        for (layer, classification), bucket in sorted(aggregate.items()):
            packages = sorted(bucket["packages"])
            if layer == "os":
                label = f"({bucket['count']} OS packages)"
                note = (
                    "Operating-system layer of the image. Not linked in-process and not "
                    "distributed today; a change in this count means a base image changed. "
                    "Distributing the image would put source-offer obligations on the "
                    "copyleft entries — see THIRD-PARTY-NOTICES.md."
                )
            elif layer == "service":
                label = f"({bucket['count']} packages inside an arm's-length service)"
                note = (
                    (descriptor.get("isolation") or "")
                    + " Not built here and not linked: this image is scanned so a change "
                    "in what it ships is visible, not because its licences bind this "
                    "project. A change in this count means the service image changed."
                ).strip()
            else:
                label = f"({bucket['count']} packages with no licence metadata)"
                note = (
                    "syft could not read a licence from the package metadata. These are "
                    "the same distributions the pip-licenses / license-checker file for "
                    "this image covers, and that file is the authoritative reading — a row "
                    "each here would be 200 findings a week that another file already "
                    "answers."
                )
            findings.append(
                {
                    "package": label,
                    "version": "",
                    "licence": ", ".join(
                        f"{name} x{count}" for name, count in bucket["licences"].most_common(6)
                    ),
                    "classification": classification,
                    "severity": FLAG,
                    "source": source_name,
                    "ecosystem": descriptor["ecosystem"],
                    "aggregate": True,
                    "layer": layer,
                    "count": bucket["count"],
                    "packages": packages[:80],
                    "packages_truncated": max(0, len(packages) - 80),
                    "note": note,
                }
            )

        sources.append(
            {
                "name": source_name,
                "label": descriptor["label"],
                "ecosystem": descriptor["ecosystem"],
                "tool": descriptor["tool"],
                "in_process": bool(descriptor["in_process"]),
                "linked": bool(descriptor.get("linked", True)),
                "isolation": descriptor.get("isolation", ""),
                "status": "ok" if rows else "empty",
                "packages": len(rows) - self_declared,
                "private_packages_skipped": self_declared,
                "top_licences": dict(source_histogram.most_common(10)),
            }
        )

    present = {source["name"] for source in sources}
    missing = [name for name in EXPECTED_SOURCES if name not in present]

    findings.sort(
        key=lambda f: (
            {DENY: 0, FLAG: 1, ALLOW: 2}.get(f["severity"], 3),
            f["source"],
            f["package"].lower(),
        )
    )

    return {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _git_sha(),
        "project_licence": PROJECT_LICENCE,
        # "incomplete" outranks "allow" but not "deny": a report with no data for one of
        # its trees must not read as a clean bill of health, and a reader that only looks
        # at this field is the reader most likely to be misled.
        "verdict": (
            worst_severity(f["severity"] for f in findings)
            if any(f["severity"] == DENY for f in findings)
            else "incomplete"
            if missing
            else worst_severity(f["severity"] for f in findings)
            if findings
            else ALLOW
        ),
        "totals": {
            "packages": total_packages,
            "sources": len(sources),
            "by_classification": dict(sorted(by_classification.items())),
            "by_severity": dict(sorted(by_severity.items())),
            "findings": len(findings),
            "deny": by_severity.get(DENY, 0),
            "flag": by_severity.get(FLAG, 0),
        },
        "licence_histogram": dict(histogram.most_common()),
        "missing_sources": missing,
        "sources": sources,
        "findings": findings,
    }


# ── Audit note ───────────────────────────────────────────────────────────────

GENERATED_BEGIN = "<!-- generated:begin — rewritten by infra/scripts/licence_report.py -->"
GENERATED_END = "<!-- generated:end -->"

_AUDIT_NAME_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})-licence\.md$")


def _digest(report: dict[str, Any]) -> dict[str, Any]:
    """The delta anchor. Only fields whose change means something: counts, and the
    identity of each finding. Deliberately excludes `generated_at` and `commit`, so a
    rerun that found nothing new produces a byte-identical digest.
    """
    return {
        "packages": report["totals"]["packages"],
        "by_severity": report["totals"]["by_severity"],
        "deny": report["totals"]["deny"],
        "flag": report["totals"]["flag"],
        "missing_sources": report["missing_sources"],
        # An aggregate row is keyed by its class and count, not by its licence
        # histogram: a base-image bump that reshuffles which GPL packages are present
        # without changing how many is not a new finding, and keying on the histogram
        # would report one every time.
        "findings": sorted(
            (
                f"{f['severity']}:{f['source']}:{f.get('layer', 'os')}-{f['classification']}:{f['count']}"
                if f.get("aggregate")
                else f"{f['severity']}:{f['source']}:{f['package']}@{f['version']}:{f['licence']}"
            )
            for f in report["findings"]
        ),
    }


def _previous_digest(audits_dir: Path, exclude: Path) -> tuple[str, dict[str, Any]] | None:
    candidates = sorted(
        (p for p in audits_dir.glob("*-licence.md") if p != exclude and _AUDIT_NAME_RE.match(p.name)),
        reverse=True,
    )
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        match = re.search(r"```json\s+digest\s*\n(?P<body>.*?)```", text, re.DOTALL)
        if not match:
            match = re.search(r"<!-- digest\s*\n(?P<body>.*?)-->", text, re.DOTALL)
        if match:
            try:
                return path.name, json.loads(match.group("body"))
            except json.JSONDecodeError:
                continue
    return None


def _delta_lines(current: dict[str, Any], previous: tuple[str, dict[str, Any]] | None) -> list[str]:
    if previous is None:
        return [
            "No earlier audit carries a digest, so there is nothing to diff against yet.",
            "This run is the baseline; the next one reports true deltas.",
        ]
    name, old = previous
    old_findings = set(old.get("findings") or [])
    new_findings = set(current["findings"])
    added = sorted(new_findings - old_findings)
    resolved = sorted(old_findings - new_findings)
    lines = [f"Compared against `{name}`.", ""]
    lines.append(
        f"- Packages: {old.get('packages', '?')} → {current['packages']}"
        f" ({current['packages'] - (old.get('packages') or 0):+d})"
    )
    lines.append(f"- Denials: {old.get('deny', '?')} → {current['deny']}")
    lines.append(f"- Flags: {old.get('flag', '?')} → {current['flag']}")
    lines.append("")
    if added:
        lines.append(f"**New findings ({len(added)})**")
        lines += [f"- `{item}`" for item in added]
    else:
        lines.append("**New findings:** none.")
    lines.append("")
    if resolved:
        lines.append(f"**No longer present ({len(resolved)})**")
        lines += [f"- `{item}`" for item in resolved]
    else:
        lines.append("**No longer present:** none.")
    return lines


def _findings_table(report: dict[str, Any], limit: int = 60) -> list[str]:
    findings = report["findings"]
    if not findings:
        return ["Nothing to report: every package classified permissive.", ""]
    lines = [
        "| Severity | Package | Version | Licence | Class | Source | Note |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in findings[:limit]:
        note = (f["note"] or "").replace("|", "\\|")
        lines.append(
            f"| {f['severity']} | `{f['package']}` | {f['version']} | {f['licence']} | "
            f"{f['classification']} | `{f['source']}` | {note} |"
        )
    if len(findings) > limit:
        lines.append("")
        lines.append(
            f"_{len(findings) - limit} further findings omitted from this table; all of "
            "them are in `licenses/report.json`._"
        )
    lines.append("")
    return lines


def render_audit(report: dict[str, Any], audits_dir: Path, out_path: Path) -> str:
    digest = _digest(report)
    previous = _previous_digest(audits_dir, exclude=out_path)
    body: list[str] = [
        GENERATED_BEGIN,
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Commit:** `{report['commit'] or 'unknown'}`",
        f"- **Verdict:** {report['verdict']}",
        f"- **Packages scored:** {report['totals']['packages']} across "
        f"{report['totals']['sources']} "
        f"{'source' if report['totals']['sources'] == 1 else 'sources'}",
        f"- **Denials / flags:** {report['totals']['deny']} / {report['totals']['flag']}",
    ]
    if report["missing_sources"]:
        body.append(
            "- **Incomplete:** no data for "
            + ", ".join(f"`{name}`" for name in report["missing_sources"])
            + " — treat the counts as a floor."
        )
    body += ["", "## Delta", ""]
    body += _delta_lines(digest, previous)
    body += ["", "## Findings", ""]
    body += _findings_table(report)
    # One "Linkage" column rather than a yes/no "In-process": an image SBOM is always
    # `in_process: no` at the file level, which said nothing about the distinction that
    # actually decides its verdicts — whether our code runs inside it.
    body += ["## Sources", "", "| File | Packages | Tool | Linkage |", "|---|---|---|---|"]
    for source in report["sources"]:
        if source["in_process"]:
            linkage = "in-process"
        elif not source.get("linked", True):
            linkage = "arm's length"
        elif source["ecosystem"] == "image":
            linkage = "image (our code runs here)"
        else:
            linkage = "not linked into what ships"
        body.append(
            f"| `{source['name']}` | {source['packages']} | {source['tool']} | {linkage} |"
        )
    body += [
        "",
        "## Digest",
        "",
        "Machine-readable anchor for the next run's delta. Do not edit by hand.",
        "",
        "```json digest",
        json.dumps(digest, indent=2, sort_keys=True),
        "```",
        "",
        GENERATED_END,
    ]
    return "\n".join(body)


def write_audit(report: dict[str, Any], out_path: Path) -> None:
    """Write the generated block, preserving anything a person wrote around it.

    The routine that reads this directory adds reasoning a scanner cannot produce —
    whether a flag matters, what was decided. Regenerating the file wholesale would
    delete exactly that, so only the marked block is replaced.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    generated = render_audit(report, out_path.parent, out_path)

    if out_path.exists():
        existing = out_path.read_text(encoding="utf-8")
        if GENERATED_BEGIN in existing and GENERATED_END in existing:
            head, _, rest = existing.partition(GENERATED_BEGIN)
            _, _, tail = rest.partition(GENERATED_END)
            out_path.write_text(head + generated + tail, encoding="utf-8")
            return
        out_path.write_text(existing.rstrip() + "\n\n" + generated + "\n", encoding="utf-8")
        return

    date = report["generated_at"][:10]
    header = (
        f"# Licence audit — {date}\n\n"
        "Generated from `licenses/` by `infra/scripts/licence_report.py`. The block "
        "below is rewritten on every run; anything outside it is preserved, so record "
        "human judgement here rather than in the generated table.\n\n"
    )
    out_path.write_text(header + generated + "\n", encoding="utf-8")


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge licences/ into one scored report.")
    parser.add_argument(
        "--licences-dir",
        type=Path,
        default=REPO_ROOT / "licenses",
        help="Directory holding the raw tool output (default: licenses/).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Where to write the report (default: <licences-dir>/report.json).",
    )
    parser.add_argument(
        "--audit-out",
        default=None,
        help="Also write a dated audit note. 'auto' means "
        "docs/audits/<UTC date>-licence.md.",
    )
    parser.add_argument(
        "--fail-on",
        choices=("deny", "flag", "never"),
        default="deny",
        help="Exit non-zero at this severity or worse (default: deny).",
    )
    args = parser.parse_args(argv)

    licences_dir: Path = args.licences_dir
    if not licences_dir.is_dir():
        print(
            f"[licence-report] no such directory: {licences_dir}. CI writes it; see "
            "licenses/README.md to generate it locally.",
            file=sys.stderr,
        )
        return 2

    report = build_report(licences_dir)
    out_path: Path = args.out or (licences_dir / "report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.audit_out:
        audit_path = (
            REPO_ROOT / "docs" / "audits" / f"{report['generated_at'][:10]}-licence.md"
            if args.audit_out == "auto"
            else Path(args.audit_out)
        )
        write_audit(report, audit_path)
        print(f"[licence-report] audit note: {audit_path}")

    totals = report["totals"]
    print(
        f"[licence-report] {out_path}: {totals['packages']} packages, "
        f"{totals['deny']} denied, {totals['flag']} flagged, verdict={report['verdict']}"
    )
    if report["missing_sources"]:
        print(
            "[licence-report] missing sources: "
            + ", ".join(report["missing_sources"])
            + " — counts are a floor, not a total."
        )
    for finding in report["findings"]:
        if finding["severity"] == DENY:
            print(
                f"[licence-report] DENY {finding['package']}=={finding['version']} "
                f"({finding['licence']}) in {finding['source']}: {finding['note']}",
                file=sys.stderr,
            )

    if args.fail_on == "never":
        return 0
    if totals["deny"]:
        return 1
    if args.fail_on == "flag" and totals["flag"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
