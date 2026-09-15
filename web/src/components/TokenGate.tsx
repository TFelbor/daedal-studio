import { useState } from 'react';
import type { FormEvent } from 'react';
import { setApiToken } from '../api/auth';
import { apiFetch } from '../api/http';
import { Wordmark } from './Wordmark';
import styles from './TokenGate.module.css';

/**
 * The one box between a fresh browser and the app.
 *
 * There is no user model here and no sign-in: the server holds one shared secret and
 * checks it on every route but the healthcheck and this bundle. So this is not a login
 * screen and must not read as one — it says where the token *is*, because the person
 * in front of it owns the server and the answer is a file on their own machine.
 *
 * The token is verified before it is kept. Storing an unchecked value would mean the
 * next thing the person saw was a page full of empty states, and no way to tell a
 * mistyped token from an empty database.
 */
export function TokenGate({ rejected }: { rejected: boolean }) {
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const candidate = value.trim();
    if (!candidate || busy) return;

    setBusy(true);
    setError(null);
    try {
      // `GET /system/info` is authenticated and cheap, and it touches nothing: the
      // question is only whether the server accepts this token.
      const response = await apiFetch('/system/info', {
        headers: { Authorization: `Bearer ${candidate}` },
      });
      if (response.status === 401) {
        setError('The server did not accept that token.');
        return;
      }
      if (!response.ok) {
        setError(`The server answered ${response.status}. The token may still be right.`);
        return;
      }
      setApiToken(candidate);
    } catch {
      setError('Could not reach the server.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.gate}>
      <form className={styles.panel} onSubmit={submit}>
        <Wordmark size={28} />
        <h1 className={styles.title}>This server wants its token</h1>
        <p className={styles.blurb}>
          Every route but the healthcheck is authenticated, because{' '}
          <em>Send to printer</em> heats a nozzle and a job can spend money. One shared
          secret, typed once, kept in this browser.
        </p>
        <label className={styles.label} htmlFor="ds-api-token">
          API token
        </label>
        <input
          id="ds-api-token"
          className={styles.input}
          type="password"
          autoComplete="off"
          autoFocus
          spellCheck={false}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Paste DS_API_TOKEN"
        />
        <button className="btn btn-primary" type="submit" disabled={busy || !value.trim()}>
          {busy ? 'Checking' : 'Unlock'}
        </button>

        {(error || rejected) && (
          <p className={`notice ${styles.error}`} role="alert">
            {error ?? 'The server refused the token this browser had stored.'}
          </p>
        )}

        {/* Where it actually is. Without this the honest answer to "what token?" is a
            search through the repository, which is how people end up disabling the
            thing instead of using it. */}
        <div className={styles.where}>
          <span className={styles.whereTitle}>Where to find it</span>
          <ul>
            <li>
              <code>DS_API_TOKEN</code> in your <code>.env</code>, if you set one.
            </li>
            <li>
              Otherwise the server generated one on first start:{' '}
              <code>~/.ds-mvp/.api_token</code>, and the path is in its log.
            </li>
            <li>
              <code>make api-token</code> prints it.
            </li>
          </ul>
        </div>
      </form>
    </div>
  );
}
