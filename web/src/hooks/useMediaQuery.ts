import { useCallback, useSyncExternalStore } from 'react';

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
 *
 * `useSyncExternalStore` rather than `useState` + `useEffect`: the viewport is an
 * external store, and this is the hook for one. It also closes the gap the effect
 * version had to patch by hand — a rotation between the first render and the
 * subscription — because React re-reads the snapshot after subscribing rather than
 * needing a `setState` in an effect body to catch up (`react-hooks/set-state-in-effect`).
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onStoreChange: () => void) => {
      if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
        return () => {};
      }
      const list = window.matchMedia(query);
      list.addEventListener('change', onStoreChange);
      return () => list.removeEventListener('change', onStoreChange);
    },
    [query],
  );

  const getSnapshot = useCallback(
    () =>
      typeof window !== 'undefined' && typeof window.matchMedia === 'function'
        ? window.matchMedia(query).matches
        : false,
    [query],
  );

  // The third argument is the server snapshot. Nothing here is server-rendered, but
  // the signature wants one and `false` is the honest answer: with no window there is
  // no viewport to match.
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
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
