/**
 * Closing a WebSocket without aborting it.
 *
 * `ws.close()` on a socket that is still `CONNECTING` does not send a close frame:
 * the spec says to *fail* the connection, so the browser tears down the TCP socket
 * mid-handshake and the peer reads a reset. In dev that peer is the Vite proxy, which
 * reports it as
 *
 *     [vite] ws proxy error: Error: read ECONNRESET
 *     [vite] ws proxy socket error: Error: read ECONNRESET
 *
 * — two lines that read like a broken backend and are nothing of the kind. React's
 * StrictMode double-invokes every effect, so the first socket each effect opens is
 * discarded while still connecting: on every single dev page load.
 *
 * Waiting for the upgrade to finish costs one round trip on a socket nobody is
 * listening to any more, and closes it the way the protocol expects.
 */
export function closeSocket(ws: WebSocket | null | undefined): void {
  if (!ws) return;
  if (ws.readyState === WebSocket.CONNECTING) {
    ws.addEventListener('open', () => ws.close(1000, 'client done'), { once: true });
    // A handshake that fails on its own needs no close, but an unhandled `error`
    // event on a socket nobody owns any more is noise of exactly the kind this
    // function exists to remove.
    ws.addEventListener('error', () => {}, { once: true });
    return;
  }
  if (ws.readyState === WebSocket.OPEN) ws.close(1000, 'client done');
}
