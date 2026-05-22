import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { Project, Topic } from '@/api/types';
import { Sidebar } from './Sidebar';
import { ProjectHeader } from './ProjectHeader';
import { NewTopicModal } from './NewTopicModal';
import { ProjectSettingsModal } from './ProjectSettingsModal';
import { TopicView } from './TopicView';

interface Props {
  project: Project;
  onClose: () => void;
}

const REFRESH_MS = 5000;

export function ProjectView({ project, onClose }: Props) {
  // Project metadata can be mutated locally (rename, workspace move, GitHub
  // URL update) via the settings modal. Keep our own copy so the header and
  // sidebar refresh without waiting on the parent.
  const [activeProject, setActiveProject] = useState<Project>(project);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [activeTopicId, setActiveTopicId] = useState<string | null>(null);
  const [isNewTopicModalOpen, setNewTopicModalOpen] = useState(false);
  const [isSettingsOpen, setSettingsOpen] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const aliveRef = useRef(true);

  // If the caller swaps in a different project, drop our overrides.
  useEffect(() => {
    setActiveProject(project);
  }, [project]);

  const fetchTopics = useCallback(async (): Promise<Topic[] | null> => {
    try {
      const { project: fetchedProject, topics: fetched } = await api.getProject(activeProject.id);
      if (!aliveRef.current) return null;
      // Reconcile project metadata from the server (cheap; same request).
      setActiveProject(fetchedProject);
      setTopics(fetched);
      setLoadError(null);
      return fetched;
    } catch (err) {
      if (!aliveRef.current) return null;
      // Project itself was deleted (e.g. from another window/tab) — bail to picker.
      if (err instanceof ApiError && err.status === 404) {
        onClose();
        return null;
      }
      const message = err instanceof ApiError ? err.message : String(err);
      setLoadError(message);
      return null;
    }
  }, [activeProject.id, onClose]);

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

  function handleTopicDeleted(deletedTopicId: string) {
    // Drop locally so the row disappears immediately — refetch reconciles.
    setTopics((prev) => prev.filter((t) => t.id !== deletedTopicId));
    setActiveTopicId((current) => (current === deletedTopicId ? null : current));
    void fetchTopics();
  }

  function handleOpenSettings() {
    setSettingsOpen(true);
  }

  async function handleProjectUpdated(updated: Project) {
    setActiveProject(updated);
    // If the workspace path moved, the server-side state needs a re-open so
    // subsequent topic creation/cwd lookups land in the right place.
    try {
      const refreshed = await api.openProject(updated.id);
      setActiveProject(refreshed);
    } catch {
      // Non-fatal — the metadata patch already succeeded.
    }
    void fetchTopics();
  }

  function handleProjectDeleted() {
    onClose();
  }

  return (
    <div className="flex h-full">
      <Sidebar
        project={activeProject}
        topics={topics}
        activeTopicId={activeTopicId}
        onSelectTopic={setActiveTopicId}
        onCloseProject={onClose}
        onNewTopic={handleNewTopic}
        onTopicDeleted={handleTopicDeleted}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <ProjectHeader
          project={activeProject}
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
            <TopicView topic={activeTopic} project={activeProject} />
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
          projectId={activeProject.id}
          onClose={() => setNewTopicModalOpen(false)}
          onCreated={handleTopicCreated}
        />
      )}

      {isSettingsOpen && (
        <ProjectSettingsModal
          project={activeProject}
          onClose={() => setSettingsOpen(false)}
          onUpdated={handleProjectUpdated}
          onDeleted={handleProjectDeleted}
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
