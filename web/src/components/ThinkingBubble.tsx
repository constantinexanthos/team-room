import { cx } from '@/lib/utils';
import { AgentLogo } from './AgentLogo';

interface Props {
  role: 'claude' | 'codex';
  /**
   * Live, partially-streamed text from the agent's in-flight turn.
   * When non-empty, the bubble renders the streaming text in the agent's
   * color (with a small blinking caret) instead of the typing dots.
   * When empty / undefined, falls back to the legacy three-dot indicator.
   */
  partial?: string;
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

export function ThinkingBubble({ role, partial }: Props) {
  const hasPartial = !!partial && partial.length > 0;
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
        {hasPartial && (
          <span className="ml-auto flex items-center gap-1.5 normal-case tracking-normal text-[10px] text-[var(--color-muted)]">
            <span className={cx('typing-dot inline-block size-1 rounded-full bg-current', ROLE_TEXT[role])} />
            <span>streaming</span>
          </span>
        )}
      </div>
      {hasPartial ? (
        <pre className="m-0 whitespace-pre-wrap break-words font-mono text-[13px] leading-relaxed text-[var(--color-text)]">
          {partial}
          <span className={cx('ml-0.5 inline-block align-baseline animate-pulse', ROLE_TEXT[role])} aria-hidden="true">
            ▎
          </span>
        </pre>
      ) : (
        <div className={cx('flex items-center gap-1.5 text-[13px]', ROLE_TEXT[role])}>
          <span className="mr-1 text-[var(--color-muted)]">thinking</span>
          <span className="typing-dot inline-block size-1 rounded-full bg-current" style={{ animationDelay: '0ms' }} />
          <span className="typing-dot inline-block size-1 rounded-full bg-current" style={{ animationDelay: '180ms' }} />
          <span className="typing-dot inline-block size-1 rounded-full bg-current" style={{ animationDelay: '360ms' }} />
        </div>
      )}
    </div>
  );
}
