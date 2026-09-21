"""The three lettering numbers that are claimed to be derived, derived.

`tests/test_vendored_font.py` pins the font's *bytes*. This file pins the three
constants whose comments say they were **computed from** those bytes — and a computed
number with no computation behind it is the worst kind, because it reads as rigorous
and rots silently. Each of the three names this file in its own docstring, which is the
promise being kept here:

- `spec.EMBOSS_TEXT_MAX_CHARS` is deliberately a plain `int` rather than an import, so
  that `pythonsrc/organizer/spec.py` stays stdlib-only and importing it does not drag
  fontTools into an image that has none. The cost of that choice is two literals that
  can drift apart; this is what stops them.
- `spec.EMBOSS_CAP_HEIGHT_MM` is the smallest whole millimetre at which the font's
  glyphs clear `Process.min_feature_mm`. That is a property of *this font*, so a font
  swap must move it rather than quietly leave it wrong.
- `compiler.STROKE_COVERAGE` is the area fraction the opening in `_stroke_em` must keep.
  Its comment argues the answer is insensitive to the exact value between two regimes;
  the way to hold that argument honest is to measure a glyph whose true stem the font
  itself states, and check the measurement lands on it.

None of these needs a mesh, a slicer or a database — they are the font and arithmetic
over it, which is why they are here and not in the archetype suites.
"""
import math
import string

import pytest

from pythonsrc.organizer import compiler, lettering, spec

#: Every printable ASCII character that has a glyph and ink, which is the set a person
#: can actually type into the composer's lettering field.
INKED_ASCII = tuple(
    c for c in string.printable if c.strip() and lettering.has_glyph(c)
)

#: The two printable ASCII glyphs whose thinnest stroke does **not** clear the
#: `min_feature_mm` floor at `EMBOSS_CAP_HEIGHT_MM`, with the cap height each would
#: need. They are not a defect and they are not rounded away: a spec that letters a `*`
#: at the default is refused in Phase 2 by name, which is the floor rule working. They
#: are listed because the default's justification is "the smallest whole millimetre that
#: clears the font", and a reader is owed the exceptions to that sentence.
ABOVE_THE_DEFAULT = ("*", "`")


def _cap_height_mm_needed(character: str, floor_mm: float) -> float:
    """The cap height at which `character`'s thinnest stroke is exactly `floor_mm`.

    The inverse of the measurement the floor is enforced with: `_stroke_em` gives a
    stroke as a fraction of the em, `scale_for` sizes the em from a cap height, so the
    cap height that puts a stroke on the floor is the floor divided by the stroke, in
    ems, times the font's own cap-height-to-em ratio.
    """
    stroke_em = compiler._stroke_em(character)
    if not math.isfinite(stroke_em) or stroke_em <= 0.0:
        return 0.0
    cap_per_em = lettering.cap_height_units() / lettering.units_per_em()
    return floor_mm * cap_per_em / stroke_em


def test_the_schemas_character_bound_is_the_letterings_own():
    """`spec` restates this number instead of importing it, for a reason that is about
    deployment and not about style: `spec.py` is imported by the api-server, which has
    no fontTools, and one import would put a font parser in an image built without one.
    Two literals is the price, and an unpinned pair is how that price turns into a bug —
    `server/app.py`'s `JobRequest` and the composer both bound against the schema's copy,
    so a drift would accept in one place what is cut in another.
    """
    assert spec.EMBOSS_TEXT_MAX_CHARS == lettering.EMBOSS_TEXT_MAX_CHARS


def test_the_default_cap_height_is_the_smallest_whole_mm_that_clears_the_font():
    """`EMBOSS_CAP_HEIGHT_MM = 8.0` is documented as derived, so derive it.

    A default that does not compile is not a default: the first thing a person types
    into the lettering field is set at this height, and if the font's ordinary glyphs do
    not clear `Process.min_feature_mm` there, the composer's own default is refused in
    Phase 2. Recomputed here so that the day the font changes, this moves or this fails —
    rather than remaining a plausible 8 that nobody re-checked.

    `ABOVE_THE_DEFAULT` is excluded and asserted separately: the claim is about the set
    the default has to serve, not about every codepoint in ASCII.
    """
    floor_mm = spec.Process().min_feature_mm
    ordinary = [c for c in INKED_ASCII if c not in ABOVE_THE_DEFAULT]
    binding = max(ordinary, key=lambda c: _cap_height_mm_needed(c, floor_mm))
    needed = _cap_height_mm_needed(binding, floor_mm)

    assert needed <= spec.EMBOSS_CAP_HEIGHT_MM, (
        f"{binding!r} needs a {needed:.3f} mm cap height to clear the "
        f"{floor_mm:g} mm floor, above the {spec.EMBOSS_CAP_HEIGHT_MM:g} mm default"
    )
    assert math.ceil(needed) == spec.EMBOSS_CAP_HEIGHT_MM, (
        f"the default is no longer the smallest whole millimetre that clears the font: "
        f"{binding!r} binds at {needed:.3f} mm, so the default should be "
        f"{math.ceil(needed):g} mm, not {spec.EMBOSS_CAP_HEIGHT_MM:g} mm"
    )


def test_the_glyphs_the_default_does_not_clear_are_the_two_it_never_did():
    """The exceptions to the sentence above, held to exactly two.

    A third one appearing means the font moved under the default, and the composer
    started refusing a character it used to set. That is a legitimate thing to happen and
    an illegitimate thing to happen *unnoticed*, which is the only reason this test
    exists — it does not argue `*` should print at 8 mm.
    """
    floor_mm = spec.Process().min_feature_mm
    refused = tuple(
        c
        for c in INKED_ASCII
        if _cap_height_mm_needed(c, floor_mm) > spec.EMBOSS_CAP_HEIGHT_MM
    )
    assert sorted(refused) == sorted(ABOVE_THE_DEFAULT)


@pytest.mark.parametrize(
    "character, expected_mm",
    [("/", 7.07), ("a", 6.21), ("s", 6.14), ("e", 6.14)],
)
def test_the_cap_heights_the_default_is_argued_from(character, expected_mm):
    """The four figures `EMBOSS_CAP_HEIGHT_MM`'s comment cites by name.

    The comment argues the default from `/` at 7,07 mm and from `a`, `s` and `e` "just
    behind it at 6,2 mm" — and from there, that a 6 mm default "would have refused most
    lowercase text on the floor rule". Prose that quotes measurements is prose that can
    be wrong; these are the measurements.
    """
    floor_mm = spec.Process().min_feature_mm
    assert _cap_height_mm_needed(character, floor_mm) == pytest.approx(
        expected_mm, abs=0.01
    )


def test_a_six_millimetre_default_would_have_refused_lowercase():
    """The counterfactual the comment rests on, since it is the whole argument for 8.

    **It is three letters, and the three are the point.** A 6 mm default refuses `a`, `e`
    and `s` and nothing else in the lowercase alphabet — so the comment's "would have
    refused most lowercase *text*" is a claim about words, not about characters, and it
    is a fair one: almost no English word avoids all three. Pinned as the exact set
    rather than as a count, because "three letters" is only a persuasive argument for
    8 mm while those three are the ones.

    7 mm clears the whole lowercase alphabet, which is why the interesting question is
    the punctuation above it rather than the letters — see
    `test_the_default_cap_height_is_the_smallest_whole_mm_that_clears_the_font`.
    """
    floor_mm = spec.Process().min_feature_mm
    refused_at_six = {
        c for c in string.ascii_lowercase if _cap_height_mm_needed(c, floor_mm) > 6.0
    }
    assert refused_at_six == {"a", "e", "s"}, (
        "a 6 mm default no longer refuses exactly the three commonest lowercase "
        "letters; the sentence in `spec.EMBOSS_CAP_HEIGHT_MM` that argues for 8 mm "
        "rests on it"
    )

    refused_at_seven = {
        c for c in string.ascii_lowercase if _cap_height_mm_needed(c, floor_mm) > 7.0
    }
    assert refused_at_seven == set()


def test_the_opening_measures_the_stem_this_font_states():
    """`STROKE_COVERAGE`'s comment claims the `H` of this font measures its design stem,
    385/2048 em, to the micron — and that claim is what licenses the looser claim beside
    it, that any coverage between the two regimes reads the same answer.

    `H` is the right witness precisely because it has no curves, no taper and no cut
    corner: two vertical stems of one stated width and a crossbar. If the morphological
    opening in `_stroke_em` is measuring what it says it measures, this is the glyph
    where it has nowhere to hide.
    """
    design_em = 385 / lettering.units_per_em()
    measured_em = compiler._stroke_em("H")

    # "To the micron" is a claim about millimetres, so convert at the default cap
    # height rather than comparing ems and hoping the reader does the arithmetic.
    cap_per_em = lettering.cap_height_units() / lettering.units_per_em()
    em_mm = spec.EMBOSS_CAP_HEIGHT_MM / cap_per_em
    error_mm = abs(measured_em - design_em) * em_mm

    assert error_mm < 0.001, (
        f"the opening measures H's stem as {measured_em:.6f} em against a design "
        f"{design_em:.6f} em — {error_mm * 1000:.1f} µm at the default cap height"
    )


def _h_stem_em_at(coverage: float, monkeypatch) -> float:
    """`H`'s measured stem with `STROKE_COVERAGE` moved to `coverage`.

    The result is cached per character, so the cache has to be cleared on the way in
    *and* on the way out — on the way out because leaving a monkeypatched measurement
    memoised would hand it to whatever runs next.
    """
    monkeypatch.setattr(compiler, "STROKE_COVERAGE", coverage)
    compiler._stroke_em.cache_clear()
    try:
        return compiler._stroke_em("H")
    finally:
        compiler._stroke_em.cache_clear()


@pytest.mark.parametrize("coverage", [0.60, 0.70, 0.75, 0.80, 0.82])
def test_the_answer_does_not_turn_on_the_coverage_that_was_chosen(coverage, monkeypatch):
    """The insensitivity `STROKE_COVERAGE`'s comment asserts, measured instead of argued.

    The comment's case for 0,80 is that it is *a gap* rather than a calibration: corner
    rounding costs a few per cent, losing a whole stroke costs a fifth or more, and
    anything between reads the same answer. Anywhere on the plateau `H` must measure its
    stated stem; if it did not, 0,80 would be a fitted constant and the comment should
    stop saying otherwise.
    """
    design_em = 385 / lettering.units_per_em()
    assert _h_stem_em_at(coverage, monkeypatch) == pytest.approx(design_em, abs=0.001)


def test_the_plateau_ends_just_above_the_coverage_that_was_chosen():
    """Where the gap runs out — which is the part the comment does not give a number for.

    The plateau holds from 0,60 to about 0,82 and `H` collapses by 0,85. **0,80 is
    inside the gap but near its top**, with roughly two hundredths of headroom and
    twenty of clearance below. That is worth a test rather than a sentence: someone
    nudging this constant up "a little" to be stricter would cross the edge, and the
    symptom would not be an error — it would be every stroke measuring thinner than it
    is, and the printability floor refusing text that prints perfectly well.
    """
    design_em = 385 / lettering.units_per_em()
    with pytest.MonkeyPatch.context() as mp:
        assert _h_stem_em_at(0.82, mp) == pytest.approx(design_em, abs=0.001)
    with pytest.MonkeyPatch.context() as mp:
        assert _h_stem_em_at(0.85, mp) < design_em - 0.005

    # And the measurement that is actually shipped is the plateau's, not the edge's.
    assert compiler.STROKE_COVERAGE == 0.80
