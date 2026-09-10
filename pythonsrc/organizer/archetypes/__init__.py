"""The archetype registry and the dispatch functions the pipeline and CLI call.

One module per archetype, each exposing the same verbs (`validate`, `derive`, `build`,
`compile`, `measure`, `fits_check`, `to_view`, `example`) plus `ARCHETYPE`,
`ARCHETYPE_VERSION` and `MEASURED_FEATURES`. The registry maps a spec's `archetype`
string to its module; adding an archetype is adding a module and a line here, and
`spec.ARCHETYPES` must name it too or the schema refuses it before this is reached.

Two archetypes as of issue #65 — the deck box (two bodies, a lip and a lift-off lid)
and the card divider (one flat plate with a label tab). Nothing outside these modules
knows the difference: `pipeline.py --spec`, the dispatch through `compile_spec` /
`verify_spec_mesh` and the CLI took no archetype-specific change to gain the second
one, which is the property the second archetype existed to test. What a second module
*did* have to share moved into `common.py` rather than being copied.
"""
from __future__ import annotations

from types import ModuleType

from ..compiler import DEFAULT_TOLERANCE_MM, CompileResult, DimensionReport, FitsResult, check_dimensions
from ..spec import ARCHETYPES, OrganizerSpec, SpecError
from . import card_divider, deck_box

REGISTRY: dict[str, ModuleType] = {
    deck_box.ARCHETYPE: deck_box,
    card_divider.ARCHETYPE: card_divider,
}

# The schema's list and the registry must agree, or a spec the schema accepts has
# nothing to compile it. Checked at import so the disagreement fails loudly.
_unregistered = sorted(set(ARCHETYPES) - set(REGISTRY))
if _unregistered:  # pragma: no cover
    raise ImportError(f"spec.ARCHETYPES names archetypes with no compiler: {_unregistered}")


def get_archetype(name: str) -> ModuleType:
    """The module for an archetype name.

    Raises:
        SpecError: For a name the registry does not know.
    """
    try:
        return REGISTRY[name]
    except KeyError:
        raise SpecError([f"unknown archetype {name!r}; known: {sorted(REGISTRY)}"]) from None


def compile_spec(spec: OrganizerSpec) -> CompileResult:
    """Compile a spec with its archetype. Raises `SpecError` if the archetype refuses it."""
    return get_archetype(spec.archetype).compile(spec)


def example_spec(name: str) -> OrganizerSpec:
    return get_archetype(name).example()


def measure_spec_mesh(spec: OrganizerSpec, mesh) -> dict[str, float]:
    """Read a spec's designed features off a mesh with the spec's own archetype."""
    return get_archetype(spec.archetype).measure(mesh)


def required_measurements(spec: OrganizerSpec) -> tuple[str, ...]:
    """The designed features the spec's archetype promises to read back off geometry."""
    return tuple(get_archetype(spec.archetype).MEASURED_FEATURES)


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
