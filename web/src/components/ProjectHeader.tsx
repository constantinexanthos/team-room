import { useEffect, useState } from 'react';
import type { Project, Topic } from '@/api/types';
import { cx, tildify } from '@/lib/utils';
import { AgentLogo } from './AgentLogo';

interface Props {
  project: Project;
  topic: Topic | null;
  onOpenSettings: () => void;
}

interface AgentHealth {
  ok: boolean;
  version?: string;
}

interface HealthPayload {
  claude?: AgentHealth;
  codex?: AgentHealth;
}

export function ProjectHeader({ project, topic, onOpenSettings }: Props) {
  const githubShort = project.github_url ? shortGithub(project.github_url) : null;
  const health = useHealth();

  return (
    <header className="flex items-center justify-between gap-4 border-b border-[var(--color-border)] bg-[var(--color-bg)] px-6 py-3.5">
      <div className="min-w-0 flex-1">
        {/* Conductor-style breadcrumb */}
        <div className="flex items-center gap-1.5 text-[13px] font-semibold">
          <span
            className={cx(
              'truncate',
              topic ? 'text-[var(--color-muted)]' : 'text-[var(--color-text)]',
            )}
            title={project.name}
          >
            {project.name}
          </span>
          {topic && (
            <>
              <Chevron />
              <span className="truncate text-[var(--color-text)]" title={topic.id}>
                {topic.id}
              </span>
            </>
          )}
        </div>

        {/* Sub-line: github + path */}
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-[var(--color-muted)]">
          {githubShort && (
            <>
              <a
                href={project.github_url ?? '#'}
                target="_blank"
                rel="noopener noreferrer"
                className="truncate text-[var(--color-costa)] hover:underline"
              >
                {githubShort}
              </a>
              <span className="opacity-40">·</span>
            </>
          )}
          <span className="truncate font-mono" title={project.workspace}>
            {tildify(project.workspace)}
          </span>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <StatusPill health={health} />

        <button
          type="button"
          onClick={onOpenSettings}
          aria-label="Project settings"
          className="rounded-md p-1.5 text-[var(--color-muted)] transition-colors hover:bg-[var(--color-bg-3)] hover:text-[var(--color-text)]"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <circle cx="5" cy="12" r="1.5" />
            <circle cx="12" cy="12" r="1.5" />
            <circle cx="19" cy="12" r="1.5" />
          </svg>
        </button>
      </div>
    </header>
  );
}

function Chevron() {
  return (
    <svg
      width="11"
      height="11"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="chevron-sep shrink-0"
      aria-hidden="true"
    >
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

function StatusPill({ health }: { health: HealthPayload | null | 'unknown' }) {
  // 'unknown' = endpoint failed → fall back to a neutral "Local CLIs" label.
  if (health === 'unknown') {
    return (
      <div
        className="status-pill flex items-center gap-1.5 rounded-full border border-[var(--color-border)] px-2.5 py-1 text-[10px] font-medium text-[var(--color-muted)]"
        title="Local Claude + Codex CLIs"
      >
        <span className="inline-block size-1.5 rounded-full bg-[var(--color-muted)]" aria-hidden="true" />
        <span className="uppercase tracking-[0.12em]">Local CLIs</span>
      </div>
    );
  }

  if (health === null) {
    // Still loading. Render a quiet placeholder of the same shape.
    return (
      <div className="status-pill flex items-center gap-2 rounded-full border border-[var(--color-border)] px-2.5 py-1 text-[10px] font-medium text-[var(--color-muted)]/70">
        <span className="inline-block size-1.5 rounded-full bg-[var(--color-border-strong)]" />
        <span className="uppercase tracking-[0.12em]">Connecting…</span>
      </div>
    );
  }

  const claude = health.claude;
  const codex = health.codex;
  const claudeTitle = claude
    ? `Claude ${claude.version ?? ''}`.trim()
    : 'Claude (no info)';
  const codexTitle = codex
    ? `Codex ${codex.version ?? ''}`.trim()
    : 'Codex (no info)';

  return (
    <div className="status-pill flex items-center gap-2.5 rounded-full border border-[var(--color-border)] px-2.5 py-1 text-[10px] font-medium">
      <AgentChip
        agent="claude"
        ok={!!claude?.ok}
        label="Claude"
        title={claudeTitle}
      />
      <span className="h-2.5 w-px bg-[var(--color-border-strong)]" aria-hidden="true" />
      <AgentChip
        agent="codex"
        ok={!!codex?.ok}
        label="Codex"
        title={codexTitle}
      />
    </div>
  );
}

function AgentChip({
  agent,
  ok,
  label,
  title,
}: {
  agent: 'claude' | 'codex';
  ok: boolean;
  label: string;
  title: string;
}) {
  const colorVar = agent === 'claude' ? '--color-claude' : '--color-codex';
  return (
    <span
      className="flex items-center gap-1.5"
      title={title}
      style={{
        color: ok ? `var(${colorVar})` : 'var(--color-muted)',
      }}
    >
      <span
        className={cx(
          'inline-block size-1.5 shrink-0 rounded-full bg-current',
          ok && 'heartbeat',
        )}
        aria-hidden="true"
      />
      <AgentLogo agent={agent} size={10} className={ok ? '' : 'opacity-50'} />
      <span className="uppercase tracking-[0.12em]">{label}</span>
    </span>
  );
}

function useHealth(): HealthPayload | null | 'unknown' {
  // null = loading, 'unknown' = endpoint missing/failed, payload = OK.
  const [state, setState] = useState<HealthPayload | null | 'unknown'>(null);

  useEffect(() => {
    let alive = true;
    let cancelled = false;

    async function pull() {
      const res = await fetch('/health', { cache: 'no-store' }).catch(() => null);
      if (!alive || cancelled) return;
      if (!res || !res.ok) {
        setState('unknown');
        return;
      }
      try {
        const json = (await res.json()) as HealthPayload;
        if (!alive || cancelled) return;
        // Sanity check: must look like our payload.
        if (json && (json.claude || json.codex)) {
          setState(json);
        } else {
          setState('unknown');
        }
      } catch {
        if (alive && !cancelled) setState('unknown');
      }
    }

    void pull();
    const id = window.setInterval(() => void pull(), 30_000);
    return () => {
      alive = false;
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  return state;
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
