import { cx } from '@/lib/utils';

type Variant = 'wordmark' | 'mark' | 'full';

interface Props {
  variant?: Variant;
  size?: number;
  className?: string;
  /** When variant === 'full', stack the mark above the wordmark. */
  stacked?: boolean;
  /** Optional smaller version of the wordmark. */
  compact?: boolean;
}

/**
 * Brand renders the Team Room wordmark, logo mark, or full lockup.
 *
 * The mark is a "facing brackets with conversation dot" glyph:
 * two stylized brackets `[` `]` with a vertical line between them,
 * suggesting two voices meeting in a single shared space.
 */
export function Brand({
  variant = 'wordmark',
  size = 22,
  className,
  stacked = false,
  compact = false,
}: Props) {
  if (variant === 'mark') {
    return <BrandMark size={size} className={className} />;
  }

  if (variant === 'wordmark') {
    return <Wordmark className={className} compact={compact} />;
  }

  // full
  if (stacked) {
    return (
      <div className={cx('flex flex-col items-center gap-3', className)}>
        <BrandMark size={size} />
        <Wordmark compact={compact} />
      </div>
    );
  }

  return (
    <div className={cx('flex items-center gap-2.5', className)}>
      <BrandMark size={size} />
      <Wordmark compact={compact} />
    </div>
  );
}

function Wordmark({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <span
      className={cx(
        'inline-block select-none font-semibold uppercase text-[var(--color-text)]',
        compact
          ? 'text-[10px] tracking-[0.28em]'
          : 'text-[12px] tracking-[0.32em]',
        className,
      )}
    >
      Team<span className="text-[var(--color-muted)]">·</span>Room
    </span>
  );
}

interface MarkProps {
  size?: number;
  className?: string;
}

/**
 * Geometric mark: two facing brackets `[ | ]` with a vertical dialogue line.
 * Left bracket carries the Claude hue, right bracket the Codex hue,
 * and the center stroke pulls from the brand text color — together it reads
 * as "two voices, one room".
 */
export function BrandMark({ size = 22, className }: MarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cx('shrink-0', className)}
      aria-hidden="true"
    >
      {/* Left bracket — Claude */}
      <path
        d="M8 5H5v14h3"
        stroke="var(--color-claude)"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Right bracket — Codex */}
      <path
        d="M16 5h3v14h-3"
        stroke="var(--color-codex)"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Center dialogue line */}
      <path
        d="M12 7v10"
        stroke="var(--color-text)"
        strokeOpacity="0.85"
        strokeWidth="1.75"
        strokeLinecap="round"
      />
    </svg>
  );
}
