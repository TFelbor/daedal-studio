/**
 * The one place the SPA talks to the server, and therefore the one place the shared
 * secret is attached.
 *
 * Every call in `web/src/` goes through `apiFetch`; a bare `fetch(` to a server route
 * would compile, run, and 401 at the one moment nobody is watching — so
 * `tests/test_frontend_auth.py` refuses one anywhere outside this file.
 *
 * Three shapes of call need three wrappers, because a browser attaches credentials to
 * exactly none of them by itself:
 *
 * - `apiFetch` for XHR, which can carry a header;
 * - `withToken` for `new WebSocket(...)`, which cannot, and takes `?token=`;
 * - `authedObjectUrl` / `downloadAuthed` for the places an `<img src>` or a download
 *   `<a href>` used to point straight at a route — the browser issues those requests
 *   itself, with no headers of ours on them.
 */

import { getApiToken, reportUnauthorized } from './auth';

/** The request headers for an authenticated call, or none when we hold no token. */
export function authHeaders(): Record<string, string> {
  const token = getApiToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * `fetch`, with the shared secret on it and a 401 reported to whoever is listening.
 *
 * The 401 is *not* swallowed: callers already know how to read a failed response, and
 * a call that silently resolved to nothing would leave a page rendering an empty state
 * that means "no data" when the truth is "not authenticated".
 */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getApiToken();
  // An explicit header wins: the token gate verifies a *candidate* through this
  // function, and the stored token — which is the one being replaced — must not
  // overwrite it.
  if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`);

  const response = await fetch(input, { ...init, headers });
  if (response.status === 401) reportUnauthorized();
  return response;
}

/**
 * Add the token to a WebSocket URL.
 *
 * The upgrade is refused before `accept()` without it, so this is not optional. A
 * query parameter is the only way in: `new WebSocket(url)` takes no headers, and the
 * alternative — accept the socket and ask for the token in the first message — leaves
 * unauthenticated sockets open until something times them out. The server logs the
 * path and never the query string, and uvicorn's access log is off.
 */
export function withToken(url: string): string {
  const token = getApiToken();
  if (!token) return url;
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}token=${encodeURIComponent(token)}`;
}

/**
 * Fetch a route the browser would otherwise request itself, as an object URL.
 *
 * `<img src="/jobs/x/blueprint">` and `<a href="/jobs/x/download" download>` are
 * requests the browser makes with no headers of ours on them, so both became 401s the
 * moment the routes closed. Fetching the bytes and handing back a `blob:` URL is the
 * only way to authenticate them. The caller must revoke it — `useAuthedObjectUrl`
 * does.
 */
export async function authedObjectUrl(url: string): Promise<string> {
  const response = await apiFetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return URL.createObjectURL(await response.blob());
}

/**
 * Download a route as a file, the way a `download` anchor used to.
 *
 * Holds the file in memory once, which is the price of authenticating a download
 * without putting the token in a URL the browser will keep.
 */
export async function downloadAuthed(url: string, filename: string): Promise<void> {
  const objectUrl = await authedObjectUrl(url);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Revoked on the next tick: revoking synchronously can beat the click.
  setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000);
}
