import { useEffect, useRef, useState } from 'react';
import { ApiError } from '@/api/client';

interface Props {
  title: string;
  body: React.ReactNode;
  confirmLabel: string;
  confirmingLabel?: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}

/**
 * Reusable destructive-action confirm modal.
 *
 * Mirrors NewProjectModal / NewTopicModal patterns: dark overlay, click-out to
 * close, Escape key to close, centered card. The confirm action runs onConfirm
 * and on error the modal stays open displaying the message — the parent only
 * unmounts the modal when onClose is called (which happens after a successful
 * confirm via the parent's onConfirm handler).
 */
export function ConfirmModal({
  title,
  body,
  confirmLabel,
  confirmingLabel,
  onConfirm,
  onClose,
}: Props) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    cancelRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !submitting) onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, submitting]);

  async function handleConfirm() {
    setError(null);
    setSubmitting(true);
    try {
      await onConfirm();
      // onClose is the parent's responsibility after a successful confirm.
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
      aria-label={title}
      onMouseDown={(e) => {
        if (e.target === overlayRef.current && !submitting) onClose();
      }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    >
      <div className="w-full max-w-md rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-2)] p-5 shadow-2xl">
        <div className="mb-4 flex items-start justify-between">
          <h2 className="text-base font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            aria-label="Close"
            className="-mt-1 -mr-1 rounded p-1 text-[var(--color-muted)] hover:bg-[var(--color-bg-3)] hover:text-[var(--color-text)] disabled:opacity-50"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M3 3l10 10M13 3L3 13" />
            </svg>
          </button>
        </div>

        <div className="text-sm text-[var(--color-text)]/85 leading-relaxed">{body}</div>

        {error && (
          <div className="mt-3 rounded-md border border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 px-3 py-2 text-xs text-[var(--color-danger)]">
            {error}
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md px-3 py-1.5 text-sm text-[var(--color-muted)] hover:text-[var(--color-text)] disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleConfirm()}
            disabled={submitting}
            className="rounded-md bg-[var(--color-danger)] px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? confirmingLabel ?? `${confirmLabel}...` : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
