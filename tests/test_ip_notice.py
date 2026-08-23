"""The in-product notice about rights and retention must survive refactors.

There is no frontend test runner in this repo, so this reads the sources as text —
exactly how the "Built with DINOv3" attribution is guarded in
`tests/test_licensing_guards.py`. It is a weak test on purpose: it can only catch
deletion, not rewording. The fragments pinned below are short for that reason.

Why it is guarded at all: the notice is the one place the product tells a person the
rule before they type, and it is the cheapest of the four IP layers by a wide margin.
A UI refactor that quietly drops it leaves the claim in the ToS and nowhere a user
will ever read it.
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
