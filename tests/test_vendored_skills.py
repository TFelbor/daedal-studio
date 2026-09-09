"""The vendored agent skills, bound to the three things that make them work.

`.claude/skills/` holds third-party skills copied into this repository so the
`claude-implement` and `claude-review` jobs can load them at a pinned commit —
see `docs/PIPELINE.md` § Skills are vendored, not installed for why a copy rather
than the action's `plugins` input.

Nothing checked that set. `tests/test_licensing_guards.py`, `licence_report.py`,
`.github/workflows/licence-data.yml` and `licenses/` between them have no mention
of `.claude/skills/`, and the `THIRD-PARTY-NOTICES.md` § 2 table listing each
skill's upstream, version and licence was maintained by hand with nothing
comparing it to the tree. So a directory added without its upstream `LICENSE`, a
notices row left behind by a deletion, and a skill nobody can invoke were all
green. Each of the four guards below closes one of those, and each failure mode
is silent in a diff:

* **`LICENSE` in every directory.** Vendoring is redistribution. Apache-2.0 stays
  coherent only if the upstream notice travels with the copy, and CLAUDE.md is
  explicit that a licence break is not an ordinary failure.
* **The `.gitignore` allowlist and the tree agree, in both directions.**
  `.claude/skills/*` is ignored and individual directories are un-ignored by
  name, so a new skill that nobody adds to that list is simply absent from CI —
  the workflows look right and the skill was never there. A stale `!` line is the
  same bug from the other side.
* **The notices table and the tree agree, in both directions.** A row with no
  directory attributes something this project does not ship; a directory with no
  row ships something it does not attribute.
* **`Skill` on `--allowedTools`.** Discovery is automatic — the action leaves
  `settingSources` at `["user", "project", "local"]`
  (`base-action/src/parse-sdk-options.ts`), so the checkout's own skills are
  indexed — but the tool allowlist is exhaustive. Without `Skill` the model sees
  every description and can invoke none of them. Nothing in the log says so.

Everything here is static: no skill is executed, no model is called.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
GITIGNORE = REPO_ROOT / ".gitignore"
NOTICES = REPO_ROOT / "THIRD-PARTY-NOTICES.md"

#: The workflows that load skills, and therefore must allow the `Skill` tool.
#: `claude-plan.yml` is deliberately absent — it is given no skills, so it needs
#: no allowance, and `claude-automerge.yml` calls no model at all.
SKILL_LOADING_WORKFLOWS = ("claude-implement.yml", "claude-review.yml")

#: A vendored skill cannot reach another skill through a plugin namespace: the
#: `superpowers:` and `ecc:` prefixes resolve for a marketplace install and not
#: for a skill loaded out of a repository. Those references were rewritten on
#: vendoring (recorded in THIRD-PARTY-NOTICES.md § 2); this is what keeps a
#: re-vendored copy from quietly reintroducing them.
PLUGIN_NAMESPACE_RE = re.compile(r"\b(?:superpowers|ecc|anthropic-skills):[a-z0-9-]+")


def _vendored_dirs() -> list[Path]:
    if not SKILLS_DIR.is_dir():
        return []
    return sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())


def _gitignore_allowlist() -> set[str]:
    """The skill directory names un-ignored by name in `.gitignore`."""
    pattern = re.compile(r"^!\.claude/skills/([^/]+)/?\s*$")
    return {
        match.group(1)
        for line in GITIGNORE.read_text().splitlines()
        if (match := pattern.match(line.strip()))
    }


def _notices_skill_rows() -> set[str]:
    """The skill names in THIRD-PARTY-NOTICES.md § 2's vendored-skills table.

    The table's first column is a backticked directory name. Reading the whole
    file rather than the section keeps this from breaking when § 2 is
    reorganised; a backticked name in the first cell of a row that also names a
    licence is specific enough, and a false positive here would have to be a
    table row that looks exactly like a skill row.
    """
    rows = set()
    row_re = re.compile(r"^\|\s*`([a-z0-9-]+)`\s*\|.*\|\s*(?:MIT|Apache-2\.0|BSD-3-Clause)\s*\|")
    for line in NOTICES.read_text().splitlines():
        if match := row_re.match(line.strip()):
            rows.add(match.group(1))
    return rows


VENDORED = _vendored_dirs()

# Parametrising over a discovered list makes an empty `.claude/skills/` pass
# every per-skill test, which is the one hole this cannot express as a
# parametrisation. `test_the_allowlist_is_not_empty` is that assertion.
_skill_ids = [p.name for p in VENDORED]


def test_the_allowlist_is_not_empty():
    """At least one skill is vendored, or the per-skill guards below vacuously pass.

    Not a claim that skills are good — a claim that this file is still testing
    something. Deleting every skill is a legitimate decision; deleting every
    skill *and* leaving these tests green is how the pipeline ends up with an
    inert `Skill` allowance nobody notices.
    """
    assert VENDORED, (
        ".claude/skills/ holds no vendored skill. If that is deliberate, remove "
        "`Skill` from the workflows' --allowedTools and delete this file; if it "
        "is not, the directories are missing from the checkout."
    )


@pytest.mark.parametrize("skill", VENDORED, ids=_skill_ids)
def test_every_vendored_skill_carries_its_upstream_licence(skill):
    """Redistribution without the upstream notice is the licence break itself."""
    licence = skill / "LICENSE"
    assert licence.is_file(), (
        f"{skill.name} is vendored with no LICENSE. Copying a third party's skill "
        "into this tree is redistribution; the upstream notice has to travel with "
        "it. See THIRD-PARTY-NOTICES.md § 2."
    )
    assert licence.read_text().strip(), f"{skill.name}/LICENSE is empty."


@pytest.mark.parametrize("skill", VENDORED, ids=_skill_ids)
def test_every_vendored_skill_declares_the_name_it_is_indexed_under(skill):
    """`name:` and the directory must agree, or the skill is not the one you cite.

    The harness indexes a skill by its frontmatter `name`. A directory renamed
    without the frontmatter following it still loads — under the old name — so
    the notices table, `.gitignore` and `docs/PIPELINE.md` would all be
    describing something the model cannot see by that name.
    """
    head = (skill / "SKILL.md").read_text()[:4096]
    match = re.search(r"^name:\s*(.+?)\s*$", head, re.MULTILINE)
    assert match, f"{skill.name}/SKILL.md has no `name:` in its frontmatter."
    assert match.group(1).strip("\"'") == skill.name, (
        f"{skill.name}/SKILL.md declares name: {match.group(1)!r}. The harness "
        "indexes the frontmatter name, so it must match the directory."
    )


@pytest.mark.parametrize("skill", VENDORED, ids=_skill_ids)
def test_vendored_skills_carry_no_plugin_namespace_references(skill):
    """`superpowers:test-driven-development` does not resolve from a repository."""
    offending = []
    for path in sorted(skill.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if found := PLUGIN_NAMESPACE_RE.search(line):
                offending.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {found.group(0)}")
    assert not offending, (
        "A vendored skill references another skill through a plugin namespace, "
        "which resolves for a marketplace install and not for a skill loaded from "
        "this repository. Rewrite to the bare name and record the modification in "
        "THIRD-PARTY-NOTICES.md § 2:\n  " + "\n  ".join(offending)
    )


def test_the_gitignore_allowlist_and_the_tree_agree():
    """Both directions. An un-tracked skill is absent from CI; a stale `!` is a lie."""
    allowlisted = _gitignore_allowlist()
    present = {p.name for p in VENDORED}

    untracked = present - allowlisted
    assert not untracked, (
        f"{sorted(untracked)} sit in .claude/skills/ but are not un-ignored by name "
        "in .gitignore, so they are absent from the CI checkout: the workflows look "
        "correct and the skill was never there."
    )

    stale = allowlisted - present
    assert not stale, (
        f".gitignore un-ignores {sorted(stale)}, which no longer exist. Remove the "
        "lines — a name kept there reads as a skill this pipeline loads."
    )


def test_the_notices_table_and_the_tree_agree():
    """Both directions, because the two failures are different licence problems."""
    rows = _notices_skill_rows()
    present = {p.name for p in VENDORED}

    unattributed = present - rows
    assert not unattributed, (
        f"{sorted(unattributed)} are vendored with no row in THIRD-PARTY-NOTICES.md "
        "§ 2. Every redistributed component needs its upstream, version and licence "
        "recorded there."
    )

    orphaned = rows - present
    assert not orphaned, (
        f"THIRD-PARTY-NOTICES.md § 2 lists {sorted(orphaned)}, which are not in the "
        "tree. A row with no directory attributes something this project does not "
        "ship."
    )


@pytest.mark.parametrize("workflow", SKILL_LOADING_WORKFLOWS)
def test_skill_loading_workflows_allow_the_skill_tool(workflow):
    """Without `Skill` on the allowlist the vendored skills are inert.

    The model still sees every description — discovery is automatic — so nothing
    in the run says the port is closed. This is the same class of two-process
    contract as `tests/test_phase_banners.py`: the skills live in one half and
    the permission to use them in the other, and only a test spans both.
    """
    text = (REPO_ROOT / ".github" / "workflows" / workflow).read_text()
    allowed = re.findall(r'--allowedTools\s+"([^"]*)"', text)
    assert allowed, f"{workflow} passes no --allowedTools; the guard cannot read it."
    for tools in allowed:
        assert "Skill" in [tool.strip() for tool in tools.split(",")], (
            f"{workflow} has an --allowedTools without `Skill`, so the vendored "
            f"skills in .claude/skills/ ({', '.join(sorted(p.name for p in VENDORED))}) "
            "cannot be invoked by that job. The allowlist is exhaustive and the "
            "failure is silent."
        )
