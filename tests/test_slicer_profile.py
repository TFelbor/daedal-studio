"""Guards on the printer profile actually reaching CuraEngine.

`pythonsrc/profiles/*.json` carry `layer_height`, `machine_width`,
`material_print_temperature` and a dozen more settings, named exactly as
CuraEngine names them — and none of it used to be passed to CuraEngine. The
slicer accepted a profile only if the filename ended in `.def.json`, and
everything else fell through to the bundled Ender 3 definition without a word.
Selecting the Anycubic Mega profile therefore sliced for an Ender 3: 210/60 degC
instead of 200/55, on a 220x220 bed instead of 210x210. Verified against
CuraEngine 4.13 in the pipeline image: the same box now yields `M104 S200` /
`M140 S55` under the Anycubic profile and `M104 S210` / `M140 S60` under the
Ender 3 one, where before the two G-code files were byte-identical.

The ordering assertions matter just as much. CuraEngine applies `-s` to whatever
object is current, and `-l` makes the loaded mesh current, so a setting placed
after it silently applies to nothing that slicing reads. Measured:
`-s adhesion_type=none` after `-l` left all 906 adhesion moves in place; before
`-l` it removed every one.

No CuraEngine binary is needed here — `subprocess.run` is stubbed, so what is
asserted is the command line the engine would receive.
"""

import json
import subprocess
from pathlib import Path

import pytest

from pythonsrc.slicer import CuraSlicer, SlicerError, format_setting_value

PROFILES = Path(__file__).resolve().parents[1] / "pythonsrc" / "profiles"


@pytest.fixture
def stub_engine(monkeypatch, tmp_path):
    """Capture the command line instead of slicing, and fake a G-code file."""
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(CuraSlicer, "_check_cura_available", lambda self: None)

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        Path(cmd[cmd.index("-o") + 1]).write_text(";FLAVOR:Marlin\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return captured


@pytest.fixture
def mesh(tmp_path):
    path = tmp_path / "part.stl"
    path.write_bytes(b"solid part\nendsolid part\n")
    return path


def _slice(profile, stub_engine, mesh, tmp_path, extra_args=None):
    slicer = CuraSlicer(cura_engine="CuraEngine", profile=profile)
    slicer.slice(mesh, tmp_path / "out.gcode", extra_args=extra_args)
    return slicer, stub_engine["cmd"]


def _settings(cmd: list[str]) -> list[tuple[str, str]]:
    """Every `-s key=value` in the command, in order."""
    return [
        tuple(cmd[i + 1].split("=", 1))
        for i, arg in enumerate(cmd)
        if arg == "-s"
    ]


# ── Translation ───────────────────────────────────────────────────────────────


def test_a_printer_profile_becomes_setting_overrides(stub_engine, mesh, tmp_path):
    _, cmd = _slice(PROFILES / "ender3.json", stub_engine, mesh, tmp_path)
    settings = dict(_settings(cmd))
    assert settings["layer_height"] == "0.2"
    assert settings["material_print_temperature"] == "210"
    assert settings["material_bed_temperature"] == "60"
    assert settings["machine_width"] == "220"
    assert settings["infill_sparse_density"] == "15"


def test_two_profiles_produce_different_settings(stub_engine, mesh, tmp_path):
    """The whole failure: both profiles used to slice identically."""
    _, ender = _slice(PROFILES / "ender3.json", stub_engine, mesh, tmp_path)
    _, anycubic = _slice(PROFILES / "anycubic_mega.json", stub_engine, mesh, tmp_path)
    assert dict(_settings(ender))["material_print_temperature"] == "210"
    assert dict(_settings(anycubic))["material_print_temperature"] == "200"
    assert dict(_settings(ender))["machine_width"] == "220"
    assert dict(_settings(anycubic))["machine_width"] == "210"


def test_connection_keys_are_not_sent_as_settings(stub_engine, mesh, tmp_path):
    """`firmware`, `base_url` and `api_key` say how to reach the printer."""
    _, cmd = _slice(PROFILES / "ender3.json", stub_engine, mesh, tmp_path)
    keys = {key for key, _ in _settings(cmd)}
    assert keys.isdisjoint({"firmware", "base_url", "api_key"})


def test_an_unknown_key_is_dropped_with_a_warning(stub_engine, mesh, tmp_path, caplog):
    """CuraEngine accepts `-s anything=1` in silence, so a typo would never surface.

    `machine_buildvolume_width` is not hypothetical: the bundled Ender 3 definition
    set the bed size under that name, and the engine went on using its 100x100
    default.
    """
    profile = tmp_path / "typo.json"
    profile.write_text(json.dumps({"machine_buildvolume_width": 220, "layer_height": 0.3}))
    with caplog.at_level("WARNING"):
        _, cmd = _slice(profile, stub_engine, mesh, tmp_path)
    keys = dict(_settings(cmd))
    assert "machine_buildvolume_width" not in keys
    assert keys["layer_height"] == "0.3"
    assert "machine_buildvolume_width" in caplog.text


def test_a_def_json_is_still_passed_as_a_definition(stub_engine, mesh, tmp_path):
    """A real CuraEngine definition belongs on `-j`, not translated into `-s`."""
    definition = PROFILES / "definitions" / "ender3_base.def.json"
    slicer, cmd = _slice(definition, stub_engine, mesh, tmp_path)
    assert slicer.profile_settings == {}
    assert str(definition) in cmd
    assert cmd[cmd.index(str(definition)) - 1] == "-j"


def test_a_null_value_is_omitted_rather_than_sent(stub_engine, mesh, tmp_path):
    """`api_key: null` is the common case, but any key may be nulled out."""
    profile = tmp_path / "nulled.json"
    profile.write_text(json.dumps({"layer_height": None, "wall_line_count": 3}))
    _, cmd = _slice(profile, stub_engine, mesh, tmp_path)
    assert dict(_settings(cmd)) == {"wall_line_count": "3"}


def test_a_profile_that_is_not_json_fails_loudly(stub_engine, mesh, tmp_path):
    profile = tmp_path / "broken.json"
    profile.write_text("{ not json")
    with pytest.raises(SlicerError):
        CuraSlicer(cura_engine="CuraEngine", profile=profile)


def test_booleans_are_rendered_the_way_curaengine_parses_them():
    """`str(True)` is "True", which CuraEngine reads as neither true nor false —
    `retraction_enable` would arrive disabled."""
    assert format_setting_value(True) == "true"
    assert format_setting_value(False) == "false"
    assert format_setting_value(None) is None
    assert format_setting_value(0.2) == "0.2"
    assert format_setting_value("grid") == "grid"


def test_profile_booleans_survive_translation(stub_engine, mesh, tmp_path):
    _, cmd = _slice(PROFILES / "ender3.json", stub_engine, mesh, tmp_path)
    settings = dict(_settings(cmd))
    assert settings["retraction_enable"] == "true"
    assert settings["support_enable"] == "false"


# ── Ordering ──────────────────────────────────────────────────────────────────


def test_every_setting_precedes_the_model(stub_engine, mesh, tmp_path):
    """A `-s` after `-l` applies to the mesh, where slicing does not read it."""
    _, cmd = _slice(
        PROFILES / "ender3.json", stub_engine, mesh, tmp_path,
        extra_args=["-s", "adhesion_type=brim"],
    )
    last_setting = max(i for i, arg in enumerate(cmd) if arg == "-s")
    assert last_setting < cmd.index("-l")


def test_extra_args_override_the_profile(stub_engine, mesh, tmp_path):
    """Later `-s` wins, so the adhesion decision must follow the profile's own.

    `ender3.json` asks for a skirt; the printability gate asks for a brim when the
    footprint is too small, and that has to be the one that takes effect.
    """
    _, cmd = _slice(
        PROFILES / "ender3.json", stub_engine, mesh, tmp_path,
        extra_args=["-s", "adhesion_type=brim", "-s", "brim_line_count=20"],
    )
    adhesion = [i for i, (key, _) in enumerate(_settings(cmd)) if key == "adhesion_type"]
    assert len(adhesion) == 2
    assert _settings(cmd)[adhesion[0]][1] == "skirt"
    assert _settings(cmd)[adhesion[-1]][1] == "brim"


# ── The bundled definition ────────────────────────────────────────────────────


def test_the_bundled_definition_names_the_build_volume_correctly():
    """`machine_buildvolume_width` is not a CuraEngine setting, and the engine does
    not say so — it just kept slicing for a 100x100 mm bed."""
    definition = json.loads(
        (PROFILES / "definitions" / "ender3_base.def.json").read_text()
    )
    overrides = definition["overrides"]
    assert overrides["machine_width"]["default_value"] == 220
    assert overrides["machine_depth"]["default_value"] == 220
    assert overrides["machine_height"]["default_value"] == 250
    assert not any(key.startswith("machine_buildvolume") for key in overrides)
