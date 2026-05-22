import { useCallback, useEffect, useState } from 'react';
import { api } from '@/api/client';
import type { Topic } from '@/api/types';

export function useTopics(projectId: string | null, intervalMs = 5000) {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    if (!projectId) {
      setTopics([]);
      return;
    }
    try {
      const list = await api.listTopics(projectId);
      setTopics(list);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [projectId]);

  useEffect(() => {
    void refetch();
    if (!projectId) return;
    const id = setInterval(refetch, intervalMs);
    return () => clearInterval(id);
  }, [projectId, intervalMs, refetch]);

  return { topics, error, refetch };
}
