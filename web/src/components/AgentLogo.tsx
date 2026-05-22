import { cx } from '@/lib/utils';

type Agent = 'claude' | 'codex';

interface Props {
  agent: Agent;
  size?: number;
  className?: string;
  title?: string;
}

/**
 * Inline SVG logo for the supported agents. Color defaults to `currentColor`
 * so parents can tint it with `text-[var(--color-claude)]` or similar.
 */
export function AgentLogo({ agent, size = 14, className, title }: Props) {
  if (agent === 'claude') {
    return <ClaudeMark size={size} className={className} title={title ?? 'Claude'} />;
  }
  return <CodexMark size={size} className={className} title={title ?? 'Codex'} />;
}

interface MarkProps {
  size: number;
  className?: string;
  title: string;
}

/**
 * Anthropic Claude mark — stylized asymmetric "C/A" sunburst.
 *
 * Simplified geometric interpretation of the Claude glyph using a small
 * grid of radial strokes — readable even at 12px, no dependency on a
 * complex path that doesn't anti-alias well at small sizes.
 */
function ClaudeMark({ size, className, title }: MarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cx('shrink-0', className)}
      role="img"
      aria-label={title}
    >
      <title>{title}</title>
      <g stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
        {/* Horizontal-ish "burst" lines, characteristic of the Claude/Anthropic glyph */}
        <line x1="3.5" y1="7.5" x2="11" y2="9" />
        <line x1="3" y1="12" x2="11.5" y2="12" />
        <line x1="3.5" y1="16.5" x2="11" y2="15" />
        <line x1="6" y1="4" x2="11" y2="9.5" />
        <line x1="6" y1="20" x2="11" y2="14.5" />
        <line x1="13" y1="9" x2="20.5" y2="7.5" />
        <line x1="12.5" y1="12" x2="21" y2="12" />
        <line x1="13" y1="15" x2="20.5" y2="16.5" />
        <line x1="13" y1="9.5" x2="18" y2="4" />
        <line x1="13" y1="14.5" x2="18" y2="20" />
      </g>
    </svg>
  );
}

/**
 * OpenAI / Codex mark — the rotational knot glyph.
 *
 * Approximation of the OpenAI hexagonal mark using rotated arcs, which
 * scales cleanly from 12px upward.
 */
function CodexMark({ size, className, title }: MarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
      className={cx('shrink-0', className)}
      role="img"
      aria-label={title}
    >
      <title>{title}</title>
      <path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.051 6.051 0 0 0 6.515 2.9A5.985 5.985 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.056 6.056 0 0 0-.747-7.073zM13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.141-.081 4.779-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085 4.783 2.759a.771.771 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1-.071 0l-4.83-2.79a4.504 4.504 0 0 1-1.648-6.113zm16.597 3.855l-5.833-3.387L15.119 7.2a.076.076 0 0 1 .071 0l4.83 2.792a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.667zm2.01-3.023l-.141-.085-4.774-2.782a.776.776 0 0 0-.785 0L9.409 9.23V6.897a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135l-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.081L8.704 5.46a.795.795 0 0 0-.393.682zm1.097-2.365l2.602-1.5 2.607 1.5v2.999l-2.597 1.5-2.607-1.5z" />
    </svg>
  );
}
