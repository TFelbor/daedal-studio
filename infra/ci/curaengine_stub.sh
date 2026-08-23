#!/usr/bin/env bash
#
# A CuraEngine that is present and slices nothing.
#
# `CuraSlicer.__init__` calls `_check_cura_available`, which refuses to construct
# unless `shutil.which(CURA_ENGINE_PATH)` finds something — so the Phase 4 tests need
# *a file by that name* on PATH. They do not need a slicer: each one stubs
# `subprocess.run` and asserts on the argv that would have been executed, which is
# where every bug that step has ever had lived (a `-s` after `-l`, `str(True)`, a
# profile that never reached the engine).
#
# So this exits non-zero on any real invocation instead of pretending to succeed.
# A stub that returned 0 and wrote nothing would let a test "slice" to an empty file
# and pass, which is worse than having no slicer at all. Real slicing belongs behind
# the `slow` marker, on a machine with the engine installed.
#
# Installed onto PATH by .github/workflows/ci.yml. Kept in the repository rather than
# heredoc'd into the workflow so that it is reviewable, and so the thing CI runs is
# the same thing you can run here.

if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "CuraEngine CI stub — present so CuraSlicer can construct; slices nothing"
    exit 0
fi

echo "The CuraEngine CI stub was invoked for real with: $*" >&2
echo "This environment has no slicer. A test that needs one belongs behind the" >&2
echo "'slow' marker, which pytest.ini deselects by default." >&2
exit 70
