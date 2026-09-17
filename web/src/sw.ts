/**
 * The service worker. An allowlist, not a blocklist — and that is the whole design.
 *
 * Every route in this app but `GET /health` and the bundle itself is authenticated with
 * one shared secret that lives in the page's `localStorage` (`api/auth.ts`). A worker
 * cannot read it, and it must never need to: a worker that answered `/jobs/{id}` from a
 * cache would be serving one person's job record to whoever opened the app next on that
 * device, and a worker that replayed a `POST` would be dispatching a print.
 *
 * So this worker handles four things and declines everything else. Declining is literal:
 * for anything outside the allowlist it returns from `fetch` without calling
 * `respondWith`, which hands the request back to the browser untouched. `/jobs`, `/ws`,
 * `/config`, `/feedback`, `/activity`, `/prompt`, `/simulators`, `/system` and every
 * prefix added after this file was written therefore reach the network exactly as they
 * would with no worker installed — not because they are listed here as exceptions, but
 * because they are not listed at all. `tests/test_pwa_shell.py` holds the two sets
 * apart.
 *
 * What it does handle:
 *
 *  1. **Navigations** — network first, with the cached shell as the fallback. Network
 *     first rather than cache first because a deploy must not need an uninstall: the
 *     newest `index.html` names the newest hashed bundle, and a stale shell pointing at
 *     a deleted asset is an app that opens to a blank page.
 *  2. **`/assets/*`** — cache first. Vite fingerprints these, so the URL *is* the
 *     version and a hit can never be stale.
 *  3. **The public root files** — the icons, the manifest, the favicons. Cache first for
 *     the same reason, by enumeration rather than by prefix, because the root is also
 *     where every API path lives.
 *  4. **Nothing else.**
 */

export {}

/** The subset of the worker globals this file touches. `lib: ["ES2023", "DOM"]` in
 *  `tsconfig.app.json` does not carry the WebWorker lib, and adding it would put
 *  worker globals into scope for the whole app — a `self.skipWaiting()` that type-checks
 *  in a React component is worse than a dozen lines of declaration.
 *
 *  Declared to the shape this file uses rather than to `any`: `respondWith` is the one
 *  call in here that can take an app offline by mistake, and a typed event is what makes
 *  passing it the wrong thing a build error instead of a deploy. */
interface ExtendableEventLike {
  waitUntil(promise: Promise<unknown>): void
}

interface FetchEventLike extends ExtendableEventLike {
  readonly request: Request
  respondWith(response: Response | Promise<Response>): void
}

declare const self: {
  addEventListener(
    type: 'install' | 'activate',
    listener: (event: ExtendableEventLike) => void,
  ): void
  addEventListener(type: 'fetch', listener: (event: FetchEventLike) => void): void
  skipWaiting(): Promise<void>
  clients: { claim(): Promise<void> }
  registration: unknown
}

/** Replaced at build time — see `vite.config.ts`. One cache per build, so `activate`
 *  can delete every other one and a deploy cannot leave a previous shell behind. */
declare const __SW_BUILD__: string

const CACHE = `ds-shell-${__SW_BUILD__}`

/**
 * The root files this worker will answer from cache, in full.
 *
 * Enumerated, never prefixed. `/` is shared with the API: a rule like "anything at the
 * root that looks static" is one endpoint away from caching `/health`, and the next
 * person to add `/photos` would have no way to know they had just made it offline-stale.
 * Adding a file to `web/public/` means adding its name here, and the test says so.
 */
const ROOT_FILES = [
  '/manifest.webmanifest',
  '/favicon.svg',
  '/favicon.ico',
  '/apple-touch-icon.png',
  '/icons.svg',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/icon-maskable-512.png',
]

/** The shell, precached on install so the first offline load has something to open. */
const PRECACHE = ['/', ...ROOT_FILES]

/** Fingerprinted build output. The URL carries the hash, so a hit is never stale. */
const ASSET_PREFIX = '/assets/'

self.addEventListener('install', event => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE)
      // Individually rather than `addAll`: that rejects the whole install if any single
      // entry 404s, and an install that fails leaves the previous worker in charge —
      // which is how a missing icon becomes a deploy that silently did not take.
      await Promise.all(
        PRECACHE.map(async url => {
          try {
            await cache.add(new Request(url, { cache: 'reload' }))
          } catch {
            /* One absent file is not a reason to keep serving the last build. */
          }
        }),
      )
      await self.skipWaiting()
    })(),
  )
})

self.addEventListener('activate', event => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys()
      await Promise.all(names.filter(name => name !== CACHE).map(name => caches.delete(name)))
      await self.clients.claim()
    })(),
  )
})

async function networkFirstShell(request: Request): Promise<Response> {
  try {
    const response = await fetch(request)
    // Only the shell is worth keeping, and only when it is really the shell: a 404 or a
    // 502 body cached here is the page every future offline load would open to.
    if (response.ok && request.mode === 'navigate') {
      const cache = await caches.open(CACHE)
      await cache.put('/', response.clone())
    }
    return response
  } catch (error) {
    const cached = await caches.match('/')
    if (cached) return cached
    throw error
  }
}

async function cacheFirst(request: Request): Promise<Response> {
  const cached = await caches.match(request)
  if (cached) return cached
  const response = await fetch(request)
  if (response.ok) {
    const cache = await caches.open(CACHE)
    await cache.put(request, response.clone())
  }
  return response
}

self.addEventListener('fetch', event => {
  const request = event.request

  // A worker sees every request the page makes, including the ones that change state.
  // Anything that is not a plain same-origin GET is not ours.
  if (request.method !== 'GET') return

  // `location` inside a worker is the worker's own script URL, so its origin is the
  // app's by construction. A cross-origin GET — the Google Fonts stylesheet — is
  // somebody else's to cache.
  const url = new URL(request.url)
  if (url.origin !== location.origin) return

  if (request.mode === 'navigate') {
    event.respondWith(networkFirstShell(request))
    return
  }

  if (url.pathname.startsWith(ASSET_PREFIX) || ROOT_FILES.includes(url.pathname)) {
    event.respondWith(cacheFirst(request))
  }

  // Everything else falls through with no `respondWith`, which is the browser doing
  // exactly what it would do if this worker were not installed.
})
