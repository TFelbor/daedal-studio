"""Three lists that must name the same archetypes, in three languages.

`spec.ARCHETYPES` is what the schema accepts, `archetypes.REGISTRY` is what can compile,
and `ARCHETYPES` in `web/src/organizer/spec.ts` is what the composer offers. The first
two already check each other at import — `archetypes/__init__.py` raises if the schema
names something with no compiler. The third had drifted all the way: the strip offered
`dice_tray`, `box_insert` and `dividers`, and none of the three existed, so a person
could pick a shape the engine would refuse and get something else without being told.
That is the same class of failure as a fits badge with no measurement behind it, and a
screenshot of it outlives any caveat.

There is no test runner in `web/`, so this is the only thing that keeps the strip
honest — the `tests/test_download_formats.py` precedent, which binds the formats the
endpoint serves to the ones the UI offers by reading the TSX. Read as text on purpose:
importing the module would need a bundler, and the point is the literal a reviewer sees.

Every module in the registry must also expose the whole archetype API. That is what
"adding an archetype is adding a module and a line" means, and it is the property the
second archetype existed to test: `pipeline.py --spec`, the CLI and Phase 3's assert
path took no archetype-specific change to gain the divider.

`callouts` joined it with issue #88, and its absence is invisible in a different way: the
preview still draws the mesh, so nothing fails — it just stops saying what size anything
is, which is the whole of what that preview is for. What each archetype's callouts have
to be true of is `tests/test_view_callouts.py`; this is where a module that has none is
refused.

`envelope` joined that API with issue #85, and it is the one verb whose absence nothing
downstream would notice: a module without it compiles, validates, measures, is offered
in the composer and reaches a printer, while no mesh it produces has ever been measured.
`tests/test_organizer_dimensional_accuracy.py` is where that failure is *named*; this is
where it is refused at the same moment as a missing `measure`.
"""
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pythonsrc.organizer.archetypes import (
    REGISTRY,
    compile_spec,
    envelope_for,
    example_spec,
    measure_spec_mesh,
    required_measurements,
)
from pythonsrc.organizer.spec import (
    ARCHETYPE_WALL_MM,
    ARCHETYPES,
    SpecError,
    wall_floor_mm,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_SPEC = REPO_ROOT / "web" / "src" / "organizer" / "spec.ts"

#: Every name an archetype module must expose. The registry dispatches through all of
#: them; a module missing one fails at the call site, phases into a run.
ARCHETYPE_API = (
    "ARCHETYPE", "ARCHETYPE_VERSION", "MEASURED_FEATURES", "USES_PROCESS_WALL_MM",
    "derive", "validate", "build", "compile", "example", "envelope",
    "measure", "fits_check", "to_view", "callouts",
)


def web_archetype_ids() -> list[str]:
    """The `id`s in `ARCHETYPES` in `web/src/organizer/spec.ts`, in order."""
    text = WEB_SPEC.read_text(encoding="utf-8")
    block = re.search(r"export const ARCHETYPES = \[(.*?)\] as const;", text, re.S)
    assert block, f"could not find the ARCHETYPES literal in {WEB_SPEC}"
    return re.findall(r"id:\s*'([^']+)'", block.group(1))


def test_the_schema_and_the_registry_name_the_same_archetypes():
    assert set(ARCHETYPES) == set(REGISTRY)


def test_the_ui_offers_exactly_the_archetypes_the_engine_can_compile():
    assert web_archetype_ids() == list(ARCHETYPES)


def test_the_ui_labels_every_archetype_it_offers():
    text = WEB_SPEC.read_text(encoding="utf-8")
    block = re.search(r"export const ARCHETYPES = \[(.*?)\] as const;", text, re.S)
    pairs = re.findall(r"\{\s*id:\s*'([^']+)',\s*label:\s*'([^']+)'\s*\}", block.group(1))
    assert [p[0] for p in pairs] == web_archetype_ids()
    assert all(label.strip() for _, label in pairs)


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_archetype_exposes_the_whole_api(name):
    module = REGISTRY[name]
    missing = [verb for verb in ARCHETYPE_API if not hasattr(module, verb)]
    assert not missing, f"{name} is missing {missing}"
    assert module.ARCHETYPE == name
    assert isinstance(module.ARCHETYPE_VERSION, str) and module.ARCHETYPE_VERSION


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_archetypes_example_names_itself_and_declares_its_measurements(name):
    spec = example_spec(name)
    assert spec.archetype == name
    features = set(REGISTRY[name].MEASURED_FEATURES)
    assert features, f"{name} promises to measure nothing"
    assert features <= set(REGISTRY[name].compile(spec).features)


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_the_registry_asks_every_archetype_what_this_spec_promises(name):
    """`required_measurements` is what the pipeline, the CLI and `verify_spec_mesh` all
    route through, so it — not `MEASURED_FEATURES` — is what a report's *within
    tolerance* actually means. A module may declare `measured_features(spec)` when its
    feature list is a function of the grid (the token tray does); the fallback is the
    fixed tuple, and either way every name it promises has to be one the compiler
    designed and one the measurer reads back.
    """
    spec = example_spec(name)
    module = REGISTRY[name]
    promised = set(required_measurements(spec))
    assert set(module.MEASURED_FEATURES) <= promised, (
        f"{name} promises less through the registry than its own tuple declares"
    )
    result = module.compile(spec)
    assert promised <= set(result.features), f"{name} promises features it never designs"
    # Through `measure_spec_mesh` rather than `module.measure`, because the signature is
    # the module's choice: a ragged layout cannot be read off a mesh alone, so the box
    # insert declares `MEASURE_NEEDS_SPEC` and takes the spec as well. The dispatch is the
    # only place that knows, which is the whole point of routing through it.
    assert promised <= set(measure_spec_mesh(spec, result.mesh)), (
        f"{name} promises features its own measure() does not read back"
    )


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_the_registry_hands_the_spec_only_to_a_measurer_that_asked_for_it(name):
    """`MEASURE_NEEDS_SPEC` is the second optional hook on this API, after
    `measured_features(spec)`, and it exists for the same archetype and the same reason:
    a ragged layout's features are not a function of the mesh alone, so the design has to
    say *where* each one is measured.

    The claim tested here is that the hook is additive — a module that does not declare it
    is called with the mesh and nothing else, and one that does is called with both. A
    dispatch that guessed from the signature would couple the API to an argument count.
    """
    module = REGISTRY[name]
    needs = getattr(module, "MEASURE_NEEDS_SPEC", False)
    assert isinstance(needs, bool)
    spec = example_spec(name)
    mesh = module.compile(spec).mesh
    if needs:
        with pytest.raises(TypeError):
            module.measure(mesh)
    else:
        assert module.measure(mesh) == measure_spec_mesh(spec, mesh)


def test_every_archetype_names_the_wall_it_builds_with_when_a_spec_does_not():
    """`spec.ARCHETYPE_WALL_MM` is the third list that has to name the same archetypes.
    Issue #72 retired one unsourced 2,8 mm for all of them, so a new archetype now has
    to choose — and an archetype with no entry would leave `process.wall_mm` None on
    every spec that states no wall, which nothing downstream can build from.

    Every default must also clear `wall_floor_mm()` at the default nozzle, or it would
    be a default `compile_spec` refuses.
    """
    assert set(ARCHETYPE_WALL_MM) == set(REGISTRY)
    for name, wall in ARCHETYPE_WALL_MM.items():
        assert isinstance(wall, float) and wall >= wall_floor_mm(), name


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_archetypes_envelope_compiles_and_is_its_own(name):
    """`envelope_for` is what the dimensional sweep collects, so a case it cannot
    compile is a sweep that errors rather than measures. Checked here on one case per
    archetype — the sweep itself compiles all of them, and this is the registry's half:
    the dispatch answers, the cases name the archetype that declared them, and at least
    one of them is marked for Phase 3's assert path.
    """
    cases = envelope_for(name)
    assert cases, f"{name} declares an empty envelope"
    assert {case.spec.archetype for case in cases} == {name}
    assert any(case.phase_3 for case in cases)
    assert len({case.id for case in cases}) == len(cases), f"{name} repeats a case id"
    # One case, compiled: the envelope asks only for parts the archetype accepts, so a
    # refusal here is a declaration that does not match the module that made it.
    compile_spec(cases[0].spec)


def test_an_archetype_with_no_envelope_is_refused_by_name():
    """The refusal a person adding the fourth archetype will read. It names the module
    and points at `SweepCase`, because "declare an envelope" is not guessable from a
    KeyError."""
    module = SimpleNamespace(
        ARCHETYPE="mystery_box", ARCHETYPE_VERSION="1", MEASURED_FEATURES=("a_mm",),
        USES_PROCESS_WALL_MM=True,
    )
    with patch.dict(REGISTRY, {"mystery_box": module}):
        with pytest.raises(SpecError) as exc:
            envelope_for("mystery_box")
    message = str(exc.value)
    assert "mystery_box" in message and "envelope()" in message and "SweepCase" in message


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_archetype_says_whether_the_process_wall_is_its_wall(name):
    """The floor only means something for an archetype that builds with the field. A
    module that does not declare either way would be held to a limit on a number it
    ignores, or exempted from one it builds with — both silently."""
    assert isinstance(REGISTRY[name].USES_PROCESS_WALL_MM, bool)
