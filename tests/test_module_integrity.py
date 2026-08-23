"""Guards against the class of damage a bad merge resolution leaves behind.

Both halves of a conflict can be syntactically valid, and Python will happily accept
a file where one definition shadows another — the later one simply wins. That is what
happened resolving the per-job-blueprint branch against the approval-gate branch:
`server/app.py` ended up with **two** `_run_pipeline` definitions, the first truncated
to the few lines the old side contributed. The file imported, `pytest tests/` was
green (every job-submission test patches `_run_pipeline`), and the surviving definition
read `blueprint_rel` as a global that no longer existed — a `NameError` the first time
anyone ran a job on the mps_native path.

Nothing in a diff review catches that reliably: the duplicate lands hundreds of lines
from its twin. A structural assertion does, in milliseconds.
"""

import ast
import collections
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

#: Every module a merge is likely to touch. Deliberately the whole application rather
#: than just the file that broke — the failure mode is the resolution, not the file.
MODULES = sorted(
    [p for p in (REPO_ROOT / "server").rglob("*.py")]
    + [p for p in (REPO_ROOT / "pythonsrc").rglob("*.py")]
)

CONFLICT_MARKERS = ("<<<<<<<", ">>>>>>>")


@pytest.mark.parametrize("path", MODULES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_module_defines_the_same_top_level_name_twice(path):
    """A duplicate definition is a shadowed one, and the shadowed half is dead code.

    It is never intentional here: a second `def` at module scope means one body is
    unreachable, and the reachable one may be missing the locals its twin defined.
    """
    tree = ast.parse(path.read_text())
    counts = collections.Counter(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )
    duplicated = {name: n for name, n in counts.items() if n > 1}
    assert not duplicated, (
        f"{path.relative_to(REPO_ROOT)} defines these top-level names more than once: "
        f"{duplicated}. The later definition wins and the earlier body is dead — "
        f"usually both sides of a merge conflict left in place."
    )


@pytest.mark.parametrize("path", MODULES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_module_carries_conflict_markers(path):
    """A committed marker is a file nobody ran. Cheap to check, so check it."""
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        assert not line.startswith(CONFLICT_MARKERS), (
            f"{path.relative_to(REPO_ROOT)}:{lineno} still carries a merge conflict "
            f"marker: {line[:40]!r}"
        )


def test_every_name_run_pipeline_reads_is_actually_bound():
    """The specific breakage above: a surviving definition reading a vanished local.

    `symtable` classifies every name in a scope, so "this function looks up
    `blueprint_rel` as a global" is a fact about the source rather than something you
    have to run the pipeline to discover. Restricted to the names the merge moved,
    because a genuine module-level global read from a function is ordinary.
    """
    import symtable

    app_py = REPO_ROOT / "server" / "app.py"
    top = symtable.symtable(app_py.read_text(), str(app_py), "exec")
    module_globals = {s.get_name() for s in top.get_symbols()}

    definitions = [c for c in top.get_children() if c.get_name() == "_run_pipeline"]
    assert len(definitions) == 1, "server/app.py must define _run_pipeline exactly once"

    suspects = ("blueprint_rel", "blueprint_container_path")
    unbound = []

    def walk(scope):
        for symbol in scope.get_symbols():
            name = symbol.get_name()
            if name not in suspects:
                continue
            local = symbol.is_assigned() or symbol.is_parameter()
            if not (local or symbol.is_free() or name in module_globals):
                unbound.append(name)
        for child in scope.get_children():
            walk(child)

    walk(definitions[0])
    assert not unbound, (
        f"_run_pipeline reads {sorted(set(unbound))} as module globals, but nothing "
        f"defines them at module scope — a NameError on the first job that reaches "
        f"that branch."
    )
