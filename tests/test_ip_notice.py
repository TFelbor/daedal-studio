"""The in-product notice — AI disclosure, rights, retention — must survive refactors.

There is no frontend test runner in this repo, so this reads the sources as text —
exactly how the "Built with DINOv3" attribution is guarded in
`tests/test_licensing_guards.py`. It is a weak test on purpose: it can only catch
deletion, not rewording. The fragments pinned below are short for that reason.

Why it is guarded at all: the notice is the one place the product tells a person the
rule before they type, and it is the cheapest of the four IP layers by a wide margin.
A UI refactor that quietly drops it leaves the claim in the ToS and nowhere a user
will ever read it. Since 2026-09-11 it also carries the EU AI Act Art. 50(1)
disclosure, where "the T&Cs say it" is not merely weak but expressly insufficient —
the Commission's May 2026 guidelines put the duty on the interface. See
`docs/deferred-legal-tasks.md` § "Open question for counsel".
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every composer a prompt can be typed into. All three must carry the notice, or the
#: landing page, the inline "New job" composer and the zoomed field disagree about
#: what the person was told.
COMPOSERS = [
    "web/src/components/PromptNotice.tsx",
    "web/src/pages/NewJob.tsx",
    "web/src/components/PromptComposer.tsx",
    "web/src/components/PromptZoom.tsx",
]


@pytest.mark.parametrize("source", COMPOSERS)
def test_every_composer_carries_the_prompt_notice(source):
    """A prompt field without the notice is a prompt field that told the user nothing."""
    text = (REPO_ROOT / source).read_text()
    assert "PromptNotice" in text, (
        f"{source} no longer references PromptNotice. Every field a prompt can be "
        "typed into has to carry the rights-and-retention line, or the three "
        "composers disagree about what the person was told."
    )


#: EU AI Act Art. 50(1). Short fragments, for the reason given at the top of this file:
#: a long quotation would fail on a line wrap rather than on a deletion.
AI_DISCLOSURE_FRAGMENTS = ["read by an AI system", "computed, not generated"]


@pytest.mark.parametrize("source", COMPOSERS)
def test_every_composer_carries_the_ai_system_disclosure(source):
    """Art. 50(1) puts the duty on the interface, so every prompt field carries it.

    `PromptNotice.tsx` is where the sentence is worded; the other three reference the
    component, which is what makes one wording reach all three fields. The
    parametrized check above already fails on a dropped reference — this one fails if
    the sentence itself leaves the shared component, which is the same deletion by a
    different route.
    """
    text = (REPO_ROOT / source).read_text()
    if source.endswith("PromptNotice.tsx"):
        for fragment in AI_DISCLOSURE_FRAGMENTS:
            assert fragment in text, (
                f"{source} no longer states that a prompt is read by an AI system. "
                "EU AI Act Art. 50(1) applies from 2026-08-02 and the Commission's "
                "guidelines say a line in the T&Cs does not discharge it — the "
                "interface has to say it. See docs/deferred-legal-tasks.md."
            )
    else:
        assert "PromptNotice" in text


def test_the_running_view_repeats_the_disclosure_on_the_composer_stage():
    """Someone opening a job from a link never passed a composer.

    The stage where the extracted spec is shown says the same thing in fewer words,
    and takes the wording from `PromptNotice.tsx` rather than spelling it out again —
    two copies of a regulated sentence is two sentences that can drift apart.
    """
    running_view = (REPO_ROOT / "web/src/pages/NewJob.tsx").read_text()
    assert "AI_SYSTEM_NOTICE_SHORT" in running_view, (
        "The running view no longer shows the Art. 50(1) disclosure on the Composer "
        "stage."
    )

    notice = (REPO_ROOT / "web/src/components/PromptNotice.tsx").read_text()
    assert "AI_SYSTEM_NOTICE_SHORT" in notice, (
        "The short disclosure must stay in PromptNotice.tsx, which is the one place "
        "either wording lives."
    )


def test_the_ai_act_position_is_recorded_for_counsel():
    """50(1) handled in the interface, 50(2) deferred with the decorative tier.

    The deferred-legal file is what a lawyer picking this up reads. A compliance
    control that exists only in a TSX file is one nobody outside the code knows about,
    which is most of the value of having done it.
    """
    deferred = (REPO_ROOT / "docs/deferred-legal-tasks.md").read_text()
    assert "50(1)" in deferred and "50(2)" in deferred
    assert "PromptNotice.tsx" in deferred, (
        "The note must name where the disclosure is, or the next person cannot check "
        "that it is still there."
    )


def test_the_notice_states_both_things_it_exists_to_state():
    """Rights, and retention. Either alone is a half-truth.

    The retention half has to match reality: the prompt is on `print_job.prompt`, the
    wrapper on `blueprint_prompt_engineered`, and the image in
    `data/outputs/{job_id}/blueprint.png`. A notice claiming less than is kept is
    worse than none.
    """
    notice = (REPO_ROOT / "web/src/components/PromptNotice.tsx").read_text()

    assert "right" in notice.lower()
    assert "kept" in notice.lower() or "retain" in notice.lower()


def test_the_retention_claim_is_documented_where_it_can_be_read_in_full():
    """The one-line notice cannot carry the detail, so it must point somewhere."""
    readme = (REPO_ROOT / "README.md").read_text()
    assert "What we retain" in readme
