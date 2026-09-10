"""The parametric organizer engine — spec schema, seed dimensions, archetype compilers.

This package exports the **schema only**. It imports nothing outside the stdlib, so the
api-server image (which installs neither trimesh nor manifold3d) can import it the day
the request model grows a spec field. The compilers live behind explicit imports:

    from pythonsrc.organizer.archetypes import compile_spec, measure_spec_mesh
    from pythonsrc.organizer.compiler import export_stl

`pipeline.py --spec` is the entry that runs them.
"""
from .spec import (  # noqa: F401
    ARCHETYPES,
    FIT_INTENT_CLEARANCE_MM,
    FIT_INTENTS,
    SCHEMA_VERSION,
    TAB_POSITIONS,
    CardStack,
    Compartment,
    Constraints,
    Divider,
    Lid,
    OrganizerSpec,
    Process,
    SpecError,
    canonical_json,
    dump_spec,
    load_spec,
    spec_diff,
    spec_hash,
)
