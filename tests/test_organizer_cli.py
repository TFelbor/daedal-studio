"""The organizer's own command line: what a developer runs before `pipeline.py --spec`.

Called in-process through `main(argv)` rather than as a subprocess so the suite needs
no interpreter path and the exit codes are asserted directly.
"""
import json

import pytest

from pythonsrc.organizer.__main__ import main
from pythonsrc.organizer.archetypes import deck_box
from pythonsrc.organizer.spec import OrganizerSpec, dump_spec


def test_example_prints_a_valid_spec(capsys):
    assert main(["example", "deck_box"]) == 0
    spec = OrganizerSpec.from_json(capsys.readouterr().out)
    assert spec.archetype == "deck_box"


def test_example_refuses_an_unknown_archetype(capsys):
    assert main(["example", "dragon"]) == 2
    assert "dragon" in capsys.readouterr().err


def test_example_prints_a_valid_divider_spec(capsys):
    assert main(["example", "card_divider"]) == 0
    spec = OrganizerSpec.from_json(capsys.readouterr().out)
    assert spec.archetype == "card_divider"
    assert spec.divider is not None and spec.lid is None


def test_example_takes_the_archetype_as_a_flag_too(capsys):
    """Two spellings of one argument: the acceptance criterion reaches for the flag and
    the existing tests for the positional, and a developer loop is not worth a rename."""
    assert main(["example", "--archetype", "card_divider"]) == 0
    assert OrganizerSpec.from_json(capsys.readouterr().out).archetype == "card_divider"


def test_example_with_no_archetype_says_which_ones_there_are(capsys):
    assert main(["example"]) == 2
    err = capsys.readouterr().err
    assert "card_divider" in err and "deck_box" in err


def test_compile_writes_the_mesh_the_features_and_the_canonical_spec(tmp_path, capsys):
    main(["example", "deck_box"])
    spec_path = tmp_path / "deck.json"
    spec_path.write_text(capsys.readouterr().out)
    out = tmp_path / "deck.stl"
    features = tmp_path / "features.json"
    spec_out = tmp_path / "spec.canonical.json"
    assert main(["compile", str(spec_path), "--out", str(out), "--features", str(features), "--spec-out", str(spec_out)]) == 0
    assert out.stat().st_size > 84
    doc = json.loads(features.read_text())
    assert doc["archetype"] == "deck_box" and doc["parts"] == ["body", "lid"]
    assert OrganizerSpec.from_json(spec_out.read_text()).archetype == "deck_box"


def test_compile_refuses_a_bad_spec_with_exit_2_and_the_problems(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"archetype": "deck_box", "compartments": [], "schema_version": 1}')
    assert main(["compile", str(bad), "--out", str(tmp_path / "x.stl")]) == 2
    assert "compartments" in capsys.readouterr().err


def test_measure_passes_a_compiled_mesh_and_prints_a_table(tmp_path, capsys):
    from pythonsrc.organizer.archetypes import example_spec
    spec_path = dump_spec(example_spec("deck_box"), tmp_path / "deck.json")
    out = tmp_path / "deck.stl"
    assert main(["compile", str(spec_path), "--out", str(out)]) == 0
    capsys.readouterr()
    assert main(["measure", str(spec_path), str(out)]) == 0
    table = capsys.readouterr().out
    assert "cavity_width_mm" in table and "OK" in table


def test_measure_fails_a_mesh_that_is_not_the_spec(tmp_path, capsys):
    import trimesh
    from pythonsrc.organizer.archetypes import example_spec
    spec_path = dump_spec(example_spec("deck_box"), tmp_path / "deck.json")
    wrong = tmp_path / "cube.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(str(wrong))
    assert main(["measure", str(spec_path), str(wrong)]) == 1


def test_compile_and_measure_run_a_divider_through_the_same_two_commands(tmp_path, capsys):
    """The acceptance criterion, as the developer loop runs it: no archetype-specific
    flag, and `measure` reports every one of the divider's seven features in tolerance."""
    from pythonsrc.organizer.archetypes import example_spec
    spec_path = dump_spec(example_spec("card_divider"), tmp_path / "divider.json")
    out = tmp_path / "divider.stl"
    features = tmp_path / "features.json"
    assert main(["compile", str(spec_path), "--out", str(out), "--features", str(features)]) == 0
    assert json.loads(features.read_text())["parts"] == ["divider"]
    capsys.readouterr()
    report = tmp_path / "dimension_report.json"
    assert main(["measure", str(spec_path), str(out), "--report", str(report)]) == 0
    table = capsys.readouterr().out
    assert "7/7 features within ±0.05 mm" in table
    doc = json.loads(report.read_text())
    assert doc["within_tolerance"] is True and doc["features_checked"] == 7
    assert set(doc["features"]) == {
        "plate_width_mm", "plate_height_mm", "thickness_mm",
        "tab_width_mm", "tab_height_mm", "tab_offset_mm", "total_height_mm",
    }


def test_measure_can_write_the_dimension_report_beside_the_table(tmp_path, capsys):
    from pythonsrc.organizer.archetypes import example_spec
    spec_path = dump_spec(example_spec("deck_box"), tmp_path / "deck.json")
    out = tmp_path / "deck.stl"
    assert main(["compile", str(spec_path), "--out", str(out)]) == 0
    report = tmp_path / "dimension_report.json"
    assert main(["measure", str(spec_path), str(out), "--report", str(report)]) == 0
    doc = json.loads(report.read_text())
    assert doc["within_tolerance"] is True
    assert doc["features_checked"] == len(deck_box.MEASURED_FEATURES) == 26
    assert "cavity_width_mm" in doc["features"]
