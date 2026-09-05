"""licence_policy.py — what this project may link, and what a licence string means.

Daedal Studio ships under Apache-2.0 (`LICENSE`), and `THIRD-PARTY-NOTICES.md` records
the reasoning for every component. This module is the *machine-readable* half of that:
the classification a licence string maps to, and the verdict a package earns from it.

It exists because the audit ran on human judgement alone and therefore ran on whatever
was in view. A dependency tree read from `requirements-base.txt` and `package.json` is
the set of packages somebody remembered to name — the resolved tree is two orders of
magnitude larger, and the packages that broke this grant twice (`pymeshfix`,
`briaai/RMBG-2.0`) were both reached transitively, by something else's default. So the
tree is captured in CI (`licenses/`, `.github/workflows/licence-data.yml`) and scored
here.

Three properties matter more than the rule list itself:

* **One list, not one per scanner.** `tests/test_licensing_guards.py` imports the same
  constants. A scanner carrying its own copy of "packages we must never install" is a
  scanner that disagrees with the tests the first time either is edited.
* **Arm's-length components are recorded, not rediscovered.** CuraEngine is AGPL-3.0
  and *is* allowed, because it is a CLI subprocess. An SBOM of the pipeline image will
  report it every single week; without `ARM_LENGTH_COMPONENTS` the weekly audit reports
  the same resolved finding forever and the one new AGPL package hides in the noise.
* **A licence this module cannot read is `UNKNOWN`, never `PERMISSIVE`.** Unknown is a
  flag — something for a person to read — because the two incidents in this repo were
  both cases of a tag that said one thing and a licence text that said another.

Torch-free and stdlib-only on purpose: it is imported by CI, by the test suite, and
potentially by the api-server image, none of which have the Phase 1/2 stack.
"""

from __future__ import annotations

from typing import Iterable

#: The licence this project grants under. A dependency that cannot be sublicensed
#: under it is a finding, not a preference.
PROJECT_LICENCE = "Apache-2.0"

# ── Classifications ──────────────────────────────────────────────────────────

PERMISSIVE = "permissive"
WEAK_COPYLEFT = "weak_copyleft"
STRONG_COPYLEFT = "strong_copyleft"
NON_COMMERCIAL = "non_commercial"
UNKNOWN = "unknown"

#: Least to most restrictive. Used to resolve SPDX `OR` (take the most permissive
#: operand — a dual-licensed package is used under the half that suits) and `AND`
#: (take the most restrictive — both apply at once). `UNKNOWN` sits mid-list rather
#: than last: an unreadable licence must not make a genuinely non-commercial operand
#: look like the lesser problem.
RESTRICTION_ORDER = (
    PERMISSIVE,
    WEAK_COPYLEFT,
    UNKNOWN,
    STRONG_COPYLEFT,
    NON_COMMERCIAL,
)

# ── Verdicts ─────────────────────────────────────────────────────────────────

ALLOW = "allow"
FLAG = "flag"
DENY = "deny"

SEVERITY_ORDER = (ALLOW, FLAG, DENY)

# ── Package-level rules ──────────────────────────────────────────────────────

#: Packages under the NVIDIA Source Code License — non-commercial research only.
#: Upstream TRELLIS.2's documented install line asks for both; the shape-only path
#: avoids them structurally. GitHub reports their licence as "Other", which is why
#: the names are pinned here rather than left to classification.
FORBIDDEN_RENDERER_PACKAGES = ("nvdiffrast", "nvdiffrec")

#: Python distributions that would put an AGPL-3.0 component *in-process*. Installing
#: any of them turns § 13 into an obligation to offer this project's source to every
#: user of the service. `octoprint` is the server itself; the other three are Ultimaker
#: libraries that link CuraEngine's internals rather than shelling out to its CLI.
AGPL_IN_PROCESS_PACKAGES = ("octoprint", "libarcus", "libsavitar", "uranium")

#: Copyleft components this project deliberately uses, and the isolation that makes
#: them safe. Keyed by the name an SBOM or a package manager reports, so a match here
#: is a *recorded* finding rather than a fresh one every audit. Adding a name here is
#: a licensing decision: it must be justified in `THIRD-PARTY-NOTICES.md` first.
ARM_LENGTH_COMPONENTS = {
    "cura-engine": "AGPL-3.0, invoked as a CLI subprocess (pythonsrc/slicer.py). Never linked.",
    "curaengine": "AGPL-3.0, invoked as a CLI subprocess (pythonsrc/slicer.py). Never linked.",
    "octoprint": "AGPL-3.0, reached over HTTP/SockJS (pythonsrc/operators/). Never imported.",
}

#: Container images this project *talks to* rather than builds on, keyed by the stem of
#: their SBOM in `licenses/sbom/`. Nothing of ours runs inside them, so **every** package
#: they contain — wheels included — is in someone else's process.
#:
#: This distinction is not cosmetic and it is not the same as "is it a base image".
#: `python:3.10-slim` and `nvidia/cuda` are scanned too, and a wheel in either of those
#: really does end up imported by our code, because our images are built *on* them.
#: `octoprint/octoprint` is the one scanned image that is a peer service: the operators
#: in `pythonsrc/operators/` reach it over HTTP and SockJS, which is exactly the isolation
#: `ARM_LENGTH_COMPONENTS` records for the distribution of the same name.
#:
#: Getting this wrong is what made every merge to `main` red: the report scored
#: OctoPrint's own AGPL plugins as in-process denials, so the one signal the gate exists
#: to carry — a *new* copyleft package in a tree we link — arrived buried under six
#: standing false positives.
ARM_LENGTH_IMAGE_SBOMS = {
    "octoprint": (
        "octoprint/octoprint:latest — a peer service reached over HTTP/SockJS "
        "(pythonsrc/operators/). Nothing here imports anything inside this image."
    ),
}


def arm_length_image(sbom_stem: str) -> str | None:
    """The isolation note for an SBOM stem, or None when the image is one we link.

    Takes the stem rather than the image ref because that is what the report has: the
    `base-` prefix is how `licence-data.yml` names a registry scan, and it says nothing
    about whether our code runs inside.
    """
    key = (sbom_stem or "").strip().lower()
    if key.startswith("base-"):
        key = key[len("base-") :]
    return ARM_LENGTH_IMAGE_SBOMS.get(key)

#: Requirement specifiers whose *extra* drags in a copyleft package. The specifier looks
#: innocuous and the licence arrives two levels down, which is why this is a named list
#: rather than a thing to notice in review: `trimesh[all]` includes trimesh's own
#: `test-more` extra, so a production image gets trimesh's **test** dependencies —
#: `pymeshlab` (GPL-3.0) and `triangle` (LGPL-3.0). Caught by the first run of the
#: committed audit, having been installed in two images since Phase 3 was written.
EXTRAS_THAT_PULL_COPYLEFT = {
    "trimesh[all]": (
        "trimesh's `all` extra includes `test-more`, which installs pymeshlab (GPL-3.0) "
        "and triangle (LGPL-3.0). Use `trimesh[easy]` for the runtime extras."
    ),
}

def find_copyleft_extras(text: str) -> list[str]:
    """Return `"specifier — reason"` for each copyleft-pulling extra named in `text`.

    Takes the whole manifest rather than a line: a Dockerfile wraps one `pip install`
    across a dozen continuations, and a line-by-line scan of that is a scan of
    fragments.
    """
    return [
        f"{specifier} — {reason}"
        for specifier, reason in EXTRAS_THAT_PULL_COPYLEFT.items()
        if specifier in text
    ]


#: Python distributions that Ubuntu's own `python3` install puts in `dist-packages`.
#: They are in the interpreter's path inside every image built on `ubuntu:22.04`, appear
#: in no requirements file, and are imported by nothing in this project. `python-apt` is
#: GPL-2 and was the first real finding of the committed audit — reported as a denial,
#: which was the wrong answer: nothing chose it and nothing links it. It is not an
#: `ALLOW` either, because a distributed image would carry source-offer obligations for
#: it, so it stays a recorded flag.
DISTRO_PROVIDED_PACKAGES = (
    "python-apt",
    "unattended-upgrades",
    "command-not-found",
    "distro-info",
    "ubuntu-advantage-tools",
    "ufw",
)

#: Weak-copyleft payloads already reviewed and accepted, with the reason. LGPL is
#: satisfied by dynamic linking and by shipping the library unmodified, but each
#: instance is a judgement, so the accepted ones are named rather than blanket-passed.
#: Anything LGPL *not* on this list stays a flag.
_PSYCOPG_NOTE = (
    "LGPL-3.0-only. The PostgreSQL driver for the telemetry database "
    "(pythonsrc/telemetry/db.py, server/config_store.py). Imported unmodified as a "
    "separate wheel — the dynamic linking the LGPL permits — and replaceable by "
    "reinstalling it; the licence text ships with the wheel. Recorded in "
    "THIRD-PARTY-NOTICES.md § 1, 'Weak copyleft — library-level'."
)

REVIEWED_WEAK_COPYLEFT = {
    "opencv-python-headless": (
        "Bundles FFmpeg (LGPLv2.1) as a shared library; the headless wheel is pinned "
        "precisely to keep the Qt 5 (LGPLv3) payload of the GUI wheels out. Nothing in "
        "this project imports cv2."
    ),
    # psycopg 3 and its two companion distributions. `psycopg-binary` carries the C
    # speedups and a bundled libpq (PostgreSQL Licence, permissive); `psycopg-pool`
    # is the connection pool. Listed under both spellings because pip-licenses and
    # syft normalise distribution names differently.
    "psycopg": _PSYCOPG_NOTE,
    "psycopg-binary": _PSYCOPG_NOTE,
    "psycopg_binary": _PSYCOPG_NOTE,
    "psycopg-pool": _PSYCOPG_NOTE,
    "psycopg_pool": _PSYCOPG_NOTE,
}

# ── Licence-string classification ────────────────────────────────────────────
#
# Matched against a normalised, lower-cased string. Order matters: LGPL contains
# "gpl-3" as a substring, so the weak patterns must be tried before the strong ones,
# or every LGPL package is reported as a § 13 problem.

_NON_COMMERCIAL_PATTERNS = (
    "cc-by-nc",
    "cc by-nc",
    "by-nc-",
    "by-nc ",
    "noncommercial",
    "non-commercial",
    "non commercial",
    "nvidia source code license",
    "nvidia-source-code",
    "research only",
    "research purposes only",
    "academic use only",
    "prosperity",  # Prosperity Public Licence — commercial use is time-limited
)

_WEAK_COPYLEFT_PATTERNS = (
    "lgpl",
    "lesser general public",
    "library general public",
    "mpl",
    "mozilla public",
    "epl",
    "eclipse public",
    "cddl",
    "cecill-c",
    "ms-rl",
)

_STRONG_COPYLEFT_PATTERNS = (
    "agpl",
    "affero",
    "gpl",
    "general public",
    "sspl",
    "server side public",
    "osl-3",
    "eupl",
)

_PERMISSIVE_PATTERNS = (
    "mit",
    "bsd",
    "apache",
    "isc",
    "python software foundation",
    "psf",
    "python-2.0",
    "cnri",
    "mit-0",
    "x11",
    "zlib",
    "unlicense",
    "cc0",
    "public domain",
    "wtfpl",
    "boost",
    "postgresql",
    "blue oak",
    "hpnd",
    "libpng",
    "openssl",
    "zpl",
    "sil open font",
    "ofl-1.1",
    "ftl",
    "afl",
    "artistic",
    "curl",
    "ncsa",
    "bsl-1.0",
    "cc-by-4.0",
    "cc-by-3.0",
)

#: What pip-licenses and license-checker emit when a package declares nothing.
_EMPTY_LICENCE_TOKENS = frozenset(
    {"", "unknown", "none", "null", "n/a", "na", "-", "other", "see license file"}
)


def normalise_licence(licence: str | None) -> str:
    """Lower-case and collapse whitespace so pattern matching is not defeated by
    formatting. `"GNU  Lesser General Public License v2 or later (LGPLv2+)"` and
    `"lgpl-2.1-or-later"` must reach the same classification.
    """
    if not licence:
        return ""
    text = " ".join(str(licence).split()).strip().strip("()").lower()
    # "GPL-2.0 or later" is one licence with a version floor, not a choice between two.
    # Left in place it splits on " or " into "gpl-2.0" and "later", and the OR rule then
    # picks the more permissive half — reporting a GPL package as unclassified.
    for qualifier in (
        " or any later version",
        " or later version",
        " or later",
        " or newer",
        " or greater",
        " or above",
    ):
        text = text.replace(qualifier, "+")
    return text


def _classify_atom(text: str) -> str:
    if text in _EMPTY_LICENCE_TOKENS:
        return UNKNOWN
    for pattern in _NON_COMMERCIAL_PATTERNS:
        if pattern in text:
            return NON_COMMERCIAL
    for pattern in _WEAK_COPYLEFT_PATTERNS:
        if pattern in text:
            return WEAK_COPYLEFT
    for pattern in _STRONG_COPYLEFT_PATTERNS:
        if pattern in text:
            return STRONG_COPYLEFT
    for pattern in _PERMISSIVE_PATTERNS:
        if pattern in text:
            return PERMISSIVE
    return UNKNOWN


def _split_expression(text: str, separator: str) -> list[str]:
    return [part for part in (p.strip(" ()") for p in text.split(separator)) if part]


def _most(classifications: Iterable[str], *, restrictive: bool) -> str:
    ranked = sorted(
        classifications,
        key=lambda c: RESTRICTION_ORDER.index(c) if c in RESTRICTION_ORDER else 0,
    )
    if not ranked:
        return UNKNOWN
    return ranked[-1] if restrictive else ranked[0]


#: How a tool joins several declared licences for one package. pip-licenses joins PyPI
#: classifiers with "; ", which is neither an SPDX `AND` nor an `OR`: `docutils` declares
#: "BSD License; GNU General Public License (GPL); Public Domain" because different files
#: in it carry different licences. Read as `AND` that is a denial; read as `OR` it is
#: permissive; the truth is that a person has to open the package.
_DECLARATION_SEPARATORS = (";",)


def is_mixed_declaration(licence: str | None) -> bool:
    """True when a package declares several licences that do not agree.

    A mixed declaration is not a licence, it is a reading task — so it earns a flag
    rather than the verdict of whichever operand happens to be strictest.
    """
    text = normalise_licence(licence)
    for separator in _DECLARATION_SEPARATORS:
        if separator not in text:
            continue
        parts = _split_expression(text, separator)
        if len(parts) > 1 and len({_classify_atom(p) for p in parts}) > 1:
            return True
    return False


#: Above this length a declaration is not an expression, it is the licence *text*.
#: `cascadio`, `embreex` and `xatlas` all put their full licence in the metadata field,
#: and MIT's own text contains " and " a dozen times ("…to use, copy, modify, merge …
#: and to permit persons…") — so expression-splitting turned three permissive packages
#: into `unknown` and asked a person to read what the tool had just been handed.
_EXPRESSION_MAX_CHARS = 200


def classify(licence: str | None) -> str:
    """Classify a licence string as one of the five classifications.

    Handles SPDX expressions the way a licensee actually uses them: `OR` means the
    project may pick, so the *most permissive* operand governs; `AND` means both bind,
    so the *most restrictive* does. A string this function cannot place is `UNKNOWN`
    rather than optimistically permissive — `openai/clip-vit-*` is tagged MIT and its
    model card forbids all deployed use, so a tag is evidence, not a verdict.
    """
    text = normalise_licence(licence)
    if not text:
        return UNKNOWN

    # Licence text rather than a licence expression: match patterns against the whole
    # thing. A GPL text still says "gnu general public"; an MIT text still says "mit".
    if len(text) > _EXPRESSION_MAX_CHARS:
        return _classify_atom(text)

    for separator, restrictive in ((";", True), (" and ", True), (" or ", False), ("|", False)):
        if separator in text:
            parts = _split_expression(text, separator)
            if len(parts) > 1:
                return _most((classify(p) for p in parts), restrictive=restrictive)

    return _classify_atom(text)


def verdict(
    package: str,
    licence: str | None,
    *,
    in_process: bool = True,
) -> tuple[str, str, str]:
    """Score one package. Returns `(severity, classification, note)`.

    `in_process` is the question the licence text turns on: AGPL-3.0 is a hard stop for
    a library this project imports and entirely fine for a binary it execs. Callers that
    read an OS-package SBOM pass `in_process=False`, because a `.deb` in an image is not
    linked into anything by being installed — what makes CuraEngine safe is
    `pythonsrc/slicer.py` calling it as a subprocess, which is asserted by the test
    suite rather than inferred here.
    """
    name = (package or "").strip().lower()
    classification = classify(licence)

    if any(forbidden in name for forbidden in FORBIDDEN_RENDERER_PACKAGES):
        return (
            DENY,
            NON_COMMERCIAL,
            "NVIDIA Source Code License — non-commercial research only. Never install; "
            "a permissive rasterizer (PyTorch3D, BSD-3-Clause) is the only option.",
        )

    # Checked before ARM_LENGTH_COMPONENTS, and only when in-process: `octoprint`
    # installed as a Python distribution is a § 13 problem, while `octoprint` reported
    # by an image SBOM is the arm's-length server this project talks HTTP to. Same
    # name, opposite verdicts — the caller's `in_process` is what separates them.
    if name in AGPL_IN_PROCESS_PACKAGES and in_process:
        return (
            DENY,
            classification if classification != UNKNOWN else STRONG_COPYLEFT,
            "Would put an AGPL-3.0 component in-process. § 13 then obliges offering "
            "this project's source to every user of the service.",
        )

    if name in ARM_LENGTH_COMPONENTS:
        return ALLOW, classification, ARM_LENGTH_COMPONENTS[name]

    if name in DISTRO_PROVIDED_PACKAGES:
        return (
            FLAG,
            classification,
            "Provided by Ubuntu's own python3 install, not by any requirements file, and "
            "imported by nothing here. Would carry source-offer obligations if the image "
            "were ever distributed.",
        )

    if is_mixed_declaration(licence):
        return (
            FLAG,
            classification,
            f"Several licences declared at once ({licence}). Which one governs depends on "
            "the file, so this needs a person rather than a verdict.",
        )

    if classification == NON_COMMERCIAL:
        return DENY, classification, "Commercial use is restricted or requires a negotiated agreement."

    if classification == STRONG_COPYLEFT:
        if in_process:
            return DENY, classification, "Strong copyleft in-process is incompatible with the Apache-2.0 grant."
        return (
            FLAG,
            classification,
            "Strong copyleft present in an image. Confirm it is reached as a subprocess "
            "or over the network, and record the isolation in THIRD-PARTY-NOTICES.md.",
        )

    if classification == WEAK_COPYLEFT:
        if name in REVIEWED_WEAK_COPYLEFT:
            return ALLOW, classification, REVIEWED_WEAK_COPYLEFT[name]
        return (
            FLAG,
            classification,
            "Weak copyleft. Satisfied by dynamic linking and unmodified shipping, but "
            "each instance needs a recorded decision.",
        )

    if classification == UNKNOWN:
        return FLAG, classification, "No readable licence declared. Read the package's own licence text."

    return ALLOW, classification, ""


def worst_severity(severities: Iterable[str]) -> str:
    """The highest severity in a set, for a report's headline verdict."""
    ranked = sorted(
        severities,
        key=lambda s: SEVERITY_ORDER.index(s) if s in SEVERITY_ORDER else 0,
    )
    return ranked[-1] if ranked else ALLOW
