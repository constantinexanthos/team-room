import type { Message } from '@/api/types';
import { formatTime, cx } from '@/lib/utils';
import { AgentLogo } from './AgentLogo';

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
      <div className="mb-1.5 flex items-center gap-2.5 text-[11px] uppercase tracking-[0.12em] text-[var(--color-muted)]">
        <span className={cx('flex items-center gap-1.5 font-semibold', ROLE_TEXT[message.role])}>
          <RoleGlyph role={message.role} />
          <span>{ROLE_LABELS[message.role]}</span>
        </span>
        {message.model && (
          <span className="font-mono text-[10px] text-[var(--color-muted)]/80 normal-case tracking-normal">
            {message.model}
          </span>
        )}
        <span className="ml-auto font-mono text-[10px] tracking-normal">{formatTime(message.ts)}</span>
      </div>
      <pre className="m-0 whitespace-pre-wrap break-words font-mono text-[13px] leading-relaxed text-[var(--color-text)]">
        {message.content}
      </pre>
    </div>
  );
}

function RoleGlyph({ role }: { role: Message['role'] }) {
  if (role === 'claude' || role === 'codex') {
    return <AgentLogo agent={role} size={12} />;
  }
  // costa / system — colored dot
  return (
    <span
      className="inline-block size-1.5 rounded-full bg-current"
      aria-hidden="true"
    />
  );
}
