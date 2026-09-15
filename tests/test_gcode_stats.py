"""Tests for G-code statistics extraction.

These use synthetic fixtures rather than real slicer output so the suite never needs
CuraEngine installed. The one real-artifact behaviour worth pinning — that CuraEngine's
CLI writes ``;Filament used: 0m`` while actually extruding metres — is covered by
`test_header_zero_filament_does_not_override_e_axis`.
"""

import math

import pytest

from pythonsrc.gcode_stats import (
    DEFAULT_FILAMENT_DIAMETER_MM,
    MATERIAL_DENSITY_G_CM3,
    filament_volume_mm3,
    header_bbox_is_populated,
    parse_gcode_file,
    parse_gcode_lines,
)


def _lines(text: str) -> list[str]:
    """Split a fixture string into lines."""
    return text.strip("\n").split("\n")


ABSOLUTE_GCODE = """
;FLAVOR:Marlin
;TIME:1200
;Filament used: 0m
;Layer height: 0.2
M82
;LAYER:0
;TYPE:SKIRT
G1 X10 Y10 E1.0
G1 X20 Y10 E3.0
;TYPE:WALL-OUTER
G1 X30 Y10 E6.0
;LAYER:1
G1 X40 Y10 E10.0
"""


def test_absolute_extrusion_sums_deltas():
    """Under M82 the E word is a position, so the total is the final value."""
    stats = parse_gcode_lines(_lines(ABSOLUTE_GCODE))
    assert stats.filament_used_mm == pytest.approx(10.0)
    assert stats.filament_mm_by_type == {
        "SKIRT": pytest.approx(3.0),
        "WALL-OUTER": pytest.approx(7.0),
    }


def test_relative_extrusion_sums_values_directly():
    """Under M83 the E word is already a delta."""
    gcode = """
;FLAVOR:Marlin
M83
;TYPE:WALL-OUTER
G1 X10 Y10 E1.0
G1 X20 Y10 E1.0
G1 X30 Y10 E1.0
"""
    stats = parse_gcode_lines(_lines(gcode))
    assert stats.filament_used_mm == pytest.approx(3.0)


def test_absolute_and_relative_disagree_by_orders_of_magnitude():
    """The same file read in the wrong mode gives a wildly different answer.

    This is why the mode is tracked rather than assumed.
    """
    body = ["G1 X1 E10", "G1 X2 E20", "G1 X3 E30"]
    absolute = parse_gcode_lines(["M82", *body])
    relative = parse_gcode_lines(["M83", *body])
    assert absolute.filament_used_mm == pytest.approx(30.0)
    assert relative.filament_used_mm == pytest.approx(60.0)


def test_g92_reset_does_not_count_as_extrusion():
    """G92 moves the datum without pushing filament."""
    gcode = """
M82
;TYPE:FILL
G1 X10 E5.0
G92 E0
G1 X20 E5.0
"""
    stats = parse_gcode_lines(_lines(gcode))
    # 5mm before the reset, 5mm after — not 5mm then nothing, and not a -5 spike.
    assert stats.filament_used_mm == pytest.approx(10.0)


def test_g92_without_e_is_ignored():
    """A G92 that resets only position words leaves the extruder datum alone."""
    stats = parse_gcode_lines(_lines("""
M82
G1 X10 E5.0
G92 X0 Y0
G1 X20 E8.0
"""))
    assert stats.filament_used_mm == pytest.approx(8.0)


def test_retraction_is_not_counted_as_consumption():
    """Negative deltas pull filament back; they must not add to the total."""
    stats = parse_gcode_lines(_lines("""
M82
;TYPE:WALL-OUTER
G1 X10 E10.0
G1 E4.0
G1 X20 E12.0
"""))
    # 10 consumed, retract to 4 (ignored), then 4 -> 12 is 8 more.
    assert stats.filament_used_mm == pytest.approx(18.0)


def test_support_is_separated_from_the_total():
    """Support and support-interface roll up into the support figure."""
    stats = parse_gcode_lines(_lines("""
M83
;TYPE:WALL-OUTER
G1 X1 E4.0
;TYPE:SUPPORT
G1 X2 E3.0
;TYPE:SUPPORT-INTERFACE
G1 X3 E1.0
"""))
    assert stats.filament_used_mm == pytest.approx(8.0)
    assert stats.support_filament_mm == pytest.approx(4.0)
    # Stored values are rounded to 4 decimal places for a tidy JSON column.
    assert stats.support_filament_mm3 == pytest.approx(
        filament_volume_mm3(4.0, DEFAULT_FILAMENT_DIAMETER_MM), abs=1e-3
    )


def test_no_support_sections_gives_zero_support():
    """A model sliced without supports reports zero, not None."""
    stats = parse_gcode_lines(_lines("M83\n;TYPE:FILL\nG1 X1 E2.0"))
    assert stats.support_filament_mm3 == 0.0


def test_extrusion_before_any_type_comment_is_bucketed_not_dropped():
    """Priming lines precede the first ;TYPE:; they still consume filament."""
    stats = parse_gcode_lines(_lines("M83\nG1 X1 E2.0\n;TYPE:FILL\nG1 X2 E1.0"))
    assert stats.filament_used_mm == pytest.approx(3.0)
    assert stats.filament_mm_by_type["UNTYPED"] == pytest.approx(2.0)


def test_volume_follows_from_diameter():
    """Volume is length times filament cross-section."""
    stats = parse_gcode_lines(_lines("M83\nG1 X1 E100.0"), filament_diameter_mm=2.85)
    expected = 100.0 * math.pi * (2.85 / 2) ** 2
    assert stats.filament_used_mm3 == pytest.approx(expected, rel=1e-6)


def test_mass_uses_material_density():
    """Mass comes from volume and the material's density."""
    stats = parse_gcode_lines(_lines("M83\nG1 X1 E1000.0"), material_type="PLA")
    expected = stats.filament_used_mm3 / 1000.0 * MATERIAL_DENSITY_G_CM3["PLA"]
    # Mass is rounded to milligrams before storage.
    assert stats.filament_used_g == pytest.approx(expected, abs=1e-3)


def test_material_name_is_matched_case_insensitively():
    """"pla" and "PLA" are the same material."""
    lower = parse_gcode_lines(_lines("M83\nG1 X1 E100.0"), material_type="pla")
    upper = parse_gcode_lines(_lines("M83\nG1 X1 E100.0"), material_type="PLA")
    assert lower.filament_used_g == upper.filament_used_g


def test_unknown_material_gives_no_mass_rather_than_a_guess():
    """An unrecognised material must not silently borrow PLA's density."""
    stats = parse_gcode_lines(_lines("M83\nG1 X1 E100.0"), material_type="Moondust")
    assert stats.filament_used_mm3 > 0
    assert stats.filament_used_g is None


def test_missing_material_gives_no_mass():
    """No material named means no mass claimed."""
    stats = parse_gcode_lines(_lines("M83\nG1 X1 E100.0"))
    assert stats.filament_used_g is None


def test_header_is_parsed():
    """Header comments become key/value pairs."""
    stats = parse_gcode_lines(_lines(ABSOLUTE_GCODE))
    assert stats.flavor == "Marlin"
    assert stats.estimated_print_time_s == 1200
    assert stats.layer_height_mm == pytest.approx(0.2)
    assert stats.header["Filament used"] == "0m"


def test_header_zero_filament_does_not_override_e_axis():
    """CuraEngine's CLI writes 0m while extruding metres; the E axis wins.

    Regression guard for the whole reason this module exists.
    """
    stats = parse_gcode_lines(_lines(ABSOLUTE_GCODE))
    assert stats.filament_used_mm == pytest.approx(10.0)
    assert stats.header_filament_disagrees is True


def test_header_filament_used_when_no_extrusion_is_derivable():
    """A file with a real header but no parseable moves falls back to the header."""
    stats = parse_gcode_lines(_lines("""
;FLAVOR:Marlin
;Filament used: 2.5m
M104 S200
"""))
    assert stats.filament_used_mm == pytest.approx(2500.0)


def test_header_filament_agreeing_is_not_flagged():
    """A header that matches the E axis raises no disagreement flag."""
    stats = parse_gcode_lines(_lines("""
;Filament used: 0.01m
M83
G1 X1 E10.0
"""))
    assert stats.header_filament_disagrees is False


def test_multi_extruder_header_filament_is_summed():
    """A per-extruder header list totals across extruders."""
    stats = parse_gcode_lines(_lines(";Filament used: 1.5m, 0.5m\nM104 S200"))
    assert stats.filament_used_mm == pytest.approx(2000.0)


def test_layer_count_from_layer_comments():
    """;LAYER: indices are zero-based, so the count is the maximum plus one."""
    stats = parse_gcode_lines(_lines(ABSOLUTE_GCODE))
    assert stats.layer_count == 2


def test_layer_count_falls_back_to_distinct_z():
    """Without ;LAYER: comments, distinct extruding Z heights stand in."""
    stats = parse_gcode_lines(_lines("""
M83
G1 Z0.2
G1 X1 E1.0
G1 Z0.4
G1 X2 E1.0
G1 X3 E1.0
"""))
    assert stats.layer_count == 2


def test_inline_comments_are_stripped():
    """A trailing comment must not be read as part of the move."""
    stats = parse_gcode_lines(_lines("M83\nG1 X1 E2.0 ; prime the nozzle E99"))
    assert stats.filament_used_mm == pytest.approx(2.0)


def test_travel_moves_without_e_are_ignored():
    """G0 moves that carry no E change nothing."""
    stats = parse_gcode_lines(_lines("M83\nG0 X50 Y50\nG1 X1 E2.0\nG0 X0 Y0"))
    assert stats.filament_used_mm == pytest.approx(2.0)


def test_g0_with_extrusion_is_counted():
    """Some post-processors emit extruding G0 moves."""
    stats = parse_gcode_lines(_lines("M83\nG0 X1 E2.0"))
    assert stats.filament_used_mm == pytest.approx(2.0)


def test_absolute_is_the_default_mode():
    """Marlin powers up in absolute extrusion; a file with no M82 must assume it."""
    stats = parse_gcode_lines(_lines("G1 X1 E5.0\nG1 X2 E9.0"))
    assert stats.filament_used_mm == pytest.approx(9.0)


def test_empty_file_is_all_zeroes_not_an_error():
    """An empty G-code file yields an empty result rather than raising."""
    stats = parse_gcode_lines([])
    assert stats.filament_used_mm == 0.0
    assert stats.layer_count is None
    assert stats.estimated_print_time_s is None


def test_malformed_lines_are_skipped():
    """Junk between valid moves must not abort the pass."""
    stats = parse_gcode_lines(_lines("""
M83
not gcode at all
;TIME:notanumber
G1 X1 E2.0
G1 E
"""))
    assert stats.filament_used_mm == pytest.approx(2.0)
    assert stats.estimated_print_time_s is None


def test_scientific_notation_in_header_is_tolerated():
    """CuraEngine writes its sentinel bbox in scientific notation."""
    stats = parse_gcode_lines(_lines(";MINX:2.14748e+06\n;MAXX:-2.14748e+06\nM83"))
    assert stats.header["MINX"] == "2.14748e+06"


def test_type_comment_after_the_header_still_sets_the_section():
    """;TYPE: appears well past the header block and must still be honoured."""
    stats = parse_gcode_lines(_lines("M83\nG1 X1 E1.0\n;TYPE:FILL\nG1 X2 E1.0"))
    assert stats.filament_mm_by_type["FILL"] == pytest.approx(1.0)


def test_to_dict_is_json_serializable():
    """Stats are stored as a JSON column, so they must serialize cleanly."""
    import json

    stats = parse_gcode_lines(_lines(ABSOLUTE_GCODE), material_type="PLA")
    assert json.loads(json.dumps(stats.to_dict()))["filament_used_mm"] == pytest.approx(10.0)


def test_parse_gcode_file_reads_from_disk(tmp_path):
    """The file entry point matches the line-iterable entry point."""
    path = tmp_path / "job.gcode"
    path.write_text(ABSOLUTE_GCODE)
    assert parse_gcode_file(path).filament_used_mm == pytest.approx(10.0)


def test_parse_gcode_file_missing_file_raises(tmp_path):
    """A missing file is an error the caller must see."""
    with pytest.raises(FileNotFoundError):
        parse_gcode_file(tmp_path / "nope.gcode")


class TestHeaderBoundingBox:
    """The header bounding box is unreliable and callers need to know when."""

    def test_cura_cli_sentinel_is_rejected(self):
        """MIN above MAX is the uninitialised +INF/-INF pair."""
        assert not header_bbox_is_populated({
            "MINX": "2.14748e+06", "MINY": "2.14748e+06",
            "MAXX": "-2.14748e+06", "MAXY": "-2.14748e+06",
        })

    def test_real_bbox_is_accepted(self):
        """A plausible bounding box passes."""
        assert header_bbox_is_populated(
            {"MINX": "10", "MINY": "12", "MAXX": "80", "MAXY": "90"}
        )

    def test_absent_keys_are_rejected(self):
        """A header without a bounding box is not a populated one."""
        assert not header_bbox_is_populated({"FLAVOR": "Marlin"})

    def test_unparseable_values_are_rejected(self):
        """Garbage values do not count as a populated box."""
        assert not header_bbox_is_populated(
            {"MINX": "x", "MINY": "0", "MAXX": "1", "MAXY": "1"}
        )
