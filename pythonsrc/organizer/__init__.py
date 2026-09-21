"""The parametric organizer engine — spec schema, seed dimensions, archetype compilers.

This package exports the **schema only**. It imports nothing outside the stdlib, so the
api-server image (which installs neither trimesh nor manifold3d) can import it the day
the request model grows a spec field. The compilers live behind explicit imports:

    from pythonsrc.organizer.archetypes import compile_spec, measure_spec_mesh
    from pythonsrc.organizer.compiler import export_stl

`pipeline.py --spec` is the entry that runs them.
"""
from .spec import (  # noqa: F401
    ARCHETYPE_WALL_MM,
    ARCHETYPES,
    DEFAULT_NOZZLE_DIAMETER_MM,
    FIT_INTENT_CLEARANCE_MM,
    FIT_INTENTS,
    SCHEMA_VERSION,
    TAB_POSITIONS,
    WALL_FLOOR_NOZZLE_MULTIPLE,
    CardStack,
    Compartment,
    Constraints,
    Divider,
    GameBox,
    Lid,
    OrganizerSpec,
    Pocket,
    Process,
    SpecError,
    Tray,
    canonical_json,
    check_wall_floor,
    dump_spec,
    game_box_record,
    load_spec,
    problem_path,
    problems_with_paths,
    spec_diff,
    spec_hash,
    wall_floor_mm,
    wall_floor_problems,
)
