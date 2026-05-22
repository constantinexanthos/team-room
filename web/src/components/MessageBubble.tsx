import type { Message } from '@/api/types';
import { formatTime, cx } from '@/lib/utils';

interface Props {
  message: Message;
}

const ROLE_LABELS: Record<Message['role'], string> = {
  claude: 'Claude',
  codex: 'Codex',
  costa: 'You',
  system: 'System',
};

const ROLE_STRIPE: Record<Message['role'], string> = {
  claude: 'border-l-[var(--color-claude)]',
  codex: 'border-l-[var(--color-codex)]',
  costa: 'border-l-[var(--color-costa)]',
  system: 'border-l-[var(--color-system)]',
};

const ROLE_TEXT: Record<Message['role'], string> = {
  claude: 'text-[var(--color-claude)]',
  codex: 'text-[var(--color-codex)]',
  costa: 'text-[var(--color-costa)]',
  system: 'text-[var(--color-system)]',
};

export function MessageBubble({ message }: Props) {
  return (
    <div
      className={cx(
        'rounded-md border border-l-[3px] border-[var(--color-border)] bg-[var(--color-bg-2)] px-4 py-3',
        ROLE_STRIPE[message.role],
      )}
    >
      <div className="mb-1.5 flex items-baseline gap-3 text-[11px] uppercase tracking-wider text-[var(--color-muted)]">
        <span className={cx('font-semibold', ROLE_TEXT[message.role])}>
          {ROLE_LABELS[message.role]}
        </span>
        <span className="font-mono">{formatTime(message.ts)}</span>
      </div>
      <pre className="m-0 whitespace-pre-wrap break-words font-mono text-[13px] leading-relaxed text-[var(--color-text)]">
        {message.content}
      </pre>
    </div>
  );
}
