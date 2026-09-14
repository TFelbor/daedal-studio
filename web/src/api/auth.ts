/**
 * Where the SPA keeps the shared secret, and how it learns it has the wrong one.
 *
 * The server authenticates every route but `GET /health` and the bundle this file is
 * part of. There is no user model here — one token, typed once, kept in
 * `localStorage`.
 *
 * The alternative considered was the server injecting the token into `index.html`
 * when the request came from loopback. It was refused: it hands the secret to every
 * process on the machine through the one route that is exempt *because* it is safe to
 * be public, it cannot work for a hosted client (which is never loopback, and behind a
 * proxy `request.client` is the proxy), and it turns a `FileResponse` into a template.
 *
 * `localStorage` rather than `sessionStorage` because re-typing the token on every tab
 * is how people end up pasting it into a chat window to have it handy, and rather than
 * a cookie because a cookie is attached to cross-site requests whether the person
 * meant it or not — see `server/auth.py`.
 */

const STORAGE_KEY = 'ds.apiToken';

/** Read once at module load; `localStorage` throws in a sandboxed iframe. */
function safeRead(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

let token: string | null = safeRead();

type Listener = () => void;
const listeners = new Set<Listener>();

function notify(): void {
  listeners.forEach((listener) => listener());
}

/** Subscribe to token changes — the gate appearing, or a paste taking effect. */
export function onAuthChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getApiToken(): string | null {
  return token;
}

export function setApiToken(value: string): void {
  token = value.trim() || null;
  try {
    if (token) window.localStorage.setItem(STORAGE_KEY, token);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // A token that lives only for this page load still works; it just will not
    // survive a reload. Better than refusing to accept it at all.
  }
  rejected = false;
  notify();
}

export function clearApiToken(): void {
  setApiToken('');
}

/**
 * Whether the server has refused the token we hold.
 *
 * Kept separate from "there is no token": the two states need different words. An
 * empty box says "paste the token"; a refused one says "that token was not accepted",
 * and it must not clear what was typed, or a single stray keystroke would lose a
 * secret the person may not have anywhere else.
 */
let rejected = false;

export function isTokenRejected(): boolean {
  return rejected;
}

export function reportUnauthorized(): void {
  if (rejected) return;
  rejected = true;
  notify();
}

/**
 * Take a token off the page URL, then remove it from the address bar.
 *
 * The startup line in the server log can be pasted whole, which is the shortest path
 * from "the server just generated a token" to "the app works". Stripped immediately
 * afterwards so it does not end up in a bookmark, in the back stack or in a screenshot.
 */
export function adoptTokenFromUrl(): void {
  try {
    const url = new URL(window.location.href);
    const supplied = url.searchParams.get('token');
    if (!supplied) return;
    setApiToken(supplied);
    url.searchParams.delete('token');
    window.history.replaceState({}, '', url.pathname + url.search + url.hash);
  } catch {
    // A URL we cannot parse is a URL with no token in it.
  }
}
