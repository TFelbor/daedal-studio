import { useEffect, useState } from 'react';
import { authedObjectUrl } from '../api/http';

/**
 * An `<img src>` for a route that needs the shared secret.
 *
 * The browser issues an image request itself, with none of our headers on it, so
 * `src="/jobs/x/blueprint"` became a 401 and a broken-image icon the moment the routes
 * closed. This fetches the bytes through `apiFetch` and hands back a `blob:` URL,
 * revoked when the component unmounts or the source changes — an object URL that is
 * never revoked keeps the whole image alive for the life of the document, and the
 * blueprint preview re-fetches on a timer while Phase 1 runs.
 *
 * Returns null while loading and on failure. The callers already have a state for
 * "no image yet", which is what a still-rendering blueprint looks like anyway.
 *
 * @param url The route to fetch, or null/'' for nothing to show.
 * @returns An object URL, or null.
 */
export function useAuthedObjectUrl(url: string | null): string | null {
  // The source is kept beside the blob so a change of `url` reads as "nothing yet"
  // during the render that follows it, without the effect having to clear the state
  // first. Clearing it there would be a setState in an effect body — a cascading
  // render, and one the linter rightly refuses.
  const [fetched, setFetched] = useState<{ source: string; objectUrl: string } | null>(null);

  useEffect(() => {
    if (!url) return;

    let live = true;
    let created: string | null = null;

    authedObjectUrl(url)
      .then((blobUrl) => {
        if (!live) {
          URL.revokeObjectURL(blobUrl);
          return;
        }
        created = blobUrl;
        setFetched({ source: url, objectUrl: blobUrl });
      })
      .catch(() => {
        // Nothing to show. The callers all have a state for that already — a
        // blueprint that has not been rendered yet looks the same.
      });

    return () => {
      live = false;
      if (created) URL.revokeObjectURL(created);
    };
  }, [url]);

  return fetched && fetched.source === url ? fetched.objectUrl : null;
}
