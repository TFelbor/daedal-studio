import { useEffect, useState } from 'react';
import { closeSocket } from '../api/ws';
import { withToken } from '../api/http';

/**
 * The server's own activity, live.
 *
 * Separate from `useJobWebSocket` because most of what this carries belongs to no
 * job: a configuration edit, a simulator coming up, a printer refusing a pause. Those
 * were the events with nowhere to appear, which is why they were invisible.
 *
 * The socket opens with a backlog batch, so a page loaded mid-session shows history
 * rather than starting blank.
 */

interface ActivityEntry {
  seq: number;
  at: string;
  level: string;
  source: string;
  text: string;
}

/** Matches the server's ring buffer, so the client cannot claim more history than exists. */
const MAX_ENTRIES = 500;

export function useActivityFeed(enabled: boolean = true) {
  const [lines, setLines] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!enabled) return;

    let mounted = true;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(withToken(`${protocol}//${window.location.host}/ws/activity`));

    // The server sends multi-line blocks as one string. Splitting them here keeps the
    // renderer a flat list, which is what makes the tail trim and the scroll simple.
    const render = (entry: ActivityEntry): string[] => {
      const stamp = new Date(entry.at).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
      const body = entry.text.split('\n');
      // Only the first line of a block carries the timestamp; the rest are indented to
      // match, so the block's own edges stay vertically aligned.
      const pad = ' '.repeat(stamp.length + 1);
      return body.map((line, i) => `${i === 0 ? stamp : pad} ${line}`);
    };

    const append = (incoming: string[]) => {
      setLines(prev => {
        const next = [...prev, ...incoming];
        return next.length > MAX_ENTRIES * 4
          ? next.slice(next.length - MAX_ENTRIES * 4)
          : next;
      });
    };

    ws.onopen = () => {
      if (mounted) setConnected(true);
    };
    ws.onclose = () => {
      if (mounted) setConnected(false);
    };
    ws.onmessage = event => {
      if (!mounted) return;
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'activity_batch') {
          append((msg.data as ActivityEntry[]).flatMap(render));
        } else if (msg.type === 'activity') {
          append(render(msg.data as ActivityEntry));
        }
      } catch {
        // A malformed frame is not worth surfacing in a diagnostic panel.
      }
    };

    return () => {
      mounted = false;
      closeSocket(ws);
    };
  }, [enabled]);

  return { lines, connected };
}
