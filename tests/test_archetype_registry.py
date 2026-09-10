"""Three lists that must name the same archetypes, in three languages.

`spec.ARCHETYPES` is what the schema accepts, `archetypes.REGISTRY` is what can compile,
and `ARCHETYPES` in `web/src/organizer/spec.ts` is what the composer offers. The first
two already check each other at import — `archetypes/__init__.py` raises if the schema
names something with no compiler. The third had drifted all the way: the strip offered
`dice_tray`, `box_insert` and `dividers`, and none of the three existed, so a person
could pick a shape the engine would refuse and get something else without being told.
That is the same class of failure as a fits badge with no measurement behind it, and a
screenshot of it outlives any caveat.

There is no test runner in `web/`, so this is the only thing that keeps the strip
honest — the `tests/test_download_formats.py` precedent, which binds the formats the
endpoint serves to the ones the UI offers by reading the TSX. Read as text on purpose:
importing the module would need a bundler, and the point is the literal a reviewer sees.

Every module in the registry must also expose the whole archetype API. That is what
"adding an archetype is adding a module and a line" means, and it is the property the
second archetype existed to test: `pipeline.py --spec`, the CLI and Phase 3's assert
path took no archetype-specific change to gain the divider.
"""
import re
from pathlib import Path

import pytest

from pythonsrc.organizer.archetypes import REGISTRY, example_spec
from pythonsrc.organizer.spec import ARCHETYPES

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_SPEC = REPO_ROOT / "web" / "src" / "organizer" / "spec.ts"

#: Every name an archetype module must expose. The registry dispatches through all of
#: them; a module missing one fails at the call site, phases into a run.
ARCHETYPE_API = (
    "ARCHETYPE", "ARCHETYPE_VERSION", "MEASURED_FEATURES",
    "derive", "validate", "build", "compile", "example",
    "measure", "fits_check", "to_view",
)


def web_archetype_ids() -> list[str]:
    """The `id`s in `ARCHETYPES` in `web/src/organizer/spec.ts`, in order."""
    text = WEB_SPEC.read_text(encoding="utf-8")
    block = re.search(r"export const ARCHETYPES = \[(.*?)\] as const;", text, re.S)
    assert block, f"could not find the ARCHETYPES literal in {WEB_SPEC}"
    return re.findall(r"id:\s*'([^']+)'", block.group(1))


def test_the_schema_and_the_registry_name_the_same_archetypes():
    assert set(ARCHETYPES) == set(REGISTRY)


def test_the_ui_offers_exactly_the_archetypes_the_engine_can_compile():
    assert web_archetype_ids() == list(ARCHETYPES)


def test_the_ui_labels_every_archetype_it_offers():
    text = WEB_SPEC.read_text(encoding="utf-8")
    block = re.search(r"export const ARCHETYPES = \[(.*?)\] as const;", text, re.S)
    pairs = re.findall(r"\{\s*id:\s*'([^']+)',\s*label:\s*'([^']+)'\s*\}", block.group(1))
    assert [p[0] for p in pairs] == web_archetype_ids()
    assert all(label.strip() for _, label in pairs)


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_archetype_exposes_the_whole_api(name):
    module = REGISTRY[name]
    missing = [verb for verb in ARCHETYPE_API if not hasattr(module, verb)]
    assert not missing, f"{name} is missing {missing}"
    assert module.ARCHETYPE == name
    assert isinstance(module.ARCHETYPE_VERSION, str) and module.ARCHETYPE_VERSION


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_archetypes_example_names_itself_and_declares_its_measurements(name):
    spec = example_spec(name)
    assert spec.archetype == name
    features = set(REGISTRY[name].MEASURED_FEATURES)
    assert features, f"{name} promises to measure nothing"
    assert features <= set(REGISTRY[name].compile(spec).features)
