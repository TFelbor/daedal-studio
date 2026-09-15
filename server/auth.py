"""One shared secret, checked on every route the app does not mark public.

`server/app.py` installed no authentication at all: `POST /jobs` spends EUR 0,32 per
hosted generation, `POST /jobs/{id}/print-dispatch` heats a nozzle for hours, and
`PUT /config` rewrites the printer credentials the server then ships to whatever host
it is pointed at. A loopback bind shrank the exposure to every process on the machine;
it did not make the server safe to publish, and a hosted beta needs exactly that.

Three decisions are worth the words.

**A header, not a cookie.** A cookie rides along on a cross-site request whether the
person meant it or not, and several routes here take no body at all
(`POST /jobs/{id}/outcome/prompt-shown`, `DELETE /jobs/{id}`) — so a `<form>` on any
page in the browser would authenticate as the operator. A bearer header cannot be sent
cross-origin without a preflight, and the preflight fails because there is deliberately
no CORS middleware. The non-browser callers already speak bearer.

**Exempt by marker, not by list.** `@public` on the endpoint is what exempts it, and
the middleware reads that off the route it matched. A list of paths in this file would
go stale the moment someone adds a route, and it would go stale in the direction that
leaves a route open. Here the default is closed: a new route is protected by writing
nothing.

**Inside the request log, not outside it.** The stack is built inner-first, so this
middleware is installed *before* `log_requests` in `app.py` and therefore runs *inside*
it. A 401 is exactly the line an operator needs in the log and in the activity feed;
rejecting outside the logger would make an attack the one thing that leaves no trace.
"""

import hmac
import logging
from typing import Awaitable, Callable, Optional

from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pythonsrc.api_token import resolve_api_token

logger = logging.getLogger(__name__)

#: Set on an endpoint function by `@public`. Read off the matched route.
PUBLIC_MARKER = "_ds_public"

#: The query parameter the WebSocket upgrade carries its token in. A browser cannot
#: set a header on `new WebSocket(...)`; this is the only way in that does not mean
#: accepting the socket first and asking afterwards.
TOKEN_QUERY_PARAM = "token"


def public(endpoint):
    """Mark an endpoint as reachable without the shared secret.

    Two endpoints wear this: `GET /health`, which exists to be polled by something
    that has no credentials (a container healthcheck, a load balancer), and the SPA
    catch-all, which serves the bundle a person needs *in order to* type the token.
    Neither reads the database, spends money or touches the printer.

    Marking a third is a security decision — see `tests/test_api_auth.py`, which
    asserts the set of marked endpoints rather than trusting the marker.
    """
    setattr(endpoint, PUBLIC_MARKER, True)
    return endpoint


def _bearer_token(scope: Scope) -> Optional[str]:
    """The token from `Authorization: Bearer <token>`, or None."""
    for name, value in scope.get("headers") or ():
        if name == b"authorization":
            try:
                text = value.decode("latin-1")
            except UnicodeDecodeError:
                return None
            scheme, _, credential = text.partition(" ")
            if scheme.lower() == "bearer" and credential.strip():
                return credential.strip()
            return None
    return None


def _query_token(scope: Scope) -> Optional[str]:
    """The token from `?token=`, read straight off the raw query string.

    Deliberately not logged anywhere — `log_requests` records `url.path`, and uvicorn's
    own access log is off (`server/logging_config.py`), so the secret does not reach
    the log file the way a URL credential usually does.
    """
    raw = scope.get("query_string") or b""
    for part in raw.split(b"&"):
        name, _, value = part.partition(b"=")
        if name == TOKEN_QUERY_PARAM.encode():
            from urllib.parse import unquote_plus

            decoded = unquote_plus(value.decode("latin-1")).strip()
            return decoded or None
    return None


class SharedSecretAuth:
    """Pure-ASGI middleware refusing anything that does not carry the shared secret.

    Pure ASGI rather than `BaseHTTPMiddleware` because it has to see the WebSocket
    upgrade: `BaseHTTPMiddleware` passes a `websocket` scope straight through, and the
    upgrade is the one route where a browser cannot send a header.

    Args:
        app: The next ASGI application in the stack.
        fastapi_app: The `FastAPI` whose routes are walked to find the `@public`
            marker. Held by reference, so routes registered after construction — every
            route in `app.py`, which is defined below the middleware — are seen.
        token: The shared secret. Resolved from `pythonsrc.api_token` when omitted,
            generating one on first start if nothing supplies it.
    """

    def __init__(self, app: ASGIApp, fastapi_app=None, token: Optional[str] = None):
        self.app = app
        self.fastapi_app = fastapi_app
        self.token = token if token is not None else resolve_api_token(create=True)

    # -- the exempt walk -----------------------------------------------------

    def _is_public(self, scope: Scope) -> bool:
        """Whether the route this request would reach is marked `@public`.

        Only a GET can be public, so nothing that writes is ever exempt — and an
        unmatched path is not public either, which is why an unknown route answers
        401 rather than telling an anonymous caller which paths exist.
        """
        if scope.get("type") != "http" or scope.get("method") != "GET":
            return False
        if self.fastapi_app is None:
            return False

        for route in self.fastapi_app.router.routes:
            match, _ = route.matches(scope)
            if match is Match.FULL:
                return getattr(getattr(route, "endpoint", None), PUBLIC_MARKER, False)
        return False

    # -- the check -----------------------------------------------------------

    def _authorised(self, scope: Scope) -> bool:
        expected = self.token
        if not expected:
            # A server with no token to check is a server with no authentication.
            # `resolve_api_token(create=True)` makes that all but impossible; if it
            # ever happens, closed is the only safe reading.
            return False

        supplied = _bearer_token(scope)
        if supplied is None and scope.get("type") == "websocket":
            supplied = _query_token(scope)
        if supplied is None:
            return False
        return hmac.compare_digest(supplied, expected)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if self._is_public(scope) or self._authorised(scope):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await self._deny_websocket(scope, receive, send)
        else:
            await _send_401(send)

    async def _deny_websocket(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Refuse the upgrade itself, with an HTTP 401 where the client allows one.

        The criterion is that the *upgrade* is refused, not that an accepted socket is
        closed a moment later: accepting first would leave unauthenticated sockets open
        until something times them out, and would put the check in every handler.

        `websocket.http.response` is an ASGI extension — uvicorn and Starlette's
        `TestClient` both offer it, and the caller then sees a real 401. A server
        without it gets a close before `accept()`, which a browser reports as a failed
        connection and nothing else; that is logged so the difference is visible.
        """
        message = await receive()
        if message.get("type") != "websocket.connect":
            return

        if "websocket.http.response" in (scope.get("extensions") or {}):
            await _send_401(send, websocket=True)
            return

        logger.warning(
            "Refusing an unauthenticated WebSocket to %s by closing it: this server "
            "does not offer the websocket.http.response extension, so the client sees "
            "a closed connection rather than a 401.",
            scope.get("path"),
        )
        await send({"type": "websocket.close", "code": 1008})


_UNAUTHORISED_BODY = (
    b'{"detail":"Not authenticated. Send the shared secret as '
    b'Authorization: Bearer <DS_API_TOKEN>."}'
)


async def _send_401(send: Callable[[Message], Awaitable[None]], websocket: bool = False) -> None:
    """The one 401, in both of ASGI's spellings."""
    prefix = "websocket.http.response" if websocket else "http.response"
    await send(
        {
            "type": f"{prefix}.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_UNAUTHORISED_BODY)).encode()),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": f"{prefix}.body", "body": _UNAUTHORISED_BODY})
