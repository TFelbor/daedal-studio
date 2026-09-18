/**
 * Turning the finished-print notification on and off, from the browser's side.
 *
 * Three facts shape this file.
 *
 * **A subscription belongs to the service worker, not to the page.** `pushManager`
 * hangs off the registration, so none of this works under `npm run dev` — the worker is
 * registered in production builds only (`main.tsx`), deliberately. `supported()`
 * therefore answers for the *browser*, and every call below waits for the registration
 * rather than assuming one.
 *
 * **The permission prompt needs a gesture.** Safari refuses `Notification.requestPermission()`
 * outside a click, and Chrome counts a prompt nobody asked for against the origin. So
 * `enablePush` is only ever called from a button, and nothing here asks on load.
 *
 * **The server is the only place a millimetre of this is decided.** The application
 * server key comes from `GET /push/vapid-public-key`; the page never holds a key of its
 * own, and a browser still holding a subscription made against an older key is told to
 * make a new one by the server answering with a different value.
 *
 * Everything goes through `apiFetch`, which is the one place the shared secret is
 * attached — `tests/test_frontend_auth.py` refuses a bare `fetch` to a server route
 * anywhere but `api/http.ts`.
 *
 * One deployment fact belongs here rather than in a bug report: a service worker is
 * registered only in a *secure context*, and `localhost` is the single insecure origin
 * browsers make an exception for. The api-server terminates no TLS today, so a phone
 * reaching it over `http://<lan-ip>:8000` has no worker and `pushSupported()` is the
 * last thing that is true — `registration()` gives up and the button below says so.
 * That is a certificate away, not a code change.
 */

import { apiFetch } from './http';

/** Whether this browser can do web push at all. */
export function pushSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  );
}

/** What the browser currently allows: the value a UI has to render around. */
export function permission(): NotificationPermission | 'unsupported' {
  return pushSupported() ? Notification.permission : 'unsupported';
}

/**
 * The registration, or null when there is not going to be one.
 *
 * `ready` never rejects and never resolves without a worker, so a bare `await` on it
 * hangs forever in dev — where no worker is registered. The race gives up instead.
 */
async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (!pushSupported()) return null;
  const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), 3000));
  return Promise.race([navigator.serviceWorker.ready, timeout]);
}

/** The subscription this device already holds, if any. */
export async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await registration();
  if (!reg) return null;
  return reg.pushManager.getSubscription();
}

/**
 * The VAPID public key, as `pushManager.subscribe` wants it.
 *
 * It is served base64url and unpadded — the only spelling web push uses — and
 * `applicationServerKey` takes bytes, so this is the conversion and not a stylistic
 * choice.
 */
function decodeKey(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = base64url.replace(/-/g, '+').replace(/_/g, '/');
  const binary = atob(padded + '='.repeat((4 - (padded.length % 4)) % 4));
  // Built on an explicit `ArrayBuffer` rather than with `Uint8Array.from`, because
  // `applicationServerKey` takes a `BufferSource` over a plain `ArrayBuffer` and the
  // inferred `ArrayBufferLike` includes `SharedArrayBuffer`, which it does not accept.
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export class PushError extends Error {}

/**
 * Ask for permission, subscribe, and tell the server.
 *
 * Called from a click, always. Throws a `PushError` with something a person can read:
 * every failure here is one they have to act on — turn notifications back on in the
 * browser, install the app first on iOS, or try again when the network is back.
 */
export async function enablePush(): Promise<void> {
  if (!pushSupported()) {
    throw new PushError('This browser cannot show notifications.');
  }

  const granted = await Notification.requestPermission();
  if (granted !== 'granted') {
    throw new PushError(
      granted === 'denied'
        ? 'Notifications are blocked for this site. Turn them back on in the browser’s site settings.'
        : 'Notifications were not allowed.',
    );
  }

  const reg = await registration();
  if (!reg) {
    throw new PushError(
      'No service worker is running. Notifications work in the installed app and in a production build, not under the dev server.',
    );
  }

  const response = await apiFetch('/push/vapid-public-key');
  if (!response.ok) throw new PushError('The server did not hand out a push key.');
  const { public_key: publicKey } = (await response.json()) as { public_key: string };

  // An existing subscription made against a *different* key can never be delivered to,
  // and `subscribe` refuses to replace one. Dropping it first is what makes a rotated
  // key recoverable without the person clearing site data.
  const existing = await reg.pushManager.getSubscription();
  if (existing) await existing.unsubscribe();

  const subscription = await reg.pushManager.subscribe({
    // The only kind a browser grants. It also means the worker must show something for
    // every push it receives — see `web/src/sw.ts`.
    userVisibleOnly: true,
    applicationServerKey: decodeKey(publicKey),
  });

  const saved = await apiFetch('/push/subscriptions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(subscription.toJSON()),
  });
  if (!saved.ok) {
    // Leaving a subscription the server does not know about would be a device that
    // believes it is subscribed and is never told anything.
    await subscription.unsubscribe();
    throw new PushError('The server would not store this device. Nothing was changed.');
  }
}

/**
 * Unsubscribe here and forget it there.
 *
 * The server call goes first: a browser that has dropped its subscription cannot tell
 * the server which endpoint to forget, and a row left behind is a notification sent
 * into the void on every later print.
 */
export async function disablePush(): Promise<void> {
  const subscription = await currentSubscription();
  if (!subscription) return;

  await apiFetch('/push/subscriptions', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ endpoint: subscription.endpoint }),
  });
  await subscription.unsubscribe();
}
