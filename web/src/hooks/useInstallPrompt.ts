import { useCallback, useEffect, useState } from 'react';

/**
 * The install affordance, and the two halves of the web platform that disagree about it.
 *
 * **Chromium** fires `beforeinstallprompt` when it decides the app is installable, and
 * that event is the *only* way to open the install dialog: it cannot be constructed, and
 * `prompt()` on a stored one works once. Calling `preventDefault()` suppresses the mini
 * infobar Chrome would otherwise show, which is the point of catching it — the offer then
 * lives somewhere a person chose to look rather than over the page they were reading.
 *
 * **iOS Safari** fires nothing and has no API. Installing is Share → Add to Home Screen,
 * and a sentence saying so is the whole of what can be built. It is still worth building:
 * the alternative is an app that is installable on iOS and never says so.
 *
 * And **once it is installed**, neither offer should be there at all — `display-mode:
 * standalone` matches inside the installed app, which is the reliable signal on both.
 */

/** Chromium's event. Not in lib.dom, because it is not in any specification. */
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

export type InstallState =
  /** Running as an installed app already. Nothing to offer. */
  | 'installed'
  /** Chromium has handed over an event; a button can open the real dialog. */
  | 'promptable'
  /** No event and no API — iOS, or a Chromium that has not decided yet. Instructions. */
  | 'manual';

export interface InstallPrompt {
  state: InstallState;
  /** True on iOS/iPadOS, where the instructions name Safari's Share menu specifically. */
  isIos: boolean;
  /** Opens the browser's own install dialog. Only meaningful while `promptable`. */
  install: () => Promise<void>;
}

function standalone(): boolean {
  if (typeof window === 'undefined') return false;
  if (window.matchMedia?.('(display-mode: standalone)').matches) return true;
  // iOS predates the media query and reports it here instead.
  return (window.navigator as { standalone?: boolean }).standalone === true;
}

function detectIos(): boolean {
  if (typeof navigator === 'undefined') return false;
  // iPadOS 13+ reports a Macintosh user agent; the touch points are what separate it
  // from a desktop, which has none.
  const ua = navigator.userAgent;
  return /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
}

export function useInstallPrompt(): InstallPrompt {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(standalone);

  useEffect(() => {
    const onBeforeInstall = (event: Event) => {
      event.preventDefault();
      setDeferred(event as BeforeInstallPromptEvent);
    };
    // Fired after an install completes, in the tab that was open at the time: the offer
    // has to go away without a reload, or it sits there inviting a second copy.
    const onInstalled = () => {
      setInstalled(true);
      setDeferred(null);
    };
    window.addEventListener('beforeinstallprompt', onBeforeInstall);
    window.addEventListener('appinstalled', onInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  const install = useCallback(async () => {
    if (!deferred) return;
    await deferred.prompt();
    await deferred.userChoice;
    // Spent either way: a dismissed prompt cannot be reopened from the same event, and
    // keeping the button live would give a button that does nothing on the second press.
    setDeferred(null);
  }, [deferred]);

  const state: InstallState = installed ? 'installed' : deferred ? 'promptable' : 'manual';
  return { state, isIos: detectIos(), install };
}
