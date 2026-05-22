import { useEffect, useState } from 'react';

interface PartialResult {
  /** Current partial text content; empty string when nothing yet. */
  text: string;
  /**
   * True once the partial file is gone (404). Either it never started
   * (turn not yet kicked off) or the agent has finished and the sidecar
   * was cleaned up. The consumer can use this to swap the "still streaming"
   * indicator off the UI.
   */
  done: boolean;
}

/**
 * Poll the partial-text sidecar file for an in-flight agent turn.
 *
 * The server route `GET /partial/<topic>/<promptId>/<turn>` returns:
 *   200 + text/plain  – current partial text (may be empty while waiting on
 *                       the first token)
 *   404               – file absent (turn complete or not started)
 *
 * Polls at `intervalMs` (default 250ms) so the UI feels live without
 * hammering the server. Auto-stops when any input changes (component
 * unmount, or topic / promptId / turn swap).
 *
 * Network errors are treated as "not done yet" — the UI keeps showing
 * whatever text it has so far rather than flicker. A 404 is the canonical
 * signal that the turn has wrapped (file deleted by the bash helper).
 */
export function usePartial(
  topic: string | null,
  promptId: string | null,
  turn: number | null,
  intervalMs = 250,
): PartialResult {
  const [text, setText] = useState('');
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!topic || !promptId || turn == null) {
      setText('');
      setDone(false);
      return;
    }

    let cancelled = false;
    const url = `/partial/${encodeURIComponent(topic)}/${encodeURIComponent(promptId)}/${encodeURIComponent(String(turn))}`;

    const poll = async () => {
      try {
        const res = await fetch(url, { cache: 'no-store' });
        if (cancelled) return;
        if (res.status === 404) {
          setDone(true);
          return;
        }
        if (!res.ok) {
          // Transient — keep the last text, try again next tick.
          return;
        }
        const body = await res.text();
        if (cancelled) return;
        setText(body);
        setDone(false);
      } catch {
        // Network blip — keep last text and retry on next interval.
      }
    };

    setText('');
    setDone(false);
    void poll();
    const id = setInterval(poll, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [topic, promptId, turn, intervalMs]);

  return { text, done };
}
