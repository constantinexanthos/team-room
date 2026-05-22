import type { Project, Topic, AgentRole } from '@/api/types';
import { cx, tildify } from '@/lib/utils';

interface Props {
  project: Project;
  topics: Topic[];
  activeTopicId: string | null;
  onSelectTopic: (topicId: string) => void;
  onCloseProject: () => void;
  onNewTopic: () => void;
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
}: Props) {
  return (
    <aside className="flex h-full w-[272px] shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-bg-2)]">
      <div className="px-4 pt-4">
        <button
          type="button"
          onClick={onCloseProject}
          className="flex items-center gap-1 text-xs uppercase tracking-wider text-[var(--color-muted)] transition-colors hover:text-[var(--color-text)]"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M15 6l-6 6 6 6" />
          </svg>
          Projects
        </button>
      </div>

      <div className="px-4 pt-3 pb-4">
        <div className="truncate text-sm font-semibold text-[var(--color-text)]" title={project.name}>
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
            className="mt-1 flex items-center gap-1 truncate text-[11px] text-[var(--color-costa)] hover:underline"
            title={project.github_url}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.748-1.026 2.748-1.026.546 1.378.202 2.397.1 2.65.64.7 1.028 1.595 1.028 2.688 0 3.847-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.02 10.02 0 0 0 22 12.017C22 6.484 17.523 2 12 2Z" />
            </svg>
            <span className="truncate">{shortGithub(project.github_url)}</span>
          </a>
        )}
      </div>

      <div className="px-4 pb-2">
        <div className="text-[10px] font-semibold uppercase tracking-[0.15em] text-[var(--color-muted)]">
          Topics
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-2">
        {topics.length === 0 ? (
          <div className="px-2 py-2 text-xs text-[var(--color-muted)]">
            No topics yet. Create one to start.
          </div>
        ) : (
          <ul className="space-y-0.5">
            {topics.map((t) => {
              const active = t.id === activeTopicId;
              const inFlight = t.status && t.status !== 'idle' && t.status !== 'crashed';
              const roleVar = t.last_role ? ROLE_VAR[t.last_role] : undefined;
              return (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => onSelectTopic(t.id)}
                    className={cx(
                      'group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors',
                      active
                        ? 'bg-[var(--color-bg-3)] text-[var(--color-text)]'
                        : 'text-[var(--color-text)]/85 hover:bg-[var(--color-bg-3)]/60 hover:text-[var(--color-text)]',
                    )}
                  >
                    <span
                      className={cx(
                        'inline-block h-1.5 w-1.5 shrink-0 rounded-full',
                        active ? 'bg-[var(--color-text)]' : 'bg-[var(--color-muted)]/60',
                      )}
                      aria-hidden="true"
                    />
                    <span className="flex-1 truncate" title={t.id}>
                      {t.id}
                    </span>
                    {inFlight && (
                      <span
                        className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--color-costa)]"
                        title={t.status}
                        aria-label={t.status}
                      />
                    )}
                    {t.last_role && roleVar && (
                      <span
                        className="ml-0.5 inline-flex items-center rounded-full px-1.5 py-px text-[9px] font-semibold uppercase tracking-wider"
                        style={{
                          color: `var(${roleVar})`,
                          backgroundColor: `color-mix(in oklab, var(${roleVar}) 18%, transparent)`,
                        }}
                      >
                        {t.last_role}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </nav>

      <div className="border-t border-[var(--color-border)] p-3">
        <button
          type="button"
          onClick={onNewTopic}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-[var(--color-muted)] transition-colors hover:bg-[var(--color-bg-3)] hover:text-[var(--color-text)]"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New topic
        </button>
      </div>
    </aside>
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
