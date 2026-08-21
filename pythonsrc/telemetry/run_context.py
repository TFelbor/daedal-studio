"""Which code produced a row.

A change to the prompt template, the repair kernel or the scoring weights silently
mixes two populations in the dataset unless rows can be split by code version — the
same failure mode `blueprint_prompt_engineered` exists to prevent, generalised.

Kept in its own torch-free module so both the API server (which passes the value to
container subprocesses via `$P2P_GIT_SHA`) and the pipeline (which records it) can
import it without pulling in either one's dependency stack.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

#: Repo root, from this file's location: pythonsrc/telemetry/ → two levels up.
_REPO_ROOT = Path(__file__).parent.parent.parent


def resolve_git_sha() -> str | None:
    """The commit of the code running this process, or None when unknowable.

    `$P2P_GIT_SHA` wins so a container image — which carries no .git — can be
    stamped at build or launch time; otherwise the working tree is asked.

    Returns:
        A short commit hash, or None.
    """
    env = os.environ.get("P2P_GIT_SHA")
    if env:
        return env.strip()
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    return None
