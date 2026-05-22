import { cx } from '@/lib/utils';

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
        'rounded-md border border-l-[3px] border-[var(--color-border)] bg-[var(--color-bg-2)] px-4 py-3 opacity-85',
        ROLE_STRIPE[role],
      )}
    >
      <div className="mb-1.5 flex items-baseline gap-3 text-[11px] uppercase tracking-wider text-[var(--color-muted)]">
        <span className={cx('font-semibold', ROLE_TEXT[role])}>{ROLE_LABEL[role]}</span>
      </div>
      <div className={cx('flex items-center gap-1.5 text-[13px]', ROLE_TEXT[role])}>
        <span className="mr-1 text-[var(--color-muted)]">thinking</span>
        <span className="inline-block size-1.5 rounded-full bg-current animate-pulse" style={{ animationDelay: '0ms' }} />
        <span className="inline-block size-1.5 rounded-full bg-current animate-pulse" style={{ animationDelay: '150ms' }} />
        <span className="inline-block size-1.5 rounded-full bg-current animate-pulse" style={{ animationDelay: '300ms' }} />
      </div>
    </div>
  );
}
