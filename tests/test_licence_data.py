"""Tests for the committed licence data and the map that describes the stack.

Three things are held here, and each of them is a thing that has already gone wrong
somewhere in this repo:

* **Classification.** `LGPL-3.0` contains `gpl-3` as a substring and `GPL-2.0 or later`
  contains " or ", so the naive readings of both are wrong in opposite directions —
  one over-reports, one under-reports. The rules live in `pythonsrc.licence_policy` and
  are the same rules `tests/test_licensing_guards.py` uses.
* **The report.** Missing data must not read as a clean bill of health, a denial must
  fail the build, and the OS layer of an image must not produce forty findings a week.
* **Drift.** A licence data file that nothing documents, a workflow that stops writing
  one, or a model swapped in the code and not in `ARCHITECTURE.md`, are all invisible in
  a diff. `docs/audits/` and `licenses/` are only worth committing while they are true.
"""

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

from pythonsrc.licence_policy import (
    ALLOW,
    DENY,
    FLAG,
    NON_COMMERCIAL,
    PERMISSIVE,
    STRONG_COPYLEFT,
    UNKNOWN,
    WEAK_COPYLEFT,
    arm_length_image,
    classify,
    verdict,
    worst_severity,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "licence-data.yml"


def _load_script(name: str):
    """Import a script from `infra/scripts/`, which is not a package."""
    path = REPO_ROOT / "infra" / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report_script = _load_script("licence_report.py")
normalise_script = _load_script("normalise_licence_data.py")
check_script = _load_script("check_licence_json.py")


# ── Classification ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "licence,expected",
    [
        ("MIT", PERMISSIVE),
        ("MIT License", PERMISSIVE),
        ("Apache-2.0", PERMISSIVE),
        ("Apache Software License", PERMISSIVE),
        ("BSD-3-Clause", PERMISSIVE),
        ("ISC", PERMISSIVE),
        ("Python-2.0", PERMISSIVE),
        ("Python Software Foundation License", PERMISSIVE),
        # LGPL contains "gpl-3"; matched as weak copyleft or every LGPL package reads
        # as a § 13 problem.
        ("LGPL-3.0", WEAK_COPYLEFT),
        ("LGPLv2+", WEAK_COPYLEFT),
        ("GNU Lesser General Public License v2 or later (LGPLv2+)", WEAK_COPYLEFT),
        ("MPL-2.0", WEAK_COPYLEFT),
        ("AGPL-3.0", STRONG_COPYLEFT),
        ("GPL-3.0-or-later", STRONG_COPYLEFT),
        # " or later" is a version floor, not an SPDX choice. Read as a choice, the
        # permissive half wins and a GPL package is reported as unclassified.
        ("GPL-2.0 or later", STRONG_COPYLEFT),
        ("GNU General Public License v2 or later (GPLv2+)", STRONG_COPYLEFT),
        ("CC BY-NC 4.0", NON_COMMERCIAL),
        ("NVIDIA Source Code License", NON_COMMERCIAL),
        ("UNKNOWN", UNKNOWN),
        ("", UNKNOWN),
        (None, UNKNOWN),
    ],
)
def test_classification(licence, expected):
    assert classify(licence) == expected


def test_or_takes_the_most_permissive_operand():
    """A dual-licensed package is used under the half that suits."""
    assert classify("(MIT OR CC0-1.0)") == PERMISSIVE
    assert classify("MIT or Apache-2.0") == PERMISSIVE
    assert classify("GPL-3.0 OR MIT") == PERMISSIVE


def test_and_takes_the_most_restrictive_operand():
    """Both licences bind at once, so the stricter one governs."""
    assert classify("Apache-2.0 AND GPL-3.0") == STRONG_COPYLEFT
    assert classify("MIT AND CC-BY-NC-4.0") == NON_COMMERCIAL


# ── Verdicts ─────────────────────────────────────────────────────────────────


def test_forbidden_renderers_are_denied_whatever_they_claim():
    """nvdiffrast's tag is not the question; its licence is non-commercial."""
    severity, classification, note = verdict("nvdiffrast", "MIT")
    assert severity == DENY
    assert classification == NON_COMMERCIAL
    assert "NVIDIA" in note


def test_octoprint_is_denied_in_process_and_allowed_at_arms_length():
    """One name, opposite verdicts — which is the whole reason `in_process` exists.

    A Python distribution named `octoprint` is § 13 exposure. The same name reported by
    an image SBOM is the server this project talks HTTP to.
    """
    assert verdict("octoprint", "AGPL-3.0", in_process=True)[0] == DENY
    severity, _, note = verdict("octoprint", "AGPL-3.0", in_process=False)
    assert severity == ALLOW
    assert "HTTP" in note


def test_curaengine_is_a_recorded_exception_not_a_finding():
    severity, classification, note = verdict("cura-engine", "AGPL-3.0-only", in_process=False)
    assert (severity, classification) == (ALLOW, STRONG_COPYLEFT)
    assert "subprocess" in note


def test_reviewed_weak_copyleft_carries_its_reason():
    severity, _, note = verdict("opencv-python-headless", "Apache-2.0 AND LGPL-2.1")
    assert severity == ALLOW
    assert "FFmpeg" in note


def test_unreviewed_weak_copyleft_is_flagged_not_allowed():
    assert verdict("some-lgpl-lib", "LGPL-3.0")[0] == FLAG


def test_an_unreadable_licence_is_flagged_not_assumed_permissive():
    assert verdict("mystery", "")[0] == FLAG
    assert verdict("mystery", "UNKNOWN")[0] == FLAG


def test_strong_copyleft_in_an_image_is_a_flag_not_a_denial():
    """Every Debian base image carries GPL packages. None is linked in-process."""
    assert verdict("bash", "GPL-3.0-or-later", in_process=False)[0] == FLAG
    assert verdict("bash", "GPL-3.0-or-later", in_process=True)[0] == DENY


# The first CI run of the committed audit reported five denials. Three were defects in
# this scoring code, and each of them is now a test: a package that declares several
# licences at once, a distro-provided package nobody chose, and a GPL library that really
# was installed. Getting the first two wrong is how a gate becomes something people
# switch off.


def test_a_mixed_declaration_is_a_reading_task_not_a_denial():
    """docutils declares "BSD License; GNU General Public License (GPL); Public Domain".

    Read as SPDX `AND` that is a denial; read as `OR` it is permissive. Neither is true —
    different files in the package carry different licences, so a person has to look.
    The classification still records that GPL is in there.
    """
    declaration = "BSD License; GNU General Public License (GPL); Public Domain"
    severity, classification, note = verdict("docutils", declaration)
    assert severity == FLAG
    assert classification == STRONG_COPYLEFT
    assert "Several licences declared" in note


def test_a_single_strong_copyleft_declaration_still_denies():
    """The mixed-declaration rule must not become a way through the gate."""
    assert verdict("pymeshlab", "GPL3")[0] == DENY
    assert verdict("pymeshlab", "GPL-3.0-only")[0] == DENY


def test_a_distro_provided_package_is_flagged_not_denied():
    """`python-apt` is in every ubuntu:22.04 image's dist-packages.

    Nothing chose it, no requirements file names it, and nothing here imports it — but it
    is GPL-2 and a distributed image would carry obligations for it, so it is a recorded
    flag rather than either a denial or a pass.
    """
    severity, _, note = verdict("python-apt", "GNU GPL")
    assert severity == FLAG
    assert "python3 install" in note


def test_the_copyleft_extra_scanner_reads_a_whole_manifest():
    """`trimesh[all]` pulls pymeshlab (GPL-3.0) through trimesh's own test extra."""
    from pythonsrc.licence_policy import find_copyleft_extras

    assert find_copyleft_extras('RUN pip install "trimesh[all]>=4.0.0"')
    assert not find_copyleft_extras('RUN pip install "trimesh[easy]>=4.0.0"')


def test_a_full_licence_text_in_the_metadata_field_is_read_as_a_licence():
    """`cascadio`, `embreex` and `xatlas` ship their whole licence in that field.

    MIT's text contains " and " a dozen times, so expression-splitting turned three
    permissive packages into `unknown` and asked a person to read what the tool had
    already been handed. Above 200 characters the string is text, not an expression.
    """
    mit_text = (
        "The MIT License (MIT)\n\nCopyright (c) 2024 Someone\n\nPermission is hereby "
        "granted, free of charge, to any person obtaining a copy of this software and "
        "associated documentation files, to deal in the Software without restriction, "
        "including without limitation the rights to use, copy, modify, merge, publish, "
        "distribute, sublicense, and/or sell copies of the Software."
    )
    assert classify(mit_text) == PERMISSIVE

    gpl_text = (
        "GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007. Copyright (C) 2007 Free "
        "Software Foundation, Inc. Everyone is permitted to copy and distribute verbatim "
        "copies of this license document, but changing it is not allowed. This licence is "
        "a free, copyleft licence for software and other kinds of works."
    )
    assert classify(gpl_text) == STRONG_COPYLEFT


def test_worst_severity_ranks_deny_above_flag():
    assert worst_severity([ALLOW, FLAG, DENY]) == DENY
    assert worst_severity([ALLOW, FLAG]) == FLAG
    assert worst_severity([]) == ALLOW


# ── The report ───────────────────────────────────────────────────────────────


@pytest.fixture
def licences_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "licenses"
    (directory / "sbom").mkdir(parents=True)
    (directory / "python.json").write_text(
        json.dumps(
            [
                {"Name": "trimesh", "Version": "4.11.2", "License": "MIT License"},
                {"Name": "chardet", "Version": "5.0.0", "License": "LGPL-2.1"},
                {"Name": "mystery", "Version": "0.1", "License": "UNKNOWN"},
            ]
        )
    )
    (directory / "python-api-server.json").write_text(
        json.dumps([{"Name": "fastapi", "Version": "0.1", "License": "MIT"}])
    )
    (directory / "node.json").write_text(
        json.dumps(
            {
                "react@19.2.6": {"licenses": "MIT"},
                "web@0.0.0": {"licenses": "UNLICENSED", "private": True},
            }
        )
    )
    (directory / "sbom" / "ds-mvp-pipeline.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "name": "cura-engine",
                        "version": "4.13.0-1",
                        "type": "deb",
                        "licenses": [{"spdxExpression": "AGPL-3.0-only"}],
                    },
                    {
                        "name": "bash",
                        "version": "5.1-6",
                        "type": "deb",
                        "licenses": [{"spdxExpression": "GPL-3.0-or-later"}],
                    },
                    {
                        "name": "coreutils",
                        "version": "8.32",
                        "type": "deb",
                        "licenses": [{"spdxExpression": "GPL-3.0-or-later"}],
                    },
                    {
                        "name": "trimesh",
                        "version": "4.11.2",
                        "type": "python",
                        "licenses": [{"value": "MIT"}],
                    },
                ]
            }
        )
    )
    # Present and declaring nothing, on purpose. `EXPECTED_SOURCES` names this file, so
    # the fixture has to carry it — and an empty artifact list keeps every package count
    # in the tests below unchanged while giving the `empty` status something to be. The
    # distinction from `unreadable` is the whole of #129.
    (directory / "sbom" / "ds-api-server.json").write_text(json.dumps({"artifacts": []}))
    return directory


def test_report_reads_every_ecosystem(licences_dir: Path):
    report = report_script.build_report(licences_dir)
    names = {source["name"] for source in report["sources"]}
    assert names == {
        "python.json",
        "python-api-server.json",
        "node.json",
        "sbom/ds-mvp-pipeline.json",
        "sbom/ds-api-server.json",
    }
    assert report["missing_sources"] == []
    assert report["unreadable_sources"] == []
    assert report["totals"]["packages"] > 0


def test_the_project_itself_is_not_scored_as_a_dependency(licences_dir: Path):
    """`web@0.0.0` is this project, declared UNLICENSED because it is private."""
    report = report_script.build_report(licences_dir)
    node = next(s for s in report["sources"] if s["name"] == "node.json")
    assert node["packages"] == 1
    assert node["private_packages_skipped"] == 1
    assert not any(f["package"] == "web" for f in report["findings"])


def test_os_layer_copyleft_is_aggregated_into_one_finding(licences_dir: Path):
    """Two GPL .debs, one row. Per-package rows would bury the finding that matters."""
    report = report_script.build_report(licences_dir)
    aggregates = [f for f in report["findings"] if f.get("aggregate")]
    assert len(aggregates) == 1
    assert aggregates[0]["count"] == 2
    assert aggregates[0]["classification"] == STRONG_COPYLEFT
    assert sorted(aggregates[0]["packages"]) == ["bash@5.1-6", "coreutils@8.32"]
    assert not any(f["package"] == "bash" for f in report["findings"])


def test_a_wheel_inside_an_image_is_still_scored_in_process(licences_dir: Path):
    """An SBOM's Python rows are linked into what runs; its .debs are the platform."""
    (licences_dir / "sbom" / "ds-mvp-pipeline.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "name": "some-agpl-wheel",
                        "version": "1.0",
                        "type": "python",
                        "licenses": [{"spdxExpression": "AGPL-3.0-only"}],
                    }
                ]
            }
        )
    )
    report = report_script.build_report(licences_dir)
    finding = next(f for f in report["findings"] if f["package"] == "some-agpl-wheel")
    assert finding["severity"] == DENY


def test_a_peer_services_own_wheels_are_not_scored_in_process(licences_dir: Path):
    """The regression that made every merge to `main` red.

    `octoprint/octoprint` is scanned like any other image, but nothing this project runs
    lives inside it — the operators reach it over HTTP. The report used to override every
    `python`-typed SBOM row to in-process, which is right for `ds-mvp-pipeline` and wrong
    here: OctoPrint's own AGPL plugins came back as six § 13 denials, `--fail-on deny`
    failed the job, and the gate spent every merge reporting a tree we never link.
    """
    (licences_dir / "sbom" / "base-octoprint.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "name": "octoprint",
                        "version": "1.11.8",
                        "type": "python",
                        "licenses": [{"value": "GNU Affero General Public License v3"}],
                    },
                    {
                        "name": "octoprint-filecheck",
                        "version": "2025.7.23",
                        "type": "python",
                        "licenses": [{"spdxExpression": "AGPL-3.0-or-later"}],
                    },
                ]
            }
        )
    )
    report = report_script.build_report(licences_dir)
    assert report["totals"]["deny"] == 0

    rows = [f for f in report["findings"] if f["source"] == "sbom/base-octoprint.json"]
    # OctoPrint itself is the recorded exception, so it stays a named `allow` row rather
    # than disappearing: an isolation nobody can see in the report is one nobody rechecks.
    named = [f for f in rows if not f.get("aggregate")]
    assert [f["package"] for f in named] == ["octoprint"]
    assert named[0]["severity"] == ALLOW
    assert "HTTP" in named[0]["note"]

    # Its plugins aggregate. AGPL is what OctoPrint *is*; a row per plugin every week
    # buries the one thing worth diffing, which is the count moving.
    aggregate = [f for f in rows if f.get("aggregate")]
    assert [f["layer"] for f in aggregate] == ["service"]
    assert aggregate[0]["count"] == 1
    assert aggregate[0]["classification"] == STRONG_COPYLEFT
    assert "octoprint/octoprint" in aggregate[0]["note"]


def test_a_base_image_our_own_images_build_on_is_still_linked(licences_dir: Path):
    """`arm's length` is not `base-`.

    `python:3.10-slim` and `nvidia/cuda` are scanned with the same `base-` prefix, and a
    wheel in either really is imported by our code — the api-server image is built on the
    first. Only an image named in `ARM_LENGTH_IMAGE_SBOMS` gets the exemption.
    """
    (licences_dir / "sbom" / "base-python-3.10-slim.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "name": "some-agpl-wheel",
                        "version": "1.0",
                        "type": "python",
                        "licenses": [{"spdxExpression": "AGPL-3.0-only"}],
                    }
                ]
            }
        )
    )
    report = report_script.build_report(licences_dir)
    finding = next(f for f in report["findings"] if f["package"] == "some-agpl-wheel")
    assert finding["severity"] == DENY


def test_arm_length_image_lookup_ignores_the_scan_prefix():
    """`licence-data.yml` names a registry scan `base-<image>`; the prefix is bookkeeping."""
    assert arm_length_image("base-octoprint") == arm_length_image("octoprint")
    assert arm_length_image("octoprint") is not None
    assert arm_length_image("ds-mvp-pipeline") is None
    assert arm_length_image("base-python-3.10-slim") is None


def test_unreadable_sbom_wheels_are_aggregated_not_listed_one_by_one(licences_dir: Path):
    """syft could not read a licence for 201 wheels in the api-server image.

    The pip-licenses file for that same image reads all of them, so a row each would be
    two hundred findings a week that another committed file already answers.
    """
    (licences_dir / "sbom" / "ds-api-server.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {"name": f"wheel{i}", "version": "1.0", "type": "python", "licenses": []}
                    for i in range(5)
                ]
            }
        )
    )
    report = report_script.build_report(licences_dir)
    rows = [
        f
        for f in report["findings"]
        if f["source"] == "sbom/ds-api-server.json"
    ]
    assert len(rows) == 1
    assert rows[0]["aggregate"] is True
    assert rows[0]["layer"] == "unreadable"
    assert rows[0]["count"] == 5
    assert "authoritative" in rows[0]["note"]


def test_a_readable_copyleft_wheel_in_an_sbom_stays_an_individual_denial(licences_dir: Path):
    """The aggregation must not swallow the finding it was added alongside."""
    (licences_dir / "sbom" / "ds-api-server.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {"name": "unreadable", "version": "1.0", "type": "python", "licenses": []},
                    {
                        "name": "pymeshlab",
                        "version": "2025.7.post1",
                        "type": "python",
                        "licenses": [{"spdxExpression": "GPL-3.0-only"}],
                    },
                ]
            }
        )
    )
    report = report_script.build_report(licences_dir)
    finding = next(f for f in report["findings"] if f["package"] == "pymeshlab")
    assert finding["severity"] == DENY


def test_permissive_rows_are_counted_but_not_listed(licences_dir: Path):
    report = report_script.build_report(licences_dir)
    assert report["totals"]["by_classification"][PERMISSIVE] >= 3
    assert not any(
        f["classification"] == PERMISSIVE and f["severity"] == ALLOW and not f["note"]
        for f in report["findings"]
    )


def test_missing_data_reads_as_incomplete_not_clean(tmp_path: Path):
    """The field a hurried reader looks at must not say `allow` over no data."""
    directory = tmp_path / "licenses"
    directory.mkdir()
    (directory / "node.json").write_text(json.dumps({"react@19.2.6": {"licenses": "MIT"}}))
    report = report_script.build_report(directory)
    assert report["missing_sources"] == [
        "python.json",
        "python-api-server.json",
        "sbom/ds-mvp-pipeline.json",
        "sbom/ds-api-server.json",
    ]
    assert report["unreadable_sources"] == []      # absent is not the same as corrupt
    assert report["verdict"] == "incomplete"


def test_a_present_but_unparseable_source_is_loud_rather_than_empty(licences_dir: Path):
    """#129: the corrupt file that read as a complete audit six times in ten.

    `missing_sources` stays empty — the file is *there* — so before this, the one field
    a hurried reader checks said complete while the largest image's whole tree was
    missing from the counts. The verdict and `unreadable_sources` are what now say
    otherwise.
    """
    corrupt = licences_dir / "sbom" / "ds-mvp-pipeline.json"
    good = report_script.build_report(licences_dir)
    corrupt.write_text(corrupt.read_text() + '4"\n }\n}\n')   # #129's own trailing bytes

    report = report_script.build_report(licences_dir)

    assert report["unreadable_sources"] == ["sbom/ds-mvp-pipeline.json"]
    assert report["missing_sources"] == []           # present, so not missing — distinct states
    assert report["verdict"] == "incomplete"
    status = {s["name"]: s["status"] for s in report["sources"]}
    assert status["sbom/ds-mvp-pipeline.json"] == "unreadable"
    assert status["sbom/ds-api-server.json"] == "empty"   # parsed, declared nothing
    # The packages really are gone from the counts; that is why it has to be loud.
    assert report["totals"]["packages"] < good["totals"]["packages"]


def test_an_unreadable_source_nobody_expected_is_still_loud(licences_dir: Path):
    """The live case: `sbom/base-ubuntu-22.04.json` is not in `EXPECTED_SOURCES`.

    Base-image SBOMs are regenerated by a job on its own schedule, so their *absence*
    from a given run is routine and they are deliberately not expected. A corrupt one
    is not routine, and `unreadable_sources` does not ask to have been expected.
    """
    (licences_dir / "sbom" / "base-ubuntu-22.04.json").write_text("{not json")

    report = report_script.build_report(licences_dir)

    assert report["unreadable_sources"] == ["sbom/base-ubuntu-22.04.json"]
    assert "sbom/base-ubuntu-22.04.json" not in report["missing_sources"]
    assert report["verdict"] == "incomplete"


def test_an_unreadable_source_moves_the_digest_so_a_note_is_written(licences_dir: Path):
    """A source falling over has to write an audit note the day it happens.

    The digest is what decides whether a dated note is written at all. If a corrupt
    source did not move it, the failure would wait for the next run that also moved a
    finding — which, for #129, was never.
    """
    before = report_script._digest(report_script.build_report(licences_dir))
    (licences_dir / "python.json").write_text("[{oops")

    after = report_script._digest(report_script.build_report(licences_dir))

    assert before != after
    assert after["unreadable_sources"] == ["python.json"]


def test_every_committed_licence_file_parses():
    """Cheap, static, and would have caught #129 on 4 September.

    The same function gates the commit step in `licence-data.yml`, so a corrupt
    artifact fails on the pull request that carries it rather than on the next audit.
    """
    bad = check_script.unparseable(REPO_ROOT / "licenses")

    assert bad == [], "unparseable licence data: " + ", ".join(
        f"{path.relative_to(REPO_ROOT)} ({reason})" for path, reason in bad
    )


def test_the_json_check_fails_the_build_on_a_corrupt_file(tmp_path: Path):
    directory = tmp_path / "licenses"
    (directory / "sbom").mkdir(parents=True)
    (directory / "node.json").write_text(json.dumps({"react@19.2.6": {"licenses": "MIT"}}))
    assert check_script.main([str(directory)]) == 0

    (directory / "sbom" / "ds-mvp-pipeline.json").write_text('{"artifacts": []}4"\n }\n}\n')

    assert check_script.main([str(directory)]) == 1


def test_a_denial_outranks_incompleteness(tmp_path: Path):
    directory = tmp_path / "licenses"
    directory.mkdir()
    (directory / "node.json").write_text(
        json.dumps({"bad@1.0": {"licenses": "CC-BY-NC-4.0"}})
    )
    report = report_script.build_report(directory)
    assert report["verdict"] == DENY


def test_main_exits_non_zero_on_a_denial(licences_dir: Path):
    (licences_dir / "python.json").write_text(
        json.dumps([{"Name": "nvdiffrast", "Version": "0.3.1", "License": "MIT"}])
    )
    code = report_script.main(["--licences-dir", str(licences_dir), "--fail-on", "deny"])
    assert code == 1
    written = json.loads((licences_dir / "report.json").read_text())
    assert written["totals"]["deny"] == 1


def test_main_does_not_fail_on_flags_by_default(licences_dir: Path):
    assert report_script.main(["--licences-dir", str(licences_dir)]) == 0
    assert report_script.main(["--licences-dir", str(licences_dir), "--fail-on", "flag"]) == 1


def test_an_unlabelled_source_file_is_still_read(licences_dir: Path):
    """A new tool must not be silently dropped from the audit."""
    (licences_dir / "python-worker.json").write_text(
        json.dumps([{"Name": "flash-attn", "Version": "2.7.3", "License": "BSD-3-Clause"}])
    )
    (licences_dir / "something-new.json").write_text(
        json.dumps([{"Name": "surprise", "Version": "1.0", "License": "MIT"}])
    )
    report = report_script.build_report(licences_dir)
    names = {source["name"] for source in report["sources"]}
    assert {"python-worker.json", "something-new.json"} <= names


# ── The audit note ───────────────────────────────────────────────────────────


def test_audit_note_preserves_human_text_across_regeneration(licences_dir: Path, tmp_path: Path):
    """The generated block is rewritten; the reasoning around it is not."""
    audit = tmp_path / "audits" / "2026-01-02-licence.md"
    report = report_script.build_report(licences_dir)
    report_script.write_audit(report, audit)
    assert report_script.GENERATED_BEGIN in audit.read_text()

    audit.write_text(audit.read_text() + "\n## Notes\n\nDecided: the LGPL row is fine.\n")
    report_script.write_audit(report_script.build_report(licences_dir), audit)

    text = audit.read_text()
    assert "Decided: the LGPL row is fine." in text
    assert text.count(report_script.GENERATED_BEGIN) == 1


def test_audit_note_diffs_against_the_previous_dated_file(licences_dir: Path, tmp_path: Path):
    audits = tmp_path / "audits"
    first = audits / "2026-01-01-licence.md"
    report_script.write_audit(report_script.build_report(licences_dir), first)

    # A new flagged package appears the next day.
    (licences_dir / "python.json").write_text(
        json.dumps(
            [
                {"Name": "trimesh", "Version": "4.11.2", "License": "MIT"},
                {"Name": "newly-lgpl", "Version": "2.0", "License": "LGPL-3.0"},
            ]
        )
    )
    second = audits / "2026-01-02-licence.md"
    report_script.write_audit(report_script.build_report(licences_dir), second)

    text = second.read_text()
    assert "Compared against `2026-01-01-licence.md`" in text
    assert "newly-lgpl" in text
    assert "No longer present" in text


def test_a_note_that_would_only_restate_the_previous_one_is_not_written(
    licences_dir: Path, tmp_path: Path
):
    """The empty-commit guard in `licence-data.yml` was unreachable, and this is why.

    `--audit-out auto` wrote `docs/audits/<today>-licence.md` on every run. A new date
    is a new path, so the workflow's staged diff always contained a file that was not
    `report.json`, and the "only the timestamp changed" branch could never be taken:
    every scheduled run committed a ~45 KB duplicate note plus a commit to `main`
    saying nothing. Thirteen notes had accumulated, several byte-identical apart from
    their dates.

    The fix is here rather than in the workflow's bash, because the digest already
    excludes `generated_at` and `commit` for exactly this purpose.
    """
    audits = tmp_path / "audits"
    report = report_script.build_report(licences_dir)
    yesterday = audits / "2026-01-01-licence.md"
    report_script.write_audit(report, yesterday)

    today = audits / "2026-01-02-licence.md"
    assert report_script.audit_note_would_repeat(report, today) == "2026-01-01-licence.md"


def test_a_note_is_written_as_soon_as_a_finding_moves(licences_dir: Path, tmp_path: Path):
    audits = tmp_path / "audits"
    report_script.write_audit(report_script.build_report(licences_dir), audits / "2026-01-01-licence.md")

    (licences_dir / "python.json").write_text(
        json.dumps(
            [
                {"Name": "trimesh", "Version": "4.11.2", "License": "MIT License"},
                {"Name": "newly-lgpl", "Version": "2.0", "License": "LGPL-3.0"},
            ]
        )
    )
    today = audits / "2026-01-02-licence.md"
    assert report_script.audit_note_would_repeat(report_script.build_report(licences_dir), today) is None


def test_the_first_note_is_always_written(licences_dir: Path, tmp_path: Path):
    """Nothing to repeat means nothing to skip — the baseline run must produce a note."""
    report = report_script.build_report(licences_dir)
    first = tmp_path / "audits" / "2026-01-01-licence.md"
    assert report_script.audit_note_would_repeat(report, first) is None


def test_an_existing_note_is_refreshed_whatever_its_digest_says(
    licences_dir: Path, tmp_path: Path
):
    """A same-day rerun updates the note it already wrote.

    Skipping it would freeze the commit sha that note records, and the file may carry
    a person's reasoning around the generated block — `write_audit` preserves that, and
    this guard must not stand between them.
    """
    audits = tmp_path / "audits"
    report = report_script.build_report(licences_dir)
    report_script.write_audit(report, audits / "2026-01-01-licence.md")
    today = audits / "2026-01-02-licence.md"
    report_script.write_audit(report, today)

    assert today.exists()
    assert report_script.audit_note_would_repeat(report, today) is None


def test_two_auto_runs_over_an_unchanged_tree_leave_one_note(
    licences_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """End to end through `--audit-out auto`, which is what CI and `make` run.

    The unit tests above pin `audit_note_would_repeat`; this pins that `main` is wired
    to it, and that the wiring is on the 'auto' path only. Without it the two runs
    produce two dated notes and `licence-data.yml`'s commit guard stays unreachable.
    """
    monkeypatch.setattr(report_script, "REPO_ROOT", tmp_path)
    audits = tmp_path / "docs" / "audits"

    monkeypatch.setattr(report_script, "_utc_now", lambda: "2026-01-01T00:00:00Z", raising=False)
    assert report_script.main(["--licences-dir", str(licences_dir), "--audit-out", "auto"]) == 0
    first = sorted(audits.glob("*-licence.md"))
    assert len(first) == 1, first

    # A second run on a later date over a tree that did not move.
    monkeypatch.setattr(report_script, "_utc_now", lambda: "2026-01-02T00:00:00Z", raising=False)
    assert report_script.main(["--licences-dir", str(licences_dir), "--audit-out", "auto"]) == 0
    assert sorted(audits.glob("*-licence.md")) == first

    # And an explicit --audit-out still writes whatever it is pointed at: the caller
    # named a file, so refusing to produce it would be the surprising answer.
    explicit = tmp_path / "somewhere" / "note.md"
    assert (
        report_script.main(
            ["--licences-dir", str(licences_dir), "--audit-out", str(explicit)]
        )
        == 0
    )
    assert explicit.exists()


def test_the_digest_ignores_the_timestamp_so_an_unchanged_run_is_visibly_unchanged(
    licences_dir: Path,
):
    first = report_script._digest(report_script.build_report(licences_dir))
    second = report_script._digest(report_script.build_report(licences_dir))
    assert first == second
    assert "generated_at" not in first
    assert "commit" not in first


def test_the_digest_keys_os_aggregates_by_count_not_by_membership(licences_dir: Path):
    """A base-image bump that swaps which GPL packages are present is not a finding."""
    before = report_script._digest(report_script.build_report(licences_dir))
    sbom = licences_dir / "sbom" / "ds-mvp-pipeline.json"
    payload = json.loads(sbom.read_text())
    for artifact in payload["artifacts"]:
        if artifact["name"] == "coreutils":
            artifact["name"] = "sed"
            artifact["version"] = "4.8"
    sbom.write_text(json.dumps(payload))
    after = report_script._digest(report_script.build_report(licences_dir))
    assert before["findings"] == after["findings"]


# ── Normalising the raw tool output ──────────────────────────────────────────


def test_permissive_licence_texts_are_dropped_and_others_kept():
    rows = [
        {"Name": "a", "License": "MIT", "LicenseText": "M" * 9000},
        {"Name": "b", "License": "LGPL-2.1", "LicenseText": "L" * 9000},
        {"Name": "c", "License": "UNKNOWN", "LicenseText": "UNKNOWN"},
    ]
    kept, dropped = normalise_script.trim_pip_licenses(rows)
    assert (kept, dropped) == (1, 1)
    assert "LicenseText" not in rows[0]
    assert rows[1]["LicenseText"].endswith(normalise_script._TRUNCATION_MARKER)
    assert "LicenseText" not in rows[2]


def test_node_paths_are_made_relative_and_stay_that_way():
    payload = {
        "react@19.2.6": {
            "licenses": "MIT",
            "path": "/home/runner/work/ds-mvp/ds-mvp/web/node_modules/react",
            "licenseFile": "/home/runner/work/ds-mvp/ds-mvp/web/node_modules/react/LICENSE",
        }
    }
    assert normalise_script.relativise_node_paths(payload) == 2
    assert payload["react@19.2.6"]["path"] == "web/node_modules/react"
    # Idempotent: a second pass must be a no-op, or the committed file churns every run.
    assert normalise_script.relativise_node_paths(payload) == 0


def test_an_sbom_is_slimmed_to_the_licence_relevant_fields():
    """syft's own output for the pipeline image is 16 MB, and none of the bulk is licence
    data: 9 MB of per-package file manifests, 6 MB of file records, and the CPE lists.
    Committed as-is that is 20 MB of churn per merge in a file nothing can diff.
    """
    payload = {
        "artifacts": [
            {
                "id": "abc",
                "name": "bash",
                "version": "5.1-6",
                "type": "deb",
                "foundBy": "dpkg-db-cataloger",
                "locations": [{"path": "/var/lib/dpkg/status"}],
                "licenses": [{"spdxExpression": "GPL-3.0-or-later"}],
                "language": "",
                "cpes": ["cpe:2.3:a:bash"] * 20,
                "purl": "pkg:deb/ubuntu/bash@5.1-6",
                "metadata": {"files": [{"path": f"/x/{i}"} for i in range(500)]},
            }
        ],
        "artifactRelationships": [{"parent": "a", "child": "b"}],
        "files": [{"id": "f", "location": {"path": "/x"}}],
        "source": {"type": "image"},
        "distro": {"id": "ubuntu"},
        "descriptor": {"name": "syft", "version": "1.0.0"},
        "schema": {"version": "16.0.0"},
    }
    count, dropped = normalise_script.slim_sbom(payload)
    assert count == 1
    assert dropped > 0
    assert set(payload) == {"artifacts", "source", "distro", "descriptor", "schema"}
    artifact = payload["artifacts"][0]
    assert set(artifact) == {"name", "version", "type", "language", "licenses", "purl"}
    # Idempotent: a re-run finds nothing left to drop.
    assert normalise_script.slim_sbom(payload)[1] == 0


def test_slimming_keeps_what_the_report_reads(licences_dir: Path):
    """A slimmed SBOM must still score identically — the fields dropped are unread."""
    path = licences_dir / "sbom" / "ds-mvp-pipeline.json"
    before = report_script.build_report(licences_dir)["findings"]
    payload = json.loads(path.read_text())
    for artifact in payload["artifacts"]:
        artifact["metadata"] = {"files": ["/a"] * 100}
        artifact["cpes"] = ["cpe:2.3:a:x"] * 10
    normalise_script.slim_sbom(payload)
    path.write_text(json.dumps(payload))
    assert report_script.build_report(licences_dir)["findings"] == before


def test_committed_node_data_holds_no_machine_paths():
    """The committed file records licences, not whose laptop resolved them."""
    path = REPO_ROOT / "licenses" / "node.json"
    if not path.exists():
        pytest.skip("licenses/node.json not present in this checkout")
    text = path.read_text()
    assert "/Users/" not in text
    assert "/home/runner/" not in text


# ── Drift guards ─────────────────────────────────────────────────────────────


def test_every_known_source_is_documented():
    """A data file nobody documents is one nobody can interpret six months later."""
    readme = (REPO_ROOT / "licenses" / "README.md").read_text()
    for filename in report_script.KNOWN_SOURCES:
        assert filename in readme, f"{filename} is unmentioned in licenses/README.md"


def test_the_workflow_produces_every_expected_source():
    """`report.json` calls a missing file incomplete; CI has to actually write it."""
    workflow = WORKFLOW.read_text()
    for filename in report_script.EXPECTED_SOURCES:
        assert f"licenses/{filename}" in workflow, f"CI never writes licenses/{filename}"


def test_the_workflow_runs_the_scripts_that_score_and_normalise():
    workflow = WORKFLOW.read_text()
    assert "infra/scripts/licence_report.py" in workflow
    assert "infra/scripts/normalise_licence_data.py" in workflow


def test_the_workflow_does_not_run_on_a_push():
    """The cadence: this data is produced on a schedule, not on every merge.

    Regenerating it costs two amd64 image builds plus syft, and the output of a merge
    that touched no dependency was `generated_at` and `commit` in `licenses/report.json`
    and nothing else — measured at ~349 billable minutes over 39 runs, the largest single
    consumer in this repository. Enforcement does not live here: it is
    `tests/test_licensing_guards.py`, which `ci.yml` runs on every push and every pull
    request. This workflow produces the evidence.
    """
    triggers = yaml.safe_load(WORKFLOW.read_text())[True]
    assert "push" not in triggers, (
        "licence-data.yml has a `push:` trigger again. It regenerates a tree that only "
        "changes when a dependency changes; running it per merge spent ~349 billable "
        "minutes to rewrite a timestamp. The `pull_request` paths filter is the "
        "pre-merge check and the schedule is the drift check."
    )
    assert set(triggers) == {"pull_request", "schedule", "workflow_dispatch"}, (
        f"unexpected trigger set {sorted(triggers)}"
    )
    crons = [entry["cron"] for entry in triggers["schedule"]]
    assert crons == ["17 4 1,15 * *"], (
        f"the schedule is {crons}; base images and unpinned ranges move without a "
        "commit here, so this is the only thing that catches a dependency that "
        "changed underneath us, and its cadence is a cost decision. It no longer "
        "pays for the macOS tree — that job came off the schedule on 2026-09-12 "
        "because `requirements-mac.txt` is not distributed; see its own comment."
    )


def test_the_audit_note_and_the_commit_cover_the_same_events():
    """A run that commits the data must also write the note explaining it.

    These were two independent conditions and they drifted: when `push` was dropped from
    the triggers the commit condition was updated and the audit-note condition was not,
    so a `workflow_dispatch` run would have committed a regenerated tree with no dated
    note beside it. They now read one `RECORDS_DATA` expression; this is what keeps it
    that way.
    """
    workflow = WORKFLOW.read_text()
    records = re.search(r"^\s*RECORDS_DATA:\s*(.+)$", workflow, re.MULTILINE)
    assert records, (
        "the `RECORDS_DATA` expression is gone; the audit note and the commit below it "
        "both read it, and they must not become two conditions again"
    )
    events = set(re.findall(r"github\.event_name == '([a-z_]+)'", records.group(1)))
    assert events == {"schedule", "workflow_dispatch"}, (
        f"RECORDS_DATA names {sorted(events)}; the events that commit the tree are the "
        "scheduled run and a dispatch, and both must also write the dated note"
    )

    score_step = workflow.split("name: Score the tree", 1)[1].split("- name:", 1)[0]
    assert '"$RECORDS_DATA" = "true"' in score_step, (
        "the audit note no longer keys on RECORDS_DATA, so a run can commit data "
        "without writing the dated note that explains where it came from"
    )

    commit_step = workflow.split("Commit the data to main", 1)[1].split("run:", 1)[0]
    assert "env.RECORDS_DATA == 'true'" in commit_step, (
        "the commit no longer keys on RECORDS_DATA; it and the audit note above have "
        "become two conditions that can disagree"
    )


def test_the_workflow_only_commits_on_main_or_the_schedule():
    """A pull request — including one from a fork — must not push to a branch.

    Asserted as "no pull-request event may commit" rather than as a fixed list of
    permitted events. The list has already changed once — `push` was dropped when the
    cadence moved off every merge — and a test that enumerates it goes red for a
    scheduling decision while saying nothing about the property that matters.
    """
    workflow = WORKFLOW.read_text()
    commit_step = workflow.split("Commit the data to main", 1)[1]
    guard = commit_step.split("run:", 1)[0]
    condition = next(
        (line for line in guard.splitlines() if line.strip().startswith("if:")), ""
    )
    events = set(re.findall(r"github\.event_name == '([a-z_]+)'", condition))
    if not events and "RECORDS_DATA" in condition:
        # The condition delegates to the job-level expression the audit note also reads
        # (see test_the_audit_note_and_the_commit_cover_the_same_events). Resolve it
        # rather than skipping: the events are still what decides whether a fork's pull
        # request can push, they are just named one level up.
        records = re.search(r"^\s*RECORDS_DATA:\s*(.+)$", workflow, re.MULTILINE)
        assert records, "the condition names RECORDS_DATA but the workflow does not define it"
        events = set(re.findall(r"github\.event_name == '([a-z_]+)'", records.group(1)))
    assert events, (
        "the commit step has no `github.event_name` guard, directly or through "
        "RECORDS_DATA, so it would run for every event this workflow accepts — a fork's "
        "pull request included."
    )
    permitted = {"push", "schedule", "workflow_dispatch"}
    assert events <= permitted, (
        f"{sorted(events - permitted)} may commit the licence data. A pull request, "
        "including one from a fork, must never push to a branch."
    )


def test_the_commit_is_gated_on_main_not_only_on_the_event():
    """The step pushes to `HEAD:${GITHUB_REF_NAME}`, so the ref has to be checked too.

    `workflow_dispatch` can be started from any branch. While it never committed that
    was harmless; now that it does, the event clause alone would land a regenerated
    `licenses/` and a dated audit note on whatever feature branch someone dispatched
    from — under a step still called "Commit the data to main". `schedule` always runs
    on the default branch, so the ref clause costs the run that needs it nothing.
    """
    workflow = WORKFLOW.read_text()
    records = re.search(r"^\s*RECORDS_DATA:\s*(.+)$", workflow, re.MULTILINE)
    assert records, "the workflow no longer defines RECORDS_DATA"
    assert "github.ref == 'refs/heads/main'" in records.group(1), (
        "RECORDS_DATA gates the commit on the event alone. The push below it is "
        "`git push origin HEAD:${GITHUB_REF_NAME}`, not a hard-coded `main`, so a "
        "workflow_dispatch from a feature branch would commit licence data there."
    )

    commit_step = workflow.split("Commit the data to main", 1)[1].split("run:", 1)[0]
    assert "RECORDS_DATA" in commit_step, (
        "the commit step stopped reading RECORDS_DATA, so the `main` gate above no "
        "longer covers it"
    )


#: The model each phase declares in code, and where it is declared. `ARCHITECTURE.md` is
#: read by the audit routines *before* the source, so a model swapped here and not there
#: makes every later conclusion wrong. Extracted by regex rather than by import: these
#: modules pull in torch, and this suite runs on machines that have none.
DECLARED_MODELS = {
    "pythonsrc/visualizer.py": r'MODEL_ID\s*=\s*"([^"]+)"',
    "pythonsrc/sculptors/trellis2.py": r'DEFAULT_MODEL_ID\s*=\s*"([^"]+)"',
    "pythonsrc/ip_screen_image.py": r'DEFAULT_MODEL_ID\s*=\s*"([^"]+)"',
    "pythonsrc/sculptors/background.py": r'"DS_BIREFNET_MODEL_ID",\s*"([^"]+)"',
    "pythonsrc/sculptors/pixazo.py": r'MODEL_SLUG\s*=\s*"([^"]+)"',
}


@pytest.mark.parametrize("source,pattern", sorted(DECLARED_MODELS.items()))
def test_architecture_map_names_the_model_the_code_loads(source, pattern):
    match = re.search(pattern, (REPO_ROOT / source).read_text())
    assert match, f"{source} no longer declares a model id matching {pattern}"
    model_id = match.group(1)
    architecture = (REPO_ROOT / "ARCHITECTURE.md").read_text()
    assert model_id in architecture, (
        f"{source} loads {model_id}, which ARCHITECTURE.md does not mention. The audit "
        "routines read that map before the source; a stale map is worse than none."
    )
