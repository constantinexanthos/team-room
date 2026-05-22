import { useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { Project, Topic, AgentRole } from '@/api/types';
import { cx, tildify } from '@/lib/utils';
import { Brand } from './Brand';
import { AgentLogo } from './AgentLogo';
import { ConfirmModal } from './ConfirmModal';

interface Props {
  project: Project;
  topics: Topic[];
  activeTopicId: string | null;
  onSelectTopic: (topicId: string) => void;
  onCloseProject: () => void;
  onNewTopic: () => void;
  onTopicDeleted: (topicId: string) => void;
}

const ROLE_VAR: Record<AgentRole, string> = {
  claude: '--color-claude',
  codex: '--color-codex',
  costa: '--color-costa',
  system: '--color-system',
};

export function Sidebar({
  project,
  topics,
  activeTopicId,
  onSelectTopic,
  onCloseProject,
  onNewTopic,
  onTopicDeleted,
}: Props) {
  const [pendingDelete, setPendingDelete] = useState<Topic | null>(null);

  async function handleConfirmDelete() {
    if (!pendingDelete) return;
    const targetId = pendingDelete.id;
    try {
      await api.deleteTopic(targetId);
    } catch (err) {
      // Re-throw so ConfirmModal can render the error and keep itself open.
      if (err instanceof ApiError) throw err;
      throw err;
    }
    // Success — close the modal and let the parent reconcile state.
    setPendingDelete(null);
    onTopicDeleted(targetId);
  }

  return (
    <aside className="flex h-full w-[272px] shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-bg-2)]">
      {/* Brand + back-to-projects nav */}
      <div className="flex items-center gap-2.5 px-4 pt-4 pb-3">
        <Brand variant="mark" size={16} />
        <button
          type="button"
          onClick={onCloseProject}
          className="group flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-[var(--color-muted)] transition-colors hover:text-[var(--color-text)]"
        >
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="transition-transform group-hover:-translate-x-0.5">
            <path d="M15 6l-6 6 6 6" />
          </svg>
          Projects
        </button>
      </div>

      {/* Project identity */}
      <div className="px-4 pb-4">
        <div className="truncate text-[13px] font-semibold text-[var(--color-text)]" title={project.name}>
          {project.name}
        </div>
        <div
          className="mt-0.5 truncate font-mono text-[11px] text-[var(--color-muted)]"
          title={project.workspace}
        >
          {tildify(project.workspace)}
        </div>
        {project.github_url && (
          <a
            href={project.github_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1.5 inline-flex items-center gap-1 truncate text-[11px] text-[var(--color-costa)] hover:underline"
            title={project.github_url}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.748-1.026 2.748-1.026.546 1.378.202 2.397.1 2.65.64.7 1.028 1.595 1.028 2.688 0 3.847-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.02 10.02 0 0 0 22 12.017C22 6.484 17.523 2 12 2Z" />
            </svg>
            <span className="truncate">{shortGithub(project.github_url)}</span>
          </a>
        )}
      </div>

      {/* Section header */}
      <div className="px-4 pb-1.5">
        <div className="flex items-center justify-between">
          <div className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[var(--color-muted)]">
            Topics
          </div>
          {topics.length > 0 && (
            <div className="font-mono text-[10px] text-[var(--color-muted)]/70">
              {topics.length}
            </div>
          )}
        </div>
      </div>

      {/* Topic list */}
      <nav className="flex-1 overflow-y-auto px-2 pb-2">
        {topics.length === 0 ? (
          <div className="px-2 py-2 text-xs text-[var(--color-muted)]">
            No topics yet. Create one to start.
          </div>
        ) : (
          <ul className="space-y-px">
            {topics.map((t) => {
              const active = t.id === activeTopicId;
              const inFlight = t.status && t.status !== 'idle' && t.status !== 'crashed';
              return (
                <li key={t.id}>
                  <div
                    data-active={active ? 'true' : 'false'}
                    className={cx(
                      'topic-item group flex w-full items-center gap-2 rounded-md pl-3 pr-1.5 py-1.5 text-[13px]',
                      active
                        ? 'bg-[var(--color-bg-3)] text-[var(--color-text)]'
                        : 'text-[var(--color-text)]/80 hover:bg-[var(--color-bg-3)]/60 hover:text-[var(--color-text)]',
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => onSelectTopic(t.id)}
                      className="flex flex-1 items-center gap-2 min-w-0 text-left"
                    >
                      <span className="flex-1 truncate font-medium" title={t.id}>
                        {t.id}
                      </span>
                      {inFlight && (
                        <span
                          className="heartbeat inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-costa)] shadow-[0_0_8px_var(--color-costa)]"
                          title={t.status}
                          aria-label={t.status ?? 'in-flight'}
                        />
                      )}
                      {t.last_role && <RolePill role={t.last_role} />}
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setPendingDelete(t);
                      }}
                      aria-label={`Delete topic ${t.id}`}
                      title="Delete topic"
                      className="shrink-0 rounded p-1 text-[var(--color-muted)] opacity-0 transition-all group-hover:opacity-100 hover:bg-[var(--color-bg)] hover:text-[var(--color-danger)] focus:opacity-100 focus:outline-none"
                    >
                      <TrashIcon />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </nav>

      {/* Footer action */}
      <div className="border-t border-[var(--color-border)] p-3">
        <button
          type="button"
          onClick={onNewTopic}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-[var(--color-muted)] transition-colors hover:bg-[var(--color-bg-3)] hover:text-[var(--color-text)]"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New topic
        </button>
      </div>

      {pendingDelete && (
        <ConfirmModal
          title="Delete topic"
          body={
            <span>
              Delete topic{' '}
              <span className="font-mono text-[var(--color-text)]">'{pendingDelete.id}'</span>?
              The transcript, state, and workspace metadata will be removed. This cannot be undone.
            </span>
          }
          confirmLabel="Delete topic"
          confirmingLabel="Deleting..."
          onConfirm={handleConfirmDelete}
          onClose={() => setPendingDelete(null)}
        />
      )}
    </aside>
  );
}

function TrashIcon() {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3 6h18" />
      <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
    </svg>
  );
}

function RolePill({ role }: { role: AgentRole }) {
  const roleVar = ROLE_VAR[role];
  const label = role === 'costa' ? 'You' : role.charAt(0).toUpperCase() + role.slice(1);

  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-1.5 py-px text-[9px] font-semibold uppercase tracking-[0.1em]"
      style={{
        color: `var(${roleVar})`,
        backgroundColor: `color-mix(in oklab, var(${roleVar}) 14%, transparent)`,
      }}
      title={`Last: ${label}`}
    >
      {role === 'claude' || role === 'codex' ? (
        <AgentLogo agent={role} size={9} />
      ) : (
        <span
          className="inline-block size-1 rounded-full bg-current"
          aria-hidden="true"
        />
      )}
      <span>{label}</span>
    </span>
  );
}

function shortGithub(url: string): string {
  try {
    const u = new URL(url);
    if (u.hostname === 'github.com') {
      const path = u.pathname.replace(/^\//, '').replace(/\.git$/, '');
      return `gh/${path}`;
    }
    return u.hostname + u.pathname;
  } catch {
    return url;
  }
}
