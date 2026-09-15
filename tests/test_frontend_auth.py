"""The SPA's half of the shared secret, and the places it is documented.

Every route but `GET /health` and the bundle itself is authenticated, which makes a
bare `fetch(` in `web/src/` a call that compiles, ships and 401s — in front of a user,
on a page that will render the failure as an empty state. There is no frontend test
runner in this repository, so these are source assertions: the wrappers exist, nothing
goes round them, and the three things a person needs in order to get past the gate are
written down where they will look.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = REPO_ROOT / "web" / "src"
ENV_TEMPLATE = REPO_ROOT / ".env.template"
NATIVE_ENV = REPO_ROOT / "infra" / "scripts" / "load_native_env.sh"
DOCKER_DOC = REPO_ROOT / "docs" / "README-docker.md"
MAKEFILE = REPO_ROOT / "Makefile"

#: The two modules allowed to call `fetch` and to construct a `WebSocket` URL. One is
#: the wrapper; the other is the token store it reads from.
WRAPPERS = {WEB_SRC / "api" / "http.ts", WEB_SRC / "api" / "auth.ts"}

#: `fetch(` not preceded by a word character or a dot — so `apiFetch(` and
#: `window.fetch(` do not match, and a bare call does.
BARE_FETCH = re.compile(r"(?<![\w.])fetch\(")


def _sources():
    for path in sorted(WEB_SRC.rglob("*.ts")):
        yield path
    for path in sorted(WEB_SRC.rglob("*.tsx")):
        yield path


# ── The wrappers are the only way out ────────────────────────────────────────


def test_no_bare_fetch_outside_the_wrapper():
    """One place attaches the token, so one place may call `fetch`."""
    offenders = []
    for path in _sources():
        if path in WRAPPERS:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if BARE_FETCH.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")

    assert not offenders, (
        "these call `fetch` directly, so they send no token and will 401: "
        + ", ".join(offenders)
        + " — use `apiFetch` from web/src/api/http.ts"
    )


def test_every_websocket_is_opened_through_withtoken():
    """The upgrade is refused before `accept()` without `?token=`."""
    offenders = []
    for path in _sources():
        if path in WRAPPERS:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if "new WebSocket(" in line and "withToken(" not in line:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")

    assert not offenders, (
        "these open a WebSocket without the token, and the upgrade is refused: "
        + ", ".join(offenders)
        + " — wrap the URL in `withToken` from web/src/api/http.ts"
    )


def test_no_route_is_pointed_at_by_a_src_or_href():
    """A browser sends none of our headers when it fetches an `<img>` or follows a
    download link, so a route in one of those attributes is a 401 the user sees as a
    broken image or as a downloaded error page under the right filename.
    """
    offenders = []
    pattern = re.compile(r"(?:src|href)=\{?[`'\"]/jobs/")
    # The wrappers and the hook quote the shape they exist to replace, in prose.
    exempt = WRAPPERS | {WEB_SRC / "hooks" / "useAuthedObjectUrl.ts"}
    for path in _sources():
        if path in exempt:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")

    assert not offenders, (
        "these point an element straight at an authenticated route: "
        + ", ".join(offenders)
        + " — use `useAuthedObjectUrl` or `downloadAuthed`"
    )


def test_the_wrappers_exist_and_say_what_they_do():
    http = (WEB_SRC / "api" / "http.ts").read_text()
    for name in ("apiFetch", "withToken", "authedObjectUrl", "downloadAuthed"):
        assert f"export async function {name}" in http or f"export function {name}" in http, (
            f"web/src/api/http.ts no longer exports {name}"
        )

    auth = (WEB_SRC / "api" / "auth.ts").read_text()
    assert "localStorage" in auth
    assert "export function getApiToken" in auth


def test_the_gate_names_where_the_token_is():
    """The one screen a person with no token can see has to answer "what token?"."""
    gate = (WEB_SRC / "components" / "TokenGate.tsx").read_text()
    assert "DS_API_TOKEN" in gate
    assert ".api_token" in gate
    assert "make api-token" in gate


# ── The two sides resolve the same token ─────────────────────────────────────


def test_the_env_template_carries_the_variable_with_a_comment():
    text = ENV_TEMPLATE.read_text()
    assert re.search(r"^DS_API_TOKEN=", text, re.MULTILINE), (
        ".env.template does not declare DS_API_TOKEN"
    )
    # A bare line would be worse than nothing: blank means "generate one", which is
    # not guessable from the name.
    assert "~/.ds-mvp/.api_token" in text
    assert "make api-token" in text


def test_a_native_run_and_a_compose_run_resolve_the_same_token():
    """`load_native_env.sh` lifts it, or the two disagree and the browser sees a 401.

    Same failure the bind address has: a value set once in `.env` that reaches only
    one of the two ways this server is started.
    """
    assert "DS_API_TOKEN" in NATIVE_ENV.read_text(), (
        "infra/scripts/load_native_env.sh does not lift DS_API_TOKEN, so `make "
        "start-native` ignores the token in .env and generates its own"
    )


def test_make_prints_the_token():
    """`make api-token` is what the gate, the README and the log line all point at."""
    text = MAKEFILE.read_text()
    assert re.search(r"^api-token:", text, re.MULTILINE), "the api-token target is gone"
    assert "resolve_api_token" in text, (
        "`make api-token` must resolve the token the same way the server does, or it "
        "can print one the server is not checking"
    )


@pytest.mark.parametrize(
    "fragment",
    [
        "DS_API_TOKEN",
        "~/.ds-mvp/.api_token",
        "make api-token",
        "Authorization: Bearer",
    ],
)
def test_the_docker_readme_explains_the_token(fragment):
    assert fragment in DOCKER_DOC.read_text(), (
        f"docs/README-docker.md does not mention {fragment!r}"
    )
