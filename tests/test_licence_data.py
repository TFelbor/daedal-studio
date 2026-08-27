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

from pythonsrc.licence_policy import (
    ALLOW,
    DENY,
    FLAG,
    NON_COMMERCIAL,
    PERMISSIVE,
    STRONG_COPYLEFT,
    UNKNOWN,
    WEAK_COPYLEFT,
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
    (directory / "sbom" / "p2p-mesh-pipeline.json").write_text(
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
    return directory


def test_report_reads_every_ecosystem(licences_dir: Path):
    report = report_script.build_report(licences_dir)
    names = {source["name"] for source in report["sources"]}
    assert names == {
        "python.json",
        "python-api-server.json",
        "node.json",
        "sbom/p2p-mesh-pipeline.json",
    }
    assert report["missing_sources"] == []
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
    (licences_dir / "sbom" / "p2p-mesh-pipeline.json").write_text(
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
    assert report["missing_sources"] == ["python.json", "python-api-server.json"]
    assert report["verdict"] == "incomplete"


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
    sbom = licences_dir / "sbom" / "p2p-mesh-pipeline.json"
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
            "path": "/home/runner/work/p2p/p2p/web/node_modules/react",
            "licenseFile": "/home/runner/work/p2p/p2p/web/node_modules/react/LICENSE",
        }
    }
    assert normalise_script.relativise_node_paths(payload) == 2
    assert payload["react@19.2.6"]["path"] == "web/node_modules/react"
    # Idempotent: a second pass must be a no-op, or the committed file churns every run.
    assert normalise_script.relativise_node_paths(payload) == 0


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


def test_the_workflow_only_commits_on_main_or_the_schedule():
    """A pull request — including one from a fork — must not push to a branch."""
    workflow = WORKFLOW.read_text()
    commit_step = workflow.split("Commit the data to main", 1)[1]
    guard = commit_step.split("run:", 1)[0]
    assert "github.event_name == 'push'" in guard
    assert "github.event_name == 'schedule'" in guard


#: The model each phase declares in code, and where it is declared. `ARCHITECTURE.md` is
#: read by the audit routines *before* the source, so a model swapped here and not there
#: makes every later conclusion wrong. Extracted by regex rather than by import: these
#: modules pull in torch, and this suite runs on machines that have none.
DECLARED_MODELS = {
    "pythonsrc/visualizer.py": r'MODEL_ID\s*=\s*"([^"]+)"',
    "pythonsrc/sculptors/trellis2.py": r'DEFAULT_MODEL_ID\s*=\s*"([^"]+)"',
    "pythonsrc/ip_screen_image.py": r'DEFAULT_MODEL_ID\s*=\s*"([^"]+)"',
    "pythonsrc/sculptors/background.py": r'"P2P_BIREFNET_MODEL_ID",\s*"([^"]+)"',
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
