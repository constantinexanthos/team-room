import { cx } from '@/lib/utils';
import { AgentLogo } from './AgentLogo';

interface Props {
  role: 'claude' | 'codex';
}

const ROLE_STRIPE = {
  claude: 'border-l-[var(--color-claude)]',
  codex: 'border-l-[var(--color-codex)]',
};

const ROLE_TEXT = {
  claude: 'text-[var(--color-claude)]',
  codex: 'text-[var(--color-codex)]',
};

const ROLE_LABEL = {
  claude: 'Claude',
  codex: 'Codex',
};

export function ThinkingBubble({ role }: Props) {
  return (
    <div
      className={cx(
        'rounded-md border border-l-[3px] border-[var(--color-border)] bg-[var(--color-bg-2)] px-4 py-3 opacity-90',
        ROLE_STRIPE[role],
      )}
    >
      <div className="mb-1.5 flex items-center gap-2.5 text-[11px] uppercase tracking-[0.12em] text-[var(--color-muted)]">
        <span className={cx('flex items-center gap-1.5 font-semibold', ROLE_TEXT[role])}>
          <AgentLogo agent={role} size={12} />
          <span>{ROLE_LABEL[role]}</span>
        </span>
      </div>
      <div className={cx('flex items-center gap-1.5 text-[13px]', ROLE_TEXT[role])}>
        <span className="mr-1 text-[var(--color-muted)]">thinking</span>
        <span className="typing-dot inline-block size-1 rounded-full bg-current" style={{ animationDelay: '0ms' }} />
        <span className="typing-dot inline-block size-1 rounded-full bg-current" style={{ animationDelay: '180ms' }} />
        <span className="typing-dot inline-block size-1 rounded-full bg-current" style={{ animationDelay: '360ms' }} />
      </div>
    </div>
  );
}
