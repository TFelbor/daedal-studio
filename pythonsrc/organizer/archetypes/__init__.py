"""The archetype registry and the dispatch functions the pipeline and CLI call.

One module per archetype, each exposing the same verbs (`validate`, `derive`, `build`,
`compile`, `measure`, `fits_check`, `to_view`, `example`) plus `ARCHETYPE` and
`ARCHETYPE_VERSION`. The registry maps a spec's `archetype` string to its module;
adding an archetype is adding a module and a line here, and `spec.ARCHETYPES` must
name it too or the schema refuses it before this is reached.
"""
from __future__ import annotations

from types import ModuleType

from ..compiler import CompileResult, FitsResult
from ..spec import ARCHETYPES, OrganizerSpec, SpecError
from . import deck_box

REGISTRY: dict[str, ModuleType] = {
    deck_box.ARCHETYPE: deck_box,
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


def fits_for(spec: OrganizerSpec) -> FitsResult:
    return get_archetype(spec.archetype).fits_check(spec)


def view_for(spec: OrganizerSpec, result: CompileResult) -> dict:
    return get_archetype(spec.archetype).to_view(spec, result)
