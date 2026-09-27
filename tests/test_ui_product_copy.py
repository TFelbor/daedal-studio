"""The UI must describe the product being built, and must not invent progress.

There is no frontend test runner in this repo, so this reads the sources as text —
the same weak-on-purpose guard `tests/test_ip_notice.py` and
`tests/test_archetype_registry.py` use. It can catch a deletion or a reintroduction,
not a rewording, so what it pins is short and load-bearing.

Two things are guarded here and they pull in opposite directions, which is why they
are in one file:

*   **The waiting-state theatre must stay gone.** `WaitingStage` drew a canvas
    cycling a hard-coded list of steps on a 1.9s timer — `flux.2-klein · loading`,
    `sparse structure · voxels`. The pipeline reported none of them, so it was
    progress the app invented, and it named the generative stack in the one place
    the product describes itself. A parametric compile finishes in well under a
    second; there is no wait left to fill.
*   **The strings that describe what actually runs must stay true.** The blueprint
    gate and the fixture badge talk about FLUX renders and bundled reference assets
    because that is what a generative job does today. Rewriting *those* for
    organizers would be the same fabrication as a fits badge with no measurement
    behind it (docs/SYSTEM-AS-BUILT.md § The fixture flag is carried out to the UI).
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = REPO_ROOT / "web/src"

#: Retired with issue #77. Every one of these existed to fill a wait that the
#: parametric path does not have.
RETIRED_FILES = [
    "web/src/components/WaitingStage.tsx",
    "web/src/components/WaitingStage.module.css",
    "web/src/components/waitingStageRenderer.ts",
    "web/src/pages/WaitingStatesGallery.tsx",
    "web/src/pages/WaitingStatesGallery.module.css",
]

#: The identifiers that went with them. A dangling import is a build failure, but a
#: *comment* pointing at a component that no longer exists is how a deleted thing
#: gets reintroduced, so the sweep covers the whole tree rather than the imports.
RETIRED_IDENTIFIERS = [
    "WaitingStage",
    "WaitingStageRenderer",
    "waitingStageRenderer",
    "WaitingKind",
    "WaitingStatesGallery",
]

#: `BootMark` is deliberately **not** retired. It is the mark the app draws while it
#: is reading its own state — a loading indicator, not theatre — and the issue says
#: to keep it everywhere except the gallery that existed to review it. These are the
#: sites where the app is genuinely waiting on itself.
BOOTMARK_SITES = [
    "web/src/components/PrintabilityCard.tsx",
    "web/src/components/PhaseProgress.tsx",
    "web/src/pages/PrintMonitor.tsx",
    "web/src/pages/JobList.tsx",
    "web/src/pages/PrinterSetup.tsx",
    "web/src/pages/JobDetail.tsx",
]

#: Every host that used to draw a waiting stage. Each must now draw the real phase
#: state instead — a frame with neither is a flat empty rectangle, which is the
#: state the drawn stage was written to replace and not what this change wants back.
STAGE_STATE_HOSTS = [
    "web/src/components/MeshViewer.tsx",
    "web/src/components/BlueprintPreview.tsx",
    "web/src/pages/NewJob.tsx",
    "web/src/pages/JobDetail.tsx",
]

#: Words that can only be the old product's subject. `sculpt` is matched only where
#: it is not part of an identifier — `skip_sculptor` / `skipSculptor` name a real
#: config key and a real request field, and renaming those would misname the key.
FIGURINE_WORDS = ["figurine", "statue", "sculpt", "low poly"]

#: The one visible string allowed to keep a banned word, with the reason. "Skip
#: sculptor" is the label on the `SKIP_SCULPTOR` toggle, which since issue #189 sits
#: under "Generative path" inside the collapsed Developer disclosure — it names the
#: phase that actually runs on that path, which is exactly what must stay true.
FIGURINE_WORD_ALLOWED = {
    ("web/src/pages/PrinterSetup.tsx", "sculpt"): "Skip sculptor",
}

_LINE_COMMENT = re.compile(r"^\s*(//|\*|/\*)")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _visible_text(path: Path) -> str:
    """The file with its comments removed.

    Crude on purpose: a comment explaining *why* a word is not used must not fail
    the check that the word is not used.
    """
    text = _BLOCK_COMMENT.sub("", path.read_text())
    return "\n".join(
        line for line in text.split("\n") if not _LINE_COMMENT.match(line)
    )


def _sources() -> list[Path]:
    return sorted(
        p
        for pattern in ("*.ts", "*.tsx", "*.css")
        for p in WEB_SRC.rglob(pattern)
    )


@pytest.mark.parametrize("source", RETIRED_FILES)
def test_the_waiting_state_theatre_is_gone(source):
    assert not (REPO_ROOT / source).exists(), (
        f"{source} is back. It drew invented progress on a timer — see the module "
        "docstring above. The real phase state is `StageState`."
    )


@pytest.mark.parametrize("identifier", RETIRED_IDENTIFIERS)
def test_nothing_in_the_app_still_names_them(identifier):
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in _sources()
        if identifier in p.read_text()
    ]
    assert offenders == [], (
        f"{identifier} is referenced by {offenders}. The component is gone; a "
        "reference to it is either a build failure or an invitation to write it again."
    )


def test_the_gallery_route_is_gone_with_the_gallery():
    """`/states` existed only to review the drawn stages."""
    app = (REPO_ROOT / "web/src/App.tsx").read_text()
    assert "/states" not in app


@pytest.mark.parametrize("source", BOOTMARK_SITES)
def test_the_boot_mark_is_kept_where_the_app_reads_its_own_state(source):
    """Deliberately not retired — see BOOTMARK_SITES.

    Removing it would replace six honest "we are fetching" marks with nothing, which
    is a different change from retiring theatre and was not what the issue asked for.
    """
    assert (REPO_ROOT / "web/src/components/BootMark.tsx").exists()
    assert "BootMark" in (REPO_ROOT / source).read_text(), (
        f"{source} no longer draws the boot mark. It is a loading mark, not theatre: "
        "the app is genuinely reading its own state there."
    )


@pytest.mark.parametrize("source", STAGE_STATE_HOSTS)
def test_every_stage_that_can_be_empty_states_the_phase_it_is_waiting_on(source):
    assert "StageState" in (REPO_ROOT / source).read_text(), (
        f"{source} draws a stage that can be empty and no longer says which phase "
        "fills it. A frame with nothing in it and nothing said about it reads as a "
        "broken pipeline."
    )


def test_the_stage_state_takes_its_words_from_the_single_source():
    """The blurbs are `pipeline.ts`'s, not a second copy.

    Two surfaces show the phase list — the composer's pipeline panel and this — and
    they carried separate copies once, so renaming a phase in one left the other
    describing the old machine.
    """
    stage = (REPO_ROOT / "web/src/components/StageState.tsx").read_text()
    assert "from '../pipeline'" in stage
    assert "PIPELINE" in stage and "phaseName" in stage


def test_the_stage_state_invents_no_progress():
    """No step vocabulary, no timer, no canvas.

    The only progress it may show is a line the pipeline actually printed. A list of
    plausible-sounding steps advancing on an interval is a measurement the app does
    not have, and it named FLUX, TRELLIS and CuraEngine while doing it.
    """
    # Comments only, so the docstring above may explain what was removed without
    # failing the check that it is removed.
    stage = _visible_text(REPO_ROOT / "web/src/components/StageState.tsx").lower()
    for invented in ("setinterval", "canvas", "flux", "trellis", "curaengine", "voxel"):
        assert invented not in stage, (
            f"StageState.tsx mentions {invented!r}. It reports the phase state and "
            "the pipeline's own output, and nothing else."
        )
    assert "logLines" in (REPO_ROOT / "web/src/components/StageState.tsx").read_text()


@pytest.mark.parametrize("word", FIGURINE_WORDS)
def test_no_visible_string_presents_a_figurine_as_the_product(word):
    """The product is a custom-fit organizer compiled from a spec.

    A vase, a planter box or a figurine on screen is the story of the benched
    generative path, which is not what anyone is being sold.
    """
    pattern = re.compile(rf"(?<![A-Za-z_]){word}", re.IGNORECASE)
    offenders = []
    for path in _sources():
        rel = str(path.relative_to(REPO_ROOT))
        for match in pattern.finditer(_visible_text(path)):
            allowed = FIGURINE_WORD_ALLOWED.get((rel, word))
            context = match.string[match.start() - 8 : match.start() + 24]
            if allowed and allowed.lower() in context.lower():
                continue
            offenders.append(f"{rel}: …{context}…")
    assert offenders == [], (
        f"{word!r} appears in user-visible copy: {offenders}. Rewrite it for "
        "organizers, or — if it describes what actually runs today — add it to "
        "FIGURINE_WORD_ALLOWED with the reason."
    )


#: The two fields that offer the example prompt. They are one control at two
#: magnifications — see PROMPT_SUBMIT_SITES, which is the same pair for the same
#: reason.
PROMPT_PLACEHOLDER_SITES = [
    "web/src/components/PromptZoom.tsx",
    "web/src/pages/NewJob.tsx",
]


def _prompt_placeholder() -> str:
    """`PROMPT_PLACEHOLDER` as `promptLimits.ts` declares it."""
    text = (REPO_ROOT / "web/src/components/promptLimits.ts").read_text()
    found = re.search(r"export const PROMPT_PLACEHOLDER =\s*'([^']+)'", text)
    assert found, (
        "promptLimits.ts no longer exports a PROMPT_PLACEHOLDER string literal. "
        "It is the one place the example prompt is written; if it moved, move this "
        "test with it rather than deleting the check."
    )
    return found.group(1)


def test_the_example_prompt_describes_something_the_engine_could_compile():
    """A placeholder is the strongest copy on the page: it is what people edit.

    The zoomed field offered "A low poly planter box with a modern geometric
    design…" while the landing field beside it offered a Commander deck box — two
    fields for the same prompt disagreeing about what the product makes.

    Read off the constant rather than out of the JSX. This used to grep both files
    for `placeholder="…"`, which stopped seeing anything the moment the landing field
    became a JSX expression — the test went red for a reason that had nothing to do
    with the copy, which is the failure mode a text guard is worst at.
    """
    prompt = _prompt_placeholder()
    assert any(
        word in prompt.lower()
        for word in ("card", "sleeve", "dice", "deck", "tray", "divider")
    ), (
        f"PROMPT_PLACEHOLDER offers {prompt!r} as an example. The engine compiles "
        "organizers — deck boxes and card dividers — and an example it would "
        "refuse teaches the wrong prompt."
    )


@pytest.mark.parametrize("source", PROMPT_PLACEHOLDER_SITES)
def test_neither_prompt_field_carries_an_example_of_its_own(source):
    """The drift the constant exists to prevent, caught if it comes back.

    `PROMPT_PLACEHOLDER`'s own docstring says one constant makes the disagreement
    impossible — and it only does while both fields read it. `PromptZoom` kept its
    literal through the change that introduced the constant, so the two example
    prompts were different again the same day.

    A short placeholder is fine: "Name this job — blank names it after the spec" is a
    label, not an example of what to build.
    """
    text = (REPO_ROOT / source).read_text()
    literals = [p for p in re.findall(r'placeholder="([^"]+)"', text) if len(p) > 40]
    assert literals == [], (
        f"{source} writes its own example prompt: {literals}. Both fields must read "
        "PROMPT_PLACEHOLDER from promptLimits.ts, or they will disagree again."
    )


#: The two fields that compose one prompt. The landing field and `PromptZoom` edit the
#: same state and submit through the same `startJob`, so the verb on their buttons is
#: one string in one module — see PROMPT_SUBMIT_LABEL.
PROMPT_SUBMIT_SITES = [
    "web/src/pages/NewJob.tsx",
    "web/src/components/PromptZoom.tsx",
]


#: Retired with the same issue, and the reason is on PROMPT_SUBMIT_LABEL: a job
#: submitted from the app never starts a print, and *generate* is the benched path.
RETIRED_STRINGS = ["Generate & print"]

_IMPORT = re.compile(r"(?m)^import\b[\s\S]*?;")


def _prompt_submit_labels() -> dict[str, str]:
    text = (REPO_ROOT / "web/src/components/promptLimits.ts").read_text()
    return dict(
        re.findall(r"export const (PROMPT_SUBMIT_[A-Z_]+) = '([^']+)'", text)
    )


def _body(path: Path) -> str:
    """The file with its imports removed.

    An identifier that is only imported is an identifier nothing renders — which is
    exactly the state a reintroduced literal beside a surviving import leaves the
    file in, so the check has to look past the import block.
    """
    return _IMPORT.sub("", path.read_text())


@pytest.mark.parametrize("retired", RETIRED_STRINGS)
def test_no_button_offers_the_retired_promise(retired):
    # Comments stripped, so the constant that replaced it may say what it replaced.
    offenders = [
        str(p.relative_to(REPO_ROOT)) for p in _sources() if retired in _visible_text(p)
    ]
    assert offenders == [], (
        f"{retired!r} is back in {offenders}. See PROMPT_SUBMIT_LABEL: the app sends "
        "`print: false`, so the print is started by a person at the dispatch gate."
    )


def test_the_prompt_submit_label_promises_only_what_the_button_does():
    """A job submitted from the app sends `print: false, start_print: false`.

    It stops after the slicer and waits for a person at the dispatch gate, so a
    button offering to print is offering something no code path behind it does —
    and *generate* is the benched path, named where the product says what it makes.
    """
    labels = _prompt_submit_labels()
    assert set(labels) == {"PROMPT_SUBMIT_LABEL", "PROMPT_SUBMIT_BUSY_LABEL"}, labels
    for name, label in labels.items():
        lowered = label.lower()
        for promised in ("print", "generate"):
            assert promised not in lowered, (
                f"{name} is {label!r}. Pressing this button creates a job that stops "
                "at the slicer; the dispatch gate is where a person starts a print."
            )


@pytest.mark.parametrize("source", PROMPT_SUBMIT_SITES)
def test_both_prompt_fields_send_under_one_label(source):
    """One control at two magnifications must not say two things.

    The zoomed field's button read `Generate & print` while the landing field's, an
    inch behind it, read `Compile & preview`. A constant rather than a literal each
    side: a text guard can only notice the drift afterwards, and this is the loudest
    verb on the page.
    """
    # Past the imports: an identifier that is only imported is one nothing renders,
    # which is the state a literal written back in beside a surviving import leaves.
    rendered = _body(REPO_ROOT / source)
    assert "PROMPT_SUBMIT_LABEL" in rendered and "PROMPT_SUBMIT_BUSY_LABEL" in rendered, (
        f"{source} no longer renders its submit label from promptLimits.ts. The two "
        "prompt fields submit the same prompt through the same call."
    )
    for label in _prompt_submit_labels().values():
        assert label not in rendered, (
            f"{source} spells {label!r} as a literal beside the constant that holds "
            "it — which is how the two buttons came to disagree in the first place."
        )


def test_the_fixture_flag_reaches_the_blueprint_alt_text():
    """The caption and the alt text must not contradict each other.

    `BlueprintPreview` renders the frame whose visible caption says "a fixture, not a
    render of this prompt" on a fixture run. Without the flag its alt text claimed the
    blueprint was drawn from the prompt, so the sentence a screen reader got was the
    one the fixture badge exists to prevent.
    """
    preview = (REPO_ROOT / "web/src/components/BlueprintPreview.tsx").read_text()
    assert "usedFixtures" in preview
    assert "a fixture, not a render of this prompt" in preview
    new_job = (REPO_ROOT / "web/src/pages/NewJob.tsx").read_text()
    assert "usedFixtures={usedFixtures}" in new_job, (
        "NewJob renders BlueprintPreview without the fixture flag it has in hand "
        "(`used_reference_assets`), so the alt text cannot tell a fixture from a render."
    )


def test_the_blueprint_gate_still_describes_what_actually_runs():
    """Unchanged by this pass, on purpose.

    Phase 2 really does reconstruct a FLUX render on the generative path, and that
    gate is the last cheap place to stop it. Copy claiming otherwise would hide the
    one cost the gate exists to put in front of a person.
    """
    gate = (REPO_ROOT / "web/src/components/BlueprintGate.tsx").read_text()
    assert "Approve the blueprint · waiting on you" in gate
    assert "Nothing has been reconstructed yet." in gate
    assert "what carries over from this image is the shape" in gate


def test_the_fixture_captions_still_describe_what_actually_runs():
    """A bundled reference asset must never be captioned as this prompt's output.

    The `dev-` output prefix and `used_reference_assets` keep fixture runs out of the
    dataset; these sentences are the same honesty on the page a person is looking at.
    """
    new_job = (REPO_ROOT / "web/src/pages/NewJob.tsx").read_text()
    assert "Reference blueprint — a fixture, not a render of this prompt" in new_job
    assert "Phase 01 output — a blueprint image, not a dimensioned spec" in new_job
    assert "Reference mesh, repaired and scaled to the print bed" in new_job
    assert "Fixture inputs" in new_job


def test_the_unavailable_spec_reasons_stay():
    """The UI may describe the parametric pipeline; it may not claim a measurement.

    Nothing in the app composes a spec yet, so these three sentences are what its
    own panels show. A fits badge with no measurement behind it is the exact failure
    the Fits Check exists to prevent.
    """
    spec = (REPO_ROOT / "web/src/organizer/spec.ts").read_text()
    for name in ("NO_SPEC_REASON", "UNCOMPOSED_SPEC_REASON", "UNMEASURED_FIT_REASON"):
        assert f"export const {name} =" in spec


# ── The two screens the beta videos record (issue #189) ───────────────────────
#
# The composer and the settings page are filmed on 3 Oct 2026 and the recording
# cannot be edited after it is posted, so a label that is true for a few weeks is a
# label that is wrong in the material forever. Three of them were on screen and two
# had stopped being true of `main`: "Spec engine · not yet wired" claimed no LLM call
# and no dimension KB existed in this build, and `pythonsrc/organizer/dimensions.py`
# and `pythonsrc/organizer/box_kb.py` both ship; "Generative branch · benched" claimed
# the generative path was "still what phases 01 and 02 actually run", which stopped
# being true when the spec submit path landed (#76).
#
# This is the same weak-on-purpose text guard as everything else in this file: it
# catches the words coming back, not a new way of saying them.

#: Development-status vocabulary, and the two words this product does not say in front
#: of people (docs/WHERE-WE-ARE.md, 22 Sep 2026: never "AI"; the line is "calculated
#: from your sleeves"). Matched case-insensitively, on a word boundary that counts an
#: underscore as a letter: a bare `in` fires on "available" for "AI", and a boundary
#: that stops at `_` fires on the identifier `AI_SYSTEM_NOTICE_SHORT`, which is how
#: `NewJob.tsx` renders the exempted disclosure below rather than a second copy of it.
DEV_STATUS_WORDS = [
    "pre-beta",
    "not yet wired",
    "benched",
    "LLM",
    "AI",
    "spec engine",
]

#: The one exemption, and it is a legal one rather than an editorial one.
#:
#: EU AI Act Art. 50(1) applies from 2026-08-02, the Commission's May 2026 guidelines
#: put the duty on the **interface**, and `PromptNotice.tsx` is where this product
#: discharges it — wording approved by the owner on 2026-09-09 (#78) and used verbatim.
#: `tests/test_ip_notice.py` fails if that sentence leaves. Rewording a regulated
#: disclosure to keep a word off a screen recording is a legal decision, not a code
#: one; see `docs/deferred-legal-tasks.md`.
#:
#: Keyed by file **and** word, like FIGURINE_WORD_ALLOWED, so this buys nothing
#: anywhere else: "AI" in any other source, or any other banned word in this one, is
#: still a failure.
DEV_STATUS_ALLOWED = {
    ("web/src/components/PromptNotice.tsx", "AI"): "EU AI Act Art. 50(1) disclosure",
}


@pytest.mark.parametrize("word", DEV_STATUS_WORDS)
def test_no_visible_string_carries_the_development_status_vocabulary(word):
    pattern = re.compile(
        rf"(?<![A-Za-z_]){re.escape(word)}(?![A-Za-z_])", re.IGNORECASE
    )
    offenders = []
    for path in _sources():
        rel = str(path.relative_to(REPO_ROOT))
        if DEV_STATUS_ALLOWED.get((rel, word)):
            continue
        for match in pattern.finditer(_visible_text(path)):
            context = match.string[max(0, match.start() - 30) : match.start() + 40]
            offenders.append(f"{rel}: …{' '.join(context.split())}…")
    assert offenders == [], (
        f"{word!r} is in user-visible copy: {offenders}. The composer and the settings "
        "page are filmed for the beta videos and the recording cannot be edited "
        "afterwards — see issue #189. If a statement about what is or is not wired is "
        "genuinely needed, say it narrowly and cite the file that makes it true."
    )


def test_the_settings_page_states_only_what_a_file_on_main_makes_true():
    """Section 01's copy, bound to the modules it is a claim about.

    The block it replaced said "Neither exists in this build". Both do, so the
    replacement is a positive statement — card footprints, sleeve envelopes and
    curated box interiors ship — and these are the three modules that have to exist
    for it to be one. A weak test, deliberately: it cannot read the sentence, but it
    fails the day the sentence is a claim about deleted code.
    """
    for module in (
        "pythonsrc/organizer/dimensions.py",
        "pythonsrc/organizer/box_kb.py",
        "pythonsrc/data/game_boxes.v1.json",
    ):
        assert (REPO_ROOT / module).exists(), (
            f"{module} is gone, and `web/src/pages/PrinterSetup.tsx` section 01 tells "
            "people it ships. Either the copy or the module is wrong."
        )

    setup = (REPO_ROOT / "web/src/pages/PrinterSetup.tsx").read_text()
    assert "Measurements ship with the app" in setup


def test_the_developer_disclosure_is_closed_and_keeps_everything_reachable():
    """Nothing was deleted to clear the screen — it was collapsed.

    The HuggingFace token, the two phase-skip switches, both simulator cards, the log
    level and the API token all still render; they are behind a `<details>` with no
    `open`, at every width. `web/e2e/viewports.spec.ts` opens it in a browser and
    checks the controls work; this is the cheap half that runs in `pytest tests/`.
    """
    setup = (REPO_ROOT / "web/src/pages/PrinterSetup.tsx").read_text()

    assert "<details className={styles.dev}>" in setup, (
        "The Developer section is no longer a closed disclosure. It holds developer "
        "configuration that reads as an unfinished product on a first-run screen."
    )
    for control in ("hf-token", "SKIP_VISUALIZER", "SKIP_SCULPTOR", "LOG_LEVEL",
                    "ApiTokenField", "settings-simulators", "handleSimAction"):
        assert control in setup, (
            f"{control} is gone from the settings page. Issue #189 moved these behind "
            "a disclosure; it did not remove any of them."
        )
