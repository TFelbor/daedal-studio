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

Global scope is not the only scope a `-s` can miss, and the second one cost more
than the first. The settings declared in `fdmextruder.def.json` are resolved from
the per-extruder container, which only `-e0 -s` writes; `material_diameter` is
one of them, both bundled definitions default it to 2,85 mm, and no profile named
it — so every Phase 4 slice computed the E axis for 2,85 mm filament while all
four bundled profiles describe 1,75 mm machines, and a printer executing that
G-code would deposit (1,75/2,85)² ≈ 38 % of the intended volume (#186). Measured
on CuraEngine 4.13 in the pipeline image, a 40 x 30 x 20 mm cube, largest E
value: 1567,82651 untouched, 1567,82651 with a global `-s material_diameter=1.75`
— unchanged, it never arrived — and 4158,25986 with `-e0 -s`.

No CuraEngine binary is needed here — `subprocess.run` is stubbed, so what is
asserted is the command line the engine would receive.
"""

import json
import logging
import subprocess
from pathlib import Path

import pytest

from pythonsrc.slicer import (
    CuraSlicer,
    SlicerError,
    extruder_scoped_settings,
    format_setting_value,
)

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


def _settings_in_scope(cmd: list[str]) -> dict[str, list[tuple[str, str]]]:
    """Every `-s key=value` again, split by the scope CuraEngine files it under.

    `_settings` is scope-blind and stays that way: every assertion written before
    `material_diameter` reads it, and they are about which settings are sent at all, not
    about where they land. This is a second reading of the same argv rather than a change
    to the first.

    The split is `-e0`, which selects the extruder container and is *sticky* — from there
    to the end of the command line a `-s` writes that container and stops writing the
    global one. Matched as `-e<n>` rather than the literal `-e0`, so a second extruder
    would be read here rather than silently counted as global.

    Args:
        cmd: The argv `CuraSlicer.slice` handed to `subprocess.run`.

    Returns:
        `{"global": [...], "extruder": [...]}`, each a list of `(key, value)` in order.
    """
    by_scope: dict[str, list[tuple[str, str]]] = {"global": [], "extruder": []}
    scope = "global"
    for index, arg in enumerate(cmd):
        if arg.startswith("-e") and arg[2:].isdigit():
            scope = "extruder"
        elif arg == "-s" and index + 1 < len(cmd):
            key, _, value = cmd[index + 1].partition("=")
            by_scope[scope].append((key, value))
    return by_scope


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
    """`api_key: null` is the common case, but any key may be nulled out.

    Asserted against global scope, which is where a profile's translation lands. The
    trailing extruder block always states `material_diameter` whatever the profile says
    (#186), and that floor is not what this test is about — reading the whole argv here
    would make it fail for the one reason it does not care about.
    """
    profile = tmp_path / "nulled.json"
    profile.write_text(json.dumps({"layer_height": None, "wall_line_count": 3}))
    _, cmd = _slice(profile, stub_engine, mesh, tmp_path)
    assert dict(_settings_in_scope(cmd)["global"]) == {"wall_line_count": "3"}


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
    """A `-s` after `-l` applies to the mesh, where slicing does not read it.

    The trailing `-e0` block added for #186 is the newest thing standing between the
    settings and the model, and it is the thing most likely to be appended *past* `-l`
    by someone who reads the command as "arguments, then files". An extruder-scoped `-s`
    placed after `-l` did still take effect on CuraEngine 4.13, unlike a bare one — but
    that is an accident of one engine version, not a rule this repository relies on, so
    the block is held to the same position as everything else.
    """
    _, cmd = _slice(
        PROFILES / "ender3.json", stub_engine, mesh, tmp_path,
        extra_args=["-s", "adhesion_type=brim"],
    )
    last_setting = max(i for i, arg in enumerate(cmd) if arg == "-s")
    assert last_setting < cmd.index("-l")
    assert cmd.index("-e0") < cmd.index("-o") < cmd.index("-l")


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


# ── Extruder scope ────────────────────────────────────────────────────────────


def test_the_filament_diameter_reaches_the_extruder_container(stub_engine, mesh, tmp_path):
    """Under-extrusion to 38 % of the intended volume, and nothing said so (#186).

    `material_diameter` is declared in `fdmextruder.def.json`, so it is resolved from the
    per-extruder container and a global `-s` writes a copy nothing reads. The engine
    accepts that argument in silence — the same failure mode as an unknown setting name,
    one level deeper, and invisible to the OctoPrint simulator the runbook uses. It
    surfaces the first time real hardware executes our G-code.

    The value has to arrive *after* an `-e0`, so this asserts the scope and not merely
    the presence: `_settings` would have been green throughout the bug.
    """
    slicer, cmd = _slice(PROFILES / "ender3.json", stub_engine, mesh, tmp_path)
    scoped = _settings_in_scope(cmd)

    assert "-e0" in cmd, "no extruder block — material_diameter cannot reach the container"
    assert dict(scoped["extruder"])["material_diameter"] == "1.75"
    assert slicer.profile_settings["material_diameter"] == "1.75"


def test_every_global_setting_precedes_the_extruder_block(stub_engine, mesh, tmp_path):
    """`-e0` is sticky: everything left behind it stops being a global setting.

    This is the ordering invariant the whole fix turns on, and the failure it guards is
    tidiness — a future reader grouping `-e0` with the other machine arguments near the
    front, where it reads as harmless. It is not. Measured on CuraEngine 4.13, same cube,
    same definitions: `-e0 -s material_diameter=1.75 -s layer_height=0.4` produced 100
    layers, the 0,2 mm default, the override lost, where a global `-s layer_height=0.4`
    produces 50; and `-e0 -s material_diameter=1.75 -s adhesion_type=none` left the skirt
    in place, where moving the `-e0` after `adhesion_type` removed it. An `-e0` emitted
    early silently disables the profile translation standing beside it — a larger bug
    than the under-extrusion it was added to fix.

    Asserted as an exact list rather than an ordering predicate: that pins both that
    nothing was moved into the extruder block at global scope's expense, and that
    `extra_args` still land globally, in profile-then-caller order.
    """
    slicer, cmd = _slice(
        PROFILES / "ender3.json", stub_engine, mesh, tmp_path,
        extra_args=["-s", "adhesion_type=brim"],
    )

    assert cmd.count("-e0") == 1, "a second -e0 would strand the settings behind the first"
    assert _settings_in_scope(cmd)["global"] == [
        *slicer.profile_settings.items(),
        ("adhesion_type", "brim"),
    ]


def test_an_extruder_scoped_extra_arg_is_promoted_into_the_block(stub_engine, mesh, tmp_path):
    """A caller's `-s` is emitted before our `-e0`, so on an extruder-scoped key it lands
    in the scope that does not decide anything — and suppressing the profile's copy in
    deference to it would make both sides lose.

    So the block is seeded from the profile and then overwritten by any key the caller
    named: the caller wins where winning is possible. Verified against the real engine,
    same cube, `ender3.json` through this wrapper: largest E 4157,75759 normally,
    1414,79251 with `-s material_diameter=3.0`, which is 4157,75759 x (1,75/3,0)².

    The caller's global copy stays where they put it. It is inert for this key, but
    removing it would mean rewriting an argument list the caller handed us.
    """
    _, cmd = _slice(
        PROFILES / "ender3.json", stub_engine, mesh, tmp_path,
        extra_args=["-s", "material_diameter=3.0"],
    )
    scoped = _settings_in_scope(cmd)

    assert dict(scoped["extruder"])["material_diameter"] == "3.0"
    assert [v for k, v in scoped["global"] if k == "material_diameter"] == ["1.75", "3.0"]


def test_a_globally_scoped_extra_arg_stays_out_of_the_extruder_block(stub_engine, mesh, tmp_path):
    """Promotion is restricted to the keys `fdmextruder.def.json` declares, and that
    restriction is load-bearing in the other direction.

    `adhesion_type` is a global setting. Carrying it into the extruder container as well
    would put the printability gate's brim decision in a place the adhesion code does not
    read from — this bug inverted, and it would be just as quiet.
    """
    _, cmd = _slice(
        PROFILES / "ender3.json", stub_engine, mesh, tmp_path,
        extra_args=["-s", "adhesion_type=brim"],
    )
    scoped = _settings_in_scope(cmd)

    assert "adhesion_type" not in dict(scoped["extruder"])
    assert [v for k, v in scoped["global"] if k == "adhesion_type"] == ["skirt", "brim"]


@pytest.mark.parametrize(
    "profile",
    [
        pytest.param(None, id="no profile at all"),
        pytest.param(
            PROFILES / "definitions" / "ender3_base.def.json", id="a .def.json profile"
        ),
        pytest.param("a profile naming nothing scoped", id="a profile with no scoped key"),
    ],
)
def test_the_diameter_is_stated_even_when_no_profile_states_it(
    profile, stub_engine, mesh, tmp_path
):
    """The block has a floor, and without one this fix would have missed its own bug.

    `_profile_settings` returns `{}` for `profile=None` and for a `.def.json` — the first
    is what `--profile` defaults to, and `DEFAULT_PROFILE` is a `required: False` config
    key with no default, so a fresh install with nothing configured takes that path.
    Seeding the extruder block only from the profile therefore left the 38 % under-
    extrusion live exactly where it is likeliest: the run with nothing configured. A
    definition cannot cover for it either — `material_diameter` in a machine's
    `overrides` was measured not to reach the container.

    Confirmed against the real engine on both paths: 1567,82651 before the floor existed,
    4158,25986 after.
    """
    if isinstance(profile, str):
        path = tmp_path / "no_scope.json"
        path.write_text(json.dumps({"layer_height": 0.3}))
        profile = path

    _, cmd = _slice(profile, stub_engine, mesh, tmp_path)
    assert dict(_settings_in_scope(cmd)["extruder"])["material_diameter"] == "1.75"


def test_the_stated_default_is_the_one_telemetry_books_the_row_at():
    """One constant, not two. `pipeline._filament_diameter` converts the E axis into
    `filament_used_g` at `gcode_stats.DEFAULT_FILAMENT_DIAMETER_MM` when a profile is
    silent; the slicer now states that same constant to the engine. The failure being
    guarded is not a wrong number, it is two numbers — the diameter the G-code was built
    for and the diameter the telemetry row was converted at — drifting apart in silence,
    which is what #186 was.
    """
    from pythonsrc.gcode_stats import DEFAULT_FILAMENT_DIAMETER_MM
    from pythonsrc.slicer import DEFAULT_FILAMENT_DIAMETER_MM as slicer_default

    assert slicer_default is DEFAULT_FILAMENT_DIAMETER_MM
    assert DEFAULT_FILAMENT_DIAMETER_MM == 1.75


def test_a_caller_who_brings_their_own_extruder_flag_is_not_rescued(
    stub_engine, mesh, tmp_path
):
    """Pinning a latent hazard rather than claiming it is handled.

    `extra_args` are emitted verbatim and before our `-e0`, so a caller who passes their
    own `-e0` scopes everything they place after it — `layer_height` here — to the
    extruder container, where slicing does not read it. That is the sticky-`-e0` failure
    this whole change is built around, arriving from the one direction the slicer does
    not control. No caller does it today: `pipeline._adhesion_args` emits only
    `adhesion_type` and `brim_line_count`, both global.

    Our own block still lands after theirs and still states the diameter, so the fix
    survives a caller doing this. What does not survive is their own global setting, and
    this test exists so that a future caller introducing that cannot do it against a
    green suite.
    """
    _, cmd = _slice(
        PROFILES / "ender3.json", stub_engine, mesh, tmp_path,
        extra_args=["-e0", "-s", "layer_height=0.4"],
    )
    scoped = _settings_in_scope(cmd)

    assert dict(scoped["extruder"])["material_diameter"] == "1.75"
    assert ("layer_height", "0.4") in scoped["extruder"], (
        "the caller's own -e0 scoped their layer_height to the extruder; if this ever "
        "reads global, the promotion logic changed and the docstring above is stale"
    )
    assert dict(scoped["global"])["layer_height"] == "0.2", (
        "the profile's global layer_height must still be the one slicing reads"
    )


def test_every_extruder_scoped_profile_key_reaches_extruder_scope(stub_engine, mesh, tmp_path):
    """The guard that makes this fix about the class of bug rather than one setting.

    `material_diameter` was the one that cost something; it was not the only key exposed.
    `fdmextruder.def.json` declares eighteen settings under three category nodes, and two
    of them appear in every bundled profile. The second is `machine_nozzle_size`, which is *not* an observable bug
    — changing it between 0,4 and 0,8 mm produced byte-identical extrusion in both scopes
    on CuraEngine 4.13 — but it is the same hazard, resolved from the same container, and
    a future engine version or a future profile key has no reason to stay benign.

    So the assertion is over the whole cross-product of bundled profiles and
    extruder-scoped names, not over a list of keys someone has to remember to extend.
    """
    profiles = sorted(PROFILES.glob("*.json"))
    assert profiles, "no bundled profiles — this test would pass vacuously"

    scoped_names = extruder_scoped_settings(CuraSlicer.DEFINITIONS_DIR)
    assert "material_diameter" in scoped_names, (
        "the scoped set is derived from fdmextruder.def.json and came back without the "
        "key this fix is about — the cross-product below would be vacuous"
    )

    unreached: list[str] = []
    for profile in profiles:
        slicer, cmd = _slice(profile, stub_engine, mesh, tmp_path)
        emitted = dict(_settings_in_scope(cmd)["extruder"])
        unreached += [
            f"{profile.name}:{key}={value} (extruder scope got {emitted.get(key)!r})"
            for key, value in slicer.profile_settings.items()
            if key in scoped_names and emitted.get(key) != value
        ]

    assert unreached == [], (
        "profile settings CuraEngine resolves from the extruder train that never reach "
        "it: " + "; ".join(unreached)
    )


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


# ── Every bundled profile translates cleanly ─────────────────────────────────


def test_no_bundled_profile_has_a_key_the_slicer_ignores(caplog):
    """A profile key that is neither a CuraEngine setting nor a documented exception is
    silently dropped — the value is in the file, a reader assumes it reached the engine,
    and it never did. `_profile_settings` warns, so this asserts nobody has to notice
    the warning.

    Added with `bambu_p1s.json` (#73), which carries `_comment` and `_sources` because
    the issue asks for the source of its temperatures to be recorded in the file. Those
    two are in `DOCUMENTATION_KEYS`; anything else new has to justify itself here.
    """
    profiles = sorted(PROFILES.glob("*.json"))
    assert profiles, "no bundled profiles — this test would pass vacuously"

    ignored: list[str] = []
    for profile in profiles:
        with caplog.at_level(logging.WARNING, logger="ds.slicer"):
            caplog.clear()
            CuraSlicer._profile_settings(profile)
            ignored += [
                f"{profile.name}: {record.message}"
                for record in caplog.records
                if "not a CuraEngine setting" in record.getMessage()
            ]

    assert ignored == [], "profile keys that never reach the engine: " + "; ".join(ignored)


def test_the_fit_keys_are_dropped_silently_and_never_reach_the_engine(caplog):
    """The fit offsets a profile suggests to the composer (issue #89) are this product's
    keys, not CuraEngine's, and they are dropped for `DOCUMENTATION_KEYS`' reason: four
    "not a CuraEngine setting" lines on every slice is exactly the noise that trains a
    reader to skip the line that would have told them about a mistyped setting name.

    The other half is the one that matters more. **Nothing downstream of Phase 2 reads
    them**, because decision (b) makes the mesh not a function of a printer: by the time
    a profile reaches the slicer, the millimetres it pre-filled are already in the spec
    the geometry was built from. A fit key arriving as a `-s` override would be this
    product trying to apply an offset to a part that already has it.
    """
    from pythonsrc.fit_offsets import CLASS_KEY, PROFILE_KEYS

    profile = PROFILES / "ender3.json"
    with caplog.at_level(logging.WARNING, logger="ds.slicer"):
        caplog.clear()
        settings = CuraSlicer._profile_settings(profile)

    for key in (*PROFILE_KEYS, CLASS_KEY):
        assert key in json.loads(profile.read_text()), f"{key} is not in the profile"
        assert key not in settings, f"{key} reached CuraEngine as a setting"
        assert key not in caplog.text, f"{key} warned rather than being dropped in silence"


def test_every_bundled_profile_declares_the_filament_diameter():
    """A profile that omits `material_diameter` inherits 2,85 mm and says nothing.

    Both `fdmprinter.def.json` and `fdmextruder.def.json` default it to 2,85 mm, and
    `ender3_base.def.json` — the definition `_resolve_definitions` pairs with every
    printer-profile JSON — does not override it. A machine-definition override would not
    help even if it were added: it was measured to leave the E axis unchanged, and
    `creality_base.def.json` already carries one at line 147 that is inert for that
    reason. The profile is therefore the only place the number can be stated.

    Every machine this project supports is a 1,75 mm machine, so the value is asserted
    and not merely the key: 2,85 mm in a bundled profile would be a machine nobody here
    has, and it would slice for it silently. `pythonsrc/pipeline.py` reads the same key to
    convert extruded length into `filament_used_g`, so an omission is wrong twice — in the
    G-code and in the telemetry row that describes it.
    """
    profiles = sorted(PROFILES.glob("*.json"))
    assert profiles, "no bundled profiles — this test would pass vacuously"

    wrong = []
    for profile in profiles:
        data = json.loads(profile.read_text())
        if data.get("material_diameter") != 1.75:
            wrong.append(f"{profile.name}: {data.get('material_diameter')!r}")

    assert wrong == [], (
        "bundled profiles that do not declare a 1,75 mm filament diameter, and so slice "
        "on fdmextruder.def.json's 2,85 mm default: " + "; ".join(wrong)
    )


def test_no_bundled_profile_carries_a_connection_secret():
    """#73's design rule: a person connects their own printer through the app, and a
    profile is committed to this repository. `bambu_test.json` shipped an `api_key` of
    "123456" — a placeholder, but a placeholder in the shape of a credential is how a
    real one eventually gets committed beside it.
    """
    offenders = []
    for profile in sorted(PROFILES.glob("*.json")):
        data = json.loads(profile.read_text())
        for key in ("api_key", "access_code", "serial", "password"):
            if data.get(key):
                offenders.append(f"{profile.name}:{key}")

    assert offenders == [], (
        "connection credentials belong in the encrypted config store, not in a "
        f"committed profile: {offenders}"
    )
