import { useEffect, useState } from 'react';
import { api } from '@/api/client';
import type { TopicStatus } from '@/api/types';

const IDLE: TopicStatus = {
  status: 'idle',
  prompt_id: null,
  started_at: null,
  orchestrator_pid: null,
  claude_done: false,
  codex_done: false,
  last_error: null,
};

export function useStatus(topicId: string | null, intervalMs = 1500) {
  const [status, setStatus] = useState<TopicStatus>(IDLE);

  useEffect(() => {
    if (!topicId) {
      setStatus(IDLE);
      return;
    }
    let cancelled = false;

    const poll = async () => {
      try {
        const s = await api.getStatus(topicId);
        if (!cancelled) setStatus(s);
      } catch {
        // 404 / network blip → treat as idle so input doesn't lock forever
        if (!cancelled) setStatus(IDLE);
      }
    };

    void poll();
    const id = setInterval(poll, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [topicId, intervalMs]);

  return status;
}
