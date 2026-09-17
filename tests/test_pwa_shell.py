"""The installable shell: the manifest, the icons and the service worker's allowlist.

There is no frontend test runner in this repository, so the parts of the PWA that are
*claims* rather than behaviour are asserted against the source. Three of them are worth
the file on their own.

**The worker must never be able to answer an API request.** Every route but
`GET /health` and the bundle is authenticated with one shared secret held in the page's
`localStorage`, which a worker cannot read — so a worker that cached `/jobs/{id}` would
either 401 forever or, worse, hand one person's job record to whoever opened the app next
on a shared tablet. `web/src/sw.ts` is written as an allowlist for that reason, and
`test_the_worker_and_the_api_share_no_path` is the assertion that keeps it one: the
worker's paths and the dev proxy's API prefixes (which is the list of what the server
owns, maintained for its own reasons) must not intersect.

**The registration must be production-only.** A worker holding a cached shell in front
of `npm run dev` is a dev server whose edits stop appearing, and that is diagnosed as a
broken build rather than as a worker.

**The manifest must name files that exist**, because a missing 512px icon is not an
error anywhere — it is an app Android quietly declines to offer an install for.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB = REPO_ROOT / "web"
PUBLIC = WEB / "public"
MANIFEST = PUBLIC / "manifest.webmanifest"
SERVICE_WORKER = WEB / "src" / "sw.ts"
MAIN = WEB / "src" / "main.tsx"
INDEX_HTML = WEB / "index.html"
VITE_CONFIG = WEB / "vite.config.ts"

#: The two sizes Android's install criteria are written against: 192 for the launcher,
#: 512 for the splash and the richer install dialog.
REQUIRED_ICON_SIZES = {"192x192", "512x512"}


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text())


# ── The manifest ─────────────────────────────────────────────────────────────


def test_the_manifest_is_a_standalone_app_scoped_to_the_root(manifest):
    """`display: standalone` is what separates an installed app from a bookmark."""
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["name"] and manifest["short_name"]


def test_the_manifest_colours_are_the_app_ground(manifest):
    """The window chrome and the splash are the dark ground, not a browser default.

    `--ground` in `web/src/global.css`. The light sheet exists and is complete, but a
    manifest carries one colour and the dark ground is the identity — see
    `docs/SYSTEM-AS-BUILT.md` § Frontend.
    """
    ground = "#2f3030"
    assert manifest["theme_color"] == ground
    assert manifest["background_color"] == ground
    assert ground in INDEX_HTML.read_text(), "the dark theme-color meta is the same value"


def test_every_icon_the_manifest_names_exists(manifest):
    """A manifest is a promise about files, and nothing checks it at build time."""
    missing = []
    for icon in manifest["icons"]:
        assert icon["src"].startswith("/"), f"{icon['src']} must be root-absolute"
        if not (PUBLIC / icon["src"].lstrip("/")).is_file():
            missing.append(icon["src"])
    assert not missing, f"the manifest names files that are not in web/public: {missing}"


def test_the_two_install_sizes_are_present(manifest):
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert REQUIRED_ICON_SIZES <= sizes, (
        f"Android offers an install only with {sorted(REQUIRED_ICON_SIZES)}; found {sorted(sizes)}"
    )


def test_a_maskable_icon_is_offered_and_is_its_own_drawing(manifest):
    """Maskable is a different cut, not a duplicate `src` with a different `purpose`.

    Android crops a launcher icon to a shape it chooses and guarantees only the central
    80% circle. The mark reaches 84% of its grid vertically, so the plain cut loses the
    filament feed under a circular mask — `infra/scripts/make_pwa_icons.py` draws the
    maskable one at 0.72 scale for exactly that. Pointing `purpose: maskable` at the same
    file would be the claim without the drawing.
    """
    by_purpose = {icon.get("purpose", "any"): icon["src"] for icon in manifest["icons"]}
    assert "maskable" in by_purpose, "no maskable icon: Android will crop the mark"
    assert by_purpose["maskable"] != by_purpose.get("any")


def test_index_html_declares_both_install_mechanisms():
    """Chromium installs from the manifest; iOS Safari does not read one."""
    html = INDEX_HTML.read_text()
    assert 'rel="manifest"' in html
    assert "apple-mobile-web-app-capable" in html, (
        "without this, an iOS install opens in Safari chrome — a bookmark with an icon"
    )
    assert "viewport-fit=cover" in html, (
        "env(safe-area-inset-*) reports zero without it, so the safe-area padding on the "
        "nav, the footer and the running view's action bar does nothing"
    )


# ── The service worker ───────────────────────────────────────────────────────


def _worker_paths() -> set[str]:
    """Every literal path the worker will answer from its cache."""
    source = SERVICE_WORKER.read_text()
    root_files = re.search(r"const ROOT_FILES = \[(.*?)\]", source, re.S)
    assert root_files, "ROOT_FILES is the allowlist; this test reads it"
    paths = set(re.findall(r"'(/[^']*)'", root_files.group(1)))
    prefix = re.search(r"const ASSET_PREFIX = '([^']+)'", source)
    assert prefix
    paths.add(prefix.group(1))
    return paths


def _proxy_prefixes() -> set[str]:
    """The API prefixes `vite.config.ts` forwards to the server in dev.

    This is the closest thing the frontend has to a list of "paths the API owns", and it
    is maintained for its own reason — an unproxied endpoint answers with `index.html` in
    dev and the JSON parse throws. Reading it here means a new endpoint added to the proxy
    is checked against the worker on the day it is added.
    """
    config = VITE_CONFIG.read_text()
    proxy = re.search(r"proxy: \{(.*?)\n    \}", config, re.S)
    assert proxy, "the proxy block is the list of API prefixes this test compares against"
    return set(re.findall(r"'(/[a-z-]+)'\s*:", proxy.group(1)))


def test_the_worker_and_the_api_share_no_path():
    """The allowlist may not contain anything the server answers with data."""
    worker = _worker_paths()
    api = _proxy_prefixes()
    assert api, "no proxy prefixes parsed — this test would pass vacuously"

    overlap = {
        path
        for path in worker
        for prefix in api
        if path == prefix or path.startswith(prefix.rstrip("/") + "/")
    }
    assert not overlap, (
        "the service worker would cache API responses it cannot authenticate: "
        f"{sorted(overlap)} — every one of these is under a prefix `vite.config.ts` "
        "proxies to the server"
    )


def test_the_worker_declines_everything_it_does_not_list():
    """An allowlist, expressed as one `respondWith` per listed case and no `else`."""
    source = SERVICE_WORKER.read_text()
    assert "ROOT_FILES.includes(" in source, (
        "membership, not a prefix match: the root is also where every API path lives"
    )
    assert "request.method !== 'GET'" in source, (
        "a worker sees POSTs too, and replaying one here would dispatch a print"
    )
    # `respondWith` is the only way a worker can answer a request at all, so counting
    # the calls counts the cases. Two: the navigation shell, and the cache-first path
    # that `/assets/*` and `ROOT_FILES` share.
    assert source.count("event.respondWith(") == 2, (
        "a `respondWith` was added or removed; every one of them is a path this worker "
        "answers instead of the network, and each needs its own reason"
    )


def test_the_worker_caches_nothing_under_jobs():
    """Said directly, because it is the one that matters.

    Not a comment check: `/jobs` appears in the file's header prose as the example of
    what is *not* handled. This asserts it appears in no executable line.
    """
    code = []
    for line in SERVICE_WORKER.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith(("*", "/*", "//")):
            continue
        code.append(line)
    body = "\n".join(code)
    assert "/jobs" not in body, "the worker has grown a rule about a job route"


def test_the_cache_name_carries_a_build_id():
    """Otherwise a deploy leaves the previous shell installed and nothing evicts it."""
    assert "__SW_BUILD__" in SERVICE_WORKER.read_text()
    assert "__SW_BUILD__" in VITE_CONFIG.read_text(), "nothing would replace it"
    activate = SERVICE_WORKER.read_text().split("'activate'", 1)[-1]
    assert "caches.delete" in activate, "old caches are never purged"


def test_the_worker_is_a_build_entry_and_lands_at_the_root():
    """`/sw.js`, unhashed. A worker's scope is the directory it is served from."""
    config = VITE_CONFIG.read_text()
    assert "src/sw.ts" in config, "the worker must be type-checked and bundled, not copied"
    assert "'sw.js'" in config, "an asset-directory worker would control /assets/ only"


def test_registration_is_production_only():
    """A cached shell in front of `npm run dev` is a dev server that stops updating."""
    main = MAIN.read_text()
    assert "serviceWorker.register" in main
    register_line = next(line for line in main.splitlines() if "serviceWorker.register" in line)
    guard = main.split("serviceWorker.register")[0]
    assert "import.meta.env.PROD" in guard, (
        "the registration is not behind a production guard: " + register_line.strip()
    )


# ── The icons on disk ────────────────────────────────────────────────────────


def test_the_icons_are_the_sizes_they_claim(manifest):
    """Generated by `infra/scripts/make_pwa_icons.py`; checked here, because a 512
    that is a stretched 180 is not an error anywhere else."""
    from PIL import Image

    for icon in manifest["icons"]:
        width, height = (int(part) for part in icon["sizes"].split("x"))
        with Image.open(PUBLIC / icon["src"].lstrip("/")) as image:
            assert image.size == (width, height), f"{icon['src']} is {image.size}"
