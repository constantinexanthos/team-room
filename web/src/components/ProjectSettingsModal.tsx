import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { Project } from '@/api/types';

interface Props {
  project: Project;
  onClose: () => void;
  onUpdated: (project: Project) => void;
  onDeleted: () => void;
}

type Mode = 'edit' | 'confirm-delete';

export function ProjectSettingsModal({ project, onClose, onUpdated, onDeleted }: Props) {
  const [mode, setMode] = useState<Mode>('edit');
  const [name, setName] = useState(project.name);
  const [workspace, setWorkspace] = useState(project.workspace);
  const [githubUrl, setGithubUrl] = useState(project.github_url ?? '');
  const [confirmName, setConfirmName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const firstFieldRef = useRef<HTMLInputElement | null>(null);
  const confirmFieldRef = useRef<HTMLInputElement | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Autofocus the right field whenever the mode changes.
  useEffect(() => {
    if (mode === 'edit') {
      firstFieldRef.current?.focus();
      firstFieldRef.current?.select();
    } else {
      confirmFieldRef.current?.focus();
    }
  }, [mode]);

  function reportError(err: unknown) {
    if (err instanceof ApiError) {
      const parsed = err.json();
      setError(parsed?.error ? String(parsed.error) : err.message);
    } else {
      setError(String(err));
    }
    setSubmitting(false);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const trimmedName = name.trim();
    const trimmedWorkspace = workspace.trim();
    const trimmedGithub = githubUrl.trim();

    if (!trimmedName) {
      setError('Project name is required.');
      return;
    }
    if (!trimmedWorkspace) {
      setError('Workspace path is required.');
      return;
    }

    // Build only the fields that actually changed — server treats PATCH as
    // partial, so this keeps logs cleaner and lets us skip no-op writes.
    const patch: Partial<Project> = {};
    if (trimmedName !== project.name) patch.name = trimmedName;
    if (trimmedWorkspace !== project.workspace) patch.workspace = trimmedWorkspace;
    const currentGithub = project.github_url ?? '';
    if (trimmedGithub !== currentGithub) {
      patch.github_url = trimmedGithub === '' ? null : trimmedGithub;
    }

    if (Object.keys(patch).length === 0) {
      onClose();
      return;
    }

    setSubmitting(true);
    try {
      const updated = await api.updateProject(project.id, patch);
      onUpdated(updated);
      onClose();
    } catch (err) {
      reportError(err);
    }
  }

  async function handleDelete(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (confirmName.trim() !== project.name) {
      setError('Project name does not match.');
      return;
    }

    setSubmitting(true);
    try {
      await api.deleteProject(project.id);
      onDeleted();
      onClose();
    } catch (err) {
      reportError(err);
    }
  }

  function switchToDelete() {
    setError(null);
    setConfirmName('');
    setMode('confirm-delete');
  }

  function switchToEdit() {
    setError(null);
    setMode('edit');
  }

  const title =
    mode === 'edit' ? 'Project settings' : `Delete ${project.name}?`;

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
      {mode === 'edit' ? (
        <form
          onSubmit={handleSave}
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

          <div className="mb-3">
            <label htmlFor="project-name" className="mb-1 block text-xs font-medium text-[var(--color-muted)]">
              Name
            </label>
            <input
              id="project-name"
              ref={firstFieldRef}
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] outline-none placeholder:text-[var(--color-muted)] focus:border-[var(--color-border-strong)]"
              autoComplete="off"
              spellCheck={false}
            />
          </div>

          <div className="mb-3">
            <label htmlFor="project-workspace" className="mb-1 block text-xs font-medium text-[var(--color-muted)]">
              Workspace path
            </label>
            <input
              id="project-workspace"
              type="text"
              value={workspace}
              onChange={(e) => setWorkspace(e.target.value)}
              className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 font-mono text-sm text-[var(--color-text)] outline-none placeholder:text-[var(--color-muted)] focus:border-[var(--color-border-strong)]"
              autoComplete="off"
              spellCheck={false}
            />
          </div>

          <div className="mb-4">
            <label htmlFor="project-github" className="mb-1 block text-xs font-medium text-[var(--color-muted)]">
              GitHub URL <span className="text-[var(--color-muted)]">(optional)</span>
            </label>
            <input
              id="project-github"
              type="text"
              value={githubUrl}
              onChange={(e) => setGithubUrl(e.target.value)}
              placeholder="https://github.com/owner/repo"
              className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] outline-none placeholder:text-[var(--color-muted)] focus:border-[var(--color-border-strong)]"
              autoComplete="off"
              spellCheck={false}
            />
          </div>

          {error && (
            <div className="mb-3 rounded-md border border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 px-3 py-2 text-xs text-[var(--color-danger)]">
              {error}
            </div>
          )}

          <div className="mt-4 flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={switchToDelete}
              disabled={submitting}
              className="text-xs text-[var(--color-danger)] hover:underline disabled:opacity-50"
            >
              Delete project
            </button>

            <div className="flex gap-2">
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
                {submitting ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </form>
      ) : (
        <form
          onSubmit={handleDelete}
          className="w-full max-w-md rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-2)] p-5 shadow-2xl"
        >
          <div className="mb-4 flex items-start justify-between">
            <h2 className="text-base font-semibold text-[var(--color-danger)]">{title}</h2>
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

          <p className="mb-3 text-sm text-[var(--color-text)]">
            This removes the project from Team Room. The files on disk at{' '}
            <span className="font-mono text-[var(--color-muted)]">{project.workspace}</span>{' '}
            are not touched.
          </p>

          <div className="mb-3">
            <label htmlFor="confirm-name" className="mb-1 block text-xs font-medium text-[var(--color-muted)]">
              Type the project name to confirm
            </label>
            <input
              id="confirm-name"
              ref={confirmFieldRef}
              type="text"
              value={confirmName}
              onChange={(e) => setConfirmName(e.target.value)}
              placeholder={project.name}
              className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] outline-none placeholder:text-[var(--color-muted)] focus:border-[var(--color-border-strong)]"
              autoComplete="off"
              spellCheck={false}
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
              onClick={switchToEdit}
              disabled={submitting}
              className="rounded-md px-3 py-1.5 text-sm text-[var(--color-muted)] hover:text-[var(--color-text)] disabled:opacity-50"
            >
              Back
            </button>
            <button
              type="submit"
              disabled={submitting || confirmName.trim() !== project.name}
              className="rounded-md bg-[var(--color-danger)] px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
            >
              {submitting ? 'Deleting…' : 'Delete project'}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
