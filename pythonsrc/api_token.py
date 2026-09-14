"""The shared secret every API route but `GET /health` is checked against.

One token, resolved the same way on both sides of the wire: the server that checks
it, and the pipeline container, the dispatch operator and the telemetry relay that
send it. `$DS_API_TOKEN` wins; otherwise a file, `$DS_API_TOKEN_PATH` or
`~/.ds-mvp/.api_token` — beside the config store's `.config_key`, and therefore
already inside the `~/.ds-mvp:/root/.ds-mvp` bind mount both containers get, so a
native run and a compose run resolve the same secret without anyone copying it.

The server generates that file on first start when nothing else supplies a token.
Nobody else does: a caller that generates its own secret would authenticate against
a server that has never seen it, and would report the failure as a bad token rather
than as a missing one. Hence `create`, which only `server/auth.py` passes as True.

There is deliberately no "unset means open" mode, unlike the GPU worker's
`DS_WORKER_API_KEY`: that worker is reached over a LAN the operator chose, while
this server holds the printer credentials and the route that spends money.
"""

import logging
import os
import secrets
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

#: The token itself, when it is passed in the environment.
API_TOKEN_ENV = "DS_API_TOKEN"

#: Where the token file lives when nothing overrides it.
API_TOKEN_PATH_ENV = "DS_API_TOKEN_PATH"

#: Bytes of entropy in a generated token, before URL-safe encoding.
TOKEN_BYTES = 32


def default_api_token_path() -> str:
    """`$DS_API_TOKEN_PATH`, else `~/.ds-mvp/.api_token`."""
    return os.environ.get(API_TOKEN_PATH_ENV) or str(Path.home() / ".ds-mvp" / ".api_token")


def resolve_api_token(create: bool = False) -> Optional[str]:
    """The shared API secret, or None when there is none and none may be made.

    Args:
        create: Generate and persist a token when neither the environment nor the
            file supplies one. Only the server passes True — see the module
            docstring.

    Returns:
        The token, or None when nothing supplies one and `create` is False.
    """
    from_env = os.environ.get(API_TOKEN_ENV, "").strip()
    if from_env:
        return from_env

    path = Path(default_api_token_path())
    try:
        stored = path.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    except OSError:
        pass

    if not create:
        return None

    token = secrets.token_urlsafe(TOKEN_BYTES)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
        path.chmod(0o600)
    except OSError as exc:
        # An unwritable path is not a reason to serve the API unauthenticated: the
        # token still guards this process, it just will not survive a restart.
        logger.warning("Could not persist the generated API token to %s: %s", path, exc)
        return token

    logger.info("Generated a new API token at %s", path)
    return token
