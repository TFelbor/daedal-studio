"""licence_policy.py — what this project may link, and what a licence string means.

Prompt2Print ships under Apache-2.0 (`LICENSE`), and `THIRD-PARTY-NOTICES.md` records
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

#: Weak-copyleft payloads already reviewed and accepted, with the reason. LGPL is
#: satisfied by dynamic linking and by shipping the library unmodified, but each
#: instance is a judgement, so the accepted ones are named rather than blanket-passed.
#: Anything LGPL *not* on this list stays a flag.
REVIEWED_WEAK_COPYLEFT = {
    "opencv-python-headless": (
        "Bundles FFmpeg (LGPLv2.1) as a shared library; the headless wheel is pinned "
        "precisely to keep the Qt 5 (LGPLv3) payload of the GUI wheels out. Nothing in "
        "this project imports cv2."
    ),
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

    for separator, restrictive in ((" and ", True), (" or ", False), ("|", False)):
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
