"""Box insert, version 1: one enclosure, several differently shaped fitted regions.

The fourth archetype, and the first where PRD §1's composition claim is true of the
code. A deck box holds one deck, a divider labels one group, a token tray lays out a
*regular* grid of one pocket repeated; this holds a card well, a token pocket and a dice
well in one body, each its own size and each its own depth, and compiles them to fit the
interior of a publisher's box.

**One archetype with a heterogeneous compartment list, not a container that nests the
existing ones.** A nested spec would change the *shape* of `compartments` — a schema
change rather than a new optional section, so every stored `spec_hash` would move — and
every archetype it could nest carries a section an insert has to refuse anyway (`lid`,
`divider`, `tray`). What an insert borrows from them is already shared: `resolve_stack`,
`rounded_rect_prism` and `base_chamfer`, `external_overshoots`, `stray_section_problem`,
`SweepCase`. What is genuinely new is *layout*, which no module had.

One body, printed open side up, flat on Z = 0, no overhangs anywhere. With `rows` from
`insert.rows`, `w` from `process.wall_mm`, `f` from `process.floor_mm`, and each
compartment's own footprint `(cw, cd)` and well depth `ch`:

    row_depth[r] = max cd in row r        row_width[r] = Σ cw in row r + (n_r + 1)·w
    external_w   = max row_width[r]       external_d   = Σ row_depth + (rows + 1)·w
    external_h   = max ch + f             row_wall[r]  = w + (external_w − row_width[r])
                                                             / (n_r + 1)
    x[r][k] = (k + 1)·row_wall[r] + Σ earlier cw in the row
    y[r]    = (r + 1)·w + Σ earlier row_depth
    z_floor = external_h − ch                (per compartment: the floor rises)
    insert  = prism(external) − ⋃ prism(cw, cd, ch + 1) at (x, y, z_floor)

Four decisions are worth reading before changing anything here, because each was a
choice between two things that both work.

**Slack is shared equally across the X walls of a narrower row.** A row that comes out
shorter than the widest one has to make the difference up somewhere: it could go into one
thick end wall, or into every wall of that row equally. Equal is what this builds, and
the reason is what it costs — nothing. The shell stays rectangular, no millimetre
anybody typed changes, and `row{r}_wall_mm` is one measurable number per row rather than
a wall that is 1,6 mm here and 6,4 mm there. What it does mean is that `process.wall_mm`
is the *minimum* wall rather than the exact one on those rows, and `to_view` says so on
the row it appears on.

**Per-compartment depth is the floor rising, not the rim falling.** Every well is cut
from its own `z_floor` through the top, so the part is one body with several floor planes
and one rim. That is the feature `token_tray` deferred — and it is why the measurement
below is regional: a shallow well puts a Z plane where nothing else has one, and a global
plane read cannot tell it from an artefact.

**A card stack lies flat.** Footprint `(fw + cc) × (fh + cc)` from `resolve_stack` and
`process.cavity_clearance_mm`, well depth `n·pitch + process.stack_slack_mm`. A sleeved
card stands 92 mm tall and the box interiors this fills run 70–75 mm
(`docs/dimension-kb-research.md` §7 — Wingspan at 72 mm), so on edge is the deck box's
orientation and not an insert's. Flat is a v1 decision rather than a permanent one; if an
orientation flag is ever wanted it goes on the `insert` section, **never** on `CardStack`,
where a field would move every stored hash.

**The interior is a limit, not a target.** `constraints.max_external_mm` is documented as
a box interior somebody measured and `effective_max_external_mm()` takes
`constraints.fit_margin_mm` off every axis of it — written for exactly this case, and
needing no change. So the externals here are derived from the *contents* and compared
against the interior; they are never stretched to fill it. An overshoot is a verdict
naming the axis, as the tray's is, because every millimetre in an insert was typed or
resolved from a sourced table. The **undershoot** is printed too, which is new: an insert
3 mm narrower than the box rattles, which slides the compartments under the lid and tips
them out. Filling to the interior, and the locking tabs that are the other answer to it,
are not built.

**What this does not build**, stated so a preview never implies it: filling to the
interior; cards on edge; rounded well corners (`process.cavity_corner_radius_mm` is read
by nobody here and `to_view` says so); finger scoops; a compartment that spans two rows;
stacking; presets of any kind — `dimensions.py` sources no token or dice size, so every
pocket is typed millimetres and `Pocket.source` carries whatever provenance the person
had.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any, Optional

import manifold3d

from ..compiler import (
    CompileResult,
    FitsResult,
    MeasureError,
    face_planes,
    face_planes_within,
    manifold_to_trimesh,
    rounded_rect_prism,
)
from ..dimensions import ResolvedStack, resolve_stack
from ..spec import (
    CardStack,
    Compartment,
    Insert,
    OrganizerSpec,
    Pocket,
    Process,
    SpecError,
    spec_hash,
)
from .common import (
    CALLOUT_TIER_EXTERNAL,
    SweepCase,
    callout,
    external_overshoots,
    external_undershoots,
    measured_chamfer,
    measured_corner_radius,
    stray_section_problem,
    view_frame,
    view_row,
)

ARCHETYPE = "box_insert"
#: Bumped when the geometry a given spec produces changes. Recorded on every job.
ARCHETYPE_VERSION = "1"
#: Every wall and every divider is `process.wall_mm` here, so `compile_spec` holds it to
#: the nozzle-derived floor. `spec.ARCHETYPE_WALL_MM["box_insert"]` is what it defaults
#: to: 1,6 mm, the token tray's figure for the token tray's reason verbatim.
USES_PROCESS_WALL_MM = True
#: `archetypes.measure_spec_mesh` passes the spec to `measure()` for this module.
#:
#: The first archetype that needs it, and it needs it for the same reason it needed
#: `measured_features(spec)`: a ragged layout's features are not readable off a global
#: plane count, so the *design* has to supply the region each compartment is measured in.
#: Additive, like `measured_features` — the other three modules keep `measure(mesh)` and
#: took no change — and the dispatch is the only place that knows the difference, so
#: `verify_spec_mesh`, the CLI and Phase 3's assert path are all unchanged.
MEASURE_NEEDS_SPEC = True
#: How this archetype names itself in a refusal or a measurement finding.
_SUBJECT = f"a box insert v{ARCHETYPE_VERSION}"

#: How much of the thinnest wall, floor or well depth a measurement region reaches past
#: the well it is measuring, on every axis.
#:
#: It has to be **under 1**, or the region would swallow a neighbouring compartment's wall
#: and report a plane count the design does not have. It has to be comfortably over the
#: ±0,05 mm dimensional claim, or a wall displaced by less than the claim allows would
#: fall outside its own region and be reported as *missing* rather than as *out of
#: tolerance* — a true finding, but the wrong one, and one that hides how far it moved.
#: 0,4 of the thinnest feature satisfies both by an order of magnitude at every spec this
#: archetype accepts: `process.min_feature_mm` is 1,0 mm by default, so the region reaches
#: at least 0,4 mm and at most 0,4 of a wall.
MEASURE_MARGIN_FRACTION = 0.4


@dataclass(frozen=True)
class Well:
    """One compartment, resolved: where its hole is and how big, in mm from the shell's
    own minimum corner.

    `stack` is the resolved card stack for a `CardStack` compartment and None for a
    `Pocket` — the one thing a well remembers about which shape it came from, because a
    card well's millimetres have a *source* and a pocket's were typed. Nothing in the
    geometry depends on it.
    """

    index: int
    row: int
    #: Position within its row, left to right from the minimum X.
    column: int
    width: float
    depth: float
    height: float
    x: float
    y: float
    #: Z of this well's own floor: `external_h − height`. The deepest well's is
    #: `process.floor_mm`; every shallower one sits on a floor that has risen.
    z_floor: float
    stack: Optional[ResolvedStack] = None
    #: `Pocket.source` for a typed compartment; None for a card well, whose provenance
    #: is the resolved stack's own `basis`.
    source: Optional[str] = None

    @property
    def key(self) -> str:
        """How this compartment names itself in a feature, e.g. `c2`."""
        return f"c{self.index}"


@dataclass(frozen=True)
class InsertDimensions:
    """Every derived dimension, in mm, from one spec. Pure arithmetic — no kernel."""

    rows: tuple[int, ...]
    wells: tuple[Well, ...]
    #: One internal depth per row, front to back: the deepest compartment in it.
    row_depths: tuple[float, ...]
    #: The X wall thickness inside one row — `process.wall_mm` plus that row's share of
    #: the slack between its own width and the widest row's.
    row_walls: tuple[float, ...]
    #: Minimum Y of each row band.
    row_y: tuple[float, ...]
    wall: float
    floor: float
    external_w: float
    external_d: float
    external_h: float
    base_chamfer: float
    corner_radius: float

    def wells_in(self, row: int) -> tuple[Well, ...]:
        return tuple(w for w in self.wells if w.row == row)

    def features(self, spec: OrganizerSpec) -> dict[str, float]:
        """The designed features by name. `measure()` reads the same names back.

        All but one of them: a card well's `c{i}_stack_height_mm` is designed and is not
        on the mesh — a stack of cards is not geometry — so it is the one figure here
        that `measured_features` leaves out, exactly as `deck_box`'s `stack_height_mm` is.
        """
        raw: dict[str, float] = {
            "external_width_mm": self.external_w,
            "external_depth_mm": self.external_d,
            "external_height_mm": self.external_h,
            "wall_mm": self.wall,
            "floor_mm": self.floor,
            "base_chamfer_mm": self.base_chamfer,
            "corner_radius_mm": self.corner_radius,
        }
        for well in self.wells:
            raw[f"{well.key}_width_mm"] = well.width
            raw[f"{well.key}_depth_mm"] = well.depth
            raw[f"{well.key}_height_mm"] = well.height
            raw[f"{well.key}_x_mm"] = well.x
            raw[f"{well.key}_y_mm"] = well.y
            if well.stack is not None:
                raw[f"{well.key}_stack_height_mm"] = well.stack.stack_height_mm
        for r, row_wall in enumerate(self.row_walls):
            raw[f"row{r}_wall_mm"] = row_wall
        for j in range(len(self.rows) + 1):
            raw[f"wall_y{j}_mm"] = self.wall
        return {k: round(float(v), 3) for k, v in raw.items()}


def _footprint(
    contents: "CardStack | Pocket", p: Process
) -> tuple[float, float, float, Optional[ResolvedStack], Optional[str]]:
    """`(width, depth, well depth, resolved stack, source)` for one compartment.

    The whole of what the two content shapes have in common, and the one place the union
    is turned into millimetres. A pocket *is* its millimetres and carries whatever
    provenance the person typed; a card stack becomes them through `resolve_stack` and the
    process clearances, lying flat — see the module docstring for why flat.
    """
    if isinstance(contents, Pocket):
        return contents.width_mm, contents.depth_mm, contents.height_mm, None, contents.source
    stack = resolve_stack(contents.count, contents.card, contents.sleeving)
    return (
        stack.footprint_w_mm + p.cavity_clearance_mm,
        stack.footprint_h_mm + p.cavity_clearance_mm,
        stack.stack_height_mm + p.stack_slack_mm,
        stack,
        None,
    )


def _structural_problems(spec: OrganizerSpec) -> list[str]:
    """Everything that must hold before `derive` can do arithmetic at all."""
    problems: list[str] = []
    if spec.archetype != ARCHETYPE:
        problems.append(f"archetype {spec.archetype!r} is not {ARCHETYPE!r}")
    for section, owner in (("lid", "deck_box"), ("divider", "card_divider"),
                           ("tray", "token_tray")):
        stray = stray_section_problem(
            spec, section=section, subject=f"box_insert v{ARCHETYPE_VERSION}", owner=owner
        )
        if stray:
            problems.append(stray)
    if spec.insert is None:
        problems.append(
            f"box_insert v{ARCHETYPE_VERSION} needs an insert section (insert is null); "
            "it carries insert.rows, which is how many compartments each row holds"
        )
    elif sum(spec.insert.rows) != len(spec.compartments):
        problems.append(
            f"insert.rows {list(spec.insert.rows)} accounts for {sum(spec.insert.rows)} "
            f"compartments and the spec has {len(spec.compartments)}; every compartment "
            "is in exactly one row — change the row counts, or add or remove "
            "compartments"
        )
    return problems


def derive(spec: OrganizerSpec) -> InsertDimensions:
    """Every dimension the geometry is built from.

    Assumes `_structural_problems` is empty, so the row counts sum to the compartment
    count and the compartments can simply be dealt out along them in order.

    A pure function of the contents, the wall and the row grouping — which is the point,
    and not only tidiness: the same derivation is what a stackable enclosure (the same
    compiler with the constraint inverted) would reuse.
    """
    insert: Insert = spec.insert  # type: ignore[assignment]
    p: Process = spec.process
    wall = p.wall_mm
    assert wall is not None  # OrganizerSpec resolves it to the archetype's default

    def r(x: float) -> float:  # every value to 1 µm, like the schema
        return round(float(x), 3)

    # Pass one: the contents, in rows, as millimetres.
    grouped: list[list[tuple]] = []
    index = 0
    for count in insert.rows:
        row: list[tuple] = []
        for _ in range(count):
            cw, cd, ch, stack, source = _footprint(spec.compartments[index].contents, p)
            row.append((index, r(cw), r(cd), r(ch), stack, source))
            index += 1
        grouped.append(row)

    row_depths = tuple(r(max(item[2] for item in row)) for row in grouped)
    row_widths = [
        r(sum(item[1] for item in row) + (len(row) + 1) * wall) for row in grouped
    ]
    external_w = r(max(row_widths))
    external_d = r(sum(row_depths) + (len(grouped) + 1) * wall)
    external_h = r(max(item[3] for row in grouped for item in row) + p.floor_mm)
    # The slack a narrower row makes up, shared equally over that row's `n + 1` X walls.
    # Never below `wall`: the widest row has no slack and gets exactly it.
    row_walls = tuple(
        r(wall + (external_w - width) / (len(row) + 1))
        for row, width in zip(grouped, row_widths, strict=True)
    )
    row_y = []
    y = wall
    for depth in row_depths:
        row_y.append(r(y))
        y = y + depth + wall

    wells: list[Well] = []
    for row_index, row in enumerate(grouped):
        x = row_walls[row_index]
        for column, (i, cw, cd, ch, stack, source) in enumerate(row):
            wells.append(Well(
                index=i, row=row_index, column=column,
                width=cw, depth=cd, height=ch,
                x=r(x), y=row_y[row_index], z_floor=r(external_h - ch),
                stack=stack, source=source,
            ))
            x = x + cw + row_walls[row_index]

    return InsertDimensions(
        rows=tuple(insert.rows), wells=tuple(wells),
        row_depths=row_depths, row_walls=row_walls, row_y=tuple(row_y),
        wall=r(wall), floor=r(p.floor_mm),
        external_w=external_w, external_d=external_d, external_h=external_h,
        base_chamfer=r(p.base_chamfer_mm), corner_radius=r(p.corner_radius_mm),
    )


def validate(spec: OrganizerSpec) -> None:
    """Refuse a spec this archetype cannot honour, naming every problem and its remedy.

    Raises:
        SpecError: With every archetype-level problem.
    """
    problems = _structural_problems(spec)
    if problems:
        raise SpecError(problems)
    d = derive(spec)
    p = spec.process
    min_feature = p.min_feature_mm
    for well in d.wells:
        for name, value in (
            ("width_mm", well.width), ("depth_mm", well.depth), ("height_mm", well.height),
        ):
            if value < min_feature:
                problems.append(
                    f"compartments[{well.index}] is {value:g} mm on {name}, below "
                    f"process.min_feature_mm {min_feature:g}; widen the compartment or "
                    "lower the minimum"
                )
    if d.wall < min_feature:
        problems.append(
            f"process.wall_mm {d.wall:g} mm is below process.min_feature_mm "
            f"{min_feature:g}; every wall and every divider is this thick — thicken the "
            "wall or lower the minimum"
        )
    if d.floor < min_feature:
        problems.append(
            f"process.floor_mm {d.floor:g} mm is below process.min_feature_mm "
            f"{min_feature:g}; it is the floor under the deepest compartment — thicken "
            "the floor or lower the minimum"
        )
    # The deck box's two edge rules, restated for a part with no lid. A round larger
    # than the wall it is cut from thins that wall at the corner to a figure the spec
    # does not claim; a chamfer at or above the floor cuts into the compartment above it.
    if d.corner_radius > d.wall + 1e-9:
        problems.append(
            f"process.corner_radius_mm {d.corner_radius:g} mm is larger than "
            f"process.wall_mm {d.wall:g} mm, which would thin the wall to "
            f"{d.corner_radius - (d.corner_radius - d.wall) * math.sqrt(2.0):.3f} mm at "
            "each corner. Reduce the radius to the wall or thicken the wall"
        )
    if d.base_chamfer >= d.floor - 1e-9:
        problems.append(
            f"process.base_chamfer_mm {d.base_chamfer:g} mm must be less than "
            f"process.floor_mm {d.floor:g} mm, or the chamfer cuts into the compartment "
            "above it. Reduce the chamfer or thicken the floor"
        )
    if problems:
        raise SpecError(problems)


def build(spec: OrganizerSpec) -> tuple[dict[str, "manifold3d.Manifold"], InsertDimensions]:
    """Validate, derive, and build the one solid in plate position."""
    validate(spec)
    d = derive(spec)
    # The **outer prism carries the chamfer** and the wells are cut into it afterwards.
    # Not stylistic: `compiler.base_chamfer` has the measurement — a chamfer cut into a
    # finished solid leaves degenerate triangles along the seam that open the mesh once
    # it is exported as float32.
    body = rounded_rect_prism(
        d.external_w, d.external_d, d.external_h, d.corner_radius,
        chamfer_mm=d.base_chamfer,
    )
    for well in d.wells:
        # +1 mm through the top, so a well's own top face is never a plane of its own —
        # an insert is open, and a coincident face is a kernel coin flip. Square-cornered:
        # `process.cavity_corner_radius_mm` is read by nobody here, and `to_view` says so.
        body = body - rounded_rect_prism(
            well.width, well.depth, well.height + 1.0
        ).translate([well.x, well.y, well.z_floor])
    return {"insert": body}, d


def compile(spec: OrganizerSpec) -> CompileResult:  # noqa: A001 — the registry's verb
    """Spec → insert mesh, parts, designed features."""
    solids, d = build(spec)
    parts = {name: manifold_to_trimesh(solid) for name, solid in solids.items()}
    return CompileResult(
        archetype=ARCHETYPE,
        archetype_version=ARCHETYPE_VERSION,
        spec_hash=spec_hash(spec),
        mesh=parts["insert"],
        parts=parts,
        features=d.features(spec),
    )


#: The pockets the example is built from, in mm, and the sentence that says so.
#:
#: Both are **design examples, not sourced sizes**, for `token_tray.EXAMPLE_SOURCE`'s
#: reason verbatim: `docs/dimension-kb-research.md` §4 sources die *sizes* without
#: sourcing the clearance a die needs around it, and nothing sources a punchboard token
#: footprint at all. Saying so on the spec itself is what `Pocket.source` is for.
EXAMPLE_TOKEN_MM: tuple[float, float, float] = (40.0, 40.0, 15.0)
EXAMPLE_DICE_MM: tuple[float, float, float] = (20.0, 20.0, 18.0)
EXAMPLE_SOURCE = (
    "design example, not a sourced size — no punchboard token footprint or die "
    "clearance is sourced in docs/dimension-kb-research.md §4"
)
#: The card well: a 60-card double-sleeved deck, resolved against the dimension table.
EXAMPLE_CARD_COUNT = 60


def example() -> OrganizerSpec:
    """The acceptance spec: three differently shaped compartments in two rows.

    A 60-card double-sleeved well across the front, and a 40 × 40 × 15 mm token pocket
    beside a 20 × 20 × 18 mm dice well behind it. 71,7 × 138,3 × 45,0 mm external at the
    defaults — the card well is 68,5 × 93,5 mm and 43,0 mm deep, and the back row is
    6,9 mm narrower than the front, so its three X walls carry 2,3 mm of slack each and
    come out at 3,9 mm where the front row's are 1,6 mm. Three different footprints,
    three different depths, one body.
    """
    token = Pocket(*EXAMPLE_TOKEN_MM, source=EXAMPLE_SOURCE)
    dice = Pocket(*EXAMPLE_DICE_MM, source=EXAMPLE_SOURCE)
    return OrganizerSpec(
        archetype=ARCHETYPE,
        compartments=(
            Compartment(CardStack(count=EXAMPLE_CARD_COUNT, sleeving="double")),
            Compartment(token),
            Compartment(dice),
        ),
        insert=Insert(rows=(1, 2)),
    )


#: The features `measure()` reads off *any* insert, whatever its layout.
#:
#: The rest — five per compartment, one wall per row, one per row boundary — depend on
#: the spec and come from `measured_features(spec)` below, which
#: `archetypes.required_measurements` prefers when a module offers it. This tuple stays
#: because the registry API declares it and because these seven are the names that do not
#: move: a module with no fixed features would have nothing to check an example against.
MEASURED_FEATURES: tuple[str, ...] = (
    "external_width_mm", "external_depth_mm", "external_height_mm",
    "wall_mm", "floor_mm", "base_chamfer_mm", "corner_radius_mm",
)


def measured_features(spec: OrganizerSpec) -> tuple[str, ...]:
    """Every feature `measure()` reads back for *this* spec's compartment list.

    It grows with the list, which is the acceptance criterion this archetype was written
    for: five figures per compartment — three sizes and **two positions** — plus one wall
    per row and one per row boundary. A fixed tuple could only promise the seven above,
    and a report that checked those would say *within tolerance* about a part whose every
    compartment might be the wrong size in the wrong place.

    The positions are features because in a ragged layout nothing else catches a
    right-sized well built in the wrong place: a regular grid's plane count moves when a
    divider does, and a ragged one's does not.
    """
    d = derive(spec)
    designed = d.features(spec)
    # Everything designed except the stack heights, which are not on the mesh.
    return tuple(k for k in designed if not k.endswith("_stack_height_mm"))


def _measure_margin(d: InsertDimensions) -> float:
    """How far a compartment's measurement region reaches past it, mm.

    A fraction of the thinnest feature in the part, so the region cannot reach a
    neighbour's wall on any axis: the X walls are at least `wall`, the Y walls are
    exactly `wall`, the bed is `floor` below the deepest well's own floor, and a well's
    walls have to keep faces inside the region's Z span. See `MEASURE_MARGIN_FRACTION`.
    """
    thinnest = min([d.wall, d.floor] + [w.height for w in d.wells])
    return MEASURE_MARGIN_FRACTION * thinnest


def _region(well: Well, d: InsertDimensions, margin: float):
    """The box one compartment is measured inside, as `face_planes_within` wants it.

    The design says where to look and the mesh says what is there — the whole of what
    makes this a measurement rather than a restatement. The Z span stops `margin` *below*
    the rim on purpose: the rim is the shell's top face and overhangs into every
    compartment's region, and a read that sometimes caught it and sometimes did not would
    make the plane count depend on how the kernel happened to triangulate an annulus.
    """
    return (
        (well.x - margin, well.x + well.width + margin),
        (well.y - margin, well.y + well.depth + margin),
        (well.z_floor - margin, d.external_h - margin),
    )


def _planes_in(part: Any, axis: int, region, expected: int, well: Well) -> list[float]:
    """The planes of one compartment's region on one axis, or the finding.

    Named per compartment rather than per part: on a ragged layout "the insert has 14 X
    planes where it should have 12" identifies nothing a person can go and look at, and
    "compartment 2's region has 1 X plane where a well has 2" identifies the well.
    """
    planes = face_planes_within(part, axis, region)
    if len(planes) != expected:
        raise MeasureError(
            f"compartment {well.index} has {len(planes)} distinct {'XYZ'[axis]} planes "
            f"in its own region where {_SUBJECT} has {expected}: found "
            f"{[round(v, 3) for v in planes]} in "
            f"{[[round(v, 3) for v in span] for span in region]}"
        )
    return planes


def measure(mesh: Any, spec: OrganizerSpec) -> dict[str, float]:
    """Read the designed features back off an insert mesh — compiled or post-Phase-3.

    **Region by region, not plane count by plane count.** One body; the shell's own six
    outer planes are the first and last on each axis, and everything else is read inside
    the box the design says one compartment occupies. That is forced by the shape rather
    than chosen: `token_tray` is a regular grid precisely so that `2n + 2` planes per axis
    *are* its layout, and it says in as many words that a ragged one "would put a Y plane
    at the top of one pocket and nowhere else", which a global read cannot tell from an
    artefact. `card_divider.measure` already reads X per region for its tab; this is that,
    generalised.

    Each compartment therefore contributes five numbers read off two X planes, two Y
    planes and one Z plane found inside its own region, and the region is wrong-sized
    rather than absent when the geometry has moved — see `MEASURE_MARGIN_FRACTION`. The
    walls are then differences between one region and the next, which is what catches a
    divider in the wrong place with every external dimension still exactly right.

    Two designed floors closer together than the plane clusterer's 1 µm would merge if Z
    were read globally. They cannot here, because each is read inside its own compartment;
    recorded because it is the failure the regional read removes rather than one it fixes.

    Args:
        mesh: The mesh to measure.
        spec: The spec it was compiled from — the source of the regions.
            `archetypes.measure_spec_mesh` passes it because `MEASURE_NEEDS_SPEC` is set.

    Raises:
        MeasureError: If the mesh is not one body, or a compartment's region does not
            hold the planes a well has.
    """
    parts = mesh.split(only_watertight=False)
    if len(parts) != 1:
        raise MeasureError(f"expected 1 body (the insert), found {len(parts)}")
    part = parts[0]
    d = derive(spec)
    x, y, z = (face_planes(part, axis) for axis in range(3))
    if min(len(x), len(y), len(z)) < 2:
        raise MeasureError(
            f"the insert has {len(x)}/{len(y)}/{len(z)} distinct X/Y/Z planes; "
            f"{_SUBJECT} has at least two on every axis (its own outside)"
        )
    margin = _measure_margin(d)

    measured: dict[str, float] = {
        "external_width_mm": x[-1] - x[0],
        "external_depth_mm": y[-1] - y[0],
        "external_height_mm": z[-1] - z[0],
        "base_chamfer_mm": measured_chamfer(part, what="insert", subject=_SUBJECT),
        "corner_radius_mm": measured_corner_radius(part, y[0], x[0]),
    }
    # Per compartment: two X planes, two Y planes and one Z plane, all inside its own
    # region. The rim is the shared reference for every depth — it is the one Z plane an
    # insert has in common — so a well's depth is the rim less its own floor.
    floors: list[float] = []
    starts: dict[int, list[float]] = {}
    ends: dict[int, list[float]] = {}
    lefts: dict[int, list[float]] = {}
    for well in d.wells:
        region = _region(well, d, margin)
        wx = _planes_in(part, 0, region, 2, well)
        wy = _planes_in(part, 1, region, 2, well)
        wz = _planes_in(part, 2, region, 1, well)
        measured[f"{well.key}_width_mm"] = wx[1] - wx[0]
        measured[f"{well.key}_depth_mm"] = wy[1] - wy[0]
        measured[f"{well.key}_height_mm"] = z[-1] - wz[0]
        measured[f"{well.key}_x_mm"] = wx[0] - x[0]
        measured[f"{well.key}_y_mm"] = wy[0] - y[0]
        floors.append(wz[0])
        starts.setdefault(well.row, []).append(wy[0])
        ends.setdefault(well.row, []).append(wy[1])
        lefts.setdefault(well.row, []).append(wx[0])
    # The floor is the one under the **deepest** compartment, which is the lowest of them
    # and the only one `process.floor_mm` names; every other is that floor plus the depth
    # the compartment above it gave up.
    measured["floor_mm"] = min(floors) - z[0]
    # One X wall per row: the outer one, whose thickness is that row's share of the slack.
    # The inner ones are pinned by the positions and widths above, so measuring them
    # again would be the same planes subtracted twice.
    for r in range(len(d.rows)):
        measured[f"row{r}_wall_mm"] = min(lefts[r]) - x[0]
    # One Y wall per row boundary, each read between the two row bands it separates —
    # the deepest well in the row in front and the front face of the row behind.
    row_count = len(d.rows)
    measured["wall_y0_mm"] = min(starts[0]) - y[0]
    for r in range(1, row_count):
        measured[f"wall_y{r}_mm"] = min(starts[r]) - max(ends[r - 1])
    measured[f"wall_y{row_count}_mm"] = y[-1] - max(ends[row_count - 1])
    # `wall_mm` is the front outer wall, reported under its own name as well as under
    # `wall_y0_mm`: it is the number the spec states, and a reader looking for "did it
    # build the wall I asked for" should not have to know the boundary numbering.
    measured["wall_mm"] = measured["wall_y0_mm"]
    return {k: float(v) for k, v in measured.items()}


def fits_check(spec: OrganizerSpec) -> FitsResult:
    """The millimetre arithmetic, and whether the result fits the box it is made for.

    Three things the other archetypes' fits lines do not do, each because an insert is
    the one part here whose *purpose* is another object's interior.

    **It reports the undershoot.** Every archetype refuses an overshoot; this one also
    says how much room is left, because an insert that rattles slides under the lid and
    tips its contents out, and "3,2 mm short of the box on width" is the only warning a
    person gets before printing eight hours of it. It is not a failure — the part fits —
    so it rides on the line rather than in a remedy.

    **The overshoot is a verdict, not a refusal**, which is `token_tray.fits_check`'s
    rule and holds here for the same reason with one addition: a card well's clearance is
    `process.cavity_clearance_mm`, which `process.fit_intent` may have chosen, so an
    `easy` insert that busts a limit is refused by nobody but is named as such — the
    deck box refuses that case because a closure has a right answer and an insert does not.

    **The basis names both provenances.** A card well resolves against a sourced table
    and a pocket does not, and a sentence that implied one source for both would be the
    fabrication this whole engine exists to refuse.
    """
    validate(spec)
    d = derive(spec)
    stacks = [w.stack for w in d.wells if w.stack is not None]
    typed = [w for w in d.wells if w.stack is None]
    sources = {w.source for w in typed if w.source}
    parts: list[str] = []
    if stacks:
        parts.append("; ".join(dict.fromkeys(s.basis for s in stacks)))
    if typed:
        parts.append(
            "user-given millimetres for the pockets"
            + ("; " + "; ".join(sorted(sources)) if sources else
               " — no token or dice size is sourced in the dimension KB")
        )
    basis = " · ".join(parts)
    shapes = ", ".join(
        f"{w.width:g} × {w.depth:g} × {w.height:g} mm"
        + (f" ({w.stack.count} cards, flat)" if w.stack is not None else "")
        for w in d.wells
    )
    line = (
        f"{len(d.wells)} compartments in {len(d.rows)} rows "
        f"({'/'.join(str(n) for n in d.rows)}) · {shapes} internal · "
        f"{d.wall:g} mm walls · {d.floor:g} mm floor under the deepest · "
        f"external {d.external_w:g} × {d.external_d:g} × {d.external_h:g} mm"
    )
    extents = (d.external_w, d.external_d, d.external_h)
    fits = True
    remedy = None
    over = external_overshoots(spec, extents, prefix="external ")
    if over:
        fits = False
        intent = (
            f" process.fit_intent {spec.process.fit_intent!r} puts "
            f"{spec.process.cavity_clearance_mm:g} mm of clearance around every card well."
            if stacks else ""
        )
        remedy = (
            "; ".join(o.note for o in over) + "." + intent
            + " Shrink a compartment, move one to another row, thin the wall, or relax "
            "the constraint."
        )
    else:
        short = external_undershoots(spec, extents)
        if short:
            line += " · " + ", ".join(s.note for s in short) + (
                " — an insert that rattles slides under the lid; nothing here fills the "
                "gap for you"
            )
    return FitsResult(fits=fits, line=line, basis=basis, remedy=remedy)


#: The five figures the phone step of the viewer shows: the first compartment's three
#: internal millimetres and the two that say where it is. Declared here so
#: `tests/test_view_callouts.py` asserts the set rather than counting rows.
TIER_1_FEATURES: tuple[str, ...] = (
    "c0_width_mm", "c0_depth_mm", "c0_height_mm", "c0_x_mm", "c0_y_mm",
)


def callouts(spec: OrganizerSpec) -> list[dict[str, Any]]:
    """The dimension lines the viewer draws on an insert, in the plate frame.

    **The first compartment only**, for `token_tray.callouts`' reason and one of this
    archetype's own. The reason it shares: a part with six compartments would carry thirty
    lines over 140 mm, which is a picture nobody can read and therefore worse than no
    picture, and the view's own table is where a person reads the whole list. The reason
    it does not: an insert's compartments are *not* copies of each other on any axis, so
    the first one is genuinely only itself — which is why the two **position** lines are
    tier 1 here where a tray has no position lines at all. Annotating every compartment is
    its own issue if anyone wants it.
    """
    d = derive(spec)
    first = d.wells[0]
    W, D, H = d.external_w, d.external_d, d.external_h
    x0, y0, cw, cd = first.x, first.y, first.width, first.depth
    up, front, left = (0.0, 0.0, 1.0), (0.0, -1.0, 0.0), (-1.0, 0.0, 0.0)
    inward = (0.0, 1.0, 0.0)
    return [
        # ── tier 1: what the contents have to fit into, and where it is ───────
        callout("c0_width_mm", "Compartment 1 width", cw, part="insert",
                frm=(x0, y0 + cd / 2.0, H), to=(x0 + cw, y0 + cd / 2.0, H), offset=up),
        callout("c0_depth_mm", "Compartment 1 depth", cd, part="insert",
                frm=(x0 + cw / 2.0, y0, H), to=(x0 + cw / 2.0, y0 + cd, H), offset=up),
        callout("c0_height_mm", "Compartment 1 depth (Z)", first.height, part="insert",
                frm=(x0 + cw / 2.0, y0, first.z_floor), to=(x0 + cw / 2.0, y0, H),
                offset=inward),
        callout("c0_x_mm", "Compartment 1 from the left", x0, part="insert",
                frm=(0.0, y0 + cd / 2.0, H), to=(x0, y0 + cd / 2.0, H), offset=up),
        callout("c0_y_mm", "Compartment 1 from the front", y0, part="insert",
                frm=(x0 + cw / 2.0, 0.0, H), to=(x0 + cw / 2.0, y0, H), offset=up),
        # ── tier 2: the outside, and what it is made of ───────────────────────
        callout("external_width_mm", "External width", W, part="insert",
                frm=(0.0, 0.0, 0.0), to=(W, 0.0, 0.0), offset=front,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("external_depth_mm", "External depth", D, part="insert",
                frm=(0.0, 0.0, 0.0), to=(0.0, D, 0.0), offset=left,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("external_height_mm", "External height", H, part="insert",
                frm=(0.0, D / 2.0, 0.0), to=(0.0, D / 2.0, H), offset=left,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("wall_mm", "Wall", d.wall, part="insert",
                frm=(x0 + cw / 2.0, 0.0, H), to=(x0 + cw / 2.0, d.wall, H), offset=up,
                tier=CALLOUT_TIER_EXTERNAL),
        callout("floor_mm", "Floor", d.floor, part="insert",
                frm=(0.0, D / 2.0, 0.0), to=(0.0, D / 2.0, d.floor), offset=left,
                tier=CALLOUT_TIER_EXTERNAL),
    ]


def to_view(spec: OrganizerSpec, result: CompileResult) -> dict[str, Any]:
    """The spec as `web/src/organizer/spec.ts` declares it: labelled millimetres, a fits
    verdict, the hash the gate binds to, and the annotated preview's `frame` and
    `callouts`.

    One row per compartment per axis, each saying where its millimetres came from: a card
    well names the sourced envelope and the clearance added to it, a pocket names
    `Pocket.source` when the person gave one and says the figure was typed when they did
    not. Neither is presented as sourced unless it is.
    """
    d = derive(spec)
    p = spec.process
    row = view_row
    dimensions = [
        row("compartments", "Compartments", len(d.wells), "compartments", False,
            "one per entry in insert.rows, in order"),
        row("rows", "Rows", len(d.rows), "rows", True,
            "insert.rows — " + "/".join(str(n) for n in d.rows) + " compartments per row"),
    ]
    for well in d.wells:
        label = f"Compartment {well.index + 1}"
        note = _provenance(well, p)
        dimensions += [
            row(f"{well.key}_width_mm", f"{label} width", well.width, "mm", True, note),
            row(f"{well.key}_depth_mm", f"{label} depth", well.depth, "mm", True, note),
            row(f"{well.key}_height_mm", f"{label} depth (Z)", well.height, "mm", True, note),
        ]
        if well.stack is not None:
            dimensions.append(row(
                f"{well.key}_stack_height_mm", f"{label} stack height",
                well.stack.stack_height_mm, "mm", False,
                f"{well.stack.count} × {well.stack.pitch_mm:g} mm, lying flat; "
                "the well is this deep plus the stack slack",
            ))
    dimensions += [
        row("wall_mm", "Wall", d.wall, "mm", True,
            "the minimum: a row narrower than the widest shares the difference equally "
            "over its own walls, so those come out thicker — see the row walls below"),
        row("floor_mm", "Floor", d.floor, "mm", True, "under the deepest compartment"),
    ]
    for r, row_wall in enumerate(d.row_walls):
        dimensions.append(row(
            f"row{r}_wall_mm", f"Row {r + 1} wall", row_wall, "mm", False,
            "process.wall_mm plus this row's share of the slack" if row_wall > d.wall
            else "this row is the widest, so it carries no slack",
        ))
    dimensions += [
        row("external_width_mm", "External width", d.external_w, "mm", False,
            "the widest row; the others are padded to it"),
        row("external_depth_mm", "External depth", d.external_d, "mm", False,
            f"{len(d.rows)} rows + {len(d.rows) + 1} walls"),
        row("external_height_mm", "External height", d.external_h, "mm", False,
            "the deepest compartment plus the floor; the insert is open"),
        row("base_chamfer_mm", "Base chamfer", p.base_chamfer_mm, "mm", True,
            "45°, against warping; design default, unsourced — three 0,2 mm layers"),
        row("corner_radius_mm", "Corner radius", p.corner_radius_mm, "mm", True,
            "external vertical corners, against elephant-foot flare; design default, "
            "unsourced"),
        row("min_feature_mm", "Minimum feature", p.min_feature_mm, "mm", True,
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
        # Stated rather than implied, the token tray's `note` precedent: the outside is
        # rounded and chamfered and every compartment is square-cornered, because
        # `process.cavity_corner_radius_mm` is read by nobody here and a preview that
        # drew a radius would show a part the compiler does not build.
        "note": (
            "square compartments — the shell is rounded and chamfered, the wells are not; "
            "cards lie flat and nothing fills the box for you"
        ),
    }


def _provenance(well: Well, p: Process) -> str:
    """What one compartment's rows say under their millimetres."""
    if well.stack is not None:
        return (
            f"{well.stack.basis}; + {p.cavity_clearance_mm:g} mm clearance across the "
            f"footprint and {p.stack_slack_mm:g} mm of stack slack on the depth"
        )
    return well.source or "user-given mm — no token or dice size is sourced"


# ── The dimensional envelope (issue #85) ──────────────────────────────────────
#
# See `common.SweepCase` for what an envelope is. Four axes, and the **layout** is the one
# this archetype contributes: it is the only parameter anywhere in the registry that
# changes both how many features there are to measure *and* where each one is, which is
# why `measure` reads regions and why the generic sweep's `set(report.features) ==
# set(required_measurements(spec))` is what keeps a ragged part honest.
#
# Every layout below is in the list for a named reason, and the reasons are what a person
# narrowing this has to argue with.

#: `(id, rows, contents)`. A content is `("pocket", w, d, h)` or `("card", count,
#: sleeving)`. The set spans: one compartment (no divider at all); differing widths,
#: depths *and* heights inside one row; rows of different widths in both orders, so the
#: slack lands in the front row in one case and the back row in the other; three rows; and
#: two mixtures of card wells with pockets, which is the composition the archetype exists
#: for and the only case where a resolved footprint and a typed one share a shell.
SWEEP_LAYOUTS: tuple[tuple[str, tuple[int, ...], tuple[tuple, ...]], ...] = (
    ("one", (1,), (("pocket", 20.0, 20.0, 15.0),)),
    ("two-ragged", (2,), (("pocket", 20.0, 20.0, 15.0), ("pocket", 30.0, 25.0, 10.0))),
    ("narrow-behind", (1, 2), (
        ("pocket", 60.0, 40.0, 20.0), ("pocket", 20.0, 20.0, 15.0),
        ("pocket", 25.0, 30.0, 18.0),
    )),
    ("narrow-in-front", (3, 1), (
        ("pocket", 15.0, 15.0, 10.0), ("pocket", 15.0, 15.0, 12.0),
        ("pocket", 15.0, 15.0, 14.0), ("pocket", 30.0, 20.0, 20.0),
    )),
    ("three-rows", (1, 1, 1), (
        ("pocket", 40.0, 30.0, 12.0), ("pocket", 20.0, 20.0, 25.0),
        ("pocket", 35.0, 15.0, 8.0),
    )),
    ("cards-and-pockets", (1, 2), (
        ("card", 60, "double"), ("pocket", 40.0, 40.0, 15.0), ("pocket", 20.0, 20.0, 18.0),
    )),
    ("two-decks", (2,), (("card", 40, "single"), ("card", 20, "none"))),
    ("deck-behind-pockets", (2, 1), (
        ("pocket", 25.0, 25.0, 30.0), ("pocket", 25.0, 25.0, 12.0),
        ("card", 100, "double"),
    )),
)
#: `None` states no wall and takes this module's own default (1,6 mm), which is what
#: almost every real spec compiles with; 1,2 mm is the nozzle floor at 0,4 mm and the
#: bottom of the audited insert band; 2,4 mm is the deck box's, swept so this archetype's
#: default cannot quietly become it.
SWEEP_WALLS: tuple[float | None, ...] = (None, 1.2, 1.6, 2.4)
SWEEP_FLOORS: tuple[float, ...] = (1.2, 2.0)
#: `(base_chamfer_mm, corner_radius_mm)`. `(0, 0)` is the square-cornered geometry — the
#: shape this archetype would have had before issue #80's primitives existed — and it is
#: swept because it is the one case where the outer prism is a plain `Manifold.cube`.
#: The chamfer stays under the smallest floor (1,2 mm) and the radius under the smallest
#: wall (1,2 mm), which are `validate`'s two edge rules; a case outside them is a refusal
#: and belongs in the module's own tests rather than in a sweep of parts that exist.
SWEEP_EDGES: tuple[tuple[float, float], ...] = ((0.6, 1.0), (0.0, 0.0), (1.0, 1.2))
#: The corner set that goes on through Phase 3's assert path: the three layouts that
#: exercise slack, mixed contents and three rows, against the unstated wall and the deck
#: box's — every one of them a point of the product above, so the corners are a subset of
#: the envelope rather than a second list to maintain.
SWEEP_PHASE_3_LAYOUTS: tuple[str, ...] = (
    "one", "narrow-behind", "narrow-in-front", "cards-and-pockets", "deck-behind-pockets",
)
SWEEP_PHASE_3_WALLS: tuple[float | None, ...] = (None, 2.4)


def _compartment(content: tuple) -> Compartment:
    """One sweep content tuple as a `Compartment`."""
    if content[0] == "card":
        return Compartment(CardStack(count=content[1], sleeving=content[2]))
    return Compartment(Pocket(width_mm=content[1], depth_mm=content[2], height_mm=content[3]))


def envelope() -> tuple[SweepCase, ...]:
    """Every spec the dimensional sweep drives this archetype over — 192 of them."""
    cases: list[SweepCase] = []
    for (name, rows, contents), wall, floor, (chamfer, radius) in itertools.product(
        SWEEP_LAYOUTS, SWEEP_WALLS, SWEEP_FLOORS, SWEEP_EDGES,
    ):
        cases.append(SweepCase(
            id=(f"{name}-wall{'default' if wall is None else f'{wall:g}'}"
                f"-floor{floor:g}-chamfer{chamfer:g}-radius{radius:g}"),
            spec=OrganizerSpec(
                archetype=ARCHETYPE,
                compartments=tuple(_compartment(c) for c in contents),
                insert=Insert(rows=rows),
                process=Process(wall_mm=wall, floor_mm=floor,
                                base_chamfer_mm=chamfer, corner_radius_mm=radius),
            ),
            phase_3=(
                name in SWEEP_PHASE_3_LAYOUTS
                and wall in SWEEP_PHASE_3_WALLS
                and floor == 2.0
                and (chamfer, radius) == SWEEP_EDGES[0]
            ),
        ))
    return tuple(cases)
