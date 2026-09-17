import { useEffect, useState } from 'react';

/**
 * A media query as React state.
 *
 * CSS is the right tool for almost every response to a viewport, and everything that
 * can stay in a stylesheet does. This exists for the handful of cases where the
 * *markup* differs rather than its layout — an element that is a disclosure on a phone
 * and a plain block on a desktop cannot be expressed as a rule, because `open` is an
 * attribute and no media query can set one.
 *
 * `matchMedia` rather than a resize listener on `innerWidth`: the browser already knows
 * when the answer changed and says so once, instead of once per frame of a drag.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(query).matches
      : false,
  );

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const list = window.matchMedia(query);
    // Read once on attach as well: the query can have changed between the initial
    // state and this effect — a rotation during hydration is enough.
    setMatches(list.matches);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    list.addEventListener('change', onChange);
    return () => list.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}

/**
 * The phone step of the app's one breakpoint ladder (`tests/test_layout_ladder.py`).
 * Named here so no component hard-codes the number a second time and the two drift.
 */
export const PHONE_QUERY = '(max-width: 720px)';

/** True below 720px — the step where every split has already become a stack. */
export function useIsPhone(): boolean {
  return useMediaQuery(PHONE_QUERY);
}
