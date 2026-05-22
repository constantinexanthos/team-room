import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '@/api/client';

interface Props {
  projectId: string;
  onClose: () => void;
  onCreated: (topicName: string) => void;
}

export function NewTopicModal({ projectId, onClose, onCreated }: Props) {
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const trimmed = name.trim();
    if (!trimmed) {
      setError('Topic name is required.');
      return;
    }
    setSubmitting(true);
    try {
      const res = await api.createTopic({ name: trimmed, project_id: projectId });
      onCreated(res.name || trimmed);
    } catch (err) {
      if (err instanceof ApiError) {
        const parsed = err.json();
        setError(parsed?.error ? String(parsed.error) : err.message);
      } else {
        setError(String(err));
      }
      setSubmitting(false);
    }
  }

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-label="New topic"
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
          <h2 className="text-base font-semibold">New topic</h2>
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
          <label htmlFor="topic-name" className="mb-1 block text-xs font-medium text-[var(--color-muted)]">
            Topic name
          </label>
          <input
            id="topic-name"
            ref={inputRef}
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. launch-prep"
            className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] outline-none placeholder:text-[var(--color-muted)] focus:border-[var(--color-border-strong)]"
            autoComplete="off"
            spellCheck={false}
          />
          <p className="mt-1 text-xs text-[var(--color-muted)]">
            Used as the JSONL filename; lowercase letters, numbers, and dashes.
          </p>
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
            {submitting ? 'Creating...' : 'Create'}
          </button>
        </div>
      </form>
    </div>
  );
}
