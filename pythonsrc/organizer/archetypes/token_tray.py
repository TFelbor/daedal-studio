"""Token tray, version 1: one open tray, a regular grid of square-cornered pockets.

The third archetype, and the first whose compartments hold something that is not a card
stack (issue #84). That is the composition wedge PRD §1 claims and the step towards the
multi-compartment box insert: `Compartment.contents` became a union, `compartments`
became genuinely plural, and this module is what reads the plural.

One body, printed open side up, flat on Z = 0, no overhangs anywhere. With `cols` from
`tray.columns`, `rows = len(compartments) // cols`, `w` from `process.wall_mm`, `f` from
`process.floor_mm`, and the pockets' own millimetres:

    x[c]       = (c+1)·w + Σ widths[:c]        y[r]       = (r+1)·w + Σ depths[:r]
    external_w = Σ widths + (cols+1)·w         external_d = Σ depths + (rows+1)·w
    external_h = height + f
    tray       = cube(external) − ⋃ cube(width[c], depth[r], height + 1) at (x[c], y[r], f)

Compartments are laid out **row-major, compartment 0 at the minimum X and Y corner**, so
`compartments[i]` is row `i // cols`, column `i % cols`.

**The grid is regular, and that is a validation rule rather than a layout convenience.**
One `width_mm` per column, one `depth_mm` per row, one `height_mm` over the whole tray.
It is what makes every pocket wall a plane *shared across the grid*: a ragged layout
would put a Y plane at the top of one pocket and nowhere else, and `measure` reads
features off distinct axis-aligned planes, so it could not tell a designed edge from an
artefact — the failure `card_divider`'s union produced and its extruded outline fixed.
Ragged pockets and per-pocket heights belong to the box-insert archetype, which needs
explicit positions anyway.

**Square pockets, square corners.** No fillets and no chamfers: the geometry here is
cubes and booleans. Issue #80 landed `compiler.rounded_rect_prism` and
`compiler.base_chamfer` and the deck box carries both, so the primitives now exist and
this archetype simply does not call them yet — `process.corner_radius_mm` and
`process.base_chamfer_mm` are read by nobody here. That is the one edge treatment this
tray most wants (`cavity_corner_radius_mm`'s docstring names the token tray as the
archetype that will turn it up, so a thumb can scoop parts out of a pocket), and it is
its own issue rather than a v1 feature. A first tray says so in `to_view` rather than
implying a radius it does not build.

**No token or dice presets ship with it.** `dimensions.py` carries no token sizes on
purpose — "an invented one is exactly the fabricated number the schema exists to
refuse" — and `docs/dimension-kb-research.md` §4 sources die *sizes* (16 mm d6, 12 mm
d6) without sourcing the clearance a die needs around it. A 16 mm die in a 16 mm pocket
is not a pocket, so a preset would be one sourced number plus one invented one, which
is the number this engine exists to refuse. Every pocket is therefore user-given
millimetres, and `Pocket.source` carries whatever provenance the person had.

**`Process` fields this archetype does not read still hash.** It reads `wall_mm`,
`floor_mm` and `min_feature_mm`. `fit_intent`, `cavity_clearance_mm` and
`stack_slack_mm` are all about a card stack, and a tray has none; `base_chamfer_mm`,
`corner_radius_mm` and `cavity_corner_radius_mm` (issue #80) are the edge treatments
above. So two tray specs differing only in `fit_intent` — or only in
`corner_radius_mm` — compile identically and hash differently. Accepted, for
`card_divider`'s reason verbatim: the spec records what was asked for, and the compiler
records what it built (`compile_features.json`).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any

import manifold3d

from ..compiler import CompileResult, FitsResult, MeasureError, manifold_to_trimesh, plane_set
from ..spec import (
    Compartment,
    OrganizerSpec,
    Pocket,
    Process,
    SpecError,
    Tray,
    spec_hash,
)
from .common import (
    CALLOUT_TIER_EXTERNAL,
    SweepCase,
    callout,
    external_overshoots,
    view_frame,
    view_row,
)

ARCHETYPE = "token_tray"
#: Bumped when the geometry a given spec produces changes. Recorded on every job.
ARCHETYPE_VERSION = "1"
#: The outer wall *and* every divider is `process.wall_mm` here, so `compile_spec`
#: holds it to the nozzle-derived floor. `spec.ARCHETYPE_WALL_MM["token_tray"]` is what
#: it defaults to: 1,6 mm, the top of the audited insert band.
USES_PROCESS_WALL_MM = True
#: How this archetype names itself in a refusal or a measurement finding.
_SUBJECT = f"a token tray v{ARCHETYPE_VERSION}"


@dataclass(frozen=True)
class TrayDimensions:
    """Every derived dimension, in mm, from one spec. Pure arithmetic — no kernel."""

    rows: int
    columns: int
    #: One internal width per column, left to right.
    widths: tuple[float, ...]
    #: One internal depth per row, front to back.
    depths: tuple[float, ...]
    #: The one internal depth-of-pocket every pocket shares.
    height: float
    wall: float
    floor: float
    external_w: float
    external_d: float
    external_h: float

    def pocket_origin(self, row: int, column: int) -> tuple[float, float]:
        """The (x, y) of one pocket's minimum corner, in mm from the tray's own."""
        x = (column + 1) * self.wall + sum(self.widths[:column])
        y = (row + 1) * self.wall + sum(self.depths[:row])
        return round(x, 3), round(y, 3)

    def features(self, spec: OrganizerSpec) -> dict[str, float]:
        """The designed features by name. `measure()` reads the same names back.

        Every one of them is on the mesh — a tray designs no figure geometry does not
        carry — so `measured_features(spec)` is exactly this key set.
        """
        raw: dict[str, float] = {
            "external_width_mm": self.external_w,
            "external_depth_mm": self.external_d,
            "external_height_mm": self.external_h,
            "wall_mm": self.wall,
            "floor_mm": self.floor,
        }
        for row in range(self.rows):
            for column in range(self.columns):
                key = _pocket_key(row, column)
                raw[f"{key}_width_mm"] = self.widths[column]
                raw[f"{key}_depth_mm"] = self.depths[row]
                raw[f"{key}_height_mm"] = self.height
        for i in range(self.columns + 1):
            raw[f"wall_x{i}_mm"] = self.wall
        for j in range(self.rows + 1):
            raw[f"wall_y{j}_mm"] = self.wall
        return {k: round(float(v), 3) for k, v in raw.items()}


def _pocket_key(row: int, column: int) -> str:
    """How one grid position names itself in a feature, e.g. `pocket_r1c2`."""
    return f"pocket_r{row}c{column}"


def _pockets(spec: OrganizerSpec) -> list[Pocket]:
    """The compartments' contents, assuming every one of them is a `Pocket`."""
    return [c.contents for c in spec.compartments]  # type: ignore[misc]


def _structural_problems(spec: OrganizerSpec) -> list[str]:
    """Everything that must hold before `derive` can do arithmetic at all."""
    problems: list[str] = []
    if spec.archetype != ARCHETYPE:
        problems.append(f"archetype {spec.archetype!r} is not {ARCHETYPE!r}")
    if spec.lid is not None:
        problems.append(
            f"token_tray v{ARCHETYPE_VERSION} is an open tray and has no closure; "
            "remove the lid section or change the archetype"
        )
    if spec.divider is not None:
        problems.append(
            f"token_tray v{ARCHETYPE_VERSION} has no divider plate; the divider section "
            "belongs to archetype 'card_divider' — remove it or change the archetype"
        )
    carded = [i for i, c in enumerate(spec.compartments) if not isinstance(c.contents, Pocket)]
    if carded:
        problems.append(
            f"token_tray v{ARCHETYPE_VERSION} holds pockets, not card stacks; "
            f"compartments{carded} carry a card stack. Give each compartment a pocket "
            "(width_mm, depth_mm, height_mm), or use archetype 'deck_box' for cards"
        )
    if spec.tray is None:
        problems.append(
            f"token_tray v{ARCHETYPE_VERSION} needs a tray section (tray is null); it "
            "carries tray.columns, and the rows follow from the compartment count"
        )
    elif spec.compartments and len(spec.compartments) % spec.tray.columns:
        problems.append(
            f"tray.columns {spec.tray.columns} does not divide the "
            f"{len(spec.compartments)} compartments; a token_tray v{ARCHETYPE_VERSION} "
            "is a full rectangular grid — add or remove compartments, or change the "
            "column count"
        )
    return problems


def _grid_problems(spec: OrganizerSpec) -> list[str]:
    """The regular-grid rule: one width per column, one depth per row, one height.

    Stated per offending position rather than as one sentence, because "the grid is
    irregular" is not something a person can act on and "compartments[4] is 18 mm wide
    where column 1 is 20 mm" is.
    """
    assert spec.tray is not None
    columns = spec.tray.columns
    pockets = _pockets(spec)
    problems: list[str] = []
    height = pockets[0].height_mm
    for i, pocket in enumerate(pockets):
        row, column = divmod(i, columns)
        first_in_column = pockets[column]
        first_in_row = pockets[row * columns]
        if pocket.width_mm != first_in_column.width_mm:
            problems.append(
                f"compartments[{i}].contents.width_mm {pocket.width_mm:g} differs from "
                f"{first_in_column.width_mm:g} mm in column {column}; a token_tray "
                f"v{ARCHETYPE_VERSION} is a regular grid — one width per column"
            )
        if pocket.depth_mm != first_in_row.depth_mm:
            problems.append(
                f"compartments[{i}].contents.depth_mm {pocket.depth_mm:g} differs from "
                f"{first_in_row.depth_mm:g} mm in row {row}; a token_tray "
                f"v{ARCHETYPE_VERSION} is a regular grid — one depth per row"
            )
        if pocket.height_mm != height:
            problems.append(
                f"compartments[{i}].contents.height_mm {pocket.height_mm:g} differs from "
                f"{height:g} mm; a token_tray v{ARCHETYPE_VERSION} has one pocket depth "
                "over the whole grid"
            )
    return problems


def derive(spec: OrganizerSpec) -> TrayDimensions:
    """Every dimension the geometry is built from.

    Assumes `_structural_problems` and `_grid_problems` are both empty — the grid is
    regular, so the first pocket of each column fixes that column's width and the first
    of each row fixes that row's depth.
    """
    assert spec.tray is not None  # validated before derive() is reached
    p: Process = spec.process
    columns = spec.tray.columns
    pockets = _pockets(spec)
    rows = len(pockets) // columns
    widths = tuple(pockets[c].width_mm for c in range(columns))
    depths = tuple(pockets[r * columns].depth_mm for r in range(rows))
    height = pockets[0].height_mm
    wall = p.wall_mm
    assert wall is not None  # OrganizerSpec resolves it to the archetype's default

    def r(x: float) -> float:  # every value to 1 µm, like the schema
        return round(float(x), 3)

    return TrayDimensions(
        rows=rows, columns=columns,
        widths=tuple(r(w) for w in widths), depths=tuple(r(d) for d in depths),
        height=r(height), wall=r(wall), floor=r(p.floor_mm),
        external_w=r(sum(widths) + (columns + 1) * wall),
        external_d=r(sum(depths) + (rows + 1) * wall),
        external_h=r(height + p.floor_mm),
    )


def validate(spec: OrganizerSpec) -> None:
    """Refuse a spec this archetype cannot honour, naming every problem and its remedy.

    Raises:
        SpecError: With every archetype-level problem.
    """
    problems = _structural_problems(spec)
    if problems:
        raise SpecError(problems)
    problems = _grid_problems(spec)
    if problems:
        raise SpecError(problems)
    d = derive(spec)
    min_feature = spec.process.min_feature_mm
    for i, pocket in enumerate(_pockets(spec)):
        for name, value in (
            ("width_mm", pocket.width_mm),
            ("depth_mm", pocket.depth_mm),
            ("height_mm", pocket.height_mm),
        ):
            if value < min_feature:
                problems.append(
                    f"compartments[{i}].contents.{name} {value:g} mm is below "
                    f"process.min_feature_mm {min_feature:g}; widen the pocket or lower "
                    "the minimum"
                )
    if d.wall < min_feature:
        problems.append(
            f"process.wall_mm {d.wall:g} mm is below process.min_feature_mm "
            f"{min_feature:g}; every divider between two pockets is this thick — "
            "thicken the wall or lower the minimum"
        )
    if d.floor < min_feature:
        problems.append(
            f"process.floor_mm {d.floor:g} mm is below process.min_feature_mm "
            f"{min_feature:g}; it is the whole bottom of the tray — thicken the floor "
            "or lower the minimum"
        )
    if problems:
        raise SpecError(problems)


def build(spec: OrganizerSpec) -> tuple[dict[str, "manifold3d.Manifold"], TrayDimensions]:
    """Validate, derive, and build the one solid in plate position."""
    validate(spec)
    d = derive(spec)

    def cube(x: float, y: float, z: float) -> "manifold3d.Manifold":
        return manifold3d.Manifold.cube([x, y, z], False)

    tray = cube(d.external_w, d.external_d, d.external_h)
    for row in range(d.rows):
        for column in range(d.columns):
            x, y = d.pocket_origin(row, column)
            # +1 mm through the top, so the pocket's own top face is never a plane of
            # its own — a tray is open, and a coincident face is a kernel coin flip.
            tray = tray - cube(d.widths[column], d.depths[row], d.height + 1.0).translate(
                [x, y, d.floor]
            )
    return {"tray": tray}, d


def compile(spec: OrganizerSpec) -> CompileResult:  # noqa: A001 — the registry's verb
    """Spec → tray mesh, parts, designed features."""
    solids, d = build(spec)
    parts = {name: manifold_to_trimesh(solid) for name, solid in solids.items()}
    return CompileResult(
        archetype=ARCHETYPE,
        archetype_version=ARCHETYPE_VERSION,
        spec_hash=spec_hash(spec),
        mesh=manifold_to_trimesh(solids["tray"]),
        parts=parts,
        features=d.features(spec),
    )


#: The pocket the example is built from, in mm, and the sentence that says so.
#:
#: 20 mm is a **design example, not a sourced token size**: it is round, it holds a
#: standard punchboard token or a 16 mm d6 with room, and nothing in
#: `docs/dimension-kb-research.md` gives a punchboard footprint or a die clearance to
#: derive it from. Saying that on the spec itself is the whole point of `Pocket.source`.
EXAMPLE_POCKET_MM: tuple[float, float, float] = (20.0, 20.0, 15.0)
EXAMPLE_SOURCE = (
    "design example, not a sourced size — no punchboard token footprint or die "
    "clearance is sourced in docs/dimension-kb-research.md §4"
)


def example() -> OrganizerSpec:
    """A 2 × 3 tray of 20 × 20 × 15 mm pockets, with the archetype's own wall and floor.

    66,4 × 44,8 × 17,0 mm external at the defaults: three 20 mm columns plus four
    1,6 mm walls, two 20 mm rows plus three, and 15 mm of pocket over a 2 mm floor.
    """
    pocket = Pocket(
        width_mm=EXAMPLE_POCKET_MM[0],
        depth_mm=EXAMPLE_POCKET_MM[1],
        height_mm=EXAMPLE_POCKET_MM[2],
        source=EXAMPLE_SOURCE,
    )
    return OrganizerSpec(
        archetype=ARCHETYPE,
        compartments=tuple(Compartment(pocket) for _ in range(6)),
        tray=Tray(columns=3),
    )


#: The features `measure()` reads off *any* tray, whatever its grid.
#:
#: The rest — one width, depth and height per grid position and one thickness per wall
#: — depend on the spec, so they come from `measured_features(spec)` below, which the
#: registry's `required_measurements` prefers when a module offers it. This tuple stays
#: because the registry API declares it and because these five are the names that do not
#: move: a module with no fixed features would have nothing to check an example against.
MEASURED_FEATURES: tuple[str, ...] = (
    "external_width_mm", "external_depth_mm", "external_height_mm", "wall_mm", "floor_mm",
)


def measured_features(spec: OrganizerSpec) -> tuple[str, ...]:
    """Every feature `measure()` reads back for *this* spec's grid.

    The first spec-dependent measurement list in the registry, and it has to be: the
    feature count grows with the grid (a 2 × 3 tray has 30 of them, a 4 × 2 has 37), so
    a fixed tuple could only ever promise the five above and would leave every pocket
    and every divider unchecked — which is the acceptance criterion this archetype was
    written for. `archetypes.required_measurements` prefers this when a module defines
    it and falls back to `MEASURED_FEATURES` when it does not, so the other two modules
    took no change.
    """
    return tuple(derive(spec).features(spec))


def _axis_planes(part: Any, axis: int) -> list[float]:
    """The distinct planes on one axis of the tray body, with the grid left to `measure`."""
    return plane_set(part.vertices[:, axis])


def _grid_from_planes(planes: list[float], axis: int) -> int:
    """How many pockets the plane count says this axis carries, or the finding.

    A tray with `n` pockets across an axis puts `2n + 2` planes on it: the outer face,
    then one pair per pocket, then the far outer face. So the count is the grid, read
    off the mesh rather than taken from the spec — which is what lets `measure` refuse a
    mesh that is not a tray at all instead of quietly measuring a deck box.

    Raises:
        MeasureError: If the count is not an even number ≥ 4.
    """
    count = len(planes)
    if count < 4 or count % 2:
        raise MeasureError(
            f"the tray has {count} distinct {'XYZ'[axis]} planes, which is not "
            f"2n + 2 for any n ≥ 1: {_SUBJECT} has one pair per pocket between two "
            f"outer faces. Found {[round(v, 3) for v in planes]}"
        )
    return (count - 2) // 2


def measure(mesh: Any) -> dict[str, float]:
    """Read the designed features back off a tray mesh — compiled or post-Phase-3.

    One body. X carries `2·columns + 2` planes and Y `2·rows + 2`, so the grid itself is
    read off the mesh; Z carries exactly three (the bed, the floor, the rim), and a
    fourth would mean pockets of different depths, which this archetype does not build.
    Every feature is then a difference of two of those planes: a pocket's internal size,
    the thickness of each wall including the outer ones, the floor and the externals.

    The walls are numbered rather than reported as one `wall_mm`, and both are returned.
    They are all the same number by construction, which is exactly why each has to be
    measured: a layout bug that put one divider in the wrong place would leave the
    design's `wall_mm` intact on the outer faces and move one inner pair, and a single
    figure read off the first wall would not see it.

    Raises:
        MeasureError: If the mesh is not one body with a tray's plane structure.
    """
    parts = mesh.split(only_watertight=False)
    if len(parts) != 1:
        raise MeasureError(f"expected 1 body (the tray), found {len(parts)}")
    part = parts[0]
    x = _axis_planes(part, 0)
    y = _axis_planes(part, 1)
    z = _axis_planes(part, 2)
    columns = _grid_from_planes(x, 0)
    rows = _grid_from_planes(y, 1)
    if len(z) != 3:
        raise MeasureError(
            f"the tray has {len(z)} distinct Z planes where {_SUBJECT} has 3 (the bed, "
            f"the floor and the rim): {[round(v, 3) for v in z]}"
        )
    measured: dict[str, float] = {
        "external_width_mm": x[-1] - x[0],
        "external_depth_mm": y[-1] - y[0],
        "external_height_mm": z[2] - z[0],
        "floor_mm": z[1] - z[0],
        "wall_mm": x[1] - x[0],
    }
    for row in range(rows):
        for column in range(columns):
            key = _pocket_key(row, column)
            measured[f"{key}_width_mm"] = x[2 * column + 2] - x[2 * column + 1]
            measured[f"{key}_depth_mm"] = y[2 * row + 2] - y[2 * row + 1]
            measured[f"{key}_height_mm"] = z[2] - z[1]
    for i in range(columns + 1):
        measured[f"wall_x{i}_mm"] = x[2 * i + 1] - x[2 * i]
    for j in range(rows + 1):
        measured[f"wall_y{j}_mm"] = y[2 * j + 1] - y[2 * j]
    return {k: float(v) for k, v in measured.items()}


def fits_check(spec: OrganizerSpec) -> FitsResult:
    """The millimetre arithmetic, and whether the result fits its external constraint.

    **Without a constraint a tray fits by construction, and says so with the sum.**
    Every millimetre in it was typed by the person asking: there is no dimension table
    behind a pocket, so there is nothing here for the arithmetic to disagree with — the
    line is the value, and it is what somebody checks against their own callipers.

    That is also why an overshoot is a *verdict* rather than a refusal. A deck box
    refuses an `easy` fit that busts a stated limit because the clearance that pushed it
    over is a number nobody typed (`deck_box._easy_fit_problems`); here every number was
    typed, so the honest answer is "it does not fit, by this much, on this axis", not a
    spec the composer cannot even show.

    `constraints.max_external_mm` is `(W, D, H)` of the tray as it sits in the box, and
    the comparison is against the limit minus `constraints.fit_margin_mm` (2,0 mm by
    default — `docs/dimension-kb-research.md` §7), on every axis. A tray that presses on
    the box walls splits them exactly as an insert does.
    """
    validate(spec)
    d = derive(spec)
    sources = {p.source for p in _pockets(spec) if p.source}
    basis = (
        "user-given millimetres; " + "; ".join(sorted(sources))
        if sources
        else "user-given millimetres — no token or dice size is sourced in the "
             "dimension KB, so nothing here was resolved from a table"
    )
    # One size when every column and row agree, and the two lists when they do not —
    # rather than one size per grid position, which for a 4 × 2 tray is eight repeats
    # of the same sentence.
    uniform = len(set(d.widths)) == 1 and len(set(d.depths)) == 1
    pocket_sizes = (
        f"{d.widths[0]:g} × {d.depths[0]:g} × {d.height:g} mm"
        if uniform
        else "widths " + "/".join(f"{w:g}" for w in d.widths)
             + " × depths " + "/".join(f"{x:g}" for x in d.depths)
             + f" × {d.height:g} mm"
    )
    line = (
        f"{d.rows} × {d.columns} grid of square pockets · {pocket_sizes} internal · "
        f"{d.wall:g} mm walls and dividers · {d.floor:g} mm floor · "
        f"external {d.external_w:g} × {d.external_d:g} × {d.external_h:g} mm"
    )
    fits = True
    remedy = None
    over = external_overshoots(
        spec, (d.external_w, d.external_d, d.external_h), prefix="external "
    )
    if over:
        fits = False
        remedy = (
            "; ".join(o.note for o in over)
            + ". Shrink the pockets, drop a row or a column, thin the wall, or relax "
            "the constraint."
        )
    return FitsResult(fits=fits, line=line, basis=basis, remedy=remedy)


def callouts(spec: OrganizerSpec) -> list[dict[str, Any]]:
    """The dimension lines the viewer draws on a tray, in the plate frame.

    **The first pocket only.** A regular grid has one width per column, one depth per row
    and one height, so a 4 × 2 tray would otherwise carry 24 pocket lines over a part
    66 mm wide — a picture nobody can read, which is worse than no picture. Row 0,
    column 0 is the position every other one is a copy of on at least one axis, and the
    view's own table (`dimensions`) is where a person reads the whole grid. Annotating
    every pocket is its own issue if anyone wants it.

    Tier 1 is that pocket's three internal figures, which is what a token or a die has
    to fit into. Tier 2 is the externals, the wall and the floor.
    """
    d = derive(spec)
    x0, y0 = d.pocket_origin(0, 0)
    w0, d0 = d.widths[0], d.depths[0]
    W, D, H = d.external_w, d.external_d, d.external_h
    up, front, left = (0.0, 0.0, 1.0), (0.0, -1.0, 0.0), (-1.0, 0.0, 0.0)
    inward = (0.0, 1.0, 0.0)
    return [
        callout("pocket_r0c0_width_mm", "Pocket width", w0, part="tray",
                frm=(x0, y0 + d0 / 2.0, H), to=(x0 + w0, y0 + d0 / 2.0, H), offset=up),
        callout("pocket_r0c0_depth_mm", "Pocket depth", d0, part="tray",
                frm=(x0 + w0 / 2.0, y0, H), to=(x0 + w0 / 2.0, y0 + d0, H), offset=up),
        callout("pocket_r0c0_height_mm", "Pocket depth (Z)", d.height, part="tray",
                frm=(x0 + w0 / 2.0, y0, d.floor), to=(x0 + w0 / 2.0, y0, H),
                offset=inward),
        callout("external_width_mm", "External width", W, part="tray",
                frm=(0.0, 0.0, 0.0), to=(W, 0.0, 0.0), offset=front,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("external_depth_mm", "External depth", D, part="tray",
                frm=(0.0, 0.0, 0.0), to=(0.0, D, 0.0), offset=left,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("external_height_mm", "External height", H, part="tray",
                frm=(0.0, D / 2.0, 0.0), to=(0.0, D / 2.0, H), offset=left,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("wall_mm", "Wall", d.wall, part="tray",
                frm=(0.0, y0 + d0 / 2.0, H), to=(d.wall, y0 + d0 / 2.0, H), offset=up,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("floor_mm", "Floor", d.floor, part="tray",
                frm=(W / 2.0, 0.0, 0.0), to=(W / 2.0, 0.0, d.floor), offset=front,
                tier=CALLOUT_TIER_EXTERNAL),
    ]


def to_view(spec: OrganizerSpec, result: CompileResult) -> dict[str, Any]:
    """The spec as `web/src/organizer/spec.ts` declares it: labelled millimetres, a fits
    verdict, the hash the gate binds to, and the annotated preview's `frame` and
    `callouts` (issue #88).

    Every pocket row says where its millimetres came from — `Pocket.source` when the
    person gave one, and *user-given mm* when they did not. Neither is presented as
    sourced, because no token or dice size is: a number shown as measured when somebody
    typed it is the failure this whole engine exists to avoid.
    """
    d = derive(spec)
    pockets = _pockets(spec)
    row = view_row
    dimensions = [
        row("rows", "Rows", d.rows, "pockets", False, "compartments ÷ tray.columns"),
        row("columns", "Columns", d.columns, "pockets", True, "tray.columns"),
    ]
    for column, width in enumerate(d.widths):
        dimensions.append(row(
            f"pocket_c{column}_width_mm", f"Pocket width, column {column}", width, "mm", True,
            _provenance(pockets[column]),
        ))
    for r_index, depth in enumerate(d.depths):
        dimensions.append(row(
            f"pocket_r{r_index}_depth_mm", f"Pocket depth, row {r_index}", depth, "mm", True,
            _provenance(pockets[r_index * d.columns]),
        ))
    dimensions += [
        row("pocket_height_mm", "Pocket depth (Z)", d.height, "mm", True,
            _provenance(pockets[0])),
        row("wall_mm", "Wall", d.wall, "mm", True,
            "outer walls and every divider; 1,2–1,6 mm insert band "
            "(roadmap §0.5 — one practitioner's practice)"),
        row("floor_mm", "Floor", d.floor, "mm", True),
        row("external_width_mm", "External width", d.external_w, "mm", False,
            f"{d.columns} pockets + {d.columns + 1} walls"),
        row("external_depth_mm", "External depth", d.external_d, "mm", False,
            f"{d.rows} pockets + {d.rows + 1} walls"),
        row("external_height_mm", "External height", d.external_h, "mm", False,
            "pocket plus floor; the tray is open"),
        row("min_feature_mm", "Minimum feature", spec.process.min_feature_mm, "mm", True,
            "the archetype refuses anything thinner"),
    ]
    return {
        "archetype": ARCHETYPE,
        "archetypeVersion": f"v{ARCHETYPE_VERSION}",
        "hash": result.spec_hash,
        "dimensions": dimensions,
        "fits": fits_check(spec).to_dict(),
        "frame": view_frame(result),
        "callouts": callouts(spec),
        # Square corners, stated rather than implied: the primitives exist since issue
        # #80 but this archetype does not call them, and a preview that drew a radius
        # would show a part the compiler does not build.
        "note": "square pockets, square corners — no fillets or chamfers in v1",
    }


def _provenance(pocket: Pocket) -> str:
    """What a pocket row says under its millimetres."""
    return pocket.source or "user-given mm — no token or dice size is sourced"


# ── The dimensional envelope (issue #85) ──────────────────────────────────────
#
# See `common.SweepCase` for what an envelope is. Four axes, and the **grid** is the one
# this archetype contributes: it is the only parameter anywhere in the registry that
# changes how many features there are to measure rather than what they measure, which is
# why this module is also the one that made `required_measurements` ask about the spec.
# A sweep that checked a fixed tuple would report *within tolerance* for a 4 × 2 tray
# while never looking at a single pocket in it.

#: (rows, columns). 1 × 1 is the only grid with no divider at all; the last two are each
#: other's transpose on purpose, because the wall counts are `columns + 1` and
#: `rows + 1` and a swapped axis would otherwise measure the same either way.
SWEEP_GRIDS: tuple[tuple[int, int], ...] = ((1, 1), (1, 3), (2, 3), (3, 3), (4, 2))
#: (width, depth, height) per pocket. The last is not square, so a swapped W and D shows.
SWEEP_POCKETS: tuple[tuple[float, float, float], ...] = (
    (12.0, 12.0, 10.0), (16.0, 16.0, 14.0), (20.0, 20.0, 15.0), (30.0, 45.0, 20.0),
)
#: `None` states no wall and takes this module's own default (1,6 mm), which is what
#: almost every real spec compiles with; 1,2 mm is the nozzle floor at 0,4 mm and the
#: bottom of the audited insert band; 2,4 mm is the deck box's, swept so the tray's
#: default cannot quietly become it.
SWEEP_WALLS: tuple[float | None, ...] = (None, 1.2, 1.6, 2.4)
SWEEP_FLOORS: tuple[float, ...] = (1.2, 2.0)
#: The corner set that goes on through Phase 3's assert path: three grids against three
#: walls, on the example pocket and a 2 mm floor — every one a point of the product
#: above, so the corners are a subset of the envelope.
SWEEP_PHASE_3_GRIDS: tuple[tuple[int, int], ...] = ((1, 1), (2, 3), (4, 2))
SWEEP_PHASE_3_WALLS: tuple[float | None, ...] = (None, 1.2, 2.4)


def envelope() -> tuple[SweepCase, ...]:
    """Every spec the dimensional sweep drives this archetype over — 160 of them."""
    cases: list[SweepCase] = []
    for (rows, columns), pocket, wall, floor in itertools.product(
        SWEEP_GRIDS, SWEEP_POCKETS, SWEEP_WALLS, SWEEP_FLOORS,
    ):
        cases.append(SweepCase(
            id=(f"{rows}x{columns}-p{pocket[0]:g}x{pocket[1]:g}x{pocket[2]:g}"
                f"-wall{'default' if wall is None else f'{wall:g}'}-floor{floor:g}"),
            spec=OrganizerSpec(
                archetype=ARCHETYPE,
                compartments=tuple(
                    Compartment(Pocket(width_mm=pocket[0], depth_mm=pocket[1],
                                       height_mm=pocket[2]))
                    for _ in range(rows * columns)
                ),
                tray=Tray(columns=columns),
                process=Process(wall_mm=wall, floor_mm=floor),
            ),
            phase_3=(
                (rows, columns) in SWEEP_PHASE_3_GRIDS
                and wall in SWEEP_PHASE_3_WALLS
                and pocket == EXAMPLE_POCKET_MM
                and floor == 2.0
            ),
        ))
    return tuple(cases)
