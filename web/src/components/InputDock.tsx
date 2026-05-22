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
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send();
    }
  };

  const disabled = locked || sending;
  const hint = sending ? 'Sending…' : lockReason || 'Enter to send · Shift+Enter for new line';

  return (
    <div className="dock-glass px-6 pt-6 pb-5">
      <div className="mx-auto max-w-[860px]">
        <div
          className={cx(
            'dock-shell flex items-end gap-3 rounded-2xl px-4 py-3 transition-all duration-200',
            disabled && 'opacity-70',
          )}
          data-busy={disabled}
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
            className="flex-1 resize-none bg-transparent font-mono text-[13px] leading-relaxed text-[var(--color-text)] placeholder:text-[var(--color-muted)]/70 focus:outline-none disabled:cursor-not-allowed"
            style={{ minHeight: 22, maxHeight: 240 }}
          />
          <button
            type="button"
            onClick={() => void send()}
            disabled={disabled || !value.trim()}
            className={cx(
              'send-btn shrink-0 rounded-xl px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.14em] transition-all duration-200',
              disabled || !value.trim()
                ? 'cursor-not-allowed text-[var(--color-muted)]'
                : 'text-[var(--color-bg)] hover:scale-[1.02] active:scale-[0.98]',
            )}
            data-ready={!disabled && !!value.trim()}
            title="Send (Enter)"
          >
            Send
          </button>
        </div>
        <div className="mt-2.5 text-center text-[10px] tracking-[0.18em] uppercase text-[var(--color-muted)]/70">
          {hint}
        </div>
      </div>
    </div>
  );
}
