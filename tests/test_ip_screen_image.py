"""The blueprint-image screen: what it must not store, load, or write.

Prompt filtering leaks. "A chunky yellow lightning-mouse, anime style" defeats a name
blocklist and still renders something recognisable, which is why this layer exists —
and why the literature is explicit that prompt-level mitigation is not sufficient on
its own.

Three properties are load-bearing and are all asserted here:

1. **No reference images.** The comparison is image-against-*text*: the blocklist terms
   are embedded as strings. Caching reference crops of protected characters to improve
   recall would mean this repo shipping the very material it exists to avoid.
2. **A rejected render is never written.** The screen runs on the in-memory image
   before `image.save`, because the path it would be saved to is the *shared*
   `data/inputs/blueprint.png` — what Phase 2 reads and what `resolve_job_artifact`
   serves as "the blueprint" for any job.
3. **The weights are permissive, checked by outcome.** `openai/clip-vit-base-patch32`
   is the trap: the repo tag says MIT while the model card's own out-of-scope section
   says "Any deployed use case of the model — whether commercial or not — is currently
   out of scope". Reading the tag is not reading the licence.

No weights are downloaded by this module's tests — the model is stubbed the way
`test_licensing_guards.py` stubs upstream's matte model.
"""

import types

import pytest

from pythonsrc import ip_screen_image

# ── The licence guard ─────────────────────────────────────────────────────────

def test_the_default_checkpoint_is_a_permissive_one():
    """Apache-2.0, and no out-of-scope clause forbidding deployment."""
    assert ip_screen_image.assert_permissive_vision_model(ip_screen_image.DEFAULT_MODEL_ID)


@pytest.mark.parametrize("denied", [
    "openai/clip-vit-base-patch32",
    "openai/clip-vit-large-patch14",
    "briaai/RMBG-2.0",
])
def test_known_encumbered_checkpoints_are_refused(denied):
    """Refused at the door, not discovered in an audit."""
    with pytest.raises(ValueError, match="not permissively licensed"):
        ip_screen_image.assert_permissive_vision_model(denied)


@pytest.mark.parametrize("spelling", [
    "openai/CLIP-ViT-Base-Patch32",
    "  openai/clip-vit-base-patch32  ",
    "openai/clip-vit-base-patch32@a1b2c3d",
    "hf.co/openai/clip-vit-base-patch32",
])
def test_the_deny_list_is_not_defeated_by_spelling(spelling):
    """A raw string comparison was already beaten once here, by a `repo@sha` pin."""
    with pytest.raises(ValueError, match="not permissively licensed"):
        ip_screen_image.assert_permissive_vision_model(spelling)


def test_a_configured_model_is_checked_not_trusted(monkeypatch):
    """`$DS_IP_MODEL_ID` is an override for pinning a revision, not for opting out."""
    monkeypatch.setenv("DS_IP_MODEL_ID", "openai/clip-vit-base-patch32")
    with pytest.raises(ValueError, match="not permissively licensed"):
        ip_screen_image.resolve_model_id()


def test_a_pinned_revision_is_preserved(monkeypatch):
    """Pinning is the reason the override exists, so it must survive the check."""
    pinned = f"{ip_screen_image.DEFAULT_MODEL_ID}@0123456789abcdef"
    monkeypatch.setenv("DS_IP_MODEL_ID", pinned)
    assert ip_screen_image.resolve_model_id() == pinned


# ── No reference images, ever ─────────────────────────────────────────────────

def test_every_candidate_is_a_string():
    """The comparison is text-side. A bytes or Path candidate means someone started
    caching reference crops of the characters this screen exists to detect."""
    for label in ip_screen_image.candidate_labels():
        assert isinstance(label, str), label


def test_the_package_ships_no_image_assets():
    """The guard against 'improving recall' by adding reference pictures."""
    from pathlib import Path

    root = Path(ip_screen_image.__file__).parent
    offenders = [
        p for p in (root / "data").rglob("*")
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
    ]
    assert offenders == [], f"reference images found: {offenders}"


def test_the_candidates_cover_the_curated_blocklist():
    """One source of truth: the terms Tier 1 refuses are the terms this looks for."""
    from pythonsrc.ip_screen import load_blocklist

    labels = " | ".join(ip_screen_image.candidate_labels()).lower()
    for entry in load_blocklist()[:12]:
        assert entry["term"].lower() in labels, entry["term"]


def test_there_are_control_labels_to_lose_against():
    """Without neutral candidates every image 'matches' whichever term is least wrong.

    A softmax over protected terms alone has no way to say "this is just a vase".
    """
    assert ip_screen_image.CONTROL_LABELS
    labels = ip_screen_image.candidate_labels()
    assert len(labels) > len(ip_screen_image.CONTROL_LABELS)


# ── The verdict is advisory until it is calibrated ────────────────────────────

def test_the_screen_is_advisory_by_default():
    """The threshold is not calibrated against real renders yet, and a false positive
    that fails Phase 1 has no appeal. So it flags for the human gate rather than
    refusing, and turning that up is an explicit env change."""
    assert ip_screen_image.DEFAULT_ENFORCEMENT == "advisory"


def test_an_unavailable_model_abstains_rather_than_failing_the_job(monkeypatch):
    """No torch, no transformers, no weights — the screen reports that it did not run.

    `not_checked` and a logged reason. Silently returning "clean" would make an absent
    screen indistinguishable from a passing one, which is the same mistake the
    printability error envelope exists to prevent.
    """
    monkeypatch.setattr(ip_screen_image, "_load_model", lambda: (_ for _ in ()).throw(
        ImportError("no transformers here"),
    ))
    ip_screen_image.reset_model_cache()

    verdict = ip_screen_image.screen_image(object())

    assert verdict.action == "not_checked"
    assert verdict.reason


def test_a_confident_match_flags_and_names_the_term(monkeypatch):
    """The scoring path, with the model stubbed — no weights, no network."""
    labels = ip_screen_image.candidate_labels()
    target = next(i for i, l in enumerate(labels) if "pikachu" in l.lower())
    scores = [0.001] * len(labels)
    scores[target] = 0.97

    monkeypatch.setattr(ip_screen_image, "_load_model", lambda: types.SimpleNamespace(
        score=lambda image: scores,
    ))
    ip_screen_image.reset_model_cache()

    verdict = ip_screen_image.screen_image(object())

    assert verdict.action == "flag"
    assert "pikachu" in (verdict.term or "").lower()
    assert verdict.score == pytest.approx(0.97, rel=1e-3)


def test_a_control_label_winning_is_a_pass(monkeypatch):
    """An ordinary object must not be flagged because some term scored least-wrong."""
    labels = ip_screen_image.candidate_labels()
    control = next(
        i for i, l in enumerate(labels) if l in ip_screen_image.CONTROL_LABELS
    )
    scores = [0.001] * len(labels)
    scores[control] = 0.9

    monkeypatch.setattr(ip_screen_image, "_load_model", lambda: types.SimpleNamespace(
        score=lambda image: scores,
    ))
    ip_screen_image.reset_model_cache()

    verdict = ip_screen_image.screen_image(object())

    assert verdict.action == "allow"


# ── A rejected render is never written ────────────────────────────────────────

def test_a_blocked_render_is_not_written_to_disk(monkeypatch, tmp_path):
    """The path it would be written to is the *shared* blueprint.

    `data/inputs/blueprint.png` is what Phase 2 reads and what `resolve_job_artifact`
    serves as "the blueprint" for any job, so a refused render saved "just to look at
    later" becomes some other job's input. Screen first, then save.
    """
    class Recorder:
        def __init__(self):
            self.saved = False

        def save(self, path):
            self.saved = True
            open(path, "wb").write(b"png")

    monkeypatch.setattr(ip_screen_image, "screen_image", lambda image: ip_screen_image.ImageVerdict(
        "block", "pikachu", 0.99, "resembles pikachu",
    ))

    image = Recorder()
    out = tmp_path / "blueprint.png"

    with pytest.raises(ip_screen_image.BlueprintRefused, match="pikachu"):
        ip_screen_image.save_screened(image, out)

    assert not image.saved
    assert not out.exists()


def test_an_allowed_render_is_written_and_its_verdict_returned(monkeypatch, tmp_path):
    class Recorder:
        def save(self, path):
            open(path, "wb").write(b"png")

    monkeypatch.setattr(ip_screen_image, "screen_image", lambda image: ip_screen_image.ImageVerdict(
        "allow", None, 0.1, "clean",
    ))

    out = tmp_path / "blueprint.png"
    verdict = ip_screen_image.save_screened(Recorder(), out)

    assert out.exists()
    assert verdict.action == "allow"


def test_a_flagged_render_is_still_written(monkeypatch, tmp_path):
    """Advisory means advisory: the image is produced and the flag travels with it.

    Refusing on a flag would make an uncalibrated threshold fail jobs with no appeal —
    which is what the human blueprint gate is for.
    """
    class Recorder:
        def save(self, path):
            open(path, "wb").write(b"png")

    monkeypatch.setattr(ip_screen_image, "screen_image", lambda image: ip_screen_image.ImageVerdict(
        "flag", "pikachu", 0.6, "resembles pikachu",
    ))

    out = tmp_path / "blueprint.png"
    verdict = ip_screen_image.save_screened(Recorder(), out)

    assert out.exists()
    assert verdict.action == "flag"
    assert verdict.term == "pikachu"


def test_an_unavailable_screen_does_not_block_the_pipeline(monkeypatch, tmp_path):
    """Phase 1 must not fail because the screen could not load."""
    class Recorder:
        def save(self, path):
            open(path, "wb").write(b"png")

    monkeypatch.setattr(ip_screen_image, "screen_image", lambda image: ip_screen_image.ImageVerdict(
        "not_checked", None, 0.0, "no transformers",
    ))

    out = tmp_path / "blueprint.png"
    verdict = ip_screen_image.save_screened(Recorder(), out)

    assert out.exists()
    assert verdict.action == "not_checked"
