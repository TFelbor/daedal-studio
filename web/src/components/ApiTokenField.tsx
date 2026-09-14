import { useState } from 'react';
import { clearApiToken, getApiToken, setApiToken } from '../api/auth';

/**
 * View, replace or forget the shared secret this browser holds.
 *
 * Deliberately **not** a config-store key. `PUT /config` would then be able to rotate
 * the credential that protects `PUT /config`, and one bad write would lock every
 * client out of the server with no way back in through the API — so this edits what
 * is in `localStorage` and nothing on the server. Rotating the real secret is an edit
 * to `.env` or to `~/.ds-mvp/.api_token`, and a restart.
 *
 * Masked by default, revealable, because the person who owns this server sometimes
 * needs to read it back out — to paste it into a second browser, or to check that
 * what is stored is what they meant to store.
 */
export function ApiTokenField() {
  const [revealed, setRevealed] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const [draft, setDraft] = useState('');
  const token = getApiToken();

  if (replacing) {
    return (
      <div className="field">
        <label className="field-label" htmlFor="api-token-new">
          API token
        </label>
        <input
          id="api-token-new"
          className="input"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={draft}
          placeholder="Paste DS_API_TOKEN"
          onChange={(event) => setDraft(event.target.value)}
        />
        <div className="row">
          <button
            type="button"
            className="btn btn-primary"
            disabled={!draft.trim()}
            onClick={() => {
              setApiToken(draft.trim());
              setDraft('');
              setReplacing(false);
            }}
          >
            Save
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              setDraft('');
              setReplacing(false);
            }}
          >
            Cancel
          </button>
        </div>
        <span className="hint">
          This changes what <em>this browser</em> sends. The server's own token is{' '}
          <code>DS_API_TOKEN</code> in <code>.env</code>, or{' '}
          <code>~/.ds-mvp/.api_token</code>; changing it there needs a restart.
        </span>
      </div>
    );
  }

  return (
    <div className="field">
      <label className="field-label" htmlFor="api-token">
        API token
      </label>
      <input
        id="api-token"
        className="input"
        readOnly
        type={revealed ? 'text' : 'password'}
        value={token ?? ''}
      />
      <div className="row">
        <button type="button" className="btn btn-secondary" onClick={() => setRevealed((v) => !v)}>
          {revealed ? 'Hide' : 'Reveal'}
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => setReplacing(true)}>
          Replace
        </button>
        {/* Forgetting sends you straight back to the gate, which is the point: it is
            how you hand this machine to someone else. */}
        <button type="button" className="btn btn-secondary" onClick={() => clearApiToken()}>
          Forget
        </button>
      </div>
      <span className="hint">
        The shared secret every request from this browser carries. Kept here, not on the
        server.
      </span>
    </div>
  );
}
