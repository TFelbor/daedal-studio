"""Every refusal `spec.emboss` earns, and the field each one names.

Acceptance criterion 3 of issue #157 — "a glyph feature below `min_feature_mm` or the
nozzle wall floor is refused in Phase 2 with a message naming the field" — was asserted
nowhere. `lettering_problems` in `archetypes/common.py` is where all of it happens, and
it enumerates five rules in its own docstring; this file is one case per rule, plus the
two archetype-level ones above them, and every case asserts **the dotted path in the
message** rather than merely that something was refused.

That is the whole point of the criterion. A refusal that does not name a field is a
refusal a person cannot act on: the composer routes problems to controls by the path
they carry (`specForm.FIELD_BY_KEY`), so an unnamed one lands on the form rather than on
the number that has to move, and a remedy nobody can find is the same as no remedy.

Where a rule quotes a remedy — "set `height_mm` to 4,2 mm or less" — the remedy is
taken out of the message and compiled, because a remedy that does not work is worse
than none: it spends the person's second attempt as well as their first.
"""
import re
from dataclasses import replace

import pytest

from pythonsrc.organizer.archetypes import REGISTRY, compile_spec, example_spec
from pythonsrc.organizer.archetypes.common import (
    LETTERING_ARCHETYPES,
    lettering_problems,
)
from pythonsrc.organizer.spec import Emboss, OrganizerSpec, SpecError

#: A face every lettering archetype in the registry honours, for the rules that are not
#: about faces. Read off the module so it cannot drift.
FIRST_FACE = {name: mod.EMBOSS_FACES[0] for name, mod in REGISTRY.items()
              if getattr(mod, "EMBOSS_FACES", ())}


def honoured_mode(archetype: str, face: str) -> str:
    """The first mode that face honours.

    `Emboss.mode` defaults to `raised`, which only the divider's tab takes — so a test
    about any *other* rule has to pick the mode off the frame or it measures the mode
    rule instead of the one it meant. Read from `emboss_frame` rather than written out,
    for the reason the composer's table is bound in `test_composer_options.py`.
    """
    probe = replace(example_spec(archetype),
                    emboss=Emboss(text="Ab", face=face, mode="recessed"))
    return REGISTRY[archetype].emboss_frame(probe).modes[0]


def lettered(archetype: str, **emboss) -> OrganizerSpec:
    """`example_spec(archetype)` with an emboss section on its first lettered face."""
    emboss.setdefault("face", FIRST_FACE[archetype])
    emboss.setdefault("mode", honoured_mode(archetype, emboss["face"]))
    return replace(example_spec(archetype), emboss=Emboss(**emboss))


def problems_for(archetype: str, **emboss) -> list[str]:
    return lettering_problems(lettered(archetype, **emboss), REGISTRY[archetype])


def remedy_mm(message: str, pattern: str) -> float:
    """The millimetre figure a refusal offers as its way out."""
    found = re.search(pattern, message)
    assert found, f"no remedy matched {pattern!r} in:\n{message}"
    return float(found.group(1).replace(",", "."))


# ── the registry binding the comment promised ─────────────────────────────────

def test_lettering_archetypes_is_the_set_that_declares_faces():
    """`LETTERING_ARCHETYPES` is named in the refusal a tray or an insert gives, and
    `common.py` says this test binds it to the modules that declare `EMBOSS_FACES`. It
    did not exist, so the tuple was a hand-maintained copy of a fact three files away.

    Both directions, because each failure is different and both are silent: a name in
    the tuple that letters nothing sends a person to an archetype that will refuse them
    again, and a module that letters with no entry is invisible in the one message that
    was supposed to list it.
    """
    declaring = {name for name, mod in REGISTRY.items()
                 if getattr(mod, "EMBOSS_FACES", ())}
    assert set(LETTERING_ARCHETYPES) == declaring
    assert len(set(LETTERING_ARCHETYPES)) == len(LETTERING_ARCHETYPES)



def test_the_kernels_mode_tuple_is_the_schemas():
    """`compiler.LETTER_MODES` says "`spec.EMBOSS_MODES` is the same tuple". Two
    literals, in the two halves of the system that must agree on what a mode is — the
    schema validates against one and the kernel switches on the other, so a mode in one
    and not the other is either a spec the kernel cannot build or a build nobody can
    ask for."""
    from pythonsrc.organizer.compiler import LETTER_MODES
    from pythonsrc.organizer.spec import EMBOSS_MODES

    assert tuple(LETTER_MODES) == tuple(EMBOSS_MODES)

# ── rule 1: the archetype letters at all ──────────────────────────────────────

@pytest.mark.parametrize("archetype", ["token_tray", "box_insert"])
def test_an_archetype_that_letters_nothing_refuses_and_names_the_ones_that_do(archetype):
    """A tray's walls are thin and an insert's faces sit inside a box nobody opens, so
    neither carries the section. The refusal has to say which shapes do, or the person
    is told no with nowhere to go."""
    spec = replace(example_spec(archetype), emboss=Emboss(text="Lands", face="lid_top"))
    problems = lettering_problems(spec, REGISTRY[archetype])

    assert len(problems) == 1
    assert problems[0].startswith("spec.emboss ")
    for owner in LETTERING_ARCHETYPES:
        assert repr(owner) in problems[0]


# ── rule 1b: the archetype letters, but not this face ─────────────────────────

def test_a_face_the_archetype_does_not_build_is_refused_by_name():
    """A card divider has a tab and no lid. `lid_top` is a legal *schema* value — the
    schema does not know which archetype it is for — so the archetype is where it is
    caught, and the message lists the faces this one does letter."""
    problems = problems_for("card_divider", text="Lands", face="lid_top")

    assert len(problems) == 1
    assert problems[0].startswith("spec.emboss.face ")
    assert "'lid_top'" in problems[0]
    assert "['tab']" in problems[0]


# ── rule 2: the font can set the text ─────────────────────────────────────────

def test_a_glyph_the_font_does_not_have_is_named_with_its_code_point():
    """Never substituted: a box printed with a different character than the one asked
    for is a wrong part that looks like a right one. The code point is in the message
    because the character itself may not render in the terminal reading it."""
    problems = problems_for("deck_box", text="Lands 中")

    assert problems
    assert any(p.startswith("spec.emboss.text") for p in problems)
    assert any("U+4E2D" in p for p in problems)


# ── rule 3: the face honours the mode ─────────────────────────────────────────

def test_raised_on_a_deck_box_face_is_refused_with_the_reason():
    """Every deck-box face is either against the bed or vertical, so all five take
    `recessed` only. The refusal names the mode field and says to sink it instead —
    without that, the obvious next move is to try another face, and all five refuse."""
    problems = problems_for("deck_box", text="Lands", mode="raised")

    assert problems
    named = [p for p in problems if p.startswith("spec.emboss.mode ")]
    assert len(named) == 1
    assert "'raised'" in named[0]
    assert "['recessed']" in named[0]


def test_the_divider_tab_is_the_one_face_that_takes_raised():
    """The counterpart, and the reason the mode rule is per face rather than global: the
    tab points up as it prints, so a raised letter on it needs no support."""
    assert problems_for("card_divider", text="Ab", mode="raised", height_mm=6.0) == []


# ── rule 4: the ink fits the face, and the remedy it offers works ─────────────

def test_text_too_large_for_the_face_is_refused_with_a_height_that_fits():
    """Never scaled and never wrapped — shrinking a person's lettering to make it fit is
    the same fabrication as shrinking the part. So the refusal has to carry a cap height
    that *does* fit, and that height is compiled here rather than trusted."""
    problems = problems_for("card_divider", text="Mountain", height_mm=8.0)

    assert problems
    named = [p for p in problems if p.startswith("spec.emboss.text ")]
    assert len(named) == 1, problems
    assert "Shorten the text" in named[0]

    remedy = remedy_mm(named[0], r"height_mm to ([0-9.]+) mm or less")
    followed = problems_for("card_divider", text="Mountain", height_mm=remedy)
    assert not [p for p in followed if p.startswith("spec.emboss.text ")], followed


def test_a_long_word_on_a_small_face_offers_two_remedies_that_contradict():
    """A sharp edge found while writing the test above, pinned rather than papered over.

    `"Mountain"` does not fit a divider's 20 × 10 mm tab at any usable size, and the two
    rules say so separately and incompatibly: the fit rule offers "set height_mm to
    2,5 mm or less", and at 2,5 mm the stroke rule answers "set height_mm to 6,3 mm or
    more". Following either leaves the other standing, so a person alternates between
    two refusals with no stated way out.

    Both messages are individually correct and neither knows about the other — the fit
    rule is measured against the face, the stroke rule against the nozzle, and nothing
    intersects the two ranges. The honest remedy is the one the fit rule already gives
    when *nothing* fits ("letter a larger face"), extended to the case where the
    remedies cross rather than only the case where the face is too small at any size.

    This test does not assert the desired behaviour, because that is a change to the
    messages and not to this PR's scope. It asserts the current behaviour so that
    fixing it is a visible diff here rather than a silent one.
    """
    fit_remedy = remedy_mm(
        next(p for p in problems_for("card_divider", text="Mountain", height_mm=8.0)
             if p.startswith("spec.emboss.text ")),
        r"height_mm to ([0-9.]+) mm or less",
    )
    at_fit = problems_for("card_divider", text="Mountain", height_mm=fit_remedy)
    stroke_remedy = remedy_mm(
        next(p for p in at_fit if p.startswith("spec.emboss.height_mm ")),
        r"height_mm to ([0-9.]+) mm or more",
    )
    assert stroke_remedy > fit_remedy, (
        "the two remedies no longer contradict — if that was deliberate, this test "
        "should become the assertion that a single workable remedy is offered"
    )


# ── rule 5: the stroke, the relief and the material behind them ───────────────

def test_a_stroke_below_the_floor_names_the_height_and_a_height_that_clears_it():
    """The criterion's own sentence. A raised stroke thinner than one extrusion is a fin
    the nozzle cannot lay; a recess narrower than one is filled by the next pass. Both
    come out as a part that does not carry the name it was printed for."""
    problems = problems_for("deck_box", text="Ill", height_mm=1.0)

    assert problems
    named = [p for p in problems if p.startswith("spec.emboss.height_mm ")]
    assert len(named) == 1, problems
    assert "min_feature_mm" in named[0] and "nozzle" in named[0]

    remedy = remedy_mm(named[0], r"height_mm to ([0-9.]+) mm or more")
    cleared = problems_for("deck_box", text="Ill", height_mm=remedy)
    assert not [p for p in cleared if p.startswith("spec.emboss.height_mm ")], cleared


def test_a_raised_letter_taller_than_its_stroke_is_wide_is_refused():
    """A fin taller than it is wide snaps off the plate or in the hand. Only reachable
    on the one face that takes `raised`, which is why it is tested there."""
    problems = problems_for(
        "card_divider", text="Ab", mode="raised", height_mm=6.0, relief_mm=2.5
    )

    named = [p for p in problems if p.startswith("spec.emboss.relief_mm ")]
    assert len(named) == 1, problems
    assert "snap off" in named[0]


def test_a_recess_that_eats_the_wall_behind_it_names_the_wall_it_leaves():
    """The rule that makes `recessed` the safe default and not the free one: sinking
    0,6 mm into a 1,4 mm tab leaves 0,8 mm, under the floor that wall is held to. The
    message has to give the millimetres left, because that is the number the person
    compares against the floor."""
    thin = replace(
        example_spec("card_divider"),
        emboss=Emboss(text="Ab", face="tab", mode="recessed", height_mm=6.0,
                      relief_mm=1.2),
    )
    problems = lettering_problems(thin, REGISTRY["card_divider"])

    named = [p for p in problems if p.startswith("spec.emboss.relief_mm ")]
    assert len(named) == 1, problems
    assert "floor" in named[0]


# ── the schema's own refusals, which are not this function's ──────────────────

@pytest.mark.parametrize("text", ["", "   ", "\t"])
def test_an_emboss_section_with_no_text_is_refused_by_the_schema(text):
    """The issue lists "empty" as one of the four sweep cases, and it is a schema
    refusal rather than a geometry one: an emboss section that decorates nothing is a
    section that should not have been sent. `Emboss` strips before it checks, so
    whitespace is empty."""
    with pytest.raises(SpecError) as caught:
        Emboss(text=text)
    assert any("text" in p for p in caught.value.problems)


def test_an_empty_emboss_from_the_wire_names_the_dotted_path():
    """Through `from_dict`, which is the path a posted spec takes — the path has to be
    the full one so the composer can route it to the text box."""
    raw = example_spec("deck_box").to_dict()
    raw["emboss"] = {"text": "  ", "face": "lid_top", "mode": "recessed"}

    with pytest.raises(SpecError) as caught:
        OrganizerSpec.from_dict(raw)
    assert any("emboss" in p and "text" in p for p in caught.value.problems)


# ── the whole path: a refusal reaches compile_spec ────────────────────────────

def test_compile_spec_refuses_the_lettering_rather_than_building_it():
    """`lettering_problems` returns a list so the caller can report it beside the
    archetype's own findings. This is the assertion that it is wired in at all — every
    test above calls the function directly, and a rule nobody calls refuses nothing."""
    with pytest.raises(SpecError) as caught:
        compile_spec(lettered("deck_box", text="Ill", height_mm=1.0))
    assert any("spec.emboss.height_mm" in p for p in caught.value.problems)
