import { useEffect, useRef, useState } from 'react';
import { api } from '@/api/client';
import type { Message } from '@/api/types';

export function useTranscript(topicId: string | null, intervalMs = 1500) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState<string | null>(null);
  const lastLengthRef = useRef(0);

  useEffect(() => {
    if (!topicId) {
      setMessages([]);
      lastLengthRef.current = 0;
      return;
    }
    let cancelled = false;

    const poll = async () => {
      try {
        const msgs = await api.fetchTranscript(topicId);
        if (cancelled) return;
        const newLength = msgs.length;
        if (newLength !== lastLengthRef.current) {
          lastLengthRef.current = newLength;
          setMessages(msgs);
        }
        setError(null);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    };

    void poll();
    const id = setInterval(poll, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [topicId, intervalMs]);

  return { messages, error };
}
