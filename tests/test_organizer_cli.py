"""The organizer's own command line: what a developer runs before `pipeline.py --spec`.

Called in-process through `main(argv)` rather than as a subprocess so the suite needs
no interpreter path and the exit codes are asserted directly.
"""
import json

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
    assert "card_divider" in err and "deck_box" in err and "token_tray" in err
    assert "box_insert" in err


def test_example_prints_a_valid_token_tray_spec_by_flag(capsys):
    """The acceptance criterion's own spelling: `example --archetype token_tray`."""
    assert main(["example", "--archetype", "token_tray"]) == 0
    spec = OrganizerSpec.from_json(capsys.readouterr().out)
    assert spec.archetype == "token_tray"
    assert spec.tray is not None and spec.lid is None and spec.divider is None
    assert len(spec.compartments) == 6


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


def test_compile_and_measure_run_a_tray_through_the_same_two_commands(tmp_path, capsys):
    """The third archetype through the same loop, with no archetype-specific flag — and
    with the feature count the *spec* decides rather than a fixed tuple: a 2 × 3 grid is
    30 features, five of them spec-independent and 25 of them the grid's own."""
    from pythonsrc.organizer.archetypes import example_spec
    spec_path = dump_spec(example_spec("token_tray"), tmp_path / "tray.json")
    out = tmp_path / "tray.stl"
    features = tmp_path / "features.json"
    assert main(["compile", str(spec_path), "--out", str(out), "--features", str(features)]) == 0
    assert json.loads(features.read_text())["parts"] == ["tray"]
    capsys.readouterr()
    report = tmp_path / "dimension_report.json"
    assert main(["measure", str(spec_path), str(out), "--report", str(report)]) == 0
    table = capsys.readouterr().out
    assert "30/30 features within ±0.05 mm" in table
    doc = json.loads(report.read_text())
    assert doc["within_tolerance"] is True and doc["features_checked"] == 30
    assert doc["missing"] == []
    # Every grid position, in all three dimensions, and every wall between and around.
    for row in range(2):
        for column in range(3):
            assert f"pocket_r{row}c{column}_width_mm" in doc["features"]
    assert {f"wall_x{i}_mm" for i in range(4)} <= set(doc["features"])
    assert {f"wall_y{j}_mm" for j in range(3)} <= set(doc["features"])


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


def test_example_prints_a_valid_box_insert_spec_by_flag(capsys):
    """The fourth archetype through the same command, with no flag of its own."""
    assert main(["example", "--archetype", "box_insert"]) == 0
    spec = OrganizerSpec.from_json(capsys.readouterr().out)
    assert spec.archetype == "box_insert"
    assert spec.insert is not None and spec.insert.rows == (1, 2)
    assert spec.lid is None and spec.divider is None and spec.tray is None
    assert len(spec.compartments) == 3


def test_compile_and_measure_run_an_insert_through_the_same_two_commands(tmp_path, capsys):
    """The developer loop over a ragged layout, which is the case that needed the
    registry's `MEASURE_NEEDS_SPEC` hook: `measure` is handed a spec and a mesh, the
    dispatch is the only thing that knows the measurer wants both, and this file took no
    archetype-specific change to gain the fourth shape.
    """
    from pythonsrc.organizer.archetypes import example_spec
    spec_path = dump_spec(example_spec("box_insert"), tmp_path / "insert.json")
    out = tmp_path / "insert.stl"
    features = tmp_path / "features.json"
    assert main(["compile", str(spec_path), "--out", str(out), "--features", str(features)]) == 0
    assert json.loads(features.read_text())["parts"] == ["insert"]

    report = tmp_path / "dimension_report.json"
    capsys.readouterr()
    assert main(["measure", str(spec_path), str(out), "--report", str(report)]) == 0
    table = capsys.readouterr().out
    assert "c0_width_mm" in table and "OK" in table
    doc = json.loads(report.read_text())
    assert doc["within_tolerance"] is True and doc["missing"] == []
    # Every compartment, in all three dimensions *and in both positions*, plus one wall
    # per row and one per row boundary — the list that grows with the compartments.
    for i in range(3):
        for axis in ("width", "depth", "height", "x", "y"):
            assert f"c{i}_{axis}_mm" in doc["features"]
    assert {f"row{r}_wall_mm" for r in range(2)} <= set(doc["features"])
    assert {f"wall_y{j}_mm" for j in range(3)} <= set(doc["features"])
