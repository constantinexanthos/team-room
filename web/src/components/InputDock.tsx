import { useCallback, useEffect, useRef, useState } from 'react';
import { cx } from '@/lib/utils';

interface Props {
  locked: boolean;
  lockReason?: string;
  onSend: (text: string) => Promise<void> | void;
  placeholder?: string;
}

export function InputDock({ locked, lockReason, onSend, placeholder = 'Type a message to the room…' }: Props) {
  const [value, setValue] = useState('');
  const [sending, setSending] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow textarea height
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }, [value]);

  // Auto-focus when unlocked
  useEffect(() => {
    if (!locked && !sending) textareaRef.current?.focus();
  }, [locked, sending]);

  const send = useCallback(async () => {
    const text = value.trim();
    if (!text || locked || sending) return;
    setSending(true);
    try {
      await onSend(text);
      setValue('');
    } catch {
      // Caller surfaces the error via toast; keep the text in the box so user can retry
    } finally {
      setSending(false);
    }
  }, [value, locked, sending, onSend]);

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void send();
    }
  };

  const disabled = locked || sending;
  const hint = sending ? 'Sending…' : lockReason || 'Cmd+Enter (or Ctrl+Enter) to send';

  return (
    <div className="border-t border-[var(--color-border)] bg-[var(--color-bg)] px-6 py-4">
      <div className="mx-auto max-w-[860px]">
        <div
          className={cx(
            'flex items-end gap-3 rounded-lg border bg-[var(--color-bg-2)] p-3 transition-colors',
            disabled
              ? 'border-[var(--color-border)] opacity-60'
              : 'border-[var(--color-border)] focus-within:border-[var(--color-costa)]',
          )}
        >
          <textarea
            ref={textareaRef}
            rows={1}
            disabled={disabled}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKey}
            placeholder={placeholder}
            spellCheck
            className="flex-1 resize-none bg-transparent font-mono text-[13px] leading-relaxed text-[var(--color-text)] placeholder:text-[var(--color-muted)] focus:outline-none disabled:cursor-not-allowed"
            style={{ minHeight: 22, maxHeight: 240 }}
          />
          <button
            type="button"
            onClick={() => void send()}
            disabled={disabled || !value.trim()}
            className={cx(
              'shrink-0 rounded-md px-4 py-2 text-[12px] font-semibold uppercase tracking-wider transition-colors',
              disabled || !value.trim()
                ? 'cursor-not-allowed bg-[var(--color-bg-3)] text-[var(--color-muted)]'
                : 'bg-[var(--color-costa)] text-[var(--color-bg)] hover:opacity-90',
            )}
            title="Send (Cmd+Enter)"
          >
            Send
          </button>
        </div>
        <div className="mt-2 text-center text-[11px] tracking-wider text-[var(--color-muted)]">{hint}</div>
      </div>
    </div>
  );
}
