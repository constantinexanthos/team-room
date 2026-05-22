import type { Project, Topic } from '@/api/types';
import { tildify } from '@/lib/utils';

interface Props {
  project: Project;
  topic: Topic | null;
  onOpenSettings: () => void;
}

export function ProjectHeader({ project, topic, onOpenSettings }: Props) {
  const title = topic ? topic.id : project.name;
  const githubShort = project.github_url ? shortGithub(project.github_url) : null;

  return (
    <header className="flex items-start justify-between gap-4 border-b border-[var(--color-border)] bg-[var(--color-bg)] px-6 py-4">
      <div className="min-w-0">
        <h1 className="truncate text-base font-semibold text-[var(--color-text)]" title={title}>
          {title}
        </h1>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-[var(--color-muted)]">
          {topic && <span className="truncate">{project.name}</span>}
          {topic && githubShort && <span className="opacity-50">·</span>}
          {!topic && githubShort && <span className="truncate">{project.name}</span>}
          {githubShort && (
            <>
              {!topic && <span className="opacity-50">·</span>}
              <a
                href={project.github_url ?? '#'}
                target="_blank"
                rel="noopener noreferrer"
                className="truncate text-[var(--color-costa)] hover:underline"
              >
                {githubShort}
              </a>
            </>
          )}
          {(topic || githubShort) && <span className="opacity-50">·</span>}
          <span className="truncate font-mono" title={project.workspace}>
            {tildify(project.workspace)}
          </span>
        </div>
      </div>

      <button
        type="button"
        onClick={onOpenSettings}
        aria-label="Project settings"
        className="rounded-md p-1.5 text-[var(--color-muted)] transition-colors hover:bg-[var(--color-bg-3)] hover:text-[var(--color-text)]"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <circle cx="5" cy="12" r="1.5" />
          <circle cx="12" cy="12" r="1.5" />
          <circle cx="19" cy="12" r="1.5" />
        </svg>
      </button>
    </header>
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
