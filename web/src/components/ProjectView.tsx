import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { Project, Topic } from '@/api/types';
import { Sidebar } from './Sidebar';
import { ProjectHeader } from './ProjectHeader';
import { NewTopicModal } from './NewTopicModal';
import { TopicView } from './TopicView';

interface Props {
  project: Project;
  onClose: () => void;
}

const REFRESH_MS = 5000;

export function ProjectView({ project, onClose }: Props) {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [activeTopicId, setActiveTopicId] = useState<string | null>(null);
  const [isNewTopicModalOpen, setNewTopicModalOpen] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const aliveRef = useRef(true);

  const fetchTopics = useCallback(async (): Promise<Topic[] | null> => {
    try {
      const { topics: fetched } = await api.getProject(project.id);
      if (!aliveRef.current) return null;
      setTopics(fetched);
      setLoadError(null);
      return fetched;
    } catch (err) {
      if (!aliveRef.current) return null;
      const message = err instanceof ApiError ? err.message : String(err);
      setLoadError(message);
      return null;
    }
  }, [project.id]);

  useEffect(() => {
    aliveRef.current = true;
    void fetchTopics();
    const handle = window.setInterval(() => {
      void fetchTopics();
    }, REFRESH_MS);
    return () => {
      aliveRef.current = false;
      window.clearInterval(handle);
    };
  }, [fetchTopics]);

  const activeTopic = topics.find((t) => t.id === activeTopicId) ?? null;

  function handleNewTopic() {
    setNewTopicModalOpen(true);
  }

  async function handleTopicCreated(newTopicName: string) {
    setNewTopicModalOpen(false);
    const fresh = await fetchTopics();
    const found = fresh?.find((t) => t.id === newTopicName);
    setActiveTopicId(found?.id ?? newTopicName);
  }

  function handleOpenSettings() {
    // Settings modal lives in a sibling task — leave a placeholder hook.
    // For now this is a no-op so the button doesn't dead-end the user.
    window.alert('Project settings — coming soon');
  }

  return (
    <div className="flex h-full">
      <Sidebar
        project={project}
        topics={topics}
        activeTopicId={activeTopicId}
        onSelectTopic={setActiveTopicId}
        onCloseProject={onClose}
        onNewTopic={handleNewTopic}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <ProjectHeader
          project={project}
          topic={activeTopic}
          onOpenSettings={handleOpenSettings}
        />

        {loadError && (
          <div className="border-b border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 px-6 py-2 text-xs text-[var(--color-danger)]">
            {loadError}
          </div>
        )}

        <div className="min-h-0 flex-1">
          {activeTopic ? (
            <TopicView topic={activeTopic} project={project} />
          ) : (
            <EmptyState
              hasTopics={topics.length > 0}
              onNewTopic={handleNewTopic}
            />
          )}
        </div>
      </main>

      {isNewTopicModalOpen && (
        <NewTopicModal
          projectId={project.id}
          onClose={() => setNewTopicModalOpen(false)}
          onCreated={handleTopicCreated}
        />
      )}
    </div>
  );
}

interface EmptyProps {
  hasTopics: boolean;
  onNewTopic: () => void;
}

function EmptyState({ hasTopics, onNewTopic }: EmptyProps) {
  return (
    <div className="flex h-full items-center justify-center px-6 text-center">
      <div className="max-w-sm">
        <div className="mb-2 text-sm text-[var(--color-text)]">
          {hasTopics ? 'Pick a topic from the sidebar' : 'No topics yet'}
        </div>
        <div className="mb-4 text-xs text-[var(--color-muted)]">
          {hasTopics
            ? 'Select one on the left to see the transcript, or start a new one.'
            : 'Create your first topic to start a conversation with Claude and Codex.'}
        </div>
        <button
          type="button"
          onClick={onNewTopic}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-2)] px-3 py-1.5 text-sm text-[var(--color-text)] transition-colors hover:bg-[var(--color-bg-3)]"
        >
          + New topic
        </button>
      </div>
    </div>
  );
}
