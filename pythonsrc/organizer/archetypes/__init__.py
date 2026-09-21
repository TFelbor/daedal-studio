"""The archetype registry and the dispatch functions the pipeline and CLI call.

One module per archetype, each exposing the same verbs (`validate`, `derive`, `build`,
`compile`, `measure`, `fits_check`, `to_view`, `example`) plus `ARCHETYPE`,
`ARCHETYPE_VERSION`, `MEASURED_FEATURES` and `USES_PROCESS_WALL_MM`. The registry maps a
spec's `archetype` string to its module; adding an archetype is adding a module and a
line here, and `spec.ARCHETYPES` must name it too or the schema refuses it before this
is reached. `spec.ARCHETYPE_WALL_MM` must name it as well — the wall it builds with when
a spec does not state one — which `tests/test_archetype_registry.py` binds.

Three archetypes as of issue #84 — the deck box (two bodies, a lip and a lift-off lid),
the card divider (one flat plate with a label tab) and the token tray (one open body, a
grid of square pockets). Nothing outside these modules knows the difference:
`pipeline.py --spec`, the dispatch through `compile_spec` / `verify_spec_mesh` and the
CLI took no archetype-specific change to gain the second one, which is the property the
second archetype existed to test. What a second module *did* have to share moved into
`common.py` rather than being copied.

`envelope_for` is the fifth thing an archetype has to satisfy, after the schema, the
registry, `ARCHETYPE_WALL_MM` and the composer's strip: the specs the dimensional sweep
drives it over. It is a dispatch like the rest, and it raises for a module that declares
none — see its docstring for why that is a refusal rather than a default.

The third archetype cost this file exactly one thing, and it is `required_measurements`:
a tray's feature list grows with its grid, so a module may now declare `measured_features(spec)`
and the registry prefers it over the fixed `MEASURED_FEATURES` tuple. Optional, with the
old behaviour as the fallback, so the deck box and the divider took no change either.
"""
from __future__ import annotations

from types import ModuleType

from ..compiler import (
    DEFAULT_TOLERANCE_MM,
    CompileResult,
    DimensionReport,
    FitsResult,
    check_dimensions,
)
from ..spec import (
    ARCHETYPE_WALL_MM,
    ARCHETYPES,
    DEFAULT_NOZZLE_DIAMETER_MM,
    OrganizerSpec,
    SpecError,
    game_box_record,
    wall_floor_problems,
)
from . import box_insert, card_divider, deck_box, token_tray
from .common import SweepCase, lettering_problems

REGISTRY: dict[str, ModuleType] = {
    deck_box.ARCHETYPE: deck_box,
    card_divider.ARCHETYPE: card_divider,
    token_tray.ARCHETYPE: token_tray,
    box_insert.ARCHETYPE: box_insert,
}

# The schema's list and the registry must agree, or a spec the schema accepts has
# nothing to compile it. Checked at import so the disagreement fails loudly.
_unregistered = sorted(set(ARCHETYPES) - set(REGISTRY))
if _unregistered:  # pragma: no cover
    raise ImportError(f"spec.ARCHETYPES names archetypes with no compiler: {_unregistered}")

# Same reason, for the wall: an archetype with no entry leaves `process.wall_mm` None
# on every spec that does not state one, and the compiler would build with nothing.
_wall_less = sorted(set(REGISTRY) - set(ARCHETYPE_WALL_MM))
if _wall_less:  # pragma: no cover
    raise ImportError(f"spec.ARCHETYPE_WALL_MM names no wall for: {_wall_less}")


def get_archetype(name: str) -> ModuleType:
    """The module for an archetype name.

    Raises:
        SpecError: For a name the registry does not know.
    """
    try:
        return REGISTRY[name]
    except KeyError:
        raise SpecError([f"unknown archetype {name!r}; known: {sorted(REGISTRY)}"]) from None


def compile_spec(
    spec: OrganizerSpec, nozzle_diameter_mm: float = DEFAULT_NOZZLE_DIAMETER_MM,
) -> CompileResult:
    """Compile a spec with its archetype, on a printer with this nozzle.

    The wall floor is enforced **here**, at compile time, rather than in Phase 3's
    `_assert_spec_dimensions` where `pipeline.py` also has the printer profile in hand.
    Three reasons, and the third is the one that settles it. Phase 3 runs after Phase 2
    has already written `compiled_mesh.stl`, `spec.json` and `compile_features.json`
    into the job directory and recorded the archetype as the job's generation model, so
    a floor enforced there refuses a part the system has already produced and described.
    Refusing an unbuildable wall is what "the archetype refuses a spec it cannot honour"
    already means, and that lives in Phase 2. And `python -m pythonsrc.organizer
    compile`, `fits_check` and the composer's preview never reach Phase 3 at all — a
    floor only Phase 3 knew about would not exist for the developer loop or the UI.

    Args:
        spec: The spec, already schema-valid.
        nozzle_diameter_mm: The printer profile's `machine_nozzle_size`; the floor is
            `spec.wall_floor_mm()` of it. Defaults to CuraEngine's 0,4 mm, which is
            what every bundled profile declares.

    The **lettering floors** are enforced here too and for the same three reasons: the
    printer's nozzle decides how thin a glyph stroke may be (`common.stroke_floor_mm`),
    a refusal after Phase 2 has written the mesh refuses a part the system has already
    produced, and a glyph the machine cannot lay must be named where a person can change
    it rather than discovered in Phase 4 as a name the slicer quietly left off the box.
    See `common.lettering_problems`.

    Raises:
        SpecError: If the archetype refuses the spec, the wall is below the floor, or the
            lettering does not fit or does not print. Every set of problems is reported
            together — a spec is refused whole.
    """
    module = get_archetype(spec.archetype)
    problems = (
        wall_floor_problems(spec, nozzle_diameter_mm) if module.USES_PROCESS_WALL_MM else []
    )
    problems.extend(lettering_problems(spec, module, nozzle_diameter_mm))
    if problems:
        try:
            module.validate(spec)
        except SpecError as exc:
            problems.extend(exc.problems)
        raise SpecError(problems)
    result = module.compile(spec)
    # The curated box is recorded **here** rather than in each archetype's `compile`,
    # because it is a fact about the spec and not about any one shape: any archetype may
    # be sized against a box interior, and four copies of this line would be four places
    # for it to be forgotten. `game_box_record` returns None for a spec with no `box`, so
    # `features_document` is unchanged for every part built to typed millimetres.
    result.game_box = game_box_record(spec)
    return result


def example_spec(name: str) -> OrganizerSpec:
    return get_archetype(name).example()


def measure_spec_mesh(spec: OrganizerSpec, mesh) -> dict[str, float]:
    """Read a spec's designed features off a mesh with the spec's own archetype.

    A module **may** declare `MEASURE_NEEDS_SPEC = True` when it cannot read its features
    off the mesh alone, and this passes the spec as a second argument when it does. The
    box insert is the first and is the reason the hook exists: its compartments are
    ragged, so a global plane count is not its layout and each one has to be measured
    inside the region the *design* says it occupies (`compiler.face_planes_within`). The
    mesh still supplies every number — what the spec supplies is where to look.

    Optional with the old signature as the fallback, exactly like `measured_features`, so
    the other three modules keep `measure(mesh)` and took no change. It is declared on the
    module rather than sniffed off the function signature because "this measurer needs the
    design" is a claim a reviewer should see in the diff, not something inferred from an
    argument count that a refactor could change by accident.
    """
    module = get_archetype(spec.archetype)
    if getattr(module, "MEASURE_NEEDS_SPEC", False):
        return module.measure(mesh, spec)
    return module.measure(mesh)


def required_measurements(spec: OrganizerSpec) -> tuple[str, ...]:
    """The designed features the spec's archetype promises to read back off geometry.

    A module **may** expose `measured_features(spec)` when its feature list is a
    function of the spec rather than a constant, and this prefers it. The token tray is
    the first: the three externals, the wall and the floor, plus one width, depth and
    height per grid position and one thickness per wall including the outer ones — which
    is 30 features for a 2 × 3 tray and 37 for a 4 × 2 (rows × columns, so the wall
    counts are `columns + 1` and `rows + 1`, and the two are not each other's mirror). A
    fixed tuple could only name the handful that do not move — the externals, the wall,
    the floor — which would leave every pocket in the grid unmeasured while the report
    still said *within tolerance*.

    `MEASURED_FEATURES` remains the fallback and remains required of every module: it is
    what `tests/test_archetype_registry.py` checks an example against, and a module with
    neither would promise nothing.
    """
    module = get_archetype(spec.archetype)
    derive_features = getattr(module, "measured_features", None)
    if derive_features is not None:
        return tuple(derive_features(spec))
    return tuple(module.MEASURED_FEATURES)


def envelope_for(name: str) -> tuple[SweepCase, ...]:
    """The specs an archetype holds itself to at `DEFAULT_TOLERANCE_MM` (issue #85).

    The dimensional sweep used to be written for the deck box and then copied per
    archetype, which meant a third archetype could be registered, compiled, offered in
    the composer and printed while nothing had ever measured a mesh it produced. A
    module now declares its own envelope — `common.SweepCase`, the parameter ranges and
    the corner set that goes on through Phase 3 — and
    `tests/test_organizer_dimensional_accuracy.py` sweeps whatever this returns for
    every name in `REGISTRY`.

    So this raises rather than returning nothing for a module that declares none: an
    archetype nothing sweeps has made no accuracy claim, and the claim is the difference
    between an archetype and a mesh generator. The refusal names the module, because the
    person who hits it is the person who just added it.

    Raises:
        SpecError: For an archetype with no `envelope()`, or one whose envelope is empty.
    """
    module = get_archetype(name)
    declare = getattr(module, "envelope", None)
    if declare is None:
        raise SpecError([
            f"archetype {name!r} declares no envelope(): every registered archetype owes "
            f"the dimensional sweep the specs it holds itself to at "
            f"{DEFAULT_TOLERANCE_MM} mm — see pythonsrc/organizer/archetypes/common.py "
            f"SweepCase"
        ])
    cases = tuple(declare())
    if not cases:
        raise SpecError([f"archetype {name!r} declares an empty envelope()"])
    return cases


def verify_spec_mesh(
    spec: OrganizerSpec,
    designed: dict[str, float],
    mesh,
    tol_mm: float = DEFAULT_TOLERANCE_MM,
) -> DimensionReport:
    """Measure `mesh` with the spec's archetype and compare it to `designed`.

    The one call the pipeline, the CLI and the tests share, so "within tolerance" means
    the same thing in all three. Raises the archetype's `MeasureError` when the mesh does
    not have the planes the design says it has — that finding is not a per-feature error
    and is not reported as one.
    """
    measured = measure_spec_mesh(spec, mesh)
    return check_dimensions(designed, measured, tol_mm, required=set(required_measurements(spec)))


def fits_for(spec: OrganizerSpec) -> FitsResult:
    return get_archetype(spec.archetype).fits_check(spec)


def view_for(spec: OrganizerSpec, result: CompileResult) -> dict:
    return get_archetype(spec.archetype).to_view(spec, result)
