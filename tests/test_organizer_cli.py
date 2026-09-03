"""The organizer's own command line: what a developer runs before `pipeline.py --spec`.

Called in-process through `main(argv)` rather than as a subprocess so the suite needs
no interpreter path and the exit codes are asserted directly.
"""
import json

import pytest

from pythonsrc.organizer.__main__ import main
from pythonsrc.organizer.spec import OrganizerSpec, dump_spec


def test_example_prints_a_valid_spec(capsys):
    assert main(["example", "deck_box"]) == 0
    spec = OrganizerSpec.from_json(capsys.readouterr().out)
    assert spec.archetype == "deck_box"


def test_example_refuses_an_unknown_archetype(capsys):
    assert main(["example", "dragon"]) == 2
    assert "dragon" in capsys.readouterr().err


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


def test_measure_can_write_the_dimension_report_beside_the_table(tmp_path, capsys):
    from pythonsrc.organizer.archetypes import example_spec
    spec_path = dump_spec(example_spec("deck_box"), tmp_path / "deck.json")
    out = tmp_path / "deck.stl"
    assert main(["compile", str(spec_path), "--out", str(out)]) == 0
    report = tmp_path / "dimension_report.json"
    assert main(["measure", str(spec_path), str(out), "--report", str(report)]) == 0
    doc = json.loads(report.read_text())
    assert doc["within_tolerance"] is True
    assert doc["features_checked"] == 19
    assert "cavity_width_mm" in doc["features"]
