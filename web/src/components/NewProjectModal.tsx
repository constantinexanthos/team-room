import { useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { Project } from '@/api/types';

interface Props {
  mode: 'folder' | 'github';
  onClose: () => void;
  onCreated: (project: Project) => void;
}

function parseRepoFromUrl(url: string): { owner: string; repo: string } | null {
  const trimmed = url.trim();
  if (!trimmed) return null;
  let s = trimmed;
  if (s.startsWith('git@')) s = 'https://' + s.slice(4).replace(':', '/');
  if (s.endsWith('.git')) s = s.slice(0, -4);
  if (s.endsWith('/')) s = s.slice(0, -1);
  const m = s.match(/^https?:\/\/[^/]+\/([^/]+)\/([^/]+)$/);
  if (!m) return null;
  return { owner: m[1], repo: m[2] };
}

function defaultClonePath(owner: string, repo: string): string {
  return `~/team-room-clones/${owner}-${repo}`;
}

export function NewProjectModal({ mode, onClose, onCreated }: Props) {
  const [workspace, setWorkspace] = useState('');
  const [githubUrl, setGithubUrl] = useState('');
  const [cloneOverride, setCloneOverride] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const firstFieldRef = useRef<HTMLInputElement | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    firstFieldRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const title = mode === 'github' ? 'Open GitHub project' : 'Open project';

  // For github mode, derive the auto clone path from the URL.
  const parsed = useMemo(() => parseRepoFromUrl(githubUrl), [githubUrl]);
  const derivedClonePath = parsed ? defaultClonePath(parsed.owner, parsed.repo) : null;
  const effectiveClonePath = cloneOverride.trim() || derivedClonePath || '';

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (mode === 'folder') {
      const trimmedWorkspace = workspace.trim();
      if (!trimmedWorkspace) {
        setError('Workspace path is required.');
        return;
      }
      setSubmitting(true);
      try {
        const body: { workspace: string; name?: string } = { workspace: trimmedWorkspace };
        if (name.trim()) body.name = name.trim();
        const project = await api.createProject(body);
        onCreated(project);
      } catch (err) {
        setSubmittingFalseAndError(err);
      }
      return;
    }

    // mode === 'github'
    const url = githubUrl.trim();
    if (!url) {
      setError('GitHub URL is required.');
      return;
    }
    if (!parsed) {
      setError('Could not parse URL. Expected https://github.com/owner/repo');
      return;
    }
    setSubmitting(true);
    try {
      const body: { github_url: string; target_dir?: string; name?: string } = {
        github_url: url,
      };
      if (cloneOverride.trim()) body.target_dir = cloneOverride.trim();
      if (name.trim()) body.name = name.trim();
      const project = await api.createProjectFromGithub(body);
      onCreated(project);
    } catch (err) {
      setSubmittingFalseAndError(err);
    }
  }

  function setSubmittingFalseAndError(err: unknown) {
    if (err instanceof ApiError) {
      const parsed = err.json();
      setError(parsed?.error ? String(parsed.error) : err.message);
    } else {
      setError(String(err));
    }
    setSubmitting(false);
  }

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onMouseDown={(e) => {
        if (e.target === overlayRef.current) onClose();
      }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    >
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-2)] p-5 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between">
          <h2 className="text-base font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mt-1 -mr-1 rounded p-1 text-[var(--color-muted)] hover:bg-[var(--color-bg-3)] hover:text-[var(--color-text)]"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M3 3l10 10M13 3L3 13" />
            </svg>
          </button>
        </div>

        {mode === 'github' ? (
          <>
            <div className="mb-3">
              <label htmlFor="github-url" className="mb-1 block text-xs font-medium text-[var(--color-muted)]">
                GitHub URL
              </label>
              <input
                id="github-url"
                ref={firstFieldRef}
                type="text"
                value={githubUrl}
                onChange={(e) => setGithubUrl(e.target.value)}
                placeholder="https://github.com/owner/repo"
                className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] outline-none placeholder:text-[var(--color-muted)] focus:border-[var(--color-border-strong)]"
                autoComplete="off"
                spellCheck={false}
              />
            </div>

            {derivedClonePath && (
              <div className="mb-3 rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-xs">
                <div className="text-[var(--color-muted)]">
                  {showAdvanced ? 'Clone target' : 'Will use'}
                </div>
                <div className="mt-0.5 truncate font-mono text-[var(--color-text)]">
                  {effectiveClonePath}
                </div>
                {!showAdvanced && (
                  <button
                    type="button"
                    onClick={() => setShowAdvanced(true)}
                    className="mt-1 text-[var(--color-costa)] hover:underline"
                  >
                    Already cloned somewhere else?
                  </button>
                )}
                {showAdvanced && (
                  <input
                    type="text"
                    value={cloneOverride}
                    onChange={(e) => setCloneOverride(e.target.value)}
                    placeholder={derivedClonePath}
                    className="mt-2 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg-2)] px-2 py-1 font-mono text-xs text-[var(--color-text)] outline-none placeholder:text-[var(--color-muted)] focus:border-[var(--color-border-strong)]"
                    autoComplete="off"
                    spellCheck={false}
                  />
                )}
                <div className="mt-1 text-[var(--color-muted)]">
                  {effectiveClonePath && 'If the folder already exists with a matching git remote, it will be reused. Otherwise it will be cloned.'}
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="mb-3">
            <label htmlFor="workspace" className="mb-1 block text-xs font-medium text-[var(--color-muted)]">
              Workspace path
            </label>
            <input
              id="workspace"
              ref={firstFieldRef}
              type="text"
              value={workspace}
              onChange={(e) => setWorkspace(e.target.value)}
              placeholder="~/path/to/repo"
              className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 font-mono text-sm text-[var(--color-text)] outline-none placeholder:text-[var(--color-muted)] focus:border-[var(--color-border-strong)]"
              autoComplete="off"
              spellCheck={false}
            />
          </div>
        )}

        <div className="mb-4">
          <label htmlFor="project-name" className="mb-1 block text-xs font-medium text-[var(--color-muted)]">
            Project name <span className="text-[var(--color-muted)]">(optional)</span>
          </label>
          <input
            id="project-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={mode === 'github' && parsed ? parsed.repo : 'Auto-detected from folder name'}
            className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] outline-none placeholder:text-[var(--color-muted)] focus:border-[var(--color-border-strong)]"
            autoComplete="off"
          />
        </div>

        {error && (
          <div className="mb-3 rounded-md border border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 px-3 py-2 text-xs text-[var(--color-danger)]">
            {error}
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md px-3 py-1.5 text-sm text-[var(--color-muted)] hover:text-[var(--color-text)] disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-[var(--color-costa)] px-3 py-1.5 text-sm font-medium text-[var(--color-bg)] hover:opacity-90 disabled:opacity-50"
          >
            {submitting
              ? mode === 'github'
                ? 'Cloning…'
                : 'Opening…'
              : mode === 'github'
              ? 'Open project'
              : 'Open project'}
          </button>
        </div>
      </form>
    </div>
  );
}
