"""Per-printer fit offsets — the numbers a machine's own accuracy argues for.

Issue #89, and the half of it that is code. The decision it was blocked on was taken by
the owner on 2026-09-17 and it is **(b): fit offsets stay in the spec.** A printer
profile is the *source the composer pre-fills from*, never a compile-time input, so:

- `spec_hash` does not change meaning and gains no second hash input;
- the tested invariant — same spec → same STL bytes — stands untouched;
- nothing in `pythonsrc/organizer/` imports this module, and the compiler cannot reach
  it even by accident. That is the structural half of the decision: (a) is not merely
  unimplemented, it is unreachable from where the geometry is built.

The offsets reach a design the way `fit_intent`'s clearance already does — resolved
once, into millimetres the spec states — except that the resolution happens one layer
further out, in `POST /organizer/resolve`, and the person can overrule it before it is
ever posted. A spec therefore always carries the millimetres its geometry was built
from, whatever machine suggested them.

**Deliberately dependency-free, and that is load-bearing rather than tidy.** The
api-server image installs no numpy, trimesh, scipy or manifold3d (`infra/docker/
server.Dockerfile` is the list), so it cannot import `pythonsrc.printability` to ask
`ProcessProfile` what a profile says. Both sides import *this* instead, which is what
stops the composer's pre-fill and the printability scorer reading the same four JSON
keys through two different readers that can disagree — `_profile_build_volume`'s rule
in `server/app.py`, applied to the fit fields.

Every number below names its source. Where the placement of a number inside a sourced
band is this project's rather than a citation's, the comment says so in those words —
`organizer.spec.Process.base_chamfer_mm`'s discipline, which labels itself **a design
default, unsourced** rather than letting a plausible millimetre pass as a measured one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

#: Bumped when a number in `FIT_OFFSET_CLASSES` moves or a field joins `FitOffsets`.
#: Recorded on `generation_params` beside the profile that supplied a pre-fill, so a
#: complaint about a fit in cohort 1 can be traced to the exact figures that were on
#: screen — the profile is edited in place, and "what did this machine suggest in
#: September" is otherwise unanswerable. `box_kb`'s `kb_version` does the same job for
#: the curated interiors, and for the same reason.
FIT_OFFSETS_VERSION = 1

#: The profile JSON keys this module reads. Namespaced `fit_*` because a printer profile
#: is otherwise CuraEngine's own vocabulary — `machine_nozzle_size`, `layer_height` —
#: and these three are ours: no slicer setting corresponds to any of them, and a reader
#: of a profile file should be able to tell at a glance which keys leave this repository.
PROFILE_KEYS: tuple[str, ...] = (
    "fit_lid_clearance_mm",
    "fit_cavity_clearance_offset_mm",
    "fit_stack_slack_mm",
)

#: The profile key naming which row of `FIT_OFFSET_CLASSES` a profile's numbers came
#: from. **Documentation, and nothing reads it to resolve a figure** — the three keys
#: above are the data, and a profile whose class says `tuned` while its numbers say
#: something else resolves to its numbers.
#:
#: It exists because a JSON file cannot carry a comment, and a bare `0.3` in a machine
#: definition is exactly the unsourced millimetre this repository refuses everywhere
#: else. `tests/test_fit_offsets.py` asserts every bundled profile's three numbers equal
#: `FIT_OFFSET_CLASSES[its class]`, which is what makes the name a binding rather than a
#: label: the numbers cannot drift from the sourced table without a test going red, and
#: the table is where the sources are written down.
CLASS_KEY = "fit_offsets_class"


@dataclass(frozen=True)
class FitOffsets:
    """What one printer's accuracy argues for, in millimetres.

    Two of the three are absolute and one is an offset, and the asymmetry is the point
    rather than an inconsistency to tidy away. A lid clearance and a stack slack are
    whole figures: nothing else decides them, so a profile states them outright. A
    cavity clearance already has something deciding it — `process.fit_intent`, the word
    a person chooses between "a box I close" and "a tray I lift cards out of" — and a
    profile that stated a whole cavity clearance would silently overrule that word,
    leaving the composer with a control that changes nothing. So the machine contributes
    an *allowance on top of* the intent's figure, the intent keeps deciding the fit, and
    the two compose instead of competing. The names say which is which.
    """

    lid_clearance_mm: float
    """Total clearance between a lid's skirt and the body's lip, mm.

    Pre-fills `spec.lid.clearance_mm` (schema default 0,2). The sourced band is
    **0,2–0,4 mm of friction-lip engagement** — `docs/dimension-kb-research.md` §5, the
    GreatLight deck-box guide — and it is a band rather than a number because the right
    end of it depends on the machine, which is the whole of why this field exists.
    """

    cavity_clearance_offset_mm: float
    """Added to whatever `process.fit_intent` resolves to, mm, total per axis.

    Not the clearance itself. `FIT_INTENT_CLEARANCE_MM` (`organizer/spec.py`) holds the
    intents' own figures — `snug` 1,5 and `easy` 4,0, the low end of
    `docs/dimension-kb-research.md` §3's 1,5–2 and 4–6 mm bands — and this is the
    machine's allowance on top. Zero is the ordinary value and means the intent's figure
    needs no help on this printer.
    """

    stack_slack_mm: float
    """Headroom over a resolved card stack, mm. Pre-fills `spec.process.stack_slack_mm`.

    **The same on every bundled profile, and deliberately so.** Nothing in the research
    sources a per-machine figure for it, and nothing should: the error this slack absorbs
    is the *stack's* — sleeve thickness varies by brand and by whether the cards were
    played with (`docs/dimension-kb-research.md` §2 keeps a 120-vs-130 µm disagreement on
    one line of Dragon Shield alone) — and a printer that is 0,2 mm out over 70 mm of
    stack is not what makes a deck refuse to go in.

    It is a field rather than an omission because the Phase 4 coupon → calibration loop
    needs somewhere to put a measured figure if one ever turns up, and a field added
    later is a profile-schema change while an unused field is a default nobody notices.
    Carrying it uniform and saying why is the honest version of both.
    """

    def to_dict(self) -> Dict[str, float]:
        """The three figures as plain JSON, keyed the way the profile file keys them."""
        return {
            "fit_lid_clearance_mm": self.lid_clearance_mm,
            "fit_cavity_clearance_offset_mm": self.cavity_clearance_offset_mm,
            "fit_stack_slack_mm": self.stack_slack_mm,
        }


#: What a profile that says nothing about fit means: today's schema defaults, exactly.
#:
#: This is the "what happens when no printer is configured" answer the decision asked to
#: be made explicit rather than left to fall through (comment of 2026-09-17, point 4).
#: A user with no printer configured, or one whose profile predates these keys, composes
#: against `Lid.clearance_mm` 0,2 and `Process.stack_slack_mm` 1,0 with no allowance on
#: the intent's clearance — which is what every spec this project has ever compiled was
#: built from. **A profile without the keys must therefore change nothing**, and
#: `tests/test_fit_offsets.py` asserts that against the pre-#89 figures directly.
DEFAULT_FIT_OFFSETS = FitOffsets(
    lid_clearance_mm=0.2,
    cavity_clearance_offset_mm=0.0,
    stack_slack_mm=1.0,
)

#: The two machine classes the bundled profiles fall into, and the sourced accuracy
#: figure behind each. Named rather than numbered so a profile file can cite one.
#:
#: **`tuned`** — a machine that is shrink-compensated and calibrated, which
#: `docs/dimension-kb-research.md` §6 puts at **±0,1 mm typical** (Bambu forum thread
#: 112292). The Bambu P1S is the one bundled profile in this class.
#:
#: **`desktop`** — a general desktop FDM machine, which the same section puts at
#: **±0,5 % with a ±0,5 mm floor** (Hubs knowledge base) and the Bambu thread at
#: **±0,2 mm uncalibrated**. The Ender 3, the Anycubic Mega S and the Klipper test
#: target are in this class.
#:
#: **The placement of each number inside its sourced band is this project's**, and it is
#: a design choice rather than a measurement — said plainly here because the rule in
#: this repository is that a millimetre either names a source or says it has none. The
#: *bands* are sourced, the *class accuracies* are sourced, and the mapping from the
#: second onto the first is reasoning, not data. The rule it applies is
#: `FIT_INTENT_CLEARANCE_MM`'s verbatim — take the low end of a sourced band, because a
#: clearance is cheap to increase by hand and expensive to discover as a part that does
#: not close — moved up one step where the machine's own sourced error would eat it.
#:
#: **And one finding falls straight out of the table, which is worth more than the
#: table.** No figure in a 0,2–0,4 mm friction band survives §6's ±0,5 mm desktop floor:
#: on a machine at the bottom of its sourced accuracy, a lid designed to any clearance in
#: that band can print interference-fit. That gap is not closable by choosing a better
#: default, and pretending otherwise is the "printer-accuracy assumption" §6 ends by
#: naming. It is what the Phase 4 test-fit coupon and the calibration loop exist to
#: measure per machine and per material — this table is the prior they start from, not
#: the answer they replace.
FIT_OFFSET_CLASSES: Dict[str, FitOffsets] = {
    "tuned": FitOffsets(
        # The low end of §5's 0,2–0,4 mm band. Also today's schema default, so the P1S
        # profile moves nothing for anybody who is already printing on one.
        lid_clearance_mm=0.2,
        # The intents' own figures came off commercial references in §3 that this class
        # of machine hits, so it asks for no allowance and states zero rather than
        # omitting the key — an absent key means "this profile predates #89", which is
        # a different claim from "this machine needs nothing".
        cavity_clearance_offset_mm=0.0,
        stack_slack_mm=1.0,
    ),
    "desktop": FitOffsets(
        # One step up the same band, not the top of it: §6 puts this class at ±0,2 mm
        # uncalibrated, which 0,2 mm of design clearance can close entirely and 0,3 mm
        # cannot. 0,4 mm would buy the ±0,5 mm floor nothing (see the note above) and
        # costs every lid on every tuned-enough machine a rattle.
        lid_clearance_mm=0.3,
        # +0,5 mm is §6's desktop floor, and the cross-check is what makes it more than
        # a plausible number: added to the intents it lands `snug` at 2,0 mm and `easy`
        # at 4,5 mm, and **both are inside §3's own sourced bands** (1,5–2 and 4–6). A
        # figure derived from the tolerance table and independently inside the clearance
        # table is two sources agreeing, which is the strongest thing this file has.
        cavity_clearance_offset_mm=0.5,
        stack_slack_mm=1.0,
    ),
}


def fit_offsets_from_profile(profile: Dict[str, Any]) -> FitOffsets:
    """The fit offsets a parsed printer profile declares, falling back to the defaults.

    Args:
        profile: Parsed contents of a `pythonsrc/profiles/*.json` file.

    Returns:
        The three figures. **A profile that declares none resolves to
        `DEFAULT_FIT_OFFSETS`** — today's schema numbers — rather than raising, because
        a profile is a slicer configuration first and a fit source second: a machine
        definition somebody wrote before #89, or exported from Cura, must still print.
        Each key falls back on its own, so a profile may state a lid clearance and say
        nothing about the rest.

    An unparseable value falls back the same way it is absent. A profile is edited by
    hand through the Settings UI, and a typo in a fit key is not a reason to refuse to
    slice — the composer shows the figure it used and says which profile it came from,
    which is where a wrong number is visible and fixable.
    """
    def _mm(key: str, fallback: float) -> float:
        declared = profile.get(key)
        if declared is None:
            return fallback
        try:
            return float(declared)
        except (TypeError, ValueError):
            return fallback

    return FitOffsets(
        lid_clearance_mm=_mm("fit_lid_clearance_mm", DEFAULT_FIT_OFFSETS.lid_clearance_mm),
        cavity_clearance_offset_mm=_mm(
            "fit_cavity_clearance_offset_mm", DEFAULT_FIT_OFFSETS.cavity_clearance_offset_mm
        ),
        stack_slack_mm=_mm("fit_stack_slack_mm", DEFAULT_FIT_OFFSETS.stack_slack_mm),
    )


def fit_offsets_record(
    profile_name: Optional[str], profile: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """What `generation_params` records about the printer behind a pre-fill.

    The column that makes the Phase 4 calibration loop possible **under (b)**, and the
    one thing option (a) would have got for free. The mesh is not a function of a
    printer any more, so nothing else in a job's row says which machine's figures were
    on screen when the person accepted them — and "this box does not close" is a
    complaint about a printer, not about a spec. Without this, cohort 1's fit reports
    join to nothing.

    It records what the profile *offered*, never what the spec ended up with. The spec
    is its own record of that, exactly, in millimetres, and a second copy here could
    disagree with it — which is the failure mode `game_box_record` avoids by being the
    one function both the screen and the database call.

    Args:
        profile_name: The profile as named on the job, e.g. `ender3.json`, or None.
        profile: Its parsed contents, or None when it could not be read.

    Returns:
        `{"profile", "fit_offsets_version", "offsets", "declared"}`. `declared` is false
        for a profile carrying none of `PROFILE_KEYS`, where `offsets` is
        `DEFAULT_FIT_OFFSETS` — so a row can tell "this machine suggested the schema's
        own numbers" from "nothing was asked", which are the same millimetres and
        different facts.
    """
    source = profile or {}
    return {
        "profile": profile_name,
        "fit_offsets_version": FIT_OFFSETS_VERSION,
        "offsets": fit_offsets_from_profile(source).to_dict(),
        "declared": any(key in source for key in PROFILE_KEYS),
    }
